"""Phase 1H 契约测试: analysis/orchestration/result_builder.py

覆盖 analyze_single_v3 抽离后的 build / finalize 两个阶段:
- build: build_trade_levels / build_signals / assemble_result / enrich_result
- finalize: finalize_run (guard → 时点 → 落盘 → 控制台摘要, 顺序敏感)

规范 §9: 测试不依赖个人路径/当日报告/当日时间戳; 时间与时点全部注入。
"""

from datetime import datetime

import pytest

from analysis.orchestration import result_builder as rb

_FIXED_NOW = datetime(2026, 10, 3, 15, 30, 0)


def _now():
    return _FIXED_NOW


# ============================================================
# build_trade_levels
# ============================================================


def _make_plan(quote, valuation, chip_data, score_total):
    return {
        "entry_low": 9.0,
        "entry_high": 10.0,
        "tp1": 12.0,
        "stop_loss": 8.5,
        "score_used": score_total,
    }


def test_build_trade_levels_injects_pe_pctile_from_valuation_hist():
    seen = {}

    def _inject(plan, score_total, pe_pctile):
        seen["plan"] = plan
        seen["score"] = score_total
        seen["pe"] = pe_pctile
        return plan

    plan, _ = rb.build_trade_levels(
        {"price": 10.0}, {}, {}, 53, {"pe_percentile_3y": 87.8},
        _make_plan, compute_levels=lambda *a: {}, inject_state=_inject,
    )

    # 批次 E 痛 3: PE 分位必须从 vh 取到并传给旁路
    assert seen["pe"] == 87.8
    assert seen["score"] == 53
    assert seen["plan"] is plan


def test_build_trade_levels_does_not_inject_when_plan_is_none():
    called = []

    plan, three_levels = rb.build_trade_levels(
        {"price": 10.0}, {}, {}, 40, {},
        lambda *a: None,                                  # V2 计划失败
        compute_levels=lambda *a: {"support": 9.0},
        inject_state=lambda *a: called.append(a),
    )

    # 失败计划不得被 mutate (原实现是 `inject(...) if plan else None`)
    assert plan is None
    assert called == []
    assert three_levels == {"support": 9.0}


def test_build_trade_levels_passes_quote_chip_and_plan_to_three_levels():
    captured = {}

    def _levels(quote, chip_data, plan):
        captured["quote"] = quote
        captured["chip"] = chip_data
        captured["plan"] = plan
        return {"support": 9.9}

    quote = {"price": 10.0}
    chip = {"kline": [{"date": "2026-10-02"}]}
    plan, three_levels = rb.build_trade_levels(
        quote, {"pe": 1}, chip, 55, {}, _make_plan,
        compute_levels=_levels, inject_state=lambda *a: None,
    )

    assert three_levels == {"support": 9.9}
    # 三价位必须与 trading_plan 同源 K 线
    assert captured == {"quote": quote, "chip": chip, "plan": plan}


# ============================================================
# build_signals
# ============================================================


def test_build_signals_splits_v2_factor_map():
    captured = {}

    def _make_signal_list(score, factors):
        captured["factors"] = factors
        return (["good1"], ["bad1"])

    good, bad = rb.build_signals(
        {"total": 55, "factors": {"trend": 5}}, _make_signal_list
    )

    assert (good, bad) == (["good1"], ["bad1"])
    assert captured["factors"] == {"trend": 5}


# ============================================================
# assemble_result (result_v3 契约键集)
# ============================================================

_EXPECTED_KEYS = {
    "code", "name", "quote", "valuation", "blocks", "fund", "valuation_hist",
    "lockup", "dragon", "macro", "chip_data", "sw_data", "announcements",
    "finance", "news", "research", "margin", "peers", "fund_daily5",
    "margin_hist", "score", "advice", "emoji", "detail", "trading_plan",
    "three_levels", "signals", "run_log", "report_date",
}


