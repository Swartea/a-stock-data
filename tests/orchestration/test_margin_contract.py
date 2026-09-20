from types import SimpleNamespace

import analysis.pipeline as pipeline
from analysis.orchestration import fetching


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
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
        "blocks": [{"name": "测试概念"}],
        "fund": {"klines": [1]},
        "lockup": {},
        "dragon": {},
        "macro": {"hsgt": {"scope": "market"}},
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


def _run_pipeline_with_margin(monkeypatch, margin_fetcher, clock=None):
    clock = clock or FakeClock()
    pipeline._src_meta.clear()

    fake_time = SimpleNamespace(time=clock.time, sleep=clock.sleep)
    monkeypatch.setattr(pipeline, "time", fake_time)
    monkeypatch.setattr(fetching, "time", fake_time)
    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_restore_v2", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        pipeline.v2,
        "analyze_single",
        lambda *_args, **_kw: _base_result(),
    )
    monkeypatch.setattr(pipeline.v2, "_make_trading_plan", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline.v2, "_make_signal_list", lambda *_args, **_kw: ([], []))
    monkeypatch.setattr(pipeline.v2, "fetch_margin_trading", margin_fetcher)

    monkeypatch.setattr(pipeline, "compute_three_levels", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_call_new", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: [])
    monkeypatch.setattr(pipeline, "_fetch_fund_flow_daily", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_fetch_margin_history", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_fetch_concept_peers", lambda *_args, **_kw: {})
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
        lambda *_args, **_kw: {
            "last_bar": None,
            "expected": "2026-09-15",
            "level": "ok",
            "text": "fresh",
        },
    )
    monkeypatch.setattr(pipeline, "_emit", lambda *_args, **_kw: {"status": {}})

    result = pipeline.analyze_single_v3("600693", "东百集团")
    return result, clock


def test_margin_success_first_try_records_total_elapsed_and_exact_value(monkeypatch):
    calls = []
    payload = {"source": "eastmoney", "balance": 123}
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.25)
        return payload

    result, returned_clock = _run_pipeline_with_margin(
        monkeypatch,
        fetcher,
        clock,
    )
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert returned_clock is clock
    assert calls == ["600693"]
    assert clock.sleeps == []
    assert result["margin"] is payload
    assert meta["ms"] == 250
    assert meta["status"] == "ok:eastmoney-datacenter, 250ms"
    assert result["run_log"]["sources"]["融资融券"] == meta["status"]
    assert meta["detail"] == pipeline._SRC_DESC["融资融券"]
    assert "at" in meta
    assert meta["timeout_sec"] == 20.0
    assert meta["timed_out"] is False


def test_margin_retries_exceptions_three_times_and_timer_includes_sleeps(monkeypatch):
    calls = []
    payload = {"balance": 456}
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.2)
        if len(calls) < 3:
            raise RuntimeError(f"boom-{len(calls)}")
        return payload

    result, _ = _run_pipeline_with_margin(monkeypatch, fetcher, clock)
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert calls == ["600693", "600693", "600693"]
    assert clock.sleeps == [1.0, 1.0]
    assert result["margin"] is payload
    assert meta["ms"] == 2600
    assert meta["status"] == "ok:eastmoney-datacenter, 2600ms"


def test_margin_all_exceptions_sleep_after_final_try_and_keep_last_error(monkeypatch):
    calls = []
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.1)
        raise ValueError(f"failure-{len(calls)}")

    result, _ = _run_pipeline_with_margin(monkeypatch, fetcher, clock)
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert calls == ["600693", "600693", "600693"]
    assert clock.sleeps == [1.0, 1.0, 1.0]
    assert result["margin"] == {"error": "failure-3"}
    assert meta["ms"] == 3300
    assert meta["status"] == "error:failure-3, 3300ms"
    assert result["run_log"]["fallback_chain"][-1] == "融资融券: failure-3"


def test_margin_error_dict_is_not_retried(monkeypatch):
    calls = []
    payload = {"error": "provider returned error"}

    def fetcher(code):
        calls.append(code)
        return payload

    result, clock = _run_pipeline_with_margin(monkeypatch, fetcher)
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert result["margin"] is payload
    assert meta["status"] == "error:provider returned error, 0ms"
    assert result["run_log"]["fallback_chain"][-1] == "融资融券: provider returned error"


def test_margin_none_return_is_currently_recorded_as_ok_without_retry(monkeypatch):
    calls = []

    def fetcher(code):
        calls.append(code)
        return None

    result, clock = _run_pipeline_with_margin(monkeypatch, fetcher)
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert result["margin"] is None
    assert meta["status"] == "ok:eastmoney-datacenter, 0ms"
    assert all(
        not item.startswith("融资融券:")
        for item in result["run_log"]["fallback_chain"]
    )


def test_margin_timeout_is_equivalent_to_raised_exception_contract(monkeypatch):
    clock = FakeClock()
    boundary_calls = []

    def timeout_boundary(label, fn, *args, timeout, **kwargs):
        boundary_calls.append((label, fn, args, timeout, kwargs))
        raise TimeoutError("融资融券 调用超时(20s)")

    monkeypatch.setattr(fetching, "_call_with_timeout", timeout_boundary)

    result, returned_clock = _run_pipeline_with_margin(
        monkeypatch,
        lambda code: {"never": code},
        clock,
    )
    meta = result["run_log"]["source_meta"]["融资融券"]

    assert returned_clock is clock
    margin_calls = [call for call in boundary_calls if call[0] == "融资融券"]
    assert len(margin_calls) == 3
    assert all(call[2] == ("600693",) for call in margin_calls)
    assert all(call[3] == fetching._MARGIN_TIMEOUT_SEC for call in margin_calls)
    assert all(call[4] == {} for call in margin_calls)
    assert clock.sleeps == [1.0, 1.0, 1.0]
    assert result["margin"] == {"error": "融资融券 调用超时(20s)"}
    assert meta["status"] == "error:融资融券 调用超时(20s), 3000ms"
    assert meta["timeout_sec"] == 20.0
    assert meta["timed_out"] is True
    assert result["run_log"]["fallback_chain"][-1] == (
        "融资融券: 融资融券 调用超时(20s)"
    )
