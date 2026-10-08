"""Offline contract tests for the S4 market-state composition.

Every date and timestamp below is a **synthetic contract fixture** chosen to make
the state machine observable.  None of them is a claim about any real exchange's
trading hours, holidays, or observed data, and no test here states that a date
was a weekday, a holiday, or a session that actually opened.

No network, no clock, no provider, and no runtime wiring is involved: the
module under test is pure, and these tests exercise it entirely offline.
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import timedelta
from typing import Any, Final

import pytest

from analysis.research.freshness import FreshnessDecision, MaxAgePolicy
from analysis.research.market_state import MarketStateDecision, evaluate_market_state
from analysis.research.quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import (
    TradingCalendar,
    TradingCalendarDay,
    TradingDayStatus,
)

# --- synthetic contract fixtures -------------------------------------------

SYNTHETIC_DATE: Final = "2026-09-14"
SYNTHETIC_NEXT_DATE: Final = "2026-09-15"
SYNTHETIC_OTHER_DATE: Final = "2026-09-11"
SYNTHETIC_EVAL_TIME: Final = "2026-09-14T15:00:00+08:00"


def _day(date: str, status: TradingDayStatus) -> TradingCalendarDay:
    return TradingCalendarDay(date=date, status=status)


def _time(
    *,
    data_as_of: str | None,
    fetched_at: str = "2026-09-14T14:59:00+08:00",
    **extra: str,
) -> TimeMetadata:
    return TimeMetadata(fetched_at=fetched_at, data_as_of=data_as_of, **extra)


def _quality(**overrides: Any) -> QualityMetadata:
    base: dict[str, Any] = {
        "freshness": FreshnessStatus.UNKNOWN,
        "completeness": CompletenessStatus.COMPLETE,
        "degraded": False,
        "quality_flags": (),
    }
    base.update(overrides)
    return QualityMetadata(**base)


_DEFAULT_CALENDAR: Final = TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.OPEN),))


def _evaluate(**overrides: Any) -> MarketStateDecision:
    """Call the evaluator with synthetic defaults, overriding what a test needs."""

    kwargs: dict[str, Any] = {
        "calendar_date": SYNTHETIC_DATE,
        "calendar": _DEFAULT_CALENDAR,
        "time": _time(data_as_of="2026-09-14T14:58:00+08:00"),
        "evaluation_time": SYNTHETIC_EVAL_TIME,
        "policy": MaxAgePolicy(timedelta(minutes=5)),
        "quality": _quality(),
    }
    kwargs.update(overrides)
    return evaluate_market_state(**kwargs)


# --- explicit calendar rows -------------------------------------------------


def test_explicit_open_row_is_preserved_exactly() -> None:
    decision = _evaluate()

    assert decision.trading_day_status is TradingDayStatus.OPEN
    assert decision.calendar_reason == "calendar_row_explicitly_open"
    assert decision.calendar_date == SYNTHETIC_DATE


def test_explicit_closed_row_is_preserved_exactly() -> None:
    decision = _evaluate(
        calendar=TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.CLOSED),))
    )

    assert decision.trading_day_status is TradingDayStatus.CLOSED
    assert decision.calendar_reason == "calendar_row_explicitly_closed"


def test_closed_row_is_not_upgraded_by_a_later_evaluation_time() -> None:
    """A closed date stays closed; no session-hours reasoning is applied."""

    decision = _evaluate(
        calendar=TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.CLOSED),)),
        evaluation_time="2026-09-14T15:00:00+08:00",
    )

    assert decision.trading_day_status is TradingDayStatus.CLOSED
    assert decision.freshness.status is FreshnessStatus.FRESH


# --- the four UNKNOWN causes -----------------------------------------------


def test_missing_calendar_returns_unknown() -> None:
    decision = _evaluate(calendar=None)

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_not_supplied"


def test_empty_calendar_returns_unknown() -> None:
    decision = _evaluate(calendar=TradingCalendar())

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_has_no_observations"


def test_unobserved_date_returns_unknown() -> None:
    calendar = TradingCalendar(
        days=(
            _day(SYNTHETIC_OTHER_DATE, TradingDayStatus.OPEN),
            _day(SYNTHETIC_NEXT_DATE, TradingDayStatus.OPEN),
        )
    )

    decision = _evaluate(calendar=calendar)

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_date_not_observed"


def test_explicit_unknown_row_returns_unknown() -> None:
    calendar = TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.UNKNOWN),))

    decision = _evaluate(calendar=calendar)

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_row_explicitly_unknown"


def test_four_unknown_causes_are_distinct() -> None:
    decisions = (
        _evaluate(calendar=None),
        _evaluate(calendar=TradingCalendar()),
        _evaluate(
            calendar=TradingCalendar(days=(_day(SYNTHETIC_NEXT_DATE, TradingDayStatus.OPEN),))
        ),
        _evaluate(
            calendar=TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.UNKNOWN),))
        ),
    )

    reasons = [decision.calendar_reason for decision in decisions]
    assert all(
        decision.trading_day_status is TradingDayStatus.UNKNOWN for decision in decisions
    )
    assert len(set(reasons)) == 4
    assert all(reason for reason in reasons)


# --- calendar-date validation ----------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "2026-9-14", "2026/09/14", "2026-13-01", "2026-02-30", " 2026-09-14", "2026-09-14 "],
)
def test_calendar_date_must_be_canonical_iso(value: str) -> None:
    with pytest.raises(ValueError):
        _evaluate(calendar_date=value)


def test_calendar_date_rejects_a_timestamp_instead_of_a_date() -> None:
    with pytest.raises(ValueError):
        _evaluate(calendar_date="2026-09-14T00:00:00+08:00")


def test_calendar_date_must_be_a_string() -> None:
    with pytest.raises(TypeError, match="calendar_date must be a string"):
        _evaluate(calendar_date=20260914)  # type: ignore[arg-type]


def test_calendar_date_is_validated_even_without_a_calendar() -> None:
    with pytest.raises(ValueError):
        _evaluate(calendar=None, calendar_date="2026/09/14")


# --- required, explicit, keyword-only inputs --------------------------------


def test_every_input_is_required() -> None:
    with pytest.raises(TypeError, match="calendar_date"):
        evaluate_market_state()  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="calendar"):
        evaluate_market_state(calendar_date=SYNTHETIC_DATE)  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="policy"):
        evaluate_market_state(calendar_date=SYNTHETIC_DATE, calendar=None)  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="quality"):
        evaluate_market_state(  # type: ignore[call-arg]
            calendar_date=SYNTHETIC_DATE,
            calendar=None,
            time=_time(data_as_of="2026-09-14T14:58:00+08:00"),
            evaluation_time=SYNTHETIC_EVAL_TIME,
            policy=MaxAgePolicy(timedelta(minutes=5)),
        )


def test_inputs_cannot_be_passed_positionally() -> None:
    with pytest.raises(TypeError):
        evaluate_market_state(SYNTHETIC_DATE)  # type: ignore[misc]


def test_signature_has_no_defaults() -> None:
    parameters = inspect.signature(evaluate_market_state).parameters
    assert set(parameters) == {
        "calendar_date",
        "calendar",
        "time",
        "evaluation_time",
        "policy",
        "quality",
    }
    assert all(
        parameter.default is inspect.Parameter.empty for parameter in parameters.values()
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    )


# --- type gates -------------------------------------------------------------


def test_type_gates_reject_wrong_input_types() -> None:
    with pytest.raises(TypeError, match="time must be TimeMetadata"):
        _evaluate(time={})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="policy must be MaxAgePolicy"):
        _evaluate(policy=timedelta(minutes=5))  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="quality must be QualityMetadata"):
        _evaluate(quality={"freshness": "fresh"})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="calendar must be TradingCalendar or None"):
        _evaluate(calendar=[_day(SYNTHETIC_DATE, TradingDayStatus.OPEN)])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="evaluation_time must be a string"):
        _evaluate(evaluation_time=1757881200)  # type: ignore[arg-type]


def test_empty_evaluation_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        _evaluate(evaluation_time="   ")


# --- no calendar inference from either clock -------------------------------


def test_calendar_is_not_inferred_from_the_evaluation_time_date() -> None:
    """evaluation_time sits on an OPEN row, but the requested date is unobserved."""

    calendar = TradingCalendar(days=(_day(SYNTHETIC_NEXT_DATE, TradingDayStatus.OPEN),))

    decision = _evaluate(
        calendar=calendar,
        calendar_date=SYNTHETIC_DATE,
        evaluation_time="2026-09-15T10:00:00+08:00",
    )

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_date_not_observed"


def test_calendar_is_not_inferred_from_data_as_of_or_fetched_at() -> None:
    """Both clocks point at an OPEN row; the requested date is still unobserved."""

    calendar = TradingCalendar(days=(_day(SYNTHETIC_NEXT_DATE, TradingDayStatus.OPEN),))

    decision = _evaluate(
        calendar=calendar,
        calendar_date=SYNTHETIC_DATE,
        evaluation_time="2026-09-15T10:00:00+08:00",
        time=_time(
            data_as_of="2026-09-15T09:55:00+08:00",
            fetched_at="2026-09-15T09:58:00+08:00",
        ),
    )

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.calendar_reason == "calendar_date_not_observed"


def test_calendar_date_is_never_used_as_an_observation_clock() -> None:
    """A date-only calendar_date cannot rescue a missing data_as_of."""

    decision = _evaluate(calendar_date="2026-09-14", time=_time(data_as_of=None))

    assert decision.trading_day_status is TradingDayStatus.OPEN
    assert decision.freshness.status is FreshnessStatus.UNKNOWN
    assert decision.freshness.reason == "data_as_of_unknown"


# --- data_as_of and fetched_at stay distinct -------------------------------


def test_data_as_of_and_fetched_at_are_not_interchangeable() -> None:
    """A fresh fetched_at must not rescue a stale data_as_of."""

    decision = _evaluate(
        time=_time(
            data_as_of="2026-09-14T14:00:00+08:00",
            fetched_at="2026-09-14T14:59:00+08:00",
        )
    )

    assert decision.freshness.status is FreshnessStatus.STALE
    assert decision.freshness.age == timedelta(hours=1)
    assert decision.quality.freshness is FreshnessStatus.STALE


# --- freshness outcomes -----------------------------------------------------


def test_fresh_observation_is_fresh() -> None:
    decision = _evaluate(time=_time(data_as_of="2026-09-14T14:56:00+08:00"))

    assert decision.freshness.status is FreshnessStatus.FRESH
    assert decision.freshness.reason == "within_max_age"
    assert decision.quality.freshness is FreshnessStatus.FRESH


def test_exact_max_age_boundary_stays_inclusive() -> None:
    decision = _evaluate(time=_time(data_as_of="2026-09-14T14:55:00+08:00"))

    assert decision.freshness.status is FreshnessStatus.FRESH
    assert decision.freshness.age == timedelta(minutes=5)


def test_stale_observation_is_stale() -> None:
    decision = _evaluate(time=_time(data_as_of="2026-09-14T14:54:59+08:00"))

    assert decision.freshness.status is FreshnessStatus.STALE
    assert decision.freshness.reason == "exceeds_max_age"
    assert decision.freshness.age == timedelta(minutes=5, seconds=1)


def test_missing_data_as_of_stays_unknown_and_reaches_quality() -> None:
    decision = _evaluate(time=_time(data_as_of=None))

    assert decision.freshness == FreshnessDecision(
        status=FreshnessStatus.UNKNOWN,
        reason="data_as_of_unknown",
        age=None,
    )
    assert decision.quality.freshness is FreshnessStatus.UNKNOWN


def test_no_other_time_field_can_substitute_for_data_as_of() -> None:
    decision = _evaluate(
        time=TimeMetadata(
            fetched_at="2026-09-14T14:59:00+08:00",
            data_as_of=None,
            period_start="2026-09-01T00:00:00+08:00",
            period_end="2026-09-14T14:00:00+08:00",
            published_at="2026-09-14T14:30:00+08:00",
            effective_from="2026-09-14T14:40:00+08:00",
            effective_to="2026-09-14T14:50:00+08:00",
        )
    )

    assert decision.freshness.status is FreshnessStatus.UNKNOWN
    assert decision.freshness.age is None


# --- propagated freshness errors, including date-only semantics -------------


def test_future_data_as_of_error_propagates_untranslated() -> None:
    with pytest.raises(ValueError, match="evaluate PIT first"):
        _evaluate(time=_time(data_as_of="2026-09-14T15:00:01+08:00"))


def test_naive_and_aware_mismatch_propagates_untranslated() -> None:
    with pytest.raises(ValueError, match="compatible timezone semantics"):
        _evaluate(time=_time(data_as_of="2026-09-14T14:58:00"))


def test_invalid_evaluation_time_propagates_untranslated() -> None:
    with pytest.raises(ValueError, match="ISO timestamp"):
        _evaluate(evaluation_time="not-a-timestamp")


def test_date_only_data_as_of_is_not_given_an_invented_timezone() -> None:
    """A date-only observation must not be silently upgraded to an aware instant."""

    with pytest.raises(ValueError, match="compatible timezone semantics"):
        _evaluate(time=_time(data_as_of="2026-09-14"))


def test_date_only_data_as_of_keeps_its_own_meaning_with_a_naive_clock() -> None:
    decision = _evaluate(
        time=_time(data_as_of="2026-09-14"),
        evaluation_time="2026-09-14T15:00:00",
    )

    # 00:00 -> 15:00 is fifteen hours, not "just refreshed at midnight-ish" and
    # not a synthesized close-of-day stamp, so the 5-minute policy sees it stale.
    assert decision.freshness.age == timedelta(hours=15)
    assert decision.freshness.status is FreshnessStatus.STALE


# --- quality composition ----------------------------------------------------


def test_quality_fields_are_preserved_verbatim() -> None:
    quality = _quality(
        completeness=CompletenessStatus.PARTIAL,
        degraded=True,
        quality_flags=("source_fallback", "pit_review"),
    )

    decision = _evaluate(quality=quality)

    assert decision.quality.completeness is CompletenessStatus.PARTIAL
    assert decision.quality.degraded is True
    assert decision.quality.quality_flags == ("source_fallback", "pit_review")
    # The input envelope is untouched.
    assert quality.freshness is FreshnessStatus.UNKNOWN
    assert quality.quality_flags == ("source_fallback", "pit_review")


def test_quality_freshness_is_taken_from_the_freshness_decision() -> None:
    fresh = _evaluate(
        quality=_quality(freshness=FreshnessStatus.STALE),
        time=_time(data_as_of="2026-09-14T14:58:00+08:00"),
    )
    assert fresh.quality.freshness is FreshnessStatus.FRESH

    stale = _evaluate(
        quality=_quality(freshness=FreshnessStatus.FRESH),
        time=_time(data_as_of="2026-09-14T14:00:00+08:00"),
    )
    assert stale.quality.freshness is FreshnessStatus.STALE


def test_closed_calendar_does_not_change_completeness_degraded_or_flags() -> None:
    decision = _evaluate(
        calendar=TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.CLOSED),)),
        quality=_quality(quality_flags=("session_rest",)),
    )

    assert decision.trading_day_status is TradingDayStatus.CLOSED
    assert decision.quality.completeness is CompletenessStatus.COMPLETE
    assert decision.quality.degraded is False
    assert decision.quality.quality_flags == ("session_rest",)


def test_unknown_calendar_and_stale_data_do_not_change_quality_fields() -> None:
    decision = _evaluate(
        calendar=None,
        time=_time(data_as_of="2026-09-14T14:00:00+08:00"),
        quality=_quality(
            completeness=CompletenessStatus.PARTIAL,
            degraded=False,
            quality_flags=(),
        ),
    )

    assert decision.trading_day_status is TradingDayStatus.UNKNOWN
    assert decision.quality.freshness is FreshnessStatus.STALE
    assert decision.quality.completeness is CompletenessStatus.PARTIAL
    assert decision.quality.degraded is False
    assert decision.quality.quality_flags == ()


# --- calendar and freshness are independent ---------------------------------


def test_freshness_varies_while_calendar_state_holds() -> None:
    calendar = _DEFAULT_CALENDAR
    fresh = _evaluate(calendar=calendar, time=_time(data_as_of="2026-09-14T14:58:00+08:00"))
    stale = _evaluate(calendar=calendar, time=_time(data_as_of="2026-09-14T13:00:00+08:00"))

    assert fresh.trading_day_status is stale.trading_day_status is TradingDayStatus.OPEN
    assert fresh.calendar_reason == stale.calendar_reason
    assert fresh.freshness.status is FreshnessStatus.FRESH
    assert stale.freshness.status is FreshnessStatus.STALE


def test_calendar_varies_while_freshness_holds() -> None:
    time = _time(data_as_of="2026-09-14T14:58:00+08:00")
    open_decision = _evaluate(calendar=_DEFAULT_CALENDAR, time=time)
    closed_decision = _evaluate(
        calendar=TradingCalendar(days=(_day(SYNTHETIC_DATE, TradingDayStatus.CLOSED),)),
        time=time,
    )

    assert open_decision.freshness == closed_decision.freshness
    assert open_decision.quality == closed_decision.quality
    assert open_decision.trading_day_status is TradingDayStatus.OPEN
    assert closed_decision.trading_day_status is TradingDayStatus.CLOSED


# --- immutability, echoing, and the result contract -------------------------


def test_decision_echoes_its_explicit_inputs() -> None:
    time = _time(data_as_of="2026-09-14T14:58:00+08:00")
    policy = MaxAgePolicy(timedelta(minutes=5))
    quality = _quality()

    decision = _evaluate(time=time, policy=policy, quality=quality)

    assert decision.time is time
    assert decision.policy is policy
    assert decision.evaluation_time == SYNTHETIC_EVAL_TIME
    assert decision.calendar_date == SYNTHETIC_DATE


def test_inputs_are_not_mutated() -> None:
    time = _time(data_as_of="2026-09-14T14:58:00+08:00")
    policy = MaxAgePolicy(timedelta(minutes=5))
    quality = _quality(quality_flags=("source_fallback",))
    calendar = _DEFAULT_CALENDAR
    before = (time.to_dict(), policy.max_age, quality, calendar)

    _evaluate(time=time, policy=policy, quality=quality, calendar=calendar)

    assert (time.to_dict(), policy.max_age, quality, calendar) == before


def test_decision_is_frozen() -> None:
    decision = _evaluate()

    with pytest.raises(FrozenInstanceError):
        decision.calendar_reason = "changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        decision.trading_day_status = TradingDayStatus.CLOSED  # type: ignore[misc]


def test_decision_contract_surface_is_small_and_evidence_only() -> None:
    assert MarketStateDecision.contract_fields() == (
        "calendar_date",
        "trading_day_status",
        "calendar_reason",
        "time",
        "evaluation_time",
        "policy",
        "freshness",
        "quality",
    )


def test_decision_carries_no_runtime_or_clock_binding() -> None:
    decision = _evaluate()

    for forbidden in (
        "provider",
        "provider_id",
        "capability_id",
        "session",
        "is_market_open",
        "now",
        "current_time",
        "fetch",
        "http",
        "pit_status",
        "availability",
    ):
        assert not hasattr(decision, forbidden)


def test_decision_rejects_inconsistent_quality_freshness() -> None:
    freshness = FreshnessDecision(
        status=FreshnessStatus.FRESH,
        reason="within_max_age",
        age=timedelta(minutes=2),
    )

    with pytest.raises(ValueError, match="quality.freshness must equal freshness.status"):
        MarketStateDecision(
            calendar_date=SYNTHETIC_DATE,
            trading_day_status=TradingDayStatus.OPEN,
            calendar_reason="calendar_row_explicitly_open",
            time=_time(data_as_of="2026-09-14T14:58:00+08:00"),
            evaluation_time=SYNTHETIC_EVAL_TIME,
            policy=MaxAgePolicy(timedelta(minutes=5)),
            freshness=freshness,
            quality=_quality(freshness=FreshnessStatus.STALE),
        )


def test_decision_rejects_a_reason_that_does_not_match_its_status() -> None:
    with pytest.raises(ValueError, match="unknown trading_day_status requires"):
        MarketStateDecision(
            calendar_date=SYNTHETIC_DATE,
            trading_day_status=TradingDayStatus.UNKNOWN,
            calendar_reason="calendar_row_explicitly_open",
            time=_time(data_as_of=None),
            evaluation_time=SYNTHETIC_EVAL_TIME,
            policy=MaxAgePolicy(timedelta(minutes=5)),
            freshness=FreshnessDecision(
                status=FreshnessStatus.UNKNOWN,
                reason="data_as_of_unknown",
                age=None,
            ),
            quality=_quality(),
        )

    with pytest.raises(ValueError, match="open requires calendar_reason"):
        MarketStateDecision(
            calendar_date=SYNTHETIC_DATE,
            trading_day_status=TradingDayStatus.OPEN,
            calendar_reason="calendar_not_supplied",
            time=_time(data_as_of=None),
            evaluation_time=SYNTHETIC_EVAL_TIME,
            policy=MaxAgePolicy(timedelta(minutes=5)),
            freshness=FreshnessDecision(
                status=FreshnessStatus.UNKNOWN,
                reason="data_as_of_unknown",
                age=None,
            ),
            quality=_quality(),
        )


def test_decision_type_gates() -> None:
    freshness = FreshnessDecision(
        status=FreshnessStatus.FRESH,
        reason="within_max_age",
        age=timedelta(minutes=2),
    )
    base: dict[str, Any] = {
        "calendar_date": SYNTHETIC_DATE,
        "trading_day_status": TradingDayStatus.OPEN,
        "calendar_reason": "calendar_row_explicitly_open",
        "time": _time(data_as_of="2026-09-14T14:58:00+08:00"),
        "evaluation_time": SYNTHETIC_EVAL_TIME,
        "policy": MaxAgePolicy(timedelta(minutes=5)),
        "freshness": freshness,
        "quality": _quality(freshness=FreshnessStatus.FRESH),
    }

    with pytest.raises(TypeError, match="trading_day_status must be TradingDayStatus"):
        MarketStateDecision(**{**base, "trading_day_status": "open"})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="freshness must be FreshnessDecision"):
        MarketStateDecision(**{**base, "freshness": {}})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="quality must be QualityMetadata"):
        MarketStateDecision(**{**base, "quality": None})  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="calendar_date"):
        MarketStateDecision(**{**base, "calendar_date": "2026/09/14"})

    with pytest.raises(ValueError, match="calendar_reason must be a non-empty trimmed string"):
        MarketStateDecision(**{**base, "calendar_reason": "  "})
