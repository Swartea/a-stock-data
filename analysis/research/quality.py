"""Data-quality metadata contract for the Research Engine.

This module describes quality; it does not score data, choose providers, infer
freshness thresholds, or wire into the existing V3 pipeline.  Domain-specific
freshness policies belong in a later layer because quote, financial, macro, and
reference data have different expected update cadences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


_QUALITY_FLAG_RE = re.compile(
    r"^[a-z0-9][a-z0-9_]*(?:[.-][a-z0-9][a-z0-9_]*)*$"
)


class FreshnessStatus(str, Enum):
    """Whether a datum is timely under an explicitly supplied policy."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class CompletenessStatus(str, Enum):
    """Whether the expected business payload is present."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QualityMetadata:
    """Small immutable quality envelope independent from business scoring.

    ``degraded`` is deliberately independent from freshness and completeness.
    For example, a fallback source may be fresh and complete but still degraded,
    while a stale datum is not automatically marked degraded until a policy says
    so. ``quality_flags`` are stable machine-readable evidence tags.
    """

    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    completeness: CompletenessStatus = CompletenessStatus.UNKNOWN
    degraded: bool = False
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.freshness, FreshnessStatus):
            raise TypeError("freshness must be FreshnessStatus")
        if not isinstance(self.completeness, CompletenessStatus):
            raise TypeError("completeness must be CompletenessStatus")
        if not isinstance(self.degraded, bool):
            raise TypeError("degraded must be bool")
        if not isinstance(self.quality_flags, tuple):
            raise TypeError("quality_flags must be a tuple")

        seen: set[str] = set()
        for flag in self.quality_flags:
            if not isinstance(flag, str) or not flag:
                raise ValueError("quality flags must be non-empty strings")
            if flag != flag.strip() or flag != flag.lower():
                raise ValueError("quality flags must be canonical lowercase tokens")
            if not _QUALITY_FLAG_RE.fullmatch(flag):
                raise ValueError(f"invalid quality flag: {flag!r}")
            if flag in seen:
                raise ValueError(f"duplicate quality flag: {flag!r}")
            seen.add(flag)

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small public metadata surface."""

        return (
            "freshness",
            "completeness",
            "degraded",
            "quality_flags",
        )
