from dataclasses import FrozenInstanceError

import pytest

from analysis.research.pit_guard import PITStatus
from analysis.research.security_lifecycle import (
    ListingLifecycleRecord,
    ListingState,
    evaluate_listing_lifecycle,
)
from analysis.research.time_semantics import TimeMetadata


def _time(
    *,
    effective_from: str | None = "2020-01-01T00:00:00+08:00",
    effective_to: str | None = None,
    published_at: str | None = None,
) -> TimeMetadata:
    return TimeMetadata(
        fetched_at="2026-09-18T09:00:00+08:00",
        published_at=published_at,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _record(
    *,
    security_id: str = "cn.sse.600693",
    state: ListingState = ListingState.LISTED,
    time: TimeMetadata | None = None,
) -> ListingLifecycleRecord:
    return ListingLifecycleRecord(
        security_id=security_id,
        state=state,
        time=time or _time(),
    )


def test_listing_state_tokens_are_stable() -> None:
    assert ListingState.LISTED.value == "listed"
    assert ListingState.SUSPENDED.value == "suspended"
    assert ListingState.DELISTED.value == "delisted"


def test_listing_lifecycle_contract_surface_is_exact() -> None:
    assert ListingLifecycleRecord.contract_fields() == (
        "security_id",
        "state",
        "time",
    )


def test_listing_lifecycle_requires_explicit_effective_from() -> None:
    with pytest.raises(ValueError, match="requires effective_from"):
        _record(time=_time(effective_from=None))


def test_listing_lifecycle_rejects_raw_state_string() -> None:
    with pytest.raises(TypeError, match="state must be ListingState"):
        ListingLifecycleRecord(
            security_id="cn.sse.600693",
            state="listed",  # type: ignore[arg-type]
            time=_time(),
        )


@pytest.mark.parametrize(
    "security_id",
    (
        "",
        "CN.SSE.600693",
        " cn.sse.600693",
        "cn sse 600693",
    ),
)
def test_listing_lifecycle_rejects_noncanonical_security_id(
    security_id: str,
) -> None:
    with pytest.raises(ValueError):
        _record(security_id=security_id)


def test_listing_lifecycle_is_immutable() -> None:
    record = _record()

    with pytest.raises(FrozenInstanceError):
        record.state = ListingState.DELISTED  # type: ignore[misc]


def test_effective_interval_is_half_open() -> None:
    record = _record(
        time=_time(
            effective_from="2020-01-01T00:00:00+08:00",
            effective_to="2024-01-01T00:00:00+08:00",
        )
    )

    before = evaluate_listing_lifecycle(
        record,
        "2019-12-31T23:59:59+08:00",
    )
    at_start = evaluate_listing_lifecycle(
        record,
        "2020-01-01T00:00:00+08:00",
    )
    before_end = evaluate_listing_lifecycle(
        record,
        "2023-12-31T23:59:59+08:00",
    )
    at_end = evaluate_listing_lifecycle(
        record,
        "2024-01-01T00:00:00+08:00",
    )

    assert (before.status, before.reason) == (
        PITStatus.REJECT,
        "not_effective_yet",
    )
    assert (at_start.status, at_start.reason) == (
        PITStatus.ALLOW,
        "allowed",
    )
    assert (before_end.status, before_end.reason) == (
        PITStatus.ALLOW,
        "allowed",
    )
    assert (at_end.status, at_end.reason) == (
        PITStatus.REJECT,
        "no_longer_effective",
    )


def test_open_ended_delisted_state_can_remain_effective() -> None:
    record = _record(
        state=ListingState.DELISTED,
        time=_time(effective_from="2024-01-01T00:00:00+08:00"),
    )

    decision = evaluate_listing_lifecycle(
        record,
        "2026-09-18T09:00:00+08:00",
    )

    assert decision.status is PITStatus.ALLOW
    assert decision.reason == "allowed"


def test_listing_state_changes_do_not_change_security_id() -> None:
    listed = _record(
        state=ListingState.LISTED,
        time=_time(
            effective_from="2020-01-01T00:00:00+08:00",
            effective_to="2023-06-01T00:00:00+08:00",
        ),
    )
    suspended = _record(
        state=ListingState.SUSPENDED,
        time=_time(
            effective_from="2023-06-01T00:00:00+08:00",
            effective_to="2024-01-01T00:00:00+08:00",
        ),
    )
    delisted = _record(
        state=ListingState.DELISTED,
        time=_time(effective_from="2024-01-01T00:00:00+08:00"),
    )

    assert listed.security_id == suspended.security_id == delisted.security_id


def test_known_publication_after_decision_is_rejected_by_a5() -> None:
    record = _record(
        time=_time(
            effective_from="2024-01-01T00:00:00+08:00",
            published_at="2024-01-03T09:00:00+08:00",
        )
    )

    decision = evaluate_listing_lifecycle(
        record,
        "2024-01-02T09:00:00+08:00",
    )

    assert decision.status is PITStatus.REJECT
    assert decision.reason == "published_after_decision"


def test_fetched_at_does_not_define_listing_effective_time() -> None:
    record = _record(
        time=TimeMetadata(
            fetched_at="2026-09-18T09:00:00+08:00",
            effective_from="2020-01-01T00:00:00+08:00",
        )
    )

    decision = evaluate_listing_lifecycle(
        record,
        "2020-01-01T00:00:00+08:00",
    )

    assert decision.status is PITStatus.ALLOW


def test_lifecycle_contract_does_not_mix_provider_or_market_data_fields() -> None:
    forbidden = {
        "provider_id",
        "provider_symbol",
        "exchange",
        "local_code",
        "name",
        "price",
        "halt_reason",
        "is_trading",
    }

    assert forbidden.isdisjoint(ListingLifecycleRecord.contract_fields())


def test_evaluator_rejects_non_lifecycle_record() -> None:
    with pytest.raises(TypeError, match="record must be ListingLifecycleRecord"):
        evaluate_listing_lifecycle(  # type: ignore[arg-type]
            "cn.sse.600693",
            "2026-09-18T09:00:00+08:00",
        )
