"""V3 result assembly boundary for the orchestration pipeline.

Phase 1H extracts only the deterministic part of ``analyze_single_v3``:
construction of the public ``result_v3`` dictionary and its two enrichment
steps (macro north-scope classification and the five-dimension scoring
breakdown).  Fetch order, data-source policy, scoring math, report text and
runtime side effects stay in ``analysis.pipeline``.

The helpers keep the existing mutation behaviour: north scope is written back
into ``result["macro"]`` in place, and ``scoring_breakdown`` is attached to the
same ``result`` object the pipeline later emits.  Console summaries remain the
pipeline's responsibility so that printed output and its ordering are
unchanged.
"""

from collections.abc import Callable
from typing import Any

__all__ = [
    "apply_north_scope",
    "apply_scoring_breakdown",
    "build_result_v3",
]

def build_result_v3(
    *,
    code: str,
    name: str,
    base_result: dict[str, Any],
    fetched: dict[str, Any],
    margin: Any,
    plan: dict[str, Any] | None,
    three_levels: dict[str, Any] | None,
    good_signals: Any,
    bad_signals: Any,
    run_log: dict[str, Any],
    sections_data: dict[str, Any],
    now_fn: Callable[[], Any],
) -> dict[str, Any]:
    """Assemble the public ``result_v3`` dictionary.

    Field names, ordering, defaults and the ``sections_data`` passthrough are
    preserved verbatim from the pre-extraction pipeline.  ``sections_data`` is
    splatted last, so an enabled section label still becomes a top-level key
    and still wins over the explicit keys above.
    """
    q = base_result["quote"]
    v = base_result["valuation"]
    score = base_result["score"]
    chip_data = base_result["chip_data"]

    result = {
        "code": code, "name": base_result.get("name") or name,
        "quote": q, "valuation": v, "blocks": base_result.get("blocks", []),
        "fund": base_result.get("fund", {}), "valuation_hist": base_result.get("valuation_hist", {}),
        "lockup": base_result.get("lockup", {}), "dragon": base_result.get("dragon", {}),
        "macro": base_result.get("macro", {}), "chip_data": chip_data,
        "sw_data": base_result.get("sw_data", {}),
        "announcements": fetched["announcements"], "finance": fetched["finance"],
        "news": fetched["news"], "research": fetched["research"],
        "margin": margin, "peers": fetched["peers"],
        "fund_daily5": fetched["fund_daily5"], "margin_hist": fetched["margin_hist"],
        "score": score, "advice": base_result["advice"], "emoji": base_result["emoji"],
        "detail": base_result["detail"], "trading_plan": plan,
        "three_levels": three_levels,
        "signals": {"good": good_signals, "bad": bad_signals},
        "run_log": run_log,
        "report_date": now_fn().strftime("%Y-%m-%d"),
        **sections_data,  # Phase 1: 注入 section.label (irm) 作为 result 顶层 key
    }

    return result


def apply_north_scope(
    result: dict[str, Any],
    classify_north_scope: Callable[[Any], tuple],
) -> tuple[str, str]:
    """Write ``macro.north_scope`` / ``macro.north_label`` onto ``result``.

    Mutates ``result["macro"]`` in place, matching the original behaviour, and
    returns ``(scope, label)`` for the caller's console summary.  The classifier
    is injected so this module carries no import-time dependency on the
    analytics package.
    """
    north_data = (result.get("macro") or {}).get("hsgt") or {}
    scope, label = classify_north_scope(north_data)
    result["macro"]["north_scope"] = scope      # "market" / "stock" / "mixed" / "unknown"
    result["macro"]["north_label"] = label      # 模板直接用的字符串 (含 scope 关键词)
    return scope, label


def apply_scoring_breakdown(
    result: dict[str, Any],
    build_scoring_breakdown: Callable[[Any], dict],
) -> dict[str, Any]:
    """Attach ``result["scoring_breakdown"]`` from the V2 ten-dimension score.

    The five-dimension aggregation itself stays in
    ``analysis.analytics.scoring``; this helper only performs the wiring and
    returns the breakdown for the caller's console summary.
    """
    breakdown = build_scoring_breakdown(result["score"])
    result["scoring_breakdown"] = breakdown
    return breakdown
