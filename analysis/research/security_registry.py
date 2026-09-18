"""In-memory Security Master registry for the Research Engine.

This B0 layer composes the previously defined identity, provider-symbol, and
listing-lifecycle contracts. It adds referential integrity and deterministic
lookup only. It does not fetch data, infer symbols, rewrite codes, or wire into
the legacy V3 pipeline.
"""

from __future__ import annotations

from typing import Iterable, Optional

from analysis.research.pit_guard import PITStatus
from analysis.research.security_lifecycle import (
    ListingLifecycleRecord,
    ListingState,
    evaluate_listing_lifecycle,
)
from analysis.research.security_master import SecurityIdentity
from analysis.research.security_symbols import (
    ProviderSymbolAlias,
    ProviderSymbolRegistry,
)


class SecurityMasterRegistry:
    """Compose Security Master contracts behind one deterministic lookup API."""

    def __init__(
        self,
        identities: Iterable[SecurityIdentity] = (),
        aliases: Iterable[ProviderSymbolAlias] = (),
        lifecycle_records: Iterable[ListingLifecycleRecord] = (),
    ) -> None:
        self._identities: dict[str, SecurityIdentity] = {}
        self._symbols = ProviderSymbolRegistry()
        self._lifecycle: dict[str, list[ListingLifecycleRecord]] = {}

        for identity in identities:
            self.register_identity(identity)
        for alias in aliases:
            self.register_alias(alias)
        for record in lifecycle_records:
            self.register_lifecycle(record)

    def register_identity(self, identity: SecurityIdentity) -> SecurityIdentity:
        """Register one stable identity, rejecting duplicate security ids."""

        if not isinstance(identity, SecurityIdentity):
            raise TypeError("identity must be a SecurityIdentity")
        if identity.security_id in self._identities:
            raise ValueError(f"duplicate security_id: {identity.security_id!r}")

        self._identities[identity.security_id] = identity
        return identity

    def register_alias(self, alias: ProviderSymbolAlias) -> ProviderSymbolAlias:
        """Register one provider symbol after validating its target identity."""

        if not isinstance(alias, ProviderSymbolAlias):
            raise TypeError("alias must be a ProviderSymbolAlias")
        self._require_known_security_id(alias.security_id)
        return self._symbols.register(alias)

    def register_lifecycle(
        self,
        record: ListingLifecycleRecord,
    ) -> ListingLifecycleRecord:
        """Register one lifecycle record after validating its target identity."""

        if not isinstance(record, ListingLifecycleRecord):
            raise TypeError("record must be a ListingLifecycleRecord")
        self._require_known_security_id(record.security_id)
        self._lifecycle.setdefault(record.security_id, []).append(record)
        return record

    def identity(self, security_id: str) -> Optional[SecurityIdentity]:
        """Return a known identity or None without guessing."""

        self._validate_security_id_lookup(security_id)
        return self._identities.get(security_id)

    def require_identity(self, security_id: str) -> SecurityIdentity:
        """Return a known identity or fail explicitly."""

        identity = self.identity(security_id)
        if identity is None:
            raise KeyError(f"unknown security_id: {security_id!r}")
        return identity

    def resolve_provider_symbol(
        self,
        provider_id: str,
        provider_symbol: str,
    ) -> Optional[str]:
        """Resolve an exact provider symbol to a stable security id."""

        return self._symbols.resolve(provider_id, provider_symbol)

    def identity_for_provider_symbol(
        self,
        provider_id: str,
        provider_symbol: str,
    ) -> Optional[SecurityIdentity]:
        """Resolve an exact provider symbol directly to its registered identity."""

        security_id = self.resolve_provider_symbol(provider_id, provider_symbol)
        if security_id is None:
            return None
        return self._identities[security_id]

    def aliases_for(self, security_id: str) -> tuple[ProviderSymbolAlias, ...]:
        """Return provider aliases for one known security."""

        self._require_known_security_id(security_id)
        return self._symbols.aliases_for(security_id)

    def lifecycle_records(
        self,
        security_id: str,
    ) -> tuple[ListingLifecycleRecord, ...]:
        """Return lifecycle records in registration order for one known security."""

        self._require_known_security_id(security_id)
        return tuple(self._lifecycle.get(security_id, ()))

    def listing_state_on(
        self,
        security_id: str,
        decision_time: str,
    ) -> Optional[ListingState]:
        """Return the single effective listing state at decision_time.

        No effective record means unknown and returns None. More than one active
        record is a registry integrity error; the registry never resolves that
        ambiguity by ordering or priority.
        """

        records = self.lifecycle_records(security_id)
        active: list[ListingLifecycleRecord] = []
        for record in records:
            decision = evaluate_listing_lifecycle(record, decision_time)
            if decision.status is PITStatus.ALLOW:
                active.append(record)

        if not active:
            return None
        if len(active) > 1:
            raise ValueError(
                f"overlapping lifecycle records for {security_id!r} at "
                f"{decision_time!r}"
            )
        return active[0].state

    def all_identities(self) -> tuple[SecurityIdentity, ...]:
        """Return identities in registration order as an immutable snapshot."""

        return tuple(self._identities.values())

    def _require_known_security_id(self, security_id: str) -> SecurityIdentity:
        identity = self.identity(security_id)
        if identity is None:
            raise KeyError(f"unknown security_id: {security_id!r}")
        return identity

    @staticmethod
    def _validate_security_id_lookup(security_id: str) -> None:
        if not isinstance(security_id, str):
            raise TypeError("security_id lookup value must be a string")
        if not security_id:
            raise ValueError("security_id lookup value must not be empty")
        if security_id != security_id.strip().lower():
            raise ValueError("security_id lookup value must be canonical")
