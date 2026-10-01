"""V3 successful-path finalization boundary for the orchestration pipeline.

Phase 1H-2 extracts only the end-of-pipeline block that runs after
``analyze_single_v3`` has a complete ``result_v3``: the K-line freshness guard,
the run-log timing stamp, the artifact ``_emit`` call, and the console summary.
The fatal V2 path and the result-builder stage stay in ``analysis.pipeline``.

Every side effect is preserved exactly as before:

* operation order — guard, then timing, then emit, then console summary;
* mutation behaviour — the guard writes into ``run_log`` and the timing helper
  writes ``finished_at`` / ``total_sec`` into the same ``run_log`` object the
  caller already holds, in place;
* return identity — the very same ``result`` object that was passed in is
  returned, so callers keep the object they built;
* artifact arguments — ``_emit`` still receives ``(code, result["name"],
  result)`` positionally;
* console text — every line and the conditional three-level block are emitted
  verbatim, including the guard line and the conditional file/status lines.

The four pipeline-level callables (``_kline_freshness``,
``_record_kline_freshness_guard``, ``_finalize_run_log_timing`` and ``_emit``)
are injected by ``analysis.pipeline`` at call time rather than imported here.
That keeps this module free of import-time coupling to the artifact writer and
preserves the existing monkeypatch surface on ``analysis.pipeline``.
"""

from collections.abc import Callable
from typing import Any

__all__ = [
    "finalize_successful_run",
]


def finalize_successful_run(
    *,
    code: str,
    result: dict[str, Any],
    plan: dict[str, Any] | None,
    score_total: Any,
    chip_data: Any,
    run_log: dict[str, Any],
    started: Any,
    kline_freshness: Callable[[Any], Any],
    record_kline_freshness_guard: Callable[[dict[str, Any], Any], Any],
    finalize_run_log_timing: Callable[[dict[str, Any], Any, Any, Any], Any],
    emit: Callable[[str, str, dict[str, Any]], Any],
    now_fn: Callable[[], Any],
    time_fn: Callable[[], float],
) -> dict[str, Any]:
    """Run the successful end-of-pipeline block and return ``result``.

    Returns the same ``result`` object that was passed in (identity is
    preserved, the dictionary is never copied or rebuilt) so the pipeline's
    return contract is unchanged.
    """
    # ---- 6. run_log 收尾: guard + 时点 ----
    fresh = kline_freshness(chip_data)
    record_kline_freshness_guard(run_log, fresh)
    print(f"\n[guard] {run_log['guard']['kline_freshness']}")

    finalize_run_log_timing(run_log, started, now_fn, time_fn)

    # ---- 7. 输出: 五件套 (MD + result_v3.json + HTML + DOCX + run_log.json) ----
    files = emit(code, result["name"], result)

    # 控制台摘要
    print("\n" + "=" * 72)
    print(f"【V3】{result['name']} ({code}) 综合 {score_total}分 "
          f"{result['emoji']}{result['advice']}  耗时 {run_log['total_sec']}s")
    # 三价位(同源) — 债 2 修法 (Task 5.2): 优先读 result['three_levels'] 4 候选取最近者;
    # 兜底用 plan['entry_low'/'tp1'/'stop_loss']（V2 同源），保证控制台/HTML/MD 输出口径一致
    tl3 = result.get("three_levels") or {}
    if plan and (tl3.get("support") or tl3.get("resistance") or tl3.get("stop_loss")):
        print(f"  三价位(同源): 支撑={(tl3.get('support') or plan['entry_low']):.2f} "
              f"压力={(tl3.get('resistance') or plan['tp1']):.2f} "
              f"止损={(tl3.get('stop_loss') or plan['stop_loss']):.2f} "
              f"(4 候选支撑={list((tl3.get('support_candidates') or {}).keys())}, "
              f"3 候选压力={list((tl3.get('resistance_candidates') or {}).keys())})")
    for key in ("md", "json", "html", "docx", "run_log"):
        p = files.get(key)
        if p:
            print(f"  {key.upper()}: {p}")
    st = files.get("status", {})
    print(f"  状态: html={st.get('html')}  docx={st.get('docx')}")
    return result
