"""Compatibility bridge for legacy V2 fetch instrumentation.

This module owns only the V2 function/source mappings and the temporary
monkey-patch used by the V3 orchestration layer.  Dependencies that carry
runtime state are passed in explicitly so the bridge does not create a second
recorder or import ``analysis.pipeline``.
"""

import time


# V2 fetch function -> source label.
_V2_FN_TO_SRC = {
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

# Source label -> field in the legacy V2 result.
_FIELD_OF = {
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

# Kept as a derived compatibility mapping even though pipeline currently does
# not consume it directly.
_TOP_FIELD_OF = {fn: _FIELD_OF[label] for fn, label in _V2_FN_TO_SRC.items()}


def _patch_v2_timers(v2_module, recorder, fmt_time):
    """Wrap available V2 fetchers and record timing without changing behavior."""
    saved = {}

    def _make_wrapper(fn_name, orig):
        def wrapper(*args, **kwargs):
            started = time.time()
            try:
                return orig(*args, **kwargs)
            finally:
                label = _V2_FN_TO_SRC.get(fn_name, fn_name)
                recorder.setdefault(label, {})["ms"] = round(
                    (time.time() - started) * 1000
                )
                recorder[label]["at"] = fmt_time(time.time())

        return wrapper

    for fn_name, label in _V2_FN_TO_SRC.items():
        if not hasattr(v2_module, fn_name):
            continue
        saved[fn_name] = getattr(v2_module, fn_name)
        setattr(v2_module, fn_name, _make_wrapper(fn_name, saved[fn_name]))
        recorder[label] = {
            "ms": None,
            "at": None,
            "status": None,
            "detail": None,
        }
    return saved


def _restore_v2(v2_module, saved):
    """Restore only the V2 functions previously replaced by the timer patch."""
    for fn_name, orig in saved.items():
        setattr(v2_module, fn_name, orig)
