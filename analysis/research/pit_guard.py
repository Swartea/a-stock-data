"""Point-in-time availability guard for the Research Engine.

This module answers one question only: could a datum have been used at a given
decision time without looking into the future?

It deliberately does not fetch data, infer missing timestamps, rank providers,
or wire into the existing V3 pipeline.  In particular, ``fetched_at`` and
``period_end`` never prove that information was publicly available at the
decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from analysis.research.time_semantics import TimeMetadata


class PITSupport(str, Enum):
    """Declared point-in-time capability of a source/dataset."""

    FULL = "full"
    BOUNDED = "bounded"
    SNAPSHOT_ONLY = "snapshot_only"
    NONE = "none"
    UNKNOWN = "unknown"


class PITStatus(str, Enum):
    """Outcome of a point-in-time availability check."""

    ALLOW = "allow"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PITDecision:
    """Explainable point-in-time decision with a stable reason code."""

    status: PITStatus
    reason: str

    @property
    def allowed(self) -> bool:
        return self.status is PITStatus.ALLOW


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


def _is_after(left: str, right: str, *, left_name: str, right_name: str) -> bool:
    left_dt = _parse_timestamp(left, field_name=left_name)
    right_dt = _parse_timestamp(right, field_name=right_name)

    if (left_dt.tzinfo is None) != (right_dt.tzinfo is None):
        raise ValueError(
            f"{left_name} and {right_name} must use compatible timezone semantics"
        )

    return left_dt > right_dt


def _is_at_or_after(
    left: str,
    right: str,
    *,
    left_name: str,
    right_name: str,
) -> bool:
    left_dt = _parse_timestamp(left, field_name=left_name)
    right_dt = _parse_timestamp(right, field_name=right_name)

    if (left_dt.tzinfo is None) != (right_dt.tzinfo is None):
        raise ValueError(
            f"{left_name} and {right_name} must use compatible timezone semantics"
        )

    return left_dt >= right_dt


def evaluate_pit(
    metadata: TimeMetadata,
    decision_time: str,
    *,
    pit_support: PITSupport = PITSupport.UNKNOWN,
    require_published_at: bool = False,
    require_effective_interval: bool = False,
    historical_query: bool = False,
) -> PITDecision:
    """Evaluate whether ``metadata`` is usable at ``decision_time``.

    Rules intentionally kept in this first A5 batch:

    * known ``published_at`` after the decision time is future leakage;
    * critical data may require ``published_at`` to be known;
    * known effective intervals must cover the decision time;
    * a required effective interval without ``effective_from`` is unknown;
    * snapshot-only / non-PIT sources cannot answer historical queries;
    * ``fetched_at`` and reporting-period timestamps are never substitutes for
      publication or effective timestamps.

    ``effective_to`` is interpreted as an exclusive upper bound: the datum is
    no longer effective at exactly ``effective_to``.
    """
    if not isinstance(metadata, TimeMetadata):
        raise TypeError("metadata must be TimeMetadata")
    if not isinstance(pit_support, PITSupport):
        raise TypeError("pit_support must be PITSupport")

    _parse_timestamp(decision_time, field_name="decision_time")

    if historical_query and pit_support is PITSupport.NONE:
        return PITDecision(PITStatus.REJECT, "pit_not_supported")
    if historical_query and pit_support is PITSupport.SNAPSHOT_ONLY:
        return PITDecision(PITStatus.REJECT, "snapshot_only_historical")

    if metadata.published_at is not None:
        if _is_after(
            metadata.published_at,
            decision_time,
            left_name="published_at",
            right_name="decision_time",
        ):
            return PITDecision(PITStatus.REJECT, "published_after_decision")
    elif require_published_at:
        return PITDecision(PITStatus.UNKNOWN, "publication_unknown")

    if metadata.effective_from is not None and _is_after(
        metadata.effective_from,
        decision_time,
        left_name="effective_from",
        right_name="decision_time",
    ):
        return PITDecision(PITStatus.REJECT, "not_effective_yet")

    if metadata.effective_to is not None and _is_at_or_after(
        decision_time,
        metadata.effective_to,
        left_name="decision_time",
        right_name="effective_to",
    ):
        return PITDecision(PITStatus.REJECT, "no_longer_effective")

    if require_effective_interval and metadata.effective_from is None:
        return PITDecision(PITStatus.UNKNOWN, "effective_from_unknown")

    return PITDecision(PITStatus.ALLOW, "allowed")