def _base_result():
    return {
        "code": "600693",
        "name": "东百集团",
        "quote": {"price": 10.0},
        "valuation": {"pe": 20.0},
        "score": {"total": 55, "factors": {}},
        "advice": "持有",
        "emoji": "🟡",
        "detail": "detail-text",
        "chip_data": {"kline": []},
    }


def _fetched():
    return {
        "announcements": {"a": 1}, "finance": {"f": 1}, "news": {"n": 1},
        "research": {"r": 1}, "margin": None, "fund_daily5": {"d": 1},
        "margin_hist": {"m": 1}, "peers": {"p": 1},
    }


def test_assemble_result_preserves_contract_key_set():
    result = rb.assemble_result(
        _base_result(), {"tp1": 12.0}, {"support": 9.0}, ["g"], ["b"],
        _fetched(), {"margin": 1}, {"sources": {}}, {}, "参数名", _now,
    )

    # sections_data 为空时不应引入额外键
    assert set(result) == _EXPECTED_KEYS


def test_assemble_result_merges_section_registry_keys():
    result = rb.assemble_result(
        _base_result(), None, {}, [], [], _fetched(), None,
        {"sources": {}}, {"irm": {"ok": True}, "holders": {"h": 1}},
        "参数名", _now,
    )

    # Section Registry 注入的 section.label 作为 result 顶层 key
    assert result["irm"] == {"ok": True}
    assert result["holders"] == {"h": 1}


def test_assemble_result_report_date_uses_injected_clock():
    result = rb.assemble_result(
        _base_result(), None, {}, [], [], _fetched(), None,
        {}, {}, "参数名", _now,
    )

    assert result["report_date"] == "2026-10-03"


def test_assemble_result_name_falls_back_to_argument():
    base = _base_result()
    base["name"] = ""
    result = rb.assemble_result(
        base, None, {}, [], [], _fetched(), None, {}, {}, "参数名", _now,
    )

    assert result["name"] == "参数名"


def test_assemble_result_defaults_absent_optional_blocks_to_empty():
    result = rb.assemble_result(
        _base_result(), None, {}, [], [], _fetched(), None, {}, {}, "", _now,
    )

    # blocks 缺省是空列表, 其余可选块缺省是空 dict (与原实现一致)
    assert result["blocks"] == []
    for key in ("fund", "valuation_hist", "lockup", "dragon", "macro", "sw_data"):
        assert result[key] == {}


# ============================================================
# enrich_result (债 3 北向口径 + 批次 C 痛 7 评分构成)
# ============================================================


def _scoring_breakdown():
    return {
        "total": {"score": 50, "max": 100},
        "tech": {"score": 14, "max": 28},
        "capital": {"score": 12.5, "max": 25},
        "valuation": {"score": 14.5, "max": 29},
        "sentiment": {"score": 4, "max": 8},
        "risk": {"score": 5, "max": 10},
    }


def test_enrich_result_attaches_north_scope_and_label():
    result = {"macro": {"hsgt": {"north": 100.0}}}
    seen = {}

    def _classify(north_data):
        seen["north_data"] = north_data
        return "market", "市场口径(非个股)"

    out = rb.enrich_result(
        result, {}, classify_north_scope=_classify,
        build_scoring_breakdown=lambda score: _scoring_breakdown(),
    )

    assert out["macro"]["north_scope"] == "market"
    assert out["macro"]["north_label"] == "市场口径(非个股)"
    # 分类器收到的应是 macro.hsgt 本身
    assert seen["north_data"] == {"north": 100.0}


def test_enrich_result_tolerates_missing_hsgt():
    result = {"macro": {}}
    out = rb.enrich_result(
        result, {}, classify_north_scope=lambda data: ("unknown", "口径未知"),
        build_scoring_breakdown=lambda score: _scoring_breakdown(),
    )

    assert out["macro"]["north_scope"] == "unknown"


def test_enrich_result_attaches_scoring_breakdown():
    result = {"macro": {}}
    out = rb.enrich_result(
        result, {"total": 50},
        classify_north_scope=lambda data: ("market", "市场口径"),
        build_scoring_breakdown=lambda score: _scoring_breakdown(),
    )

    # 批次 C 痛 7: 评分构成必须落 result, 渲染层据此渲染 5 维卡片
    assert out["scoring_breakdown"] == _scoring_breakdown()
    assert out["scoring_breakdown"]["total"]["max"] == 100


