import pytest

from analysis.research.pit_guard import (
    PITStatus,
    PITSupport,
    evaluate_pit,
)
from analysis.research.time_semantics import TimeMetadata


def test_published_after_decision_is_rejected():
    metadata = TimeMetadata(
        fetched_at="2026-04-30T18:00:00+08:00",
        period_end="2026-03-31",
        published_at="2026-04-30T17:00:00+08:00",
    )

    decision = evaluate_pit(metadata, "2026-04-30T16:00:00+08:00")

    assert decision.status is PITStatus.REJECT
    assert decision.reason == "published_after_decision"
    assert decision.allowed is False


def test_fetch_time_after_decision_does_not_create_future_leakage():
    metadata = TimeMetadata(
        fetched_at="2026-09-15T21:00:00+08:00",
        data_as_of="2026-04-30T15:00:00+08:00",
        published_at="2026-04-30T15:30:00+08:00",
    )

    decision = evaluate_pit(metadata, "2026-04-30T16:00:00+08:00")

    assert decision == type(decision)(PITStatus.ALLOW, "allowed")


def test_period_end_never_substitutes_for_missing_publication_time():
    metadata = TimeMetadata(
        fetched_at="2026-04-30T15:00:00+08:00",
        period_start="2026-01-01",
        period_end="2026-03-31",
        published_at=None,
    )

    decision = evaluate_pit(
        metadata,
        "2026-04-30T16:00:00+08:00",
        require_published_at=True,
    )

    assert decision.status is PITStatus.UNKNOWN
    assert decision.reason == "publication_unknown"


def test_unknown_publication_can_be_allowed_when_policy_does_not_require_it():
    metadata = TimeMetadata(
        fetched_at="2026-04-30T15:00:00+08:00",
        published_at=None,
    )

    decision = evaluate_pit(metadata, "2026-04-30T16:00:00+08:00")

    assert decision.status is PITStatus.ALLOW


def test_effective_from_after_decision_is_rejected():
    metadata = TimeMetadata(
        fetched_at="2026-01-01",
        effective_from="2026-07-01",
    )

    decision = evaluate_pit(metadata, "2026-06-30")

    assert decision.status is PITStatus.REJECT
    assert decision.reason == "not_effective_yet"


def test_effective_to_is_an_exclusive_upper_bound():
    metadata = TimeMetadata(
        fetched_at="2026-01-01",
        effective_from="2026-01-01",
        effective_to="2026-07-01",
    )

    before = evaluate_pit(metadata, "2026-06-30")
    at_end = evaluate_pit(metadata, "2026-07-01")

    assert before.status is PITStatus.ALLOW
    assert at_end.status is PITStatus.REJECT
    assert at_end.reason == "no_longer_effective"


def test_required_effective_interval_without_start_is_unknown():
    metadata = TimeMetadata(
        fetched_at="2026-01-01",
        effective_from=None,
        effective_to=None,
    )

    decision = evaluate_pit(
        metadata,
        "2026-06-30",
        require_effective_interval=True,
    )

    assert decision.status is PITStatus.UNKNOWN
    assert decision.reason == "effective_from_unknown"


def test_open_ended_effective_interval_can_cover_decision_time():
    metadata = TimeMetadata(
        fetched_at="2026-01-01",
        effective_from="2026-01-01",
        effective_to=None,
    )

    decision = evaluate_pit(
        metadata,
        "2026-06-30",
        require_effective_interval=True,
    )

    assert decision.status is PITStatus.ALLOW


@pytest.mark.parametrize(
    ("support", "reason"),
    (
        (PITSupport.SNAPSHOT_ONLY, "snapshot_only_historical"),
        (PITSupport.NONE, "pit_not_supported"),
    ),
)
def test_non_historical_sources_cannot_answer_historical_queries(support, reason):
    metadata = TimeMetadata(fetched_at="2026-09-15")

    decision = evaluate_pit(
        metadata,
        "2025-12-31",
        pit_support=support,
        historical_query=True,
    )

    assert decision.status is PITStatus.REJECT
    assert decision.reason == reason


def test_snapshot_only_source_is_not_rejected_for_non_historical_use_by_support_alone():
    metadata = TimeMetadata(fetched_at="2026-09-15")

    decision = evaluate_pit(
        metadata,
        "2026-09-15",
        pit_support=PITSupport.SNAPSHOT_ONLY,
        historical_query=False,
    )

    assert decision.status is PITStatus.ALLOW


def test_iso_z_timestamps_are_supported():
    metadata = TimeMetadata(
        fetched_at="2026-04-30T16:00:00Z",
        published_at="2026-04-30T15:00:00Z",
    )

    decision = evaluate_pit(metadata, "2026-04-30T16:00:00Z")

    assert decision.status is PITStatus.ALLOW


def test_timezone_aware_and_naive_values_cannot_be_compared_silently():
    metadata = TimeMetadata(
        fetched_at="2026-04-30",
        published_at="2026-04-30T15:00:00+08:00",
    )

    with pytest.raises(ValueError, match="compatible timezone semantics"):
        evaluate_pit(metadata, "2026-04-30T16:00:00")


def test_invalid_metadata_or_support_type_is_rejected():
    with pytest.raises(TypeError):
        evaluate_pit({}, "2026-01-01")  # type: ignore[arg-type]

    metadata = TimeMetadata(fetched_at="2026-01-01")
    with pytest.raises(TypeError):
        evaluate_pit(metadata, "2026-01-01", pit_support="full")  # type: ignore[arg-type]
