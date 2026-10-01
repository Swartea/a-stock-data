"""Focused tests for the V3 fetch stage boundary (Phase 1H-4).

These tests exercise ``analysis.orchestration.fetch_stage`` directly through
injected fakes, so they need no network access and never import
``quant_analyzer_v2`` or ``analysis.pipeline``.  They pin the contracts the
extraction had to preserve: the complete operation order, the exact arguments
handed to every injected dependency, the identity of ``base_result`` / the
section objects / the fetched payloads, the ``fetched`` key set, insertion
order and initial ``None`` values, and the returned structure.
"""

import pytest

from analysis.orchestration.fetch_stage import (
    FetchStageResult,
    run_fetch_stage,
)


# --------------------------------------------------------------- fixtures

SECTIONS = ("公告摘要", "资金面", "同业对比")
NEW_IMPORTS = {"announcements": "mod_a", "finance": "mod_b"}
SRC_DESC = {"tencent": "腾讯行情"}
FIELD_OF = {"quote": "quote_field"}


def _fmt_time(t):
    return "2026-09-16T00:00:00+00:00"


def _status_of(blob):
    return "ok" if isinstance(blob, dict) else "error"


@pytest.fixture
def calls():
    """Ordered record of every injected side effect."""
    return []


@pytest.fixture
def base_result():
    """Stand-in for the V2 result dict; carries a ``blocks`` list."""
    return {
        "code": "600693",
        "quote": {"price": 12.34},
        "blocks": ["block_a", "block_b"],
    }


class _Recorder(dict):
    """Minimal shared recorder whose mutations are observable in place."""


def _invoke(
    calls,
    base_result,
    *,
    recorder=None,
    run_log=None,
    sections=SECTIONS,
    margin_payload=None,
    section_payload=None,
    call_new_results=None,
    supplements_writes=None,
    enabled_raises=None,
    call_new_raises_at=None,
    margin_raises=None,
    supplements_raises=None,
):
    """Call the stage with recording fakes; returns ``FetchStageResult``."""
    recorder = _Recorder() if recorder is None else recorder
    run_log = {} if run_log is None else run_log
    margin_payload = {"rzrq": [1, 2]} if margin_payload is None else margin_payload
    section_payload = {"资金面": {"ok": True}} if section_payload is None else section_payload
    call_new_results = (
        {"公告": "ann_blob", "财务摘要": "fin_blob", "研报观点": "res_blob", "新闻舆情": "news_blob"}
        if call_new_results is None
        else call_new_results
    )

    def record_v2_source_statuses(base, rec, log, field_of, src_desc):
        calls.append(("record_v2_source_statuses", base, rec, log, field_of, src_desc))
        rec["tencent"] = {"label": "腾讯行情"}
        log["sources"] = {"tencent": "ok"}

    def call_new(rec, log, new_imports, src_desc, status_of, label, src_key, code, *extra):
        calls.append(("call_new", rec, log, new_imports, src_desc, status_of, label, src_key, code, extra))
        if call_new_raises_at == label:
            raise RuntimeError("call_new failed: " + label)
        return call_new_results.get(label)

    def enabled_sections():
        calls.append(("enabled_sections",))
        if enabled_raises is not None:
            raise enabled_raises
        return sections

    def fetch_sections(log, section_list, code, base):
        calls.append(("fetch_sections", log, section_list, code, base))
        return section_payload

    def fetch_margin(log, src_desc, fmt_time, margin_trading, code):
        calls.append(("fetch_margin", log, src_desc, fmt_time, margin_trading, code))
        if margin_raises is not None:
            raise margin_raises
        return margin_payload

    def fetch_supplements(rec, log, fetched, src_desc, fmt_time, code, blocks, *fetchers):
        calls.append(("fetch_supplements", rec, log, fetched, src_desc, fmt_time, code, blocks, fetchers))
        if supplements_raises is not None:
            raise supplements_raises
        for key, value in (supplements_writes or {}).items():
            fetched[key] = value

    margin_trading = object()
    fund_flow = object()
    margin_hist = object()
    concept_peers = object()

    result = run_fetch_stage(
        base_result=base_result,
        code="600693",
        recorder=recorder,
        run_log=run_log,
        record_v2_source_statuses=record_v2_source_statuses,
        field_of=FIELD_OF,
        src_desc=SRC_DESC,
        status_of=_status_of,
        call_new=call_new,
        fetch_sections=fetch_sections,
        enabled_sections=enabled_sections,
        fetch_margin=fetch_margin,
        fetch_supplements=fetch_supplements,
        new_imports=NEW_IMPORTS,
        fmt_time=_fmt_time,
        margin_trading=margin_trading,
        fetch_fund_flow_daily=fund_flow,
        fetch_margin_history=margin_hist,
        fetch_concept_peers=concept_peers,
    )
    return result, {
        "recorder": recorder,
        "run_log": run_log,
        "margin_trading": margin_trading,
        "fund_flow": fund_flow,
        "margin_hist": margin_hist,
        "concept_peers": concept_peers,
        "margin_payload": margin_payload,
        "section_payload": section_payload,
        "sections": sections,
    }


# ----------------------------------------------------------------- tests

# --- operation order ------------------------------------------------------

def test_full_operation_order_is_recorded(calls, base_result):
    _invoke(calls, base_result)
    assert [c[0] for c in calls] == [
        "record_v2_source_statuses",
        "call_new", "call_new", "call_new", "call_new",
        "enabled_sections",
        "fetch_sections",
        "fetch_margin",
        "fetch_supplements",
    ]


def test_four_call_new_runs_in_announcement_finance_research_news_order(calls, base_result):
    _invoke(calls, base_result)
    labels = [c[6] for c in calls if c[0] == "call_new"]
    src_keys = [c[7] for c in calls if c[0] == "call_new"]
    assert labels == ["公告", "财务摘要", "研报观点", "新闻舆情"]
    assert src_keys == ["公告", "财务", "研报", "新闻"]


def test_research_call_new_still_passes_days_200(calls, base_result):
    _invoke(calls, base_result)
    extras = {c[6]: c[9] for c in calls if c[0] == "call_new"}
    assert extras["研报观点"] == (200,)
    assert extras["公告"] == ()
    assert extras["财务摘要"] == ()
    assert extras["新闻舆情"] == ()


def test_status_recording_runs_before_any_fetch(calls, base_result):
    _invoke(calls, base_result)
    assert calls[0][0] == "record_v2_source_statuses"
    # every fetch happens strictly after it
    assert all(c[0] != "call_new" for c in calls[:1])


# --- dependency arguments -------------------------------------------------

def test_status_recording_receives_injected_dependencies(calls, base_result):
    result, ctx = _invoke(calls, base_result)
    call = calls[0]
    assert call[1] is base_result                      # base_result identity
    assert call[2] is ctx["recorder"]                  # shared recorder identity
    assert call[3] is ctx["run_log"]                   # shared run_log identity
    assert call[4] is FIELD_OF
    assert call[5] is SRC_DESC


def test_call_new_receives_injected_dependencies_in_original_positions(calls, base_result):
    _invoke(calls, base_result)
    for call in [c for c in calls if c[0] == "call_new"]:
        assert call[1] is not None                      # recorder
        assert call[2] is not None                      # run_log
        assert call[3] is NEW_IMPORTS
        assert call[4] is SRC_DESC
        assert call[5] is _status_of
        assert call[8] == "600693"                      # code


def test_call_new_shares_the_same_recorder_and_run_log_as_status_recording(calls, base_result):
    _invoke(calls, base_result)
    recorder, run_log = calls[0][2], calls[0][3]
    for call in [c for c in calls if c[0] == "call_new"]:
        assert call[1] is recorder
        assert call[2] is run_log


def test_fetch_sections_gets_run_log_sections_code_and_base_result(calls, base_result):
    result, ctx = _invoke(calls, base_result)
    call = next(c for c in calls if c[0] == "fetch_sections")
    assert call[1] is ctx["run_log"]
    assert call[2] == SECTIONS                        # enabled_sections() output
    assert call[3] == "600693"
    assert call[4] is base_result                     # base_result identity


def test_fetch_margin_gets_run_log_src_desc_fmt_time_and_v2_callable(calls, base_result):
    result, ctx = _invoke(calls, base_result)
    call = next(c for c in calls if c[0] == "fetch_margin")
    assert call[1] is ctx["run_log"]
    assert call[2] is SRC_DESC
    assert call[3] is _fmt_time
    assert call[4] is ctx["margin_trading"]           # v2.fetch_margin_trading seam
    assert call[5] == "600693"