def test_enrich_result_preserves_existing_macro_keys():
    result = {"macro": {"hsgt": {}, "hot_stocks": [1, 2]}}
    out = rb.enrich_result(
        result, {},
        classify_north_scope=lambda data: ("mixed", "混合口径"),
        build_scoring_breakdown=lambda score: _scoring_breakdown(),
    )

    # 不得覆盖已有宏观子键
    assert out["macro"]["hot_stocks"] == [1, 2]


# ============================================================
# finalize_run (顺序敏感: guard → 时点 → 落盘)
# ============================================================


def _run_log():
    return {"sources": {}, "fallback_chain": [], "guard": {}}


def test_finalize_run_records_guard_before_emit():
    order = []
    run_log = _run_log()

    def _freshness(chip_data):
        order.append("freshness")
        return {"level": "ok", "text": "contract-test"}

    def _record(log, fresh):
        order.append("record_guard")
        log["guard"]["kline_freshness"] = fresh["text"]

    def _timing(log, started, now_fn, time_fn):
        order.append("timing")
        log["total_sec"] = 1.5

    def _emit(code, name, result):
        order.append("emit")
        # 落盘瞬间 run_log 必须已带 guard 与时点
        assert log_at_emit["guard"]["kline_freshness"] == "contract-test"
        assert log_at_emit["total_sec"] == 1.5
        return {"md": "a.md", "json": "a.json", "status": {"html": "ok", "docx": "skip"}}

    log_at_emit = run_log
    files = rb.finalize_run(
        "600693",
        {"name": "东百集团", "code": "600693", "emoji": "🟡", "advice": "持有",
         "three_levels": {}},
        None, {"kline": []}, run_log, _FIXED_NOW, 55,
        _emit, _now, lambda: 100.0,
        kline_freshness=_freshness, record_guard=_record, finalize_timing=_timing,
    )

    # 顺序敏感: guard 与时点都必须先于落盘
    assert order == ["freshness", "record_guard", "timing", "emit"]
    assert files["md"] == "a.md"


def test_finalize_run_emit_receives_result_name_and_payload():
    captured = {}
    result = {"name": "杰瑞股份", "code": "002353", "emoji": "🟡",
              "advice": "持有", "three_levels": {}}

    def _emit(code, name, payload):
        captured["code"] = code
        captured["name"] = name
        captured["payload"] = payload
        return {}

    rb.finalize_run(
        "002353", result, None, {"kline": []}, _run_log(), _FIXED_NOW, 53,
        _emit, _now, lambda: 100.0,
        kline_freshness=lambda chip: {"level": "ok", "text": "t"},
        record_guard=lambda log, fresh: log["guard"].update(kline_freshness="t"),
        finalize_timing=lambda log, started, now_fn, time_fn: log.update(total_sec=0),
    )

    assert captured["code"] == "002353"
    assert captured["name"] == "杰瑞股份"
    assert captured["payload"] is result


def test_finalize_run_console_summary_prefers_three_levels_over_plan(capsys):
    result = {
        "name": "东百集团", "code": "600693", "emoji": "🟡", "advice": "持有",
        "three_levels": {
            "support": 9.5, "resistance": 11.0, "stop_loss": 8.8,
            "support_candidates": {"ma60": 9.5, "boll_lower": 9.9},
            "resistance_candidates": {"ma60": 11.0},
        },
    }
    plan = {"entry_low": 1.0, "tp1": 2.0, "stop_loss": 3.0}

    rb.finalize_run(
        "600693", result, plan, {"kline": []}, _run_log(), _FIXED_NOW, 55,
        lambda *_a: {}, _now, lambda: 100.0,
        kline_freshness=lambda chip: {"level": "ok", "text": "guard-t"},
        record_guard=lambda log, fresh: log["guard"].update(kline_freshness="guard-t"),
        finalize_timing=lambda log, *_a: log.update(total_sec=2.0),
    )

    out = capsys.readouterr().out
    # 三价位(同源) 行必须打印, 且取 three_levels 而非 plan 兜底值
    assert "三价位(同源)" in out
    assert "支撑=9.50" in out
    assert "压力=11.00" in out
    assert "止损=8.80" in out
    assert "ma60" in out
    assert "综合 55分" in out


