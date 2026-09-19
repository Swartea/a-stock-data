from datetime import date, datetime

from analysis.orchestration import helpers


class _FixedDateTime(datetime):
    fixed_now = datetime(2026, 9, 15, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_now


def _set_now(monkeypatch, value: datetime):
    _FixedDateTime.fixed_now = value
    monkeypatch.setattr(helpers, "datetime", _FixedDateTime)


def test_latest_trading_day_weekend_rolls_back_to_friday(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 12, 12, 0, 0))  # Saturday
    assert helpers._latest_trading_day() == date(2026, 9, 11)


def test_latest_trading_day_before_open_rolls_back_over_weekend(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 14, 8, 30, 0))  # Monday before 09:30
    assert helpers._latest_trading_day() == date(2026, 9, 11)


def test_latest_trading_day_after_open_uses_today(monkeypatch):
    _set_now(monkeypatch, datetime(2026, 9, 15, 10, 0, 0))
    assert helpers._latest_trading_day() == date(2026, 9, 15)


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
