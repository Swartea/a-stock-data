"""Explicit time semantics for the Trading Research Engine.

The existing fetcher contract exposes ``as_of`` and ``fetched_at``.  That is
sufficient for the current V3 compatibility layer, but it is not sufficient for
point-in-time research because several distinct clocks can exist at once.

This module defines those clocks without wiring them into any existing fetcher,
pipeline, score, trading plan, or report.  In particular, no field is inferred
from another field: a financial period end is not a publication time, a fetch
time is not a data time, and a classification effective date is not a fetch
time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


TIME_FIELDS = (
    "fetched_at",
    "data_as_of",
    "period_start",
    "period_end",
    "published_at",
    "effective_from",
    "effective_to",
)

TIME_FIELD_SEMANTICS = {
    "fetched_at": "when this system retrieved the payload",
    "data_as_of": "the observation or snapshot time represented by the payload",
    "period_start": "start of the reporting or measurement period",
    "period_end": "end of the reporting or measurement period",
    "published_at": "when the information became publicly available",
    "effective_from": "when a classification or rule becomes effective",
    "effective_to": "when a classification or rule stops being effective",
}


@dataclass(frozen=True)
class TimeMetadata:
    """Serialization-friendly metadata for the seven research time semantics.

    ``fetched_at`` is required because the collector always knows when it made
    the observation.  The remaining fields are optional because many providers
    do not expose every clock.  Unknown values stay ``None``; callers must not
    invent them from adjacent fields.
    """

    fetched_at: str
    data_as_of: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    published_at: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_at, str) or not self.fetched_at.strip():
            raise ValueError("fetched_at must be a non-empty timestamp string")

        for field_name in TIME_FIELDS[1:]:
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string or None")

    def to_dict(self) -> dict[str, Optional[str]]:
        """Return the stable wire shape used by future DataEnvelope adapters."""
        return {field_name: getattr(self, field_name) for field_name in TIME_FIELDS}

    @classmethod
    def from_legacy(
        cls,
        *,
        fetched_at: str,
        as_of: Optional[str] = None,
    ) -> "TimeMetadata":
        """Adapt the current fetcher time fields without inventing semantics.

        The legacy ``as_of`` value maps only to ``data_as_of``.  It must not be
        copied into period, publication, or effective-time fields because the
        current contract does not prove those meanings.
        """
        return cls(fetched_at=fetched_at, data_as_of=as_of)
