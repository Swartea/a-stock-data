from types import SimpleNamespace

import pytest

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


def _base_result(blocks=None):
    return {
        "code": "600693",
        "name": "东百集团",
        "quote": {"price": 10.0},
        "valuation": {},
        "score": {"total": 50, "factors": {}},
        "chip_data": {},
        "valuation_hist": {},
        "blocks": blocks if blocks is not None else [{"name": "测试概念"}],
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


def _run_pipeline_with_supplements(
    monkeypatch,
    *,
    fund_fetcher=None,
    margin_fetcher=None,
    peers_fetcher=None,
    clock=None,
    blocks=None,
    seed_meta=None,
):
    clock = clock or FakeClock()
    pipeline._src_meta.clear()

    fake_time = SimpleNamespace(time=clock.time, sleep=clock.sleep)
    monkeypatch.setattr(pipeline, "time", fake_time)
    monkeypatch.setattr(fetching, "time", fake_time)
    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_restore_v2", lambda *_args, **_kw: None)

    def analyze_single(*_args, **_kw):
        if seed_meta:
            for label, meta in seed_meta.items():
                pipeline._src_meta[label] = dict(meta)
        return _base_result(blocks)

    monkeypatch.setattr(pipeline.v2, "analyze_single", analyze_single)
    monkeypatch.setattr(pipeline.v2, "_make_trading_plan", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline.v2, "_make_signal_list", lambda *_args, **_kw: ([], []))

    monkeypatch.setattr(pipeline, "compute_three_levels", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_call_new", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: [])
    monkeypatch.setattr(pipeline, "_fetch_margin", lambda *_args, **_kw: None)

    monkeypatch.setattr(
        pipeline,
        "_fetch_fund_flow_daily",
        fund_fetcher or (lambda *_args, **_kw: {"fund": "ok"}),
    )
    monkeypatch.setattr(
        pipeline,
        "_fetch_margin_history",
        margin_fetcher or (lambda *_args, **_kw: {"margin_hist": "ok"}),
    )
    monkeypatch.setattr(
        pipeline,
        "_fetch_concept_peers",
        peers_fetcher or (lambda *_args, **_kw: {"peers": "ok"}),
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
    return result, clock


def test_supplements_success_forward_exact_arguments_and_record_separate_statuses(monkeypatch):
    calls = []
    blocks = [{"name": "概念A"}, {"name": "概念B"}]
    clock = FakeClock()

    def fund_fetcher(code):
        calls.append(("fund", code))
        clock.advance(0.1)
        return {"fund": 1}

    def margin_fetcher(code):
        calls.append(("margin_hist", code))
        clock.advance(0.2)
        return {"margin_hist": 2}

    def peers_fetcher(code, seen_blocks):
        calls.append(("peers", code, seen_blocks))
        clock.advance(0.3)
        return {"peers": 3}

    result, _ = _run_pipeline_with_supplements(
        monkeypatch,
        fund_fetcher=fund_fetcher,
        margin_fetcher=margin_fetcher,
        peers_fetcher=peers_fetcher,
        clock=clock,
        blocks=blocks,
    )
    run_log = result["run_log"]

    assert calls == [
        ("fund", "600693"),
        ("margin_hist", "600693"),
        ("peers", "600693", blocks),
    ]
    assert result["fund_daily5"] == {"fund": 1}
    assert result["margin_hist"] == {"margin_hist": 2}
    assert result["peers"] == {"peers": 3}

    assert run_log["source_meta"]["资金面-5日主力"]["ms"] == 100
    assert run_log["source_meta"]["两融历史"]["ms"] == 200
    assert run_log["source_meta"]["同业对比"]["ms"] == 300
    assert run_log["supplements"] == {
        "资金面-5日主力": "ok, 100ms",
        "两融历史": "ok, 200ms",
        "同业对比": "ok, 300ms",
    }
    for label in ("资金面-5日主力", "两融历史", "同业对比"):
        assert label not in run_log["sources"]
        assert run_log["source_meta"][label]["detail"] == pipeline._SRC_DESC.get(label, label)
        assert "at" in run_log["source_meta"][label]


@pytest.mark.parametrize(
    ("result_key", "label", "fetcher_slot"),
    [
        ("fund_daily5", "资金面-5日主力", "fund"),
        ("peers", "同业对比", "peers"),
    ],
)
def test_error_dict_retries_once_for_fund_and_peers_and_uses_success(
    monkeypatch,
    result_key,
    label,
    fetcher_slot,
):
    calls = []
    clock = FakeClock()
    success = {"ok": fetcher_slot}

    def retrying_fetcher(*args):
        calls.append(args)
        clock.advance(0.25)
        if len(calls) == 1:
            return {"error": "first error"}
        return success

    kwargs = {f"{fetcher_slot}_fetcher": retrying_fetcher}
    result, _ = _run_pipeline_with_supplements(
        monkeypatch,
        clock=clock,
        **kwargs,
    )
    meta = result["run_log"]["source_meta"][label]

    assert len(calls) == 2
    assert clock.sleeps == [1.5]
    assert result[result_key] is success
    assert meta["ms"] == 2000
    assert meta["status"] == "ok, 2000ms"
    assert result["run_log"]["supplements"][label] == "ok, 2000ms"


def test_margin_history_error_dict_is_not_retried(monkeypatch):
    calls = []
    payload = {"error": "margin provider error"}

    def margin_fetcher(code):
        calls.append(code)
        return payload

    result, clock = _run_pipeline_with_supplements(
        monkeypatch,
        margin_fetcher=margin_fetcher,
    )
    meta = result["run_log"]["source_meta"]["两融历史"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert result["margin_hist"] is payload
    assert meta["status"] == "error:margin provider error, 0ms"


def test_second_error_dict_keeps_first_error_payload(monkeypatch):
    calls = []

    def fund_fetcher(code):
        calls.append(code)
        if len(calls) == 1:
            return {"error": "first error"}
        return {"error": "second error"}

    result, clock = _run_pipeline_with_supplements(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )
    meta = result["run_log"]["source_meta"]["资金面-5日主力"]

    assert calls == ["600693", "600693"]
    assert clock.sleeps == [1.5]
    assert result["fund_daily5"] == {"error": "first error"}
    assert meta["status"] == "error:first error, 1500ms"


def test_first_exception_is_not_retried(monkeypatch):
    calls = []

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        raise RuntimeError("peers exploded")

    result, clock = _run_pipeline_with_supplements(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )
    meta = result["run_log"]["source_meta"]["同业对比"]

    assert len(calls) == 1
    assert clock.sleeps == []
    assert result["peers"] == {"error": "peers exploded"}
    assert meta["status"] == "error:peers exploded, 0ms"


def test_retry_exception_replaces_first_error_payload(monkeypatch):
    calls = []

    def fund_fetcher(code):
        calls.append(code)
        if len(calls) == 1:
            return {"error": "first error"}
        raise RuntimeError("retry exploded")

    result, clock = _run_pipeline_with_supplements(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )
    meta = result["run_log"]["source_meta"]["资金面-5日主力"]

    assert calls == ["600693", "600693"]
    assert clock.sleeps == [1.5]
    assert result["fund_daily5"] == {"error": "retry exploded"}
    assert meta["status"] == "error:retry exploded, 1500ms"


def test_supplement_meta_reuses_existing_sparse_entry_without_normalizing(monkeypatch):
    result, _ = _run_pipeline_with_supplements(
        monkeypatch,
        seed_meta={
            "资金面-5日主力": {
                "at": "preexisting-at",
                "custom": "keep-me",
                "status": "old",
            }
        },
    )
    meta = result["run_log"]["source_meta"]["资金面-5日主力"]

    assert meta["at"] == "preexisting-at"
    assert meta["custom"] == "keep-me"
    assert meta["status"] == "ok, 0ms"
    assert meta["detail"] == pipeline._SRC_DESC.get("资金面-5日主力", "资金面-5日主力")