def test_finalize_run_console_summary_falls_back_per_field_to_plan(capsys):
    result = {"name": "东百集团", "code": "600693", "emoji": "🟡",
              "advice": "持有", "three_levels": {"support": 9.5}}
    plan = {"entry_low": 9.0, "tp1": 11.5, "stop_loss": 8.1}

    rb.finalize_run(
        "600693", result, plan, {"kline": []}, _run_log(), _FIXED_NOW, 55,
        lambda *_a: {}, _now, lambda: 100.0,
        kline_freshness=lambda chip: {"level": "ok", "text": "guard-t"},
        record_guard=lambda log, fresh: log["guard"].update(kline_freshness="guard-t"),
        finalize_timing=lambda log, *_a: log.update(total_sec=2.0),
    )

    out = capsys.readouterr().out
    # 逐字段兜底: support 取 three_levels, 缺失的 resistance/stop_loss 回落 V2 同源 plan
    assert "支撑=9.50" in out
    assert "压力=11.50" in out
    assert "止损=8.10" in out


def test_finalize_run_console_summary_omits_line_when_three_levels_empty(capsys):
    result = {"name": "东百集团", "code": "600693", "emoji": "🟡",
              "advice": "持有", "three_levels": {}}
    plan = {"entry_low": 9.0, "tp1": 11.5, "stop_loss": 8.1}

    rb.finalize_run(
        "600693", result, plan, {"kline": []}, _run_log(), _FIXED_NOW, 55,
        lambda *_a: {}, _now, lambda: 100.0,
        kline_freshness=lambda chip: {"level": "ok", "text": "guard-t"},
        record_guard=lambda log, fresh: log["guard"].update(kline_freshness="guard-t"),
        finalize_timing=lambda log, *_a: log.update(total_sec=2.0),
    )

    # three_levels 三档全空时不打印该行 (原实现同, 避免整行只有兜底值误导)
    assert "三价位(同源)" not in capsys.readouterr().out


def test_finalize_run_skips_three_levels_line_without_plan(capsys):
    result = {"name": "东百集团", "code": "600693", "emoji": "🟡",
              "advice": "持有", "three_levels": {"support": 9.5}}

    rb.finalize_run(
        "600693", result, None, {"kline": []}, _run_log(), _FIXED_NOW, 55,
        lambda *_a: {}, _now, lambda: 100.0,
        kline_freshness=lambda chip: {"level": "ok", "text": "guard-t"},
        record_guard=lambda log, fresh: log["guard"].update(kline_freshness="guard-t"),
        finalize_timing=lambda log, *_a: log.update(total_sec=2.0),
    )

    # plan 为 None 时不得打印三价位行 (原实现同)
    assert "三价位(同源)" not in capsys.readouterr().out


def test_finalize_run_uses_real_helpers_by_default():
    """默认注入口必须是 helpers 里的真实实现, 防止接线漏传。"""
    assert rb._kline_freshness is not None
    assert rb._record_kline_freshness_guard is not None
    assert rb._finalize_run_log_timing is not None


@pytest.mark.parametrize("missing", ["code", "quote", "valuation",
                                    "score", "chip_data", "advice",
                                    "emoji", "detail"])
def test_assemble_result_requires_core_v2_keys(missing):
    """核心 V2 键缺失必须显式报错, 不得静默产出半成品 result。

    注: name 是唯一用 .get() 的核心键 (缺省回落调用方传入的 name)。
    """
    base = _base_result()
    base.pop(missing)

    with pytest.raises(KeyError):
        rb.assemble_result(
            base, None, {}, [], [], _fetched(), None, {}, {}, "x", _now,
        )