def test_fetch_supplements_gets_blocks_and_the_three_fetcher_callables(calls, base_result):
    result, ctx = _invoke(calls, base_result)
    call = next(c for c in calls if c[0] == "fetch_supplements")
    assert call[1] is ctx["recorder"]
    assert call[2] is ctx["run_log"]
    assert call[3] is result.fetched                   # same dict, mutated in place
    assert call[4] is SRC_DESC
    assert call[5] is _fmt_time
    assert call[6] == "600693"
    assert call[7] == ["block_a", "block_b"]          # base_result["blocks"]
    assert call[8] == (ctx["fund_flow"], ctx["margin_hist"], ctx["concept_peers"])


def test_base_result_without_blocks_passes_empty_list(calls):
    base = {"code": "600693"}
    result, _ = _invoke(calls, base)
    call = next(c for c in calls if c[0] == "fetch_supplements")
    assert call[7] == []


# --- fetched mapping ------------------------------------------------------

def test_fetched_keys_and_insertion_order_are_preserved(calls, base_result):
    result, _ = _invoke(calls, base_result)
    assert list(result.fetched) == [
        "announcements", "finance", "news", "research",
        "margin", "fund_daily5", "margin_hist", "peers",
    ]


def test_fetched_starts_all_none_and_is_filled_in_order(calls, base_result):
    seen = {}

    def call_new(rec, log, new_imports, src_desc, status_of, label, src_key, code, *extra):
        calls.append(("call_new", label))
        seen.setdefault("call_order", []).append(label)
        return f"{label}_blob"

    def fetch_supplements(rec, log, fetched, src_desc, fmt_time, code, blocks, *fetchers):
        # the mapping reaches supplements fully built: 4 new fetchers + margin
        seen["at_supplements"] = dict(fetched)
        seen["supplements_arg"] = fetched
        calls.append(("fetch_supplements",))

    result = run_fetch_stage(
        base_result=base_result, code="600693",
        recorder=_Recorder(), run_log={},
        record_v2_source_statuses=lambda *a: calls.append(("record_v2_source_statuses",)),
        field_of=FIELD_OF, src_desc=SRC_DESC, status_of=_status_of,
        call_new=call_new,
        fetch_sections=lambda *a: {},
        enabled_sections=lambda: SECTIONS,
        fetch_margin=lambda *a: {"m": 1},
        fetch_supplements=fetch_supplements,
        new_imports=NEW_IMPORTS, fmt_time=_fmt_time,
        margin_trading=object(), fetch_fund_flow_daily=object(),
        fetch_margin_history=object(), fetch_concept_peers=object(),
    )
    # the four new fetchers run in the original order and land in their keys
    assert seen["call_order"] == ["公告", "财务摘要", "研报观点", "新闻舆情"]
    # the same dict object travels all the way out to the caller
    assert seen["supplements_arg"] is result.fetched
    # all 8 keys already existed before supplements wrote its three
    assert seen["at_supplements"] == {
        "announcements": "公告_blob",
        "finance": "财务摘要_blob",
        "news": "新闻舆情_blob",
        "research": "研报观点_blob",
        "margin": {"m": 1},
        "fund_daily5": None,
        "margin_hist": None,
        "peers": None,
    }


def test_fetched_values_are_the_returned_payloads(calls, base_result):
    result, _ = _invoke(calls, base_result)
    assert result.fetched["announcements"] == "ann_blob"
    assert result.fetched["finance"] == "fin_blob"
    assert result.fetched["research"] == "res_blob"
    assert result.fetched["news"] == "news_blob"
    assert result.fetched["margin"] is result.margin


def test_supplements_writes_land_in_the_same_fetched_dict(calls, base_result):
    result, _ = _invoke(
        calls, base_result,
        supplements_writes={"fund_daily5": [1, 2], "margin_hist": [3], "peers": ["600519"]},
    )
    assert result.fetched["fund_daily5"] == [1, 2]
    assert result.fetched["margin_hist"] == [3]
    assert result.fetched["peers"] == ["600519"]


def test_untouched_keys_remain_none_without_supplements(calls, base_result):
    result, _ = _invoke(calls, base_result)
    assert result.fetched["fund_daily5"] is None
    assert result.fetched["margin_hist"] is None
    assert result.fetched["peers"] is None


# --- returned structure ---------------------------------------------------

def test_returns_named_tuple_with_three_fields(calls, base_result):
    result, _ = _invoke(calls, base_result)
    assert isinstance(result, FetchStageResult)
    assert result._fields == ("fetched", "sections_data", "margin")
    assert result.fetched is result[0]
    assert result.sections_data is result[1]
    assert result.margin is result[2]


def test_returned_payloads_are_the_very_objects_the_helpers_produced(calls, base_result):
    result, ctx = _invoke(calls, base_result)
    assert result.margin is ctx["margin_payload"]
    assert result.sections_data is ctx["section_payload"]


def test_sections_payload_is_the_one_built_from_enabled_sections(calls, base_result):
    result, ctx = _invoke(calls, base_result, sections=("A", "B"))
    fetch_call = next(c for c in calls if c[0] == "fetch_sections")
    assert fetch_call[2] == ("A", "B")
    assert result.sections_data is ctx["section_payload"]


# --- shared state ---------------------------------------------------------

def test_recorder_and_run_log_are_mutated_in_place(calls, base_result):
    recorder, run_log = _Recorder(), {"existing": 1}
    result, ctx = _invoke(calls, base_result, recorder=recorder, run_log=run_log)
    assert ctx["recorder"] is recorder
    assert recorder["tencent"] == {"label": "腾讯行情"}
    assert run_log["existing"] == 1
    assert run_log["sources"] == {"tencent": "ok"}


# --- failure behaviour ----------------------------------------------------

def test_failing_call_new_propagates_without_running_later_steps(calls, base_result):
    with pytest.raises(RuntimeError, match="call_new failed: 财务摘要"):
        _invoke(calls, base_result, call_new_raises_at="财务摘要")
    names = [c[0] for c in calls]
    assert "fetch_margin" not in names
    assert "fetch_supplements" not in names


def test_failing_enabled_sections_propagates_before_section_fetch(calls, base_result):
    with pytest.raises(RuntimeError):
        _invoke(calls, base_result, enabled_raises=RuntimeError("registry down"))
    names = [c[0] for c in calls]
    assert names[-1] == "enabled_sections"
    assert "fetch_sections" not in names


def test_failing_margin_fetch_propagates_before_supplements(calls, base_result):
    with pytest.raises(RuntimeError, match="margin down"):
        _invoke(calls, base_result, margin_raises=RuntimeError("margin down"))
    names = [c[0] for c in calls]
    assert names[-1] == "fetch_margin"
    assert "fetch_supplements" not in names


def test_failing_supplements_propagates_after_every_other_step(calls, base_result):
    with pytest.raises(RuntimeError, match="supplements down"):
        _invoke(calls, base_result, supplements_raises=RuntimeError("supplements down"))
    names = [c[0] for c in calls]
    assert names[-1] == "fetch_supplements"


def test_failing_helper_is_not_swallowed_by_the_stage(calls, base_result):
    # Optional-failure tolerance lives inside the helpers (supplements key),
    # not here: the stage must not add its own try/except around them.
    with pytest.raises(RuntimeError):
        _invoke(calls, base_result, call_new_raises_at="公告")


# --- console text ---------------------------------------------------------

def test_banner_line_is_printed_between_status_recording_and_first_fetch(
    calls, base_result, capsys
):
    _invoke(calls, base_result)
    out = capsys.readouterr().out
    assert "\n[V3+] 追加数据块: 公告 / 财务 / 研报 / 新闻 / Section Registry / 两融 / 5日资金 / 同业…" in out


def test_only_the_banner_is_printed_by_the_stage(calls, base_result, capsys):
    _invoke(calls, base_result)
    out = capsys.readouterr().out
    # Exactly one print call, and its text is the banner verbatim.
    assert out == (
        "\n[V3+] 追加数据块: 公告 / 财务 / 研报 / 新闻 / "
        "Section Registry / 两融 / 5日资金 / 同业…\n"
    )


# --- module hygiene -------------------------------------------------------

def test_module_does_not_import_pipeline_or_v2():
    import ast

    import analysis.orchestration.fetch_stage as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert not any(name.startswith("analysis.pipeline") for name in imported)
    assert "quant_analyzer_v2" not in imported
    # and no analysis.* dependency at all: every seam is injected
    assert not any(name.startswith("analysis") for name in imported)


def test_stage_does_not_reach_into_pipeline_module_namespace():
    import analysis.orchestration.fetch_stage as mod

    names = set(mod.__dict__)
    assert "v2" not in names
    assert "enabled_sections" not in names
    assert "_call_new" not in names
    assert "_fetch_margin" not in names
    assert "_fetch_sections" not in names
    assert "_fetch_supplements" not in names
    assert "status_of" not in names
