"""Result build / finalize stages for the V3 pipeline (Phase 1H).

``analyze_single_v3`` used to own twelve responsibilities inline.  Phases 1A-1G
moved the helper-level concerns into their own boundaries; this module takes the
two remaining *pure* stages so the orchestrator is reduced to a fetch / build /
finalize shape:

- **build**  — three levels, state-machine injection, signal split, result
  assembly, then the north-scope and scoring-breakdown enrichment.
- **finalize** — K-line freshness guard, run-log timing, artifact emission and
  the console summary.

Business semantics are unchanged: threshold values, result keys, console wording
and emission order are identical to the previous inline implementation.  Only the
stage boundaries move.  V2 stays injected (``make_trading_plan`` /
``make_signal_list`` / ``emit``) because those call sites depend on the
monkey-patched ``quant_analyzer_v2`` module state owned by the fetch stage.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional

from analysis.analytics.scope import _classify_north_scope
from analysis.analytics.scoring import _build_scoring_breakdown
from analysis.orchestration.helpers import (
    _finalize_run_log_timing,
    _kline_freshness,
    _record_kline_freshness_guard,
)
from analysis.three_levels import compute_three_levels
from analysis.trading_plan import inject_state_to_plan

__all__ = [
    "assemble_result",
    "build_signals",
    "build_trade_levels",
    "enrich_result",
    "finalize_run",
]


# ============================================================
# Stage: build
# ============================================================


def build_trade_levels(
    quote: dict,
    valuation: dict,
    chip_data: dict,
    score_total: Any,
    valuation_hist: dict,
    make_trading_plan: Callable[..., Optional[dict]],
    compute_levels: Callable[..., dict] = compute_three_levels,
    inject_state: Callable[..., Any] = inject_state_to_plan,
) -> tuple[Optional[dict], dict]:
    """Build the trading plan, inject the 5-state machine, derive three levels.

    Returns ``(plan, three_levels)``.

    ``compute_levels`` / ``inject_state`` are injectable so ``pipeline.py`` can
    hand in its own module-level references; contract tests monkeypatch those
    names on ``pipeline`` to isolate this stage.

    ``inject_state`` is only called when ``plan`` is truthy, matching the
    previous inline behavior: a failed V2 plan must not be mutated.
    """
    plan = make_trading_plan(quote, valuation, chip_data, score_total)

    # 批次 E 痛 3 (PE 分位 > 85% 旁路): 见 analysis.trading_plan.apply_pe_pctl_bypass
    pe_pctile = valuation_hist.get("pe_percentile_3y")
    inject_state(plan, score_total, pe_pctile) if plan else None

    # 债 2 修法: 支撑下沿/压力上沿与 trading_plan 同源 K 线
    three_levels = compute_levels(quote, chip_data, plan)
    return plan, three_levels


def build_signals(
    score: dict,
    make_signal_list: Callable[..., tuple[list, list]],
) -> tuple[list, list]:
    """Split V2's factor map into ``(good_signals, bad_signals)``."""
    return make_signal_list(score, score["factors"])


def assemble_result(
    base_result: dict,
    plan: Optional[dict],
    three_levels: dict,
    good_signals: list,
    bad_signals: list,
    fetched: dict,
    margin: Any,
    run_log: dict,
    sections_data: dict,
    name: str,
    now_fn: Callable[[], datetime],
) -> dict:
    """Assemble the ``result_v3`` contract dict (contract keys unchanged)."""
    score = base_result["score"]
    return {
        "code": base_result["code"],
        "name": base_result.get("name") or name,
        "quote": base_result["quote"],
        "valuation": base_result["valuation"],
        "blocks": base_result.get("blocks", []),
        "fund": base_result.get("fund", {}),
        "valuation_hist": base_result.get("valuation_hist", {}),
        "lockup": base_result.get("lockup", {}),
        "dragon": base_result.get("dragon", {}),
        "macro": base_result.get("macro", {}),
        "chip_data": base_result["chip_data"],
        "sw_data": base_result.get("sw_data", {}),
        "announcements": fetched["announcements"],
        "finance": fetched["finance"],
        "news": fetched["news"],
        "research": fetched["research"],
        "margin": margin,
        "peers": fetched["peers"],
        "fund_daily5": fetched["fund_daily5"],
        "margin_hist": fetched["margin_hist"],
        "score": score,
        "advice": base_result["advice"],
        "emoji": base_result["emoji"],
        "detail": base_result["detail"],
        "trading_plan": plan,
        "three_levels": three_levels,
        "signals": {"good": good_signals, "bad": bad_signals},
        "run_log": run_log,
        "report_date": now_fn().strftime("%Y-%m-%d"),
        **sections_data,
    }


