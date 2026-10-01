"""V2 source-status recording and appended fetch block for the V3 pipeline.

Phase 1H-4 extracts two consecutive blocks of ``analyze_single_v3``:

* §3 逐类状态判定 — recording the V2 data-class statuses onto the shared
  recorder and the run log;
* §4 V3 追加数据块 — the four new fetchers, the enabled Section Registry
  fetch, the margin fetch and the supplements fetch.

Everything else stays in ``analysis.pipeline``: the V2 invocation, the 申万
TLS handling, the trading plan / three-level model, the result assembly with
its two enrichment steps, and the successful finalization.

Every side effect is preserved exactly as before:

* call order — the status recording runs first, then the ``fetched`` mapping
  is created, then the banner line, then the four ``_call_new`` calls in
  their original order (公告 / 财务 / 研报 / 新闻, research still passing
  ``days=200``), then Section Registry, then margin, then supplements;
* ``fetched`` — the same eight keys in the same order, all initialised to
  ``None``; only the four new fetchers and ``"margin"`` are ever assigned, and
  ``_fetch_supplements`` keeps writing its three keys into that same dict;
* shared state — the recorder and ``run_log`` objects passed in are the very
  objects the injected helpers mutate; nothing is copied or rebuilt;
* identity — ``base_result``, the section objects and the fetched payloads are
  handed through unchanged, and the caller receives that same ``fetched`` dict;
* failure tolerance — no call in this stage is wrapped; the retry / timeout
  semantics stay entirely inside the existing helpers, and a failing optional
  fetch keeps recording into ``supplements`` as it does today.

Every pipeline-level dependency is injected by ``analysis.pipeline`` at call
time rather than imported here.  That keeps this module free of import-time
coupling to ``analysis.pipeline`` and ``quant_analyzer_v2`` and preserves the
existing monkeypatch surface on ``analysis.pipeline``.
"""

from collections.abc import Callable, MutableMapping
from typing import Any, NamedTuple

__all__ = [
    "FetchStageResult",
    "run_fetch_stage",
]

# V3 追加数据块的 8 个 key (顺序即拆分前字面量顺序, 全部先置 None)
_APPENDED_FETCH_KEYS = (
    "announcements",
    "finance",
    "news",
    "research",
    "margin",
    "fund_daily5",
    "margin_hist",
    "peers",
)


class FetchStageResult(NamedTuple):
    """Outcome of the appended fetch stage.

    ``fetched`` is the very dict this stage filled in (the supplements helper
    writes three of its keys into it in place), ``sections_data`` is the value
    returned by the Section Registry fetch, and ``margin`` is the very object
    the margin fetch produced — also stored under ``fetched["margin"]``.
    """

    fetched: dict[str, Any]
    sections_data: Any
    margin: Any


def run_fetch_stage(
    *,
    base_result: MutableMapping[str, Any],
    code: str,
    recorder: MutableMapping[str, Any],
    run_log: MutableMapping[str, Any],
    record_v2_source_statuses: Callable[..., Any],
    field_of: Any,
    src_desc: Any,
    status_of: Callable[[Any], str],
    call_new: Callable[..., Any],
    fetch_sections: Callable[..., Any],
    enabled_sections: Callable[[], Any],
    fetch_margin: Callable[..., Any],
    fetch_supplements: Callable[..., Any],
    new_imports: Any,
    fmt_time: Callable[[Any], str],
    margin_trading: Any,
    fetch_fund_flow_daily: Any,
    fetch_margin_history: Any,
    fetch_concept_peers: Any,
) -> FetchStageResult:
    """Record V2 source statuses, then run the appended V3 fetch block."""
    # ---- 3. 逐类状态判定 (V2 的 10 类) ----
    record_v2_source_statuses(
        base_result,
        recorder,
        run_log,
        field_of,
        src_desc,
    )

    # ---- 4. V3 追加数据块: 4 新 fetcher + 两融 (逐个记录耗时/状态/实际源) ----
    fetched: dict[str, Any] = dict.fromkeys(_APPENDED_FETCH_KEYS)

    print("\n[V3+] 追加数据块: 公告 / 财务 / 研报 / 新闻 / Section Registry / 两融 / 5日资金 / 同业…")
    fetched["announcements"] = call_new(
        recorder, run_log, new_imports, src_desc, status_of,
        "公告", "公告", code,
    )
    fetched["finance"] = call_new(
        recorder, run_log, new_imports, src_desc, status_of,
        "财务摘要", "财务", code,
    )
    fetched["research"] = call_new(
        recorder, run_log, new_imports, src_desc, status_of,
        "研报观点", "研报", code, 200,
    )  # days=200: 小票近90日常无覆盖(真实)
    fetched["news"] = call_new(
        recorder, run_log, new_imports, src_desc, status_of,
        "新闻舆情", "新闻", code,
    )
    # Section Registry: 5 新节走新路径（灰度老路径仍保留 4 旧 fetcher；spec §3.3）
    sections = enabled_sections()
    sections_data = fetch_sections(run_log, sections, code, base_result)

    margin = fetch_margin(
        run_log,
        src_desc,
        fmt_time,
        margin_trading,
        code,
    )
    fetched["margin"] = margin

    # 附加: 近5日主力 + 两融方向历史 + 同业(概念口径) — 失败不致命, 记入 supplements
    # 灰度保留：spec §3.3（"先保留 4 旧 fetcher 走老路径，5 新节走新注册表；下版本统一"）
    fetch_supplements(
        recorder,
        run_log,
        fetched,
        src_desc,
        fmt_time,
        code,
        base_result.get("blocks", []),
        fetch_fund_flow_daily,
        fetch_margin_history,
        fetch_concept_peers,
    )

    return FetchStageResult(
        fetched=fetched,
        sections_data=sections_data,
        margin=margin,
    )
