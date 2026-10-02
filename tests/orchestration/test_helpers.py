from calendar import monthrange
from dataclasses import replace
from datetime import date, datetime

import pytest

from analysis.orchestration import helpers
from analysis.research.trading_calendar import TradingCalendar, TradingDayStatus
from analysis.research.trading_calendar_evidence import (
    trading_calendar_evidence_from_szse_rows,
)


class _FixedDateTime(datetime):
    fixed_now = datetime(2026, 9, 15, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_now


def _set_now(monkeypatch, value: datetime):
    _FixedDateTime.fixed_now = value
    monkeypatch.setattr(helpers, "datetime", _FixedDateTime)


def _szse_rows(year: int, month: int, closed=()) -> list[dict]:
    """构造覆盖整月的官方日历行：``closed`` 中的日与所有周末标记为休市。"""
    closed_days = set(closed)
    count = monthrange(year, month)[1]
    rows = []
    for day in range(1, count + 1):
        current = date(year, month, day)
        is_closed = day in closed_days or current.weekday() >= 5
        rows.append({"jyrq": current.isoformat(), "jybz": "0" if is_closed else "1"})
    return rows


def _install_calendar(monkeypatch, months, *, calls=None):
    """用离线桩替换官方抓取适配器，返回抓取调用记录。"""

    def fake_fetch(year, month, *, fetched_at, **kwargs):
        if calls is not None:
            calls.append((year, month, fetched_at))
        key = (year, month)
        if key not in months:
            raise AssertionError(f"unexpected month requested: {key}")
        return trading_calendar_evidence_from_szse_rows(
            months[key],
            year=year,
            month=month,
            fetched_at=fetched_at,
        )

    monkeypatch.setattr(helpers, "fetch_szse_trading_calendar", fake_fetch)
    return calls


@pytest.fixture(autouse=True)
def _isolate_calendar_cache(monkeypatch):
    """清空月度缓存并禁止任何真实网络抓取，保证全部用例离线且互不干扰。"""

    def blocked(*args, **kwargs):
        raise AssertionError("tests must not perform real calendar fetches")

    helpers._clear_trading_calendar_cache()
    monkeypatch.setattr(helpers, "fetch_szse_trading_calendar", blocked)
    yield
    helpers._clear_trading_calendar_cache()


def test_latest_trading_day_weekend_rolls_back_to_friday(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 12, 12, 0, 0))  # Saturday
    assert helpers._latest_trading_day() == date(2026, 9, 11)


def test_latest_trading_day_before_open_rolls_back_over_weekend(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 14, 8, 30, 0))  # Monday before 09:30
    assert helpers._latest_trading_day() == date(2026, 9, 11)


def test_latest_trading_day_after_open_uses_today(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    assert helpers._latest_trading_day() == date(2026, 9, 15)


def test_weekday_holiday_resolves_to_previous_explicitly_open_day(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))  # Tuesday 法定节假日
    _install_calendar(
        monkeypatch,
        {(2026, 9): _szse_rows(2026, 9, closed={15, 16})},
    )

    # 工作日估计会给出 09-15，官方日历证明休市后应回退到 09-14。
    assert helpers._latest_trading_day() == date(2026, 9, 14)


def test_weekend_uses_official_calendar_after_open(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 12, 12, 0, 0))  # Saturday
    _install_calendar(
        monkeypatch,
        {(2026, 9): _szse_rows(2026, 9, closed={12, 13})},
    )

    assert helpers._latest_trading_day() == date(2026, 9, 11)


def test_before_open_on_first_of_month_resolves_into_previous_month(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 10, 1, 8, 0, 0))  # 09:30 前
    calls: list[tuple[int, int, str]] = []
    _install_calendar(
        monkeypatch,
        {(2026, 9): _szse_rows(2026, 9, closed={30})},
        calls=calls,
    )

    # 起点是 09-30（已闭市），回溯必须跨月取到 09-29。
    assert helpers._latest_trading_day() == date(2026, 9, 29)
    assert [(y, m, ts[:19]) for y, m, ts in calls] == [
        (2026, 9, "2026-10-01T08:00:00")
    ]


def test_before_open_on_new_year_crosses_year_boundary(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 1, 1, 8, 0, 0))  # 09:30 前
    calls: list[tuple[int, int, str]] = []
    _install_calendar(
        monkeypatch,
        {(2025, 12): _szse_rows(2025, 12, closed={29, 30, 31})},
        calls=calls,
    )

    # 跨年边界：只提供 2025-12 证据即可回溯到 12-26（跳过元旦+周末）。
    assert helpers._latest_trading_day() == date(2025, 12, 26)
    assert [(y, m, ts[:19]) for y, m, ts in calls] == [
        (2025, 12, "2026-01-01T08:00:00")
    ]


def test_month_evidence_is_reused_within_24h_and_refetched_after_expiry(monkeypatch):
    months = {(2026, 9): _szse_rows(2026, 9, closed={15})}
    calls: list[tuple[int, int, str]] = []
    _install_calendar(monkeypatch, months, calls=calls)
    monotonic_now = [100.0]
    monkeypatch.setattr(helpers.time, "monotonic", lambda: monotonic_now[0])

    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    assert helpers._latest_trading_day() == date(2026, 9, 14)
    assert helpers._latest_trading_day() == date(2026, 9, 14)
    assert helpers._latest_trading_day() == date(2026, 9, 14)
    assert len(calls) == 1  # 24 小时内复用同一个月证据

    monotonic_now[0] += helpers._CALENDAR_CACHE_TTL.total_seconds() + 1
    _set_now(monkeypatch, datetime(2026, 9, 16, 10, 0, 1))  # 单调时钟超过 24 小时
    assert helpers._latest_trading_day() == date(2026, 9, 16)
    assert len(calls) == 2
    assert calls[1][:2] == (2026, 9)


