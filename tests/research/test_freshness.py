from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from analysis.research.freshness import (
    FreshnessDecision,
    MaxAgePolicy,
    evaluate_freshness,
)
from analysis.research.quality import FreshnessStatus
from analysis.research.time_semantics import TimeMetadata


def _meta(*, data_as_of: str | None, fetched_at: str = "2026-09-15T22:00:00+08:00") -> TimeMetadata:
    return TimeMetadata(fetched_at=fetched_at, data_as_of=data_as_of)


def test_unknown_data_as_of_stays_unknown() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of=None),
        "2026-09-15T15:00:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision == FreshnessDecision(
        status=FreshnessStatus.UNKNOWN,
        reason="data_as_of_unknown",
        age=None,
    )


def test_age_below_max_age_is_fresh() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T14:56:00+08:00"),
        "2026-09-15T15:00:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision.status is FreshnessStatus.FRESH
    assert decision.reason == "within_max_age"
    assert decision.age == timedelta(minutes=4)


def test_exact_max_age_boundary_is_fresh() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T14:55:00+08:00"),
        "2026-09-15T15:00:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision.status is FreshnessStatus.FRESH
    assert decision.age == timedelta(minutes=5)


def test_age_above_max_age_is_stale() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T14:54:59+08:00"),
        "2026-09-15T15:00:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision.status is FreshnessStatus.STALE
    assert decision.reason == "exceeds_max_age"
    assert decision.age == timedelta(minutes=5, seconds=1)


def test_fetched_at_does_not_participate_in_freshness_age() -> None:
    decision = evaluate_freshness(
        _meta(
            data_as_of="2026-09-15T14:59:00+08:00",
            fetched_at="2026-09-16T09:00:00+08:00",
        ),
        "2026-09-15T15:00:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=2)),
    )

    assert decision.status is FreshnessStatus.FRESH
    assert decision.age == timedelta(minutes=1)


def test_future_data_as_of_is_rejected_instead_of_labeled_fresh() -> None:
    with pytest.raises(ValueError, match="evaluate PIT first"):
        evaluate_freshness(
            _meta(data_as_of="2026-09-15T15:00:01+08:00"),
            "2026-09-15T15:00:00+08:00",
            policy=MaxAgePolicy(timedelta(minutes=5)),
        )


def test_timezone_aware_values_compare_by_actual_instant() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T07:00:00+00:00"),
        "2026-09-15T15:03:00+08:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision.status is FreshnessStatus.FRESH
    assert decision.age == timedelta(minutes=3)


def test_iso_z_timestamp_is_supported() -> None:
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T07:00:00Z"),
        "2026-09-15T07:05:00+00:00",
        policy=MaxAgePolicy(timedelta(minutes=5)),
    )

    assert decision.status is FreshnessStatus.FRESH
    assert decision.age == timedelta(minutes=5)


def test_naive_and_aware_timestamps_cannot_be_mixed_silently() -> None:
    with pytest.raises(ValueError, match="compatible timezone semantics"):
        evaluate_freshness(
            _meta(data_as_of="2026-09-15T15:00:00"),
            "2026-09-15T15:01:00+08:00",
            policy=MaxAgePolicy(timedelta(minutes=5)),
        )


def test_invalid_evaluation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="ISO timestamp"):
        evaluate_freshness(
            _meta(data_as_of="2026-09-15T15:00:00+08:00"),
            "not-a-time",
            policy=MaxAgePolicy(timedelta(minutes=5)),
        )


def test_max_age_policy_requires_non_negative_timedelta() -> None:
    with pytest.raises(TypeError, match="timedelta"):
        MaxAgePolicy(5)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-negative"):
        MaxAgePolicy(timedelta(seconds=-1))


def test_evaluator_requires_explicit_policy_and_time_metadata() -> None:
    with pytest.raises(TypeError, match="metadata must be TimeMetadata"):
        evaluate_freshness(  # type: ignore[arg-type]
            {},
            "2026-09-15T15:00:00+08:00",
            policy=MaxAgePolicy(timedelta(minutes=5)),
        )

    with pytest.raises(TypeError, match="policy must be MaxAgePolicy"):
        evaluate_freshness(
            _meta(data_as_of="2026-09-15T15:00:00+08:00"),
            "2026-09-15T15:01:00+08:00",
            policy=timedelta(minutes=5),  # type: ignore[arg-type]
        )


def test_policy_and_decision_are_immutable() -> None:
    policy = MaxAgePolicy(timedelta(minutes=5))
    decision = evaluate_freshness(
        _meta(data_as_of="2026-09-15T14:59:00+08:00"),
        "2026-09-15T15:00:00+08:00",
        policy=policy,
    )

    with pytest.raises(FrozenInstanceError):
        policy.max_age = timedelta(minutes=10)  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed"  # type: ignore[misc]


def test_policy_contract_has_no_global_domain_or_provider_binding() -> None:
    policy = MaxAgePolicy(timedelta(days=1))

    for forbidden in (
        "provider",
        "provider_id",
        "capability_id",
        "domain",
        "source",
        "default_max_age",
        "trading_calendar",
    ):
        assert not hasattr(policy, forbidden)
