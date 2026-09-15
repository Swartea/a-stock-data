from calendar import monthrange

import pytest

from analysis.research.trading_calendar import TradingDayStatus
from analysis.research.trading_calendar_szse import trading_calendar_from_szse_rows


def _rows(year: int = 2024, month: int = 2):
    count = monthrange(year, month)[1]
    return [
        {
            "jyrq": f"{year:04d}-{month:02d}-{day:02d}",
            "jybz": "0" if day == 19 else "1",
        }
        for day in range(1, count + 1)
    ]


def test_normalizes_complete_leap_month_and_preserves_flags():
    calendar = trading_calendar_from_szse_rows(_rows(), year=2024, month=2)

    assert len(calendar.days) == 29
    assert calendar.status_on("2024-02-01") is TradingDayStatus.OPEN
    assert calendar.status_on("2024-02-19") is TradingDayStatus.CLOSED


def test_input_order_does_not_change_normalized_order():
    calendar = trading_calendar_from_szse_rows(
        list(reversed(_rows())), year=2024, month=2
    )

    assert calendar.days[0].date == "2024-02-01"
    assert calendar.days[-1].date == "2024-02-29"


def test_empty_payload_preserves_unknown_semantics_without_synthetic_closures():
    calendar = trading_calendar_from_szse_rows([], year=2026, month=12)

    assert calendar.days == ()
    assert calendar.status_on("2026-12-01") is TradingDayStatus.UNKNOWN
    assert calendar.is_open_on("2026-12-01") is None


def test_missing_date_rejects_partial_non_empty_month():
    rows = _rows()
    rows.pop(10)

    with pytest.raises(ValueError, match="cover every date"):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_duplicate_date_is_rejected():
    rows = _rows()
    rows.append(dict(rows[0]))

    with pytest.raises(ValueError, match="duplicate"):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_wrong_month_row_is_rejected():
    rows = _rows()
    rows[0] = {"jyrq": "2024-01-01", "jybz": "1"}

    with pytest.raises(ValueError, match="outside requested month"):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_unknown_trading_flag_is_rejected():
    rows = _rows()
    rows[0]["jybz"] = "2"

    with pytest.raises(ValueError, match='exactly "0" or "1"'):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_trading_flag_is_not_silently_coerced_from_integer():
    rows = _rows()
    rows[0]["jybz"] = 1

    with pytest.raises(ValueError, match='exactly "0" or "1"'):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_missing_provider_fields_are_rejected():
    rows = _rows()
    rows[0] = {"jyrq": "2024-02-01"}

    with pytest.raises(ValueError, match="contain jyrq and jybz"):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_noncanonical_provider_date_is_rejected():
    rows = _rows()
    rows[0]["jyrq"] = " 2024-02-01"

    with pytest.raises(ValueError, match="canonical"):
        trading_calendar_from_szse_rows(rows, year=2024, month=2)


def test_adapter_does_not_apply_weekday_or_weekend_heuristics():
    rows = _rows()
    saturday = next(row for row in rows if row["jyrq"] == "2024-02-03")
    saturday["jybz"] = "1"

    calendar = trading_calendar_from_szse_rows(rows, year=2024, month=2)

    assert calendar.status_on("2024-02-03") is TradingDayStatus.OPEN


def test_rows_and_requested_month_types_are_strict():
    with pytest.raises(TypeError, match="sequence"):
        trading_calendar_from_szse_rows("not rows", year=2024, month=2)
    with pytest.raises(TypeError, match="mapping"):
        trading_calendar_from_szse_rows(["bad row"], year=2024, month=2)
    with pytest.raises(TypeError, match="year"):
        trading_calendar_from_szse_rows([], year=True, month=2)
    with pytest.raises(TypeError, match="month"):
        trading_calendar_from_szse_rows([], year=2024, month="2")


def test_invalid_calendar_month_is_rejected_even_for_empty_payload():
    with pytest.raises(ValueError, match="valid calendar month"):
        trading_calendar_from_szse_rows([], year=2024, month=13)