def test_provider_failure_falls_back_to_weekday_estimate(monkeypatch):
    def failing_fetch(year, month, *, fetched_at, **kwargs):
        raise RuntimeError("provider down")

    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    monkeypatch.setattr(helpers, "fetch_szse_trading_calendar", failing_fetch)

    assert helpers._latest_trading_day() == date(2026, 9, 15)


def test_malformed_provider_response_falls_back_without_caching(monkeypatch):
    attempts = []

    def bad_fetch(year, month, *, fetched_at, **kwargs):
        attempts.append((year, month))
        return object()

    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    monkeypatch.setattr(helpers, "fetch_szse_trading_calendar", bad_fetch)

    assert helpers._latest_trading_day() == date(2026, 9, 15)
    assert helpers._latest_trading_day() == date(2026, 9, 15)
    # 无效证据不入缓存，第二次会重新抓取而不是固化降级结果。
    assert attempts == [(2026, 9), (2026, 9)]


def test_empty_month_evidence_never_infers_closure(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    _install_calendar(monkeypatch, {(2026, 9): []})

    # 空月历 = 没有证据，只能退回工作日估计。
    assert helpers._latest_trading_day() == date(2026, 9, 15)


def test_unknown_status_falls_back_instead_of_skipping_the_date(monkeypatch):
    """某日状态 UNKNOWN 时不得当成休市继续回溯。"""
    _set_now(monkeypatch, datetime(2026, 9, 14, 10, 0, 0))  # Monday 09:30 后
    rows = _szse_rows(2026, 9, closed={14})
    _install_calendar(monkeypatch, {(2026, 9): rows})

    # 官方日历证明 09-14 休市 → 09-11（工作日估计会错误地给出 09-14）。
    assert helpers._latest_trading_day() == date(2026, 9, 11)

    # 同一份证据去掉 09-14 观测 → UNKNOWN：既不能跳过该日，也不能推断其休市，
    # 必须回退到工作日估计。
    full = trading_calendar_evidence_from_szse_rows(
        rows, year=2026, month=9, fetched_at="2026-09-14T10:00:00+08:00"
    )
    partial = TradingCalendar(
        days=tuple(d for d in full.calendar.days if d.date != "2026-09-14")
    )
    assert partial.status_on("2026-09-14") is TradingDayStatus.UNKNOWN

    monkeypatch.setattr(
        helpers,
        "fetch_szse_trading_calendar",
        lambda *a, **k: replace(full, calendar=partial),
    )
    helpers._clear_trading_calendar_cache()  # 丢弃上一轮完整证据，强制走 UNKNOWN 路径
    assert helpers._latest_trading_day() == date(2026, 9, 14)


def test_lookback_beyond_two_months_falls_back_to_estimate(monkeypatch):
    """跨月回溯预算用尽时回退，绝不无限回溯或推断休市。"""
    _set_now(monkeypatch, datetime(2026, 1, 2, 10, 0, 0))  # 09:30 后
    calls: list[tuple[int, int, str]] = []
    _install_calendar(
        monkeypatch,
        {
            (2026, 1): _szse_rows(2026, 1, closed={1, 2}),
            (2025, 12): _szse_rows(2025, 12, closed=set(range(1, 32))),
        },
        calls=calls,
    )

    # 1 月与 12 月都无开市日，预算耗尽 → 工作日估计 2026-01-02，且不再请求 11 月。
    assert helpers._latest_trading_day() == date(2026, 1, 2)
    assert [(y, m, ts[:19]) for y, m, ts in calls] == [
        (2026, 1, "2026-01-02T10:00:00"),
        (2025, 12, "2026-01-02T10:00:00"),
    ]


def test_kline_freshness_ok(monkeypatch):
    monkeypatch.setattr(helpers, "_latest_trading_day", lambda: date(2026, 9, 14))
    result = helpers._kline_freshness({"kline": [{"date": "2026-09-14"}]})

    assert result["level"] == "ok"
    assert result["last_bar"] == "2026-09-14"
    assert result["expected"] == "2026-09-14"


def test_kline_freshness_warns_on_stale_bar(monkeypatch):
    monkeypatch.setattr(helpers, "_latest_trading_day", lambda: date(2026, 9, 14))
    result = helpers._kline_freshness({"kline": [{"date": "2026-09-11"}]})

    assert result["level"] == "warn"
    assert result["last_bar"] == "2026-09-11"
    assert "数据延迟" in result["text"]


def test_kline_freshness_uses_window_end_when_kline_missing(monkeypatch):
    monkeypatch.setattr(helpers, "_latest_trading_day", lambda: date(2026, 9, 14))
    result = helpers._kline_freshness({"window_end": "2026-09-14 15:00:00"})

    assert result["level"] == "ok"
    assert result["last_bar"] == "2026-09-14"


def test_kline_freshness_na_on_fetch_error(monkeypatch):
    monkeypatch.setattr(helpers, "_latest_trading_day", lambda: date(2026, 9, 14))
    result = helpers._kline_freshness({"error": "source unavailable"})

    assert result["level"] == "na"
    assert result["last_bar"] is None
    assert "source unavailable" in result["text"]
