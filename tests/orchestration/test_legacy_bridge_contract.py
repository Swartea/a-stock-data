import re

import pytest

import analysis.pipeline as pipeline
from analysis.orchestration import legacy_bridge


EXPECTED_V2_FN_TO_SRC = {
    "fetch_tencent_quote": "行情",
    "fetch_full_valuation": "估值一致预期",
    "fetch_eastmoney_concept_blocks": "概念板块",
    "fetch_fund_flow_minute": "当日资金流",
    "fetch_valuation_history": "估值历史分位",
    "fetch_lockup_expiry": "解禁日历",
    "fetch_dragon_tiger": "龙虎榜",
    "fetch_macro_snapshot": "宏观底色",
    "fetch_chip_distribution": "筹码K线",
    "fetch_sw_stability": "申万分类",
}

EXPECTED_FIELD_OF = {
    "行情": "quote",
    "估值一致预期": "valuation",
    "概念板块": "blocks",
    "当日资金流": "fund",
    "估值历史分位": "valuation_hist",
    "解禁日历": "lockup",
    "龙虎榜": "dragon",
    "宏观底色": "macro",
    "筹码K线": "chip_data",
    "申万分类": "sw_data",
}


@pytest.fixture(autouse=True)
def _clean_source_status_recorder():
    pipeline._src_meta.clear()
    yield
    pipeline._src_meta.clear()


def _stub_for(name):
    def stub(*args, **kwargs):
        return {"fn": name, "args": args, "kwargs": kwargs}

    return stub


def _install_only(monkeypatch, target_name, target_fn):
    for fn_name in EXPECTED_V2_FN_TO_SRC:
        if fn_name == target_name:
            monkeypatch.setattr(pipeline.v2, fn_name, target_fn, raising=False)
        else:
            monkeypatch.delattr(pipeline.v2, fn_name, raising=False)


def _patch():
    return legacy_bridge._patch_v2_timers(
        pipeline.v2,
        pipeline._src_meta,
        pipeline._fmt_time,
    )


def _restore(saved):
    legacy_bridge._restore_v2(pipeline.v2, saved)


def test_legacy_source_and_result_field_mappings_are_locked():
    assert legacy_bridge._V2_FN_TO_SRC == EXPECTED_V2_FN_TO_SRC
    assert legacy_bridge._FIELD_OF == EXPECTED_FIELD_OF
    assert set(legacy_bridge._V2_FN_TO_SRC.values()) == set(legacy_bridge._FIELD_OF)

    expected_top = {
        fn_name: EXPECTED_FIELD_OF[label]
        for fn_name, label in EXPECTED_V2_FN_TO_SRC.items()
    }
    assert legacy_bridge._TOP_FIELD_OF == expected_top

    # pipeline keeps importing these names so its existing result/status logic
    # sees the same exact mappings after extraction.
    assert pipeline._V2_FN_TO_SRC is legacy_bridge._V2_FN_TO_SRC
    assert pipeline._FIELD_OF is legacy_bridge._FIELD_OF
    assert pipeline._TOP_FIELD_OF is legacy_bridge._TOP_FIELD_OF


def test_patch_wraps_available_functions_and_restore_is_symmetric(monkeypatch):
    originals = {}
    for fn_name in EXPECTED_V2_FN_TO_SRC:
        original = _stub_for(fn_name)
        originals[fn_name] = original
        monkeypatch.setattr(pipeline.v2, fn_name, original, raising=False)

    saved = _patch()
    try:
        assert saved == originals
        assert set(pipeline._src_meta) == set(EXPECTED_FIELD_OF)
        for label in EXPECTED_FIELD_OF:
            assert pipeline._src_meta[label] == {
                "ms": None,
                "at": None,
                "status": None,
                "detail": None,
            }

        wrapped = pipeline.v2.fetch_tencent_quote
        assert wrapped is not originals["fetch_tencent_quote"]
        result = wrapped("600693", flag=True)

        assert result == {
            "fn": "fetch_tencent_quote",
            "args": ("600693",),
            "kwargs": {"flag": True},
        }
        meta = pipeline._src_meta["行情"]
        assert isinstance(meta["ms"], int)
        assert meta["ms"] >= 0
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", meta["at"])
        assert meta["status"] is None
        assert meta["detail"] is None
    finally:
        _restore(saved)

    for fn_name, original in originals.items():
        assert getattr(pipeline.v2, fn_name) is original


def test_patch_skips_missing_v2_function_without_creating_meta(monkeypatch):
    target_name = "fetch_tencent_quote"
    target_label = EXPECTED_V2_FN_TO_SRC[target_name]

    monkeypatch.delattr(pipeline.v2, target_name, raising=False)
    originals = {}
    for fn_name in EXPECTED_V2_FN_TO_SRC:
        if fn_name == target_name:
            continue
        original = _stub_for(fn_name)
        originals[fn_name] = original
        monkeypatch.setattr(pipeline.v2, fn_name, original, raising=False)

    saved = _patch()
    try:
        assert target_name not in saved
        assert target_label not in pipeline._src_meta
        assert set(saved) == set(originals)
    finally:
        _restore(saved)


def test_timer_wrapper_recreates_sparse_meta_after_recorder_clear(monkeypatch):
    target_name = "fetch_tencent_quote"
    original = _stub_for(target_name)
    _install_only(monkeypatch, target_name, original)

    saved = _patch()
    try:
        assert pipeline._src_meta["行情"] == {
            "ms": None,
            "at": None,
            "status": None,
            "detail": None,
        }

        # analyze_single_v3 currently clears the recorder after patching and
        # before calling V2. The bridge must preserve that sparse re-creation.
        pipeline._src_meta.clear()
        pipeline.v2.fetch_tencent_quote("600693")

        meta = pipeline._src_meta["行情"]
        assert set(meta) == {"ms", "at"}
        assert isinstance(meta["ms"], int)
        assert meta["ms"] >= 0
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", meta["at"])
    finally:
        _restore(saved)


def test_timer_wrapper_records_timing_and_reraises_original_error(monkeypatch):
    target_name = "fetch_tencent_quote"

    def boom(*args, **kwargs):
        raise RuntimeError("legacy fetch failed")

    _install_only(monkeypatch, target_name, boom)
    saved = _patch()
    try:
        pipeline._src_meta.clear()
        with pytest.raises(RuntimeError, match="legacy fetch failed"):
            pipeline.v2.fetch_tencent_quote("600693")

        meta = pipeline._src_meta["行情"]
        assert set(meta) == {"ms", "at"}
        assert isinstance(meta["ms"], int)
        assert meta["ms"] >= 0
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", meta["at"])
    finally:
        _restore(saved)


def test_restore_only_restores_saved_functions_and_does_not_touch_status(monkeypatch):
    target_name = "fetch_tencent_quote"
    original = _stub_for(target_name)
    _install_only(monkeypatch, target_name, original)

    saved = _patch()
    pipeline._src_meta["自定义"] = {"status": "keep"}

    _restore(saved)

    assert pipeline.v2.fetch_tencent_quote is original
    assert pipeline._src_meta["自定义"] == {"status": "keep"}