def enrich_result(
    result: dict,
    score: dict,
    classify_north_scope: Callable[[dict], tuple[str, str]] = _classify_north_scope,
    build_scoring_breakdown: Callable[[dict], dict] = _build_scoring_breakdown,
) -> dict:
    """Attach north-funding scope labels and the 5-dimension scoring breakdown.

    债 3 修法: ``macro.north_scope`` / ``macro.north_label`` give the renderers a
    real label instead of a hardcoded string, so a market-wide reading can no
    longer be misread as a single-stock one.

    批次 C 痛 7: ``scoring_breakdown`` makes the composite score auditable.

    Mutates and returns ``result`` (the previous inline behavior).
    """
    # ---- 债 3 修法: 北向资金口径分类 ----
    north_data = (result.get("macro") or {}).get("hsgt") or {}
    scope, label = classify_north_scope(north_data)
    result["macro"]["north_scope"] = scope
    result["macro"]["north_label"] = label
    print(f"[v3] 北向资金 scope={scope} label='{label}'")

    # ---- 批次 C 痛 7: 5 维评分构成 ----
    result["scoring_breakdown"] = build_scoring_breakdown(score)
    bd = result["scoring_breakdown"]
    print(
        f"[v3] 评分构成: 总分 {bd['total']['score']}/{bd['total']['max']} | "
        f"技术 {bd['tech']['score']}/{bd['tech']['max']} | "
        f"资金 {bd['capital']['score']}/{bd['capital']['max']} | "
        f"估值 {bd['valuation']['score']}/{bd['valuation']['max']} | "
        f"情绪 {bd['sentiment']['score']}/{bd['sentiment']['max']} | "
        f"风险 {bd['risk']['score']}/{bd['risk']['max']}"
    )
    return result


# ============================================================
# Stage: finalize
# ============================================================


def _print_console_summary(
    result: dict,
    plan: Optional[dict],
    run_log: dict,
    score_total: Any,
    files: dict,
) -> None:
    """Print the end-of-run console summary (wording/order unchanged)."""
    print("\n" + "=" * 72)
    print(
        f"【V3】{result['name']} ({result['code']}) 综合 {score_total}分 "
        f"{result['emoji']}{result['advice']}  耗时 {run_log['total_sec']}s"
    )
    # 三价位(同源) — 债 2 修法: 优先读 result['three_levels'];
    # 兜底用 plan['entry_low'/'tp1'/'stop_loss'] (V2 同源), 保证控制台/HTML/MD 口径一致
    tl3 = result.get("three_levels") or {}
    if plan and (tl3.get("support") or tl3.get("resistance") or tl3.get("stop_loss")):
        print(
            f"  三价位(同源): 支撑={(tl3.get('support') or plan['entry_low']):.2f} "
            f"压力={(tl3.get('resistance') or plan['tp1']):.2f} "
            f"止损={(tl3.get('stop_loss') or plan['stop_loss']):.2f} "
            f"(4 候选支撑={list((tl3.get('support_candidates') or {}).keys())}, "
            f"3 候选压力={list((tl3.get('resistance_candidates') or {}).keys())})"
        )
    for key in ("md", "json", "html", "docx", "run_log"):
        p = files.get(key)
        if p:
            print(f"  {key.upper()}: {p}")
    st = files.get("status", {})
    print(f"  状态: html={st.get('html')}  docx={st.get('docx')}")


def finalize_run(
    code: str,
    result: dict,
    plan: Optional[dict],
    chip_data: dict,
    run_log: dict,
    started: datetime,
    score_total: Any,
    emit: Callable[[str, str, dict], dict],
    now_fn: Callable[[], datetime],
    time_fn: Callable[[], float],
    kline_freshness: Callable[..., dict] = _kline_freshness,
    record_guard: Callable[..., Any] = _record_kline_freshness_guard,
    finalize_timing: Callable[..., Any] = _finalize_run_log_timing,
) -> dict:
    """Guard, close the run log, emit artifacts, print the summary.

    Ordering is load-bearing: the freshness guard must land in ``run_log``
    *before* the timing is closed, and both must happen before ``emit`` so the
    serialized run log carries the final guard state.

    The three guard/timing callables are injectable so ``pipeline.py`` can pass
    its own module-level references (contract tests patch them on ``pipeline``).

    Returns the ``files`` mapping from ``emit``.
    """
    # ---- K 线新鲜度 guard ----
    fresh = kline_freshness(chip_data)
    record_guard(run_log, fresh)
    print(f"\n[guard] {run_log['guard']['kline_freshness']}")

    # ---- run_log 收尾: 时点 ----
    finalize_timing(run_log, started, now_fn, time_fn)

    # ---- 输出: 五件套 (MD + result_v3.json + HTML + DOCX + run_log.json) ----
    files = emit(code, result["name"], result)

    _print_console_summary(result, plan, run_log, score_total, files)
    return files
