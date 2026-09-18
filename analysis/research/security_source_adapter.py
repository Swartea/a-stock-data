"""Pure Security Master source-payload normalization boundary.

This B0 adapter accepts one explicit canonical payload shape from an external
source layer and converts it into the existing Security Master domain
contracts. It performs no HTTP requests and no exchange/symbol inference.

Provider-specific scraping/parsing belongs outside this module. Callers must
supply canonical provider_id and fetched_at explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from analysis.research.security_lifecycle import (
    ListingLifecycleRecord,
    ListingState,
)
from analysis.research.security_master import Exchange, SecurityIdentity, SecurityType
from analysis.research.security_registry import SecurityMasterRegistry
from analysis.research.security_symbols import ProviderSymbolAlias
from analysis.research.time_semantics import TimeMetadata


class SecurityMasterSourceError(ValueError):
    """Raised when an external Security Master payload violates the contract."""


@dataclass(frozen=True)
class SecurityMasterBatch:
    """Normalized immutable Security Master records from one source payload."""

    identities: tuple[SecurityIdentity, ...]
    aliases: tuple[ProviderSymbolAlias, ...]
    lifecycle_records: tuple[ListingLifecycleRecord, ...]

    def to_registry(self) -> SecurityMasterRegistry:
        """Build a validated in-memory registry from this batch."""

        return SecurityMasterRegistry(
            identities=self.identities,
            aliases=self.aliases,
            lifecycle_records=self.lifecycle_records,
        )


def normalize_security_master_payload(
    payload: Mapping[str, object],
    *,
    provider_id: str,
    fetched_at: str,
) -> SecurityMasterBatch:
    """Normalize a canonical source payload into B0 domain records.

    Canonical payload shape::

        {
            "securities": [
                {
                    "security_id": "cn.sse.600693",
                    "exchange": "sse",
                    "local_code": "600693",
                    "security_type": "equity",
                    "provider_symbols": ["1.600693"],
                    "lifecycle": [
                        {
                            "state": "listed",
                            "effective_from": "...",
                            "effective_to": None,
                            "published_at": None,
                        }
                    ],
                }
            ]
        }

    Missing/invalid fields are rejected. Empty securities is valid and produces
    an empty batch. No field is inferred from local_code or provider_symbol.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    _validate_provider_id(provider_id)
    _validate_nonempty_string(fetched_at, "fetched_at")

    raw_securities = payload.get("securities")
    if raw_securities is None:
        raise SecurityMasterSourceError("payload must contain securities")
    if not _is_sequence(raw_securities):
        raise SecurityMasterSourceError("securities must be a sequence")

    identities: list[SecurityIdentity] = []
    aliases: list[ProviderSymbolAlias] = []
    lifecycle_records: list[ListingLifecycleRecord] = []

    for index, raw_security in enumerate(raw_securities):
        if not isinstance(raw_security, Mapping):
            raise SecurityMasterSourceError(
                f"securities[{index}] must be a mapping"
            )

        security_id = _required_string(raw_security, "security_id", index)
        exchange = _enum_value(
            Exchange,
            raw_security.get("exchange"),
            f"securities[{index}].exchange",
        )
        local_code = _required_string(raw_security, "local_code", index)
        security_type = _enum_value(
            SecurityType,
            raw_security.get("security_type"),
            f"securities[{index}].security_type",
        )

        try:
            identity = SecurityIdentity(
                security_id=security_id,
                exchange=exchange,
                local_code=local_code,
                security_type=security_type,
            )
        except (TypeError, ValueError) as exc:
            raise SecurityMasterSourceError(
                f"invalid securities[{index}] identity: {exc}"
            ) from exc
        identities.append(identity)

        raw_symbols = raw_security.get("provider_symbols", ())
        if not _is_sequence(raw_symbols):
            raise SecurityMasterSourceError(
                f"securities[{index}].provider_symbols must be a sequence"
            )
        for symbol_index, raw_symbol in enumerate(raw_symbols):
            if not isinstance(raw_symbol, str):
                raise SecurityMasterSourceError(
                    "provider symbol must be a string at "
                    f"securities[{index}].provider_symbols[{symbol_index}]"
                )
            try:
                aliases.append(
                    ProviderSymbolAlias(
                        security_id=security_id,
                        provider_id=provider_id,
                        provider_symbol=raw_symbol,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise SecurityMasterSourceError(
                    "invalid provider symbol at "
                    f"securities[{index}].provider_symbols[{symbol_index}]: {exc}"
                ) from exc

        raw_lifecycle = raw_security.get("lifecycle", ())
        if not _is_sequence(raw_lifecycle):
            raise SecurityMasterSourceError(
                f"securities[{index}].lifecycle must be a sequence"
            )
        for lifecycle_index, raw_record in enumerate(raw_lifecycle):
            lifecycle_records.append(
                _normalize_lifecycle_record(
                    raw_record,
                    security_id=security_id,
                    fetched_at=fetched_at,
                    path=f"securities[{index}].lifecycle[{lifecycle_index}]",
                )
            )

    batch = SecurityMasterBatch(
        identities=tuple(identities),
        aliases=tuple(aliases),
        lifecycle_records=tuple(lifecycle_records),
    )

    try:
        batch.to_registry()
    except (TypeError, ValueError, KeyError) as exc:
        raise SecurityMasterSourceError(
            f"normalized Security Master payload violates registry integrity: {exc}"
        ) from exc

    return batch


def _normalize_lifecycle_record(
    raw_record: object,
    *,
    security_id: str,
    fetched_at: str,
    path: str,
) -> ListingLifecycleRecord:
    if not isinstance(raw_record, Mapping):
        raise SecurityMasterSourceError(f"{path} must be a mapping")

    state = _enum_value(ListingState, raw_record.get("state"), f"{path}.state")
    effective_from = _required_mapping_string(
        raw_record,
        "effective_from",
        f"{path}.effective_from",
    )
    effective_to = _optional_mapping_string(
        raw_record,
        "effective_to",
        f"{path}.effective_to",
    )
    published_at = _optional_mapping_string(
        raw_record,
        "published_at",
        f"{path}.published_at",
    )

    try:
        return ListingLifecycleRecord(
            security_id=security_id,
            state=state,
            time=TimeMetadata(
                fetched_at=fetched_at,
                published_at=published_at,
                effective_from=effective_from,
                effective_to=effective_to,
            ),
        )
    except (TypeError, ValueError) as exc:
        raise SecurityMasterSourceError(f"invalid {path}: {exc}") from exc


def _required_string(
    row: Mapping[str, object],
    field_name: str,
    index: int,
) -> str:
    value = row.get(field_name)
    path = f"securities[{index}].{field_name}"
    if not isinstance(value, str) or not value:
        raise SecurityMasterSourceError(f"{path} must be a non-empty string")
    return value


def _required_mapping_string(
    row: Mapping[str, object],
    field_name: str,
    path: str,
) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value:
        raise SecurityMasterSourceError(f"{path} must be a non-empty string")
    return value


def _optional_mapping_string(
    row: Mapping[str, object],
    field_name: str,
    path: str,
) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SecurityMasterSourceError(f"{path} must be None or non-empty string")
    return value


def _enum_value(enum_type, value: object, path: str):
    if not isinstance(value, str):
        raise SecurityMasterSourceError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise SecurityMasterSourceError(
            f"{path} has unsupported value {value!r}"
        ) from exc


def _validate_provider_id(provider_id: str) -> None:
    if not isinstance(provider_id, str):
        raise TypeError("provider_id must be a string")
    if not provider_id or provider_id != provider_id.strip().lower():
        raise ValueError("provider_id must be canonical lowercase token")


def _validate_nonempty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )
