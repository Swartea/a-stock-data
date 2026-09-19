"""Explicit max-age freshness evaluation for the Research Engine.

Freshness is policy-dependent.  This module deliberately requires callers to
supply a ``MaxAgePolicy`` instead of defining one global threshold for quotes,
daily bars, financial statements, macro data, or reference data.

The evaluator uses ``TimeMetadata.data_as_of`` as the observation clock.  It
never substitutes ``fetched_at`` or reporting-period timestamps for that clock,
and it does not decide point-in-time availability; future observations belong
to the A5 PIT guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from analysis.research.quality import FreshnessStatus
from analysis.research.time_semantics import TimeMetadata


@dataclass(frozen=True)
class MaxAgePolicy:
    """Wall-clock freshness policy with an explicit maximum observation age."""

    max_age: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.max_age, timedelta):
            raise TypeError("max_age must be datetime.timedelta")
        if self.max_age < timedelta(0):
            raise ValueError("max_age must be non-negative")


@dataclass(frozen=True)
class FreshnessDecision:
    """Explainable freshness outcome under one explicit policy."""

    status: FreshnessStatus
    reason: str
    age: timedelta | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, FreshnessStatus):
            raise TypeError("status must be FreshnessStatus")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")
        if self.age is not None and not isinstance(self.age, timedelta):
            raise TypeError("age must be datetime.timedelta or None")


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO timestamp string")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp string") from exc


def evaluate_freshness(
    metadata: TimeMetadata,
    evaluation_time: str,
    *,
    policy: MaxAgePolicy,
) -> FreshnessDecision:
    """Evaluate observation freshness using an explicitly supplied max age.

    Rules:

    * unknown ``data_as_of`` remains ``UNKNOWN``;
    * ``age <= max_age`` is ``FRESH`` (the boundary is inclusive);
    * ``age > max_age`` is ``STALE``;
    * ``fetched_at`` does not participate in freshness age calculation;
    * future ``data_as_of`` values are rejected rather than mislabeled fresh;
    * naive and timezone-aware timestamps must not be mixed silently.

    This is deliberately wall-clock based.  Trading-calendar-aware policies can
    be added later after B1 Trading Calendar without changing this contract.
    """
    if not isinstance(metadata, TimeMetadata):
        raise TypeError("metadata must be TimeMetadata")
    if not isinstance(policy, MaxAgePolicy):
        raise TypeError("policy must be MaxAgePolicy")

    evaluation_dt = _parse_timestamp(evaluation_time, field_name="evaluation_time")

    if metadata.data_as_of is None:
        return FreshnessDecision(
            status=FreshnessStatus.UNKNOWN,
            reason="data_as_of_unknown",
            age=None,
        )

    data_dt = _parse_timestamp(metadata.data_as_of, field_name="data_as_of")
    if (data_dt.tzinfo is None) != (evaluation_dt.tzinfo is None):
        raise ValueError(
            "data_as_of and evaluation_time must use compatible timezone semantics"
        )

    age = evaluation_dt - data_dt
    if age < timedelta(0):
        raise ValueError(
            "data_as_of must not be after evaluation_time; evaluate PIT first"
        )

    if age <= policy.max_age:
        return FreshnessDecision(
            status=FreshnessStatus.FRESH,
            reason="within_max_age",
            age=age,
        )

    return FreshnessDecision(
        status=FreshnessStatus.STALE,
        reason="exceeds_max_age",
        age=age,
    )
