from types import SimpleNamespace

import analysis.pipeline as pipeline
from analysis.orchestration import fetching


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _base_result():
    return {
        "code": "600693",
        "name": "东百集团",
        "quote": {"price": 10.0},
        "valuation": {},
        "score": {"total": 50, "factors": {}},
        "chip_data": {},
        "valuation_hist": {},
        "blocks": [],
        "fund": {"klines": [1]},
        "lockup": {},
        "dragon": {},
        "macro": {"hsgt": {}},
        "sw_data": {},
        "advice": "中性",
        "emoji": "",
        "detail": {},
    }


def _scoring_breakdown():
    return {
        "total": {"score": 50, "max": 100},
        "tech": {"score": 14, "max": 28},
        "capital": {"score": 12.5, "max": 25},
        "valuation": {"score": 14.5, "max": 29},
        "sentiment": {"score": 4, "max": 8},
        "risk": {"score": 5, "max": 10},
    }


def _run_pipeline(monkeypatch, freshness):
    clock = FakeClock()
    base_result = _base_result()
    pipeline._src_meta.clear()

    fake_time = SimpleNamespace(time=clock.time, sleep=clock.sleep)
    monkeypatch.setattr(pipeline, "time", fake_time)
    monkeypatch.setattr(fetching, "time", fake_time)
    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_restore_v2", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        pipeline.v2,
        "analyze_single",
        lambda *_args, **_kw: base_result,
    )
    monkeypatch.setattr(pipeline.v2, "_make_trading_plan", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline.v2, "_make_signal_list", lambda *_args, **_kw: ([], []))
    monkeypatch.setattr(pipeline, "compute_three_levels", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_call_new", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: [])
    monkeypatch.setattr(pipeline, "_fetch_margin", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_supplements",
        lambda _recorder, run_log, *_args, **_kw: run_log.__setitem__(
            "supplements", {}
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_classify_north_scope",
        lambda *_args, **_kw: ("market", "市场口径"),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_scoring_breakdown",
        lambda *_args, **_kw: _scoring_breakdown(),
    )
    monkeypatch.setattr(
        pipeline,
        "_kline_freshness",
        lambda *_args, **_kw: freshness,
    )
    monkeypatch.setattr(pipeline, "_emit", lambda *_args, **_kw: {"status": {}})

    return pipeline.analyze_single_v3("600693", "东百集团")


def test_kline_guard_formats_exact_ok_status_and_does_not_append_fallback(monkeypatch):
    freshness = {
        "last_bar": "2026-09-15",
        "expected": "2026-09-15",
        "level": "ok",
        "text": "K线已更新到最新交易日",
    }

    result = _run_pipeline(monkeypatch, freshness)
    run_log = result["run_log"]

    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=2026-09-15 vs 最新交易日=2026-09-15 -> "
        "ok (K线已更新到最新交易日)"
    )
    assert not any(item.startswith("K线时点:") for item in run_log["fallback_chain"])


def test_kline_guard_uses_na_when_last_bar_is_missing(monkeypatch):
    freshness = {
        "last_bar": None,
        "expected": "2026-09-15",
        "level": "error",
        "text": "缺少K线数据",
    }

    result = _run_pipeline(monkeypatch, freshness)
    run_log = result["run_log"]

    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=N/A vs 最新交易日=2026-09-15 -> error (缺少K线数据)"
    )
    assert not any(item.startswith("K线时点:") for item in run_log["fallback_chain"])


def test_kline_guard_warn_appends_exact_warn_fallback(monkeypatch):
    freshness = {
        "last_bar": "2026-09-12",
        "expected": "2026-09-15",
        "level": "warn",
        "text": "K线落后最新交易日",
    }

    result = _run_pipeline(monkeypatch, freshness)
    run_log = result["run_log"]

    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=2026-09-12 vs 最新交易日=2026-09-15 -> "
        "warn (K线落后最新交易日)"
    )
    assert run_log["fallback_chain"].count("K线时点: K线落后最新交易日 [WARN]") == 1


def test_kline_guard_only_exact_warn_level_adds_fallback(monkeypatch):
    freshness = {
        "last_bar": "2026-09-12",
        "expected": "2026-09-15",
        "level": "WARN",
        "text": "大写状态",
    }

    result = _run_pipeline(monkeypatch, freshness)
    run_log = result["run_log"]

    assert run_log["guard"]["kline_freshness"].endswith("WARN (大写状态)")
    assert not any(item.startswith("K线时点:") for item in run_log["fallback_chain"])
