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

    def advance(self, seconds):
        self.now += seconds


class FakeSection:
    def __init__(self, label, fetch_fn):
        self.label = label
        self._fetch_fn = fetch_fn

    def fetch(self, code, ctx):
        return self._fetch_fn(code, ctx)


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


def _run_pipeline_with_sections(monkeypatch, sections, clock=None):
    clock = clock or FakeClock()
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
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: sections)
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
        lambda *_args, **_kw: {
            "last_bar": None,
            "expected": "2026-09-15",
            "level": "ok",
            "text": "fresh",
        },
    )
    monkeypatch.setattr(pipeline, "_emit", lambda *_args, **_kw: {"status": {}})

    result = pipeline.analyze_single_v3("600693", "东百集团")
    return result, base_result, clock


def test_sections_run_in_registry_order_with_exact_context_and_top_level_results(monkeypatch):
    calls = []
    clock = FakeClock()
    payload_a = {"value": "A"}
    payload_b = {"value": "B"}

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.125)
        return payload_a

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.250)
        return payload_b

    sections = [
        FakeSection("Section A", fetch_a),
        FakeSection("Section B", fetch_b),
    ]
    result, base_result, _ = _run_pipeline_with_sections(
        monkeypatch,
        sections,
        clock,
    )
    run_log = result["run_log"]

    assert [(label, code) for label, code, _ctx in calls] == [
        ("A", "600693"),
        ("B", "600693"),
    ]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert result["Section A"] is payload_a
    assert result["Section B"] is payload_b
    assert run_log["sections_count"] == 2
    assert run_log["sources"]["Section A"] == "ok, 125ms"
    assert run_log["sources"]["Section B"] == "ok, 250ms"
    assert not any(item.startswith("Section A:") for item in run_log["fallback_chain"])
    assert not any(item.startswith("Section B:") for item in run_log["fallback_chain"])


def test_section_exception_becomes_error_payload_and_does_not_stop_later_sections(monkeypatch):
    calls = []
    clock = FakeClock()

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.100)
        return {"value": "A"}

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.200)
        raise RuntimeError("boom")

    def fetch_c(code, ctx):
        calls.append(("C", code, ctx))
        clock.advance(0.250)
        return {"value": "C"}

    sections = [
        FakeSection("Section A", fetch_a),
        FakeSection("Section B", fetch_b),
        FakeSection("Section C", fetch_c),
    ]
    result, base_result, _ = _run_pipeline_with_sections(
        monkeypatch,
        sections,
        clock,
    )
    run_log = result["run_log"]

    assert [label for label, _code, _ctx in calls] == ["A", "B", "C"]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert result["Section B"] == {"error": "boom"}
    assert result["Section C"] == {"value": "C"}
    assert run_log["sections_count"] == 2
    assert run_log["sources"]["Section A"] == "ok, 100ms"
    assert run_log["sources"]["Section B"] == "error: boom"
    assert run_log["sources"]["Section C"] == "ok, 250ms"
    assert "Section B: boom" in run_log["fallback_chain"]


def test_empty_section_registry_keeps_count_zero_and_adds_no_section_results(monkeypatch):
    result, _base_result_obj, _clock = _run_pipeline_with_sections(monkeypatch, [])
    run_log = result["run_log"]

    assert run_log["sections_count"] == 0
    assert "Section A" not in result
    assert "Section B" not in result
    assert "Section A" not in run_log["sources"]
    assert "Section B" not in run_log["sources"]
