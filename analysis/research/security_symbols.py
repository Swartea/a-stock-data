"""Provider-symbol alias mapping for the Research Engine Security Master.

This B0 layer answers one narrow question: which stable security_id does a
provider-specific symbol refer to?

The contract is deliberately provider-neutral. It stores canonical provider
ids from A2 as data, but it does not depend on endpoint logic, networking,
exchange-prefix heuristics, or mutable display names. Provider symbols are
preserved exactly; callers must not assume they are interchangeable across
providers.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import re
from typing import Iterable, Optional


_SECURITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ProviderSymbolAlias:
    """One explicit provider symbol mapped to one stable security identity."""

    security_id: str
    provider_id: str
    provider_symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str):
            raise TypeError("security_id must be a string")
        if (
            not self.security_id
            or self.security_id != self.security_id.strip().lower()
            or not _SECURITY_ID_RE.fullmatch(self.security_id)
        ):
            raise ValueError("security_id must be a canonical machine-readable token")

        if not isinstance(self.provider_id, str):
            raise TypeError("provider_id must be a string")
        if (
            not self.provider_id
            or self.provider_id != self.provider_id.strip().lower()
            or not _PROVIDER_ID_RE.fullmatch(self.provider_id)
        ):
            raise ValueError("provider_id must be a canonical lowercase provider token")

        if not isinstance(self.provider_symbol, str):
            raise TypeError("provider_symbol must be a string")
        if not self.provider_symbol:
            raise ValueError("provider_symbol must not be empty")
        if self.provider_symbol != self.provider_symbol.strip():
            raise ValueError("provider_symbol must not contain surrounding whitespace")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small provider-symbol mapping surface."""

        return tuple(field.name for field in fields(cls))


class ProviderSymbolRegistry:
    """Exact, deterministic lookup from provider symbol to stable security id."""

    def __init__(self, aliases: Iterable[ProviderSymbolAlias] = ()) -> None:
        self._lookup: dict[tuple[str, str], ProviderSymbolAlias] = {}
        self._by_security: dict[str, list[ProviderSymbolAlias]] = {}
        for alias in aliases:
            self.register(alias)

    def register(self, alias: ProviderSymbolAlias) -> ProviderSymbolAlias:
        """Register one explicit alias, rejecting provider-symbol collisions."""

        if not isinstance(alias, ProviderSymbolAlias):
            raise TypeError("alias must be a ProviderSymbolAlias")

        key = (alias.provider_id, alias.provider_symbol)
        existing = self._lookup.get(key)
        if existing is not None:
            raise ValueError(
                "provider symbol collision for "
                f"{alias.provider_id!r}:{alias.provider_symbol!r}; "
                f"already mapped to {existing.security_id!r}"
            )

        self._lookup[key] = alias
        self._by_security.setdefault(alias.security_id, []).append(alias)
        return alias

    def resolve(self, provider_id: str, provider_symbol: str) -> Optional[str]:
        """Return the stable security id for an exact known provider symbol."""

        key = self._lookup_key(provider_id, provider_symbol)
        alias = self._lookup.get(key)
        if alias is None:
            return None
        return alias.security_id

    def require(self, provider_id: str, provider_symbol: str) -> str:
        """Resolve a provider symbol or fail explicitly when it is unknown."""

        security_id = self.resolve(provider_id, provider_symbol)
        if security_id is None:
            raise KeyError(
                f"unknown provider symbol: {provider_id!r}:{provider_symbol!r}"
            )
        return security_id

    def aliases_for(self, security_id: str) -> tuple[ProviderSymbolAlias, ...]:
        """Return aliases for one security in registration order."""

        if not isinstance(security_id, str):
            raise TypeError("security_id lookup value must be a string")
        if (
            not security_id
            or security_id != security_id.strip().lower()
            or not _SECURITY_ID_RE.fullmatch(security_id)
        ):
            raise ValueError("security_id lookup value must be canonical")
        return tuple(self._by_security.get(security_id, ()))

    @staticmethod
    def _lookup_key(provider_id: str, provider_symbol: str) -> tuple[str, str]:
        if not isinstance(provider_id, str):
            raise TypeError("provider_id lookup value must be a string")
        if (
            not provider_id
            or provider_id != provider_id.strip().lower()
            or not _PROVIDER_ID_RE.fullmatch(provider_id)
        ):
            raise ValueError("provider_id lookup value must be canonical")

        if not isinstance(provider_symbol, str):
            raise TypeError("provider_symbol lookup value must be a string")
        if not provider_symbol:
            raise ValueError("provider_symbol lookup value must not be empty")
        if provider_symbol != provider_symbol.strip():
            raise ValueError(
                "provider_symbol lookup value must not contain surrounding whitespace"
            )
        return provider_id, provider_symbol
