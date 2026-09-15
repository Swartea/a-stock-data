from dataclasses import FrozenInstanceError

import pytest

from analysis.research.trading_calendar import (
    TradingCalendar,
    TradingCalendarDay,
    TradingDayStatus,
)


def _day(date: str, status: TradingDayStatus) -> TradingCalendarDay:
    return TradingCalendarDay(date=date, status=status)


def test_trading_day_status_tokens_are_stable():
    assert TradingDayStatus.OPEN.value == "open"
    assert TradingDayStatus.CLOSED.value == "closed"
    assert TradingDayStatus.UNKNOWN.value == "unknown"


def test_calendar_day_preserves_three_state_open_semantics():
    assert _day("2026-09-14", TradingDayStatus.OPEN).is_open is True
    assert _day("2026-09-13", TradingDayStatus.CLOSED).is_open is False
    assert _day("2026-09-12", TradingDayStatus.UNKNOWN).is_open is None


def test_calendar_day_requires_enum_not_string_coercion():
    with pytest.raises(TypeError, match="status must be TradingDayStatus"):
        TradingCalendarDay(date="2026-09-14", status="open")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    ["", "2026-09-1", "2026/09/01", "2026-02-30", " 2026-09-01"],
)
def test_calendar_day_rejects_noncanonical_dates(value):
    with pytest.raises(ValueError):
        _day(value, TradingDayStatus.OPEN)


def test_calendar_requires_immutable_tuple_container():
    with pytest.raises(TypeError, match="days must be a tuple"):
        TradingCalendar(days=[_day("2026-09-14", TradingDayStatus.OPEN)])  # type: ignore[arg-type]


def test_calendar_requires_unique_strictly_ascending_dates():
    with pytest.raises(ValueError, match="unique and strictly ascending"):
        TradingCalendar(
            days=(
                _day("2026-09-15", TradingDayStatus.OPEN),
                _day("2026-09-14", TradingDayStatus.OPEN),
            )
        )

    with pytest.raises(ValueError, match="unique and strictly ascending"):
        TradingCalendar(
            days=(
                _day("2026-09-14", TradingDayStatus.OPEN),
                _day("2026-09-14", TradingDayStatus.CLOSED),
            )
        )


def test_status_lookup_returns_explicit_open_closed_and_unknown_rows():
    calendar = TradingCalendar(
        days=(
            _day("2026-09-12", TradingDayStatus.UNKNOWN),
            _day("2026-09-13", TradingDayStatus.CLOSED),
            _day("2026-09-14", TradingDayStatus.OPEN),
        )
    )

    assert calendar.status_on("2026-09-12") is TradingDayStatus.UNKNOWN
    assert calendar.status_on("2026-09-13") is TradingDayStatus.CLOSED
    assert calendar.status_on("2026-09-14") is TradingDayStatus.OPEN
    assert calendar.is_open_on("2026-09-12") is None
    assert calendar.is_open_on("2026-09-13") is False
    assert calendar.is_open_on("2026-09-14") is True


def test_missing_weekend_is_unknown_not_inferred_closed():
    calendar = TradingCalendar(
        days=(
            _day("2026-09-11", TradingDayStatus.OPEN),
            _day("2026-09-14", TradingDayStatus.OPEN),
        )
    )

    assert calendar.status_on("2026-09-12") is TradingDayStatus.UNKNOWN
    assert calendar.is_open_on("2026-09-12") is None


def test_empty_or_unpublished_calendar_keeps_dates_unknown():
    calendar = TradingCalendar()

    assert calendar.status_on("2027-01-01") is TradingDayStatus.UNKNOWN
    assert calendar.is_open_on("2027-01-01") is None


def test_missing_date_between_known_rows_stays_unknown():
    calendar = TradingCalendar(
        days=(
            _day("2026-09-14", TradingDayStatus.OPEN),
            _day("2026-09-16", TradingDayStatus.OPEN),
        )
    )

    assert calendar.status_on("2026-09-15") is TradingDayStatus.UNKNOWN


def test_lookup_rejects_invalid_date_instead_of_returning_unknown():
    calendar = TradingCalendar()

    with pytest.raises(ValueError):
        calendar.status_on("2026/09/15")


def test_calendar_contract_is_immutable():
    day = _day("2026-09-14", TradingDayStatus.OPEN)
    calendar = TradingCalendar(days=(day,))

    with pytest.raises(FrozenInstanceError):
        day.status = TradingDayStatus.CLOSED  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        calendar.days = ()  # type: ignore[misc]
