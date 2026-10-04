"""Phase 1H 接线测试: pipeline.py 必须走 result_builder 阶段边界。

与 test_fetching_wiring.py 同构 —— 编排层抽离后, 主流程不允许再内联
build / finalize 实现, 也不允许绕过 pipeline 自身的注入口(契约测试在
pipeline 上打桩 compute_three_levels / _emit / _kline_freshness 等)。
"""

import analysis.pipeline as pipeline
from analysis.orchestration import result_builder


def test_pipeline_uses_build_trade_levels_boundary():
    assert pipeline.build_trade_levels is result_builder.build_trade_levels


def test_pipeline_uses_build_signals_boundary():
    assert pipeline.build_signals is result_builder.build_signals


def test_pipeline_uses_assemble_result_boundary():
    assert pipeline.assemble_result is result_builder.assemble_result


def test_pipeline_uses_enrich_result_boundary():
    assert pipeline.enrich_result is result_builder.enrich_result


def test_pipeline_uses_finalize_run_boundary():
    assert pipeline.finalize_run is result_builder.finalize_run


def test_pipeline_passes_injection_seams_into_result_builder():
    """契约测试在 pipeline 上打桩, 所以这些名必须由 pipeline 传入而非模块内绑定。

    若 result_builder 直接绑定自身 import 的实现, 下面这些 monkeypatch 会失效,
    端到端契约测试将退化成真实抓取/真实落盘。
    """
    src = __import__("inspect").getsource(pipeline.analyze_single_v3)

    for seam in (
        "compute_levels=compute_three_levels",
        "inject_state=inject_state_to_plan",
        "classify_north_scope=_classify_north_scope",
        "build_scoring_breakdown=_build_scoring_breakdown",
        "kline_freshness=_kline_freshness",
        "record_guard=_record_kline_freshness_guard",
        "finalize_timing=_finalize_run_log_timing",
        "_emit,",
    ):
        assert seam in src, f"analyze_single_v3 必须把注入口 {seam!r} 传给 result_builder"


def test_pipeline_keeps_legacy_re_exports():
    """v3 薄壳与既有测试仍从 pipeline 取这些名字, 不得因抽离而消失。"""
    for name in (
        "_classify_north_scope",
        "_build_scoring_breakdown",
        "_emit",
        "_dump_run_log",
        "_kline_freshness",
        "_latest_trading_day",
        "_patch_v2_timers",
        "_restore_v2",
        "_retry_call",
        "compute_three_levels",
        "inject_state_to_plan",
    ):
        assert hasattr(pipeline, name), f"pipeline 透传契约丢失: {name}"
