from calendar import monthrange

import pytest

from analysis.research.quality import CompletenessStatus, FreshnessStatus
from analysis.research.trading_calendar import TradingDayStatus
from analysis.research.trading_calendar_szse_fetch import (
    SZSE_TRADING_CALENDAR_REFERER,
    SZSE_TRADING_CALENDAR_TIMEOUT,
    SZSE_TRADING_CALENDAR_URL,
    SZSECalendarFetchError,
    fetch_szse_trading_calendar,
    requests_json_transport,
)


def _rows(year: int = 2024, month: int = 2):
    count = monthrange(year, month)[1]
    return [
        {
            "jyrq": f"{year:04d}-{month:02d}-{day:02d}",
            "jybz": "0" if day == 19 else "1",
        }
        for day in range(1, count + 1)
    ]


def test_fetch_boundary_calls_injected_transport_and_returns_evidence():
    calls = []

    def transport(url, *, params, timeout):
        calls.append((url, params, timeout))
        return {"data": _rows()}

    evidence = fetch_szse_trading_calendar(
        2024,
        2,
        fetched_at="2024-01-25T10:00:00+08:00",
        transport=transport,
    )

    assert calls == [
        (
            SZSE_TRADING_CALENDAR_URL,
            {"month": "2024-2"},
            SZSE_TRADING_CALENDAR_TIMEOUT,
        )
    ]
    assert evidence.provider.provider_id == "szse"
    assert evidence.calendar.status_on("2024-02-19") is TradingDayStatus.CLOSED
    assert evidence.time.fetched_at == "2024-01-25T10:00:00+08:00"
    assert evidence.time.period_start == "2024-02-01"
    assert evidence.time.period_end == "2024-02-29"
    assert evidence.quality.completeness is CompletenessStatus.COMPLETE
    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN


def test_empty_data_is_valid_empty_evidence_not_synthetic_closure():
    evidence = fetch_szse_trading_calendar(
        2026,
        12,
        fetched_at="2026-09-16T09:00:00+08:00",
        transport=lambda *args, **kwargs: {"data": []},
    )

    assert evidence.calendar.days == ()
    assert evidence.calendar.status_on("2026-12-01") is TradingDayStatus.UNKNOWN
    assert evidence.quality.completeness is CompletenessStatus.EMPTY
    assert evidence.quality.degraded is False


def test_missing_data_field_is_rejected_as_malformed_response():
    with pytest.raises(SZSECalendarFetchError, match="must contain data"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {},
        )


def test_non_mapping_or_non_list_response_shapes_are_rejected():
    with pytest.raises(SZSECalendarFetchError, match="response must be a mapping"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: [],
        )

    with pytest.raises(SZSECalendarFetchError, match="data must be a list"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {"data": ()},
        )


def test_non_mapping_data_row_is_rejected_at_fetch_boundary():
    with pytest.raises(SZSECalendarFetchError, match="rows must be mappings"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {"data": ["bad-row"]},
        )


def test_transport_failures_are_wrapped_with_stable_boundary_error():
    def failing_transport(*args, **kwargs):
        raise OSError("network down")

    with pytest.raises(SZSECalendarFetchError, match="transport failed") as exc_info:
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=failing_transport,
        )

    assert isinstance(exc_info.value.__cause__, OSError)


def test_calendar_row_validation_remains_owned_by_existing_strict_adapter():
    rows = _rows()
    rows.pop()

    with pytest.raises(ValueError, match="cover every date"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {"data": rows},
        )


def test_invalid_month_and_transport_type_fail_before_network_call():
    called = False

    def transport(*args, **kwargs):
        nonlocal called
        called = True
        return {"data": []}

    with pytest.raises(ValueError, match="valid calendar month"):
        fetch_szse_trading_calendar(
            2024,
            13,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=transport,
        )
    assert called is False

    with pytest.raises(TypeError, match="transport must be callable"):
        fetch_szse_trading_calendar(
            2024,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=None,  # type: ignore[arg-type]
        )


def test_year_and_month_types_are_strict():
    with pytest.raises(TypeError, match="year"):
        fetch_szse_trading_calendar(
            True,
            2,
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {"data": []},
        )
    with pytest.raises(TypeError, match="month"):
        fetch_szse_trading_calendar(
            2024,
            "2",  # type: ignore[arg-type]
            fetched_at="2024-01-25T10:00:00+08:00",
            transport=lambda *args, **kwargs: {"data": []},
        )


def test_default_requests_transport_uses_official_http_contract(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            calls.append("raise_for_status")

        def json(self):
            calls.append("json")
            return {"data": []}

    def fake_get(url, *, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return Response()

    monkeypatch.setattr(
        "analysis.research.trading_calendar_szse_fetch.requests.get", fake_get
    )

    payload = requests_json_transport(
        SZSE_TRADING_CALENDAR_URL,
        params={"month": "2024-2"},
    )

    assert payload == {"data": []}
    assert calls[0] == (
        SZSE_TRADING_CALENDAR_URL,
        {"month": "2024-2"},
        {"User-Agent": "Mozilla/5.0", "Referer": SZSE_TRADING_CALENDAR_REFERER},
        SZSE_TRADING_CALENDAR_TIMEOUT,
    )
    assert calls[1:] == ["raise_for_status", "json"]
