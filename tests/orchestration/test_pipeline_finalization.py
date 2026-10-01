"""Focused tests for the V3 successful-path finalization boundary (Phase 1H-2).

These tests exercise ``analysis.orchestration.finalization`` directly through
injected fakes, so they need no network access and produce no reports.  They
pin the contracts the extraction had to preserve: operation order, ``result``
identity, the freshness-guard console text, the artifact-writer call arguments,
and the optional three-level / status console output.
"""

import pytest

from analysis.orchestration.finalization import finalize_successful_run


# --------------------------------------------------------------- fixtures

@pytest.fixture
def calls():
    """Ordered record of every injected side effect."""
    return []


@pytest.fixture
def run_log():
    return {
        "guard": {},
        "finished_at": None,
        "total_sec": None,
        "started_at": "2026-09-16T00:00:00+00:00",
    }


@pytest.fixture
def result():
    return {
        "code": "000001",
        "name": "平安银行",
        "emoji": "🟢",
        "advice": "持有",
        "three_levels": {
            "support": 10.20,
            "resistance": 12.80,
            "stop_loss": 9.60,
            "support_candidates": {"近端前低": 10.20, "MA20": 10.05},
            "resistance_candidates": {"近端前高": 12.80},
        },
    }


@pytest.fixture
def files(calls):
    def _emit(code, name, payload):
        calls.append(("emit", code, name, payload))
        return {
            "md": "/out/a.md",
            "json": "/out/a.json",
            "html": None,
            "docx": "/out/a.docx",
            "run_log": "/out/run_log.json",
            "status": {"html": "ok", "docx": "failed"},
        }

    return _emit


@pytest.fixture
def run(calls, run_log, result, files):
    """Invoke the helper with recording fakes; returns (returned, payload)."""

    def _invoke(*, plan=None, chip_data={"kline": []}):
        def kline_freshness(chip):
            calls.append(("kline_freshness", chip))
            return {"status": "ok", "detail": "baostock 2026-09-15"}

        def record_guard(log, fresh):
            calls.append(("record_guard", fresh))
            log["guard"]["kline_freshness"] = f"{fresh['status']}: {fresh['detail']}"

        def finalize_timing(log, started, now_fn, time_fn):
            calls.append(("finalize_timing", started, now_fn, time_fn))
            log["finished_at"] = "2026-09-16T00:00:12+00:00"
            log["total_sec"] = 12.3

        returned = finalize_successful_run(
            code="000001",
            result=result,
            plan=plan,
            score_total=53,
            chip_data=chip_data,
            run_log=run_log,
            started=object(),
            kline_freshness=kline_freshness,
            record_kline_freshness_guard=record_guard,
            finalize_run_log_timing=finalize_timing,
            emit=files,
            now_fn=lambda: None,
            time_fn=lambda: 0.0,
        )
        return returned

    return _invoke


# ----------------------------------------------------------------- tests

def test_operation_order_is_guard_then_timing_then_emit(run, calls):
    run()
    assert [c[0] for c in calls] == [
        "kline_freshness", "record_guard", "finalize_timing", "emit",
    ]


def test_returns_the_same_result_object(run, result):
    assert run() is result


def test_guard_console_text_uses_recorded_guard_text(run, capsys):
    run()
    out = capsys.readouterr().out
    assert "[guard] ok: baostock 2026-09-15" in out


def test_emit_receives_code_name_and_result_positionally(run, calls, result):
    run()
    emit = next(c for c in calls if c[0] == "emit")
    assert emit[1] == "000001"
    assert emit[2] == "平安银行"
    assert emit[3] is result


def test_run_log_is_mutated_in_place_by_guard_and_timing(run, run_log):
    run()
    assert run_log["guard"]["kline_freshness"] == "ok: baostock 2026-09-15"
    assert run_log["finished_at"] == "2026-09-16T00:00:12+00:00"
    assert run_log["total_sec"] == 12.3


def test_console_summary_reports_score_advice_and_timing(run, capsys):
    run()
    out = capsys.readouterr().out
    assert "【V3】平安银行 (000001) 综合 53分 🟢持有  耗时 12.3s" in out


def test_three_level_line_printed_when_plan_and_levels_present(run, capsys):
    plan = {"entry_low": 9.90, "tp1": 13.10, "stop_loss": 9.40}
    run(plan=plan)
    out = capsys.readouterr().out
    assert "三价位(同源): 支撑=10.20 压力=12.80 止损=9.60" in out
    assert "4 候选支撑=['近端前低', 'MA20']" in out
    assert "3 候选压力=['近端前高']" in out


def test_three_level_line_skipped_without_plan(run, capsys):
    run(plan=None)
    assert "三价位(同源)" not in capsys.readouterr().out


def test_three_level_falls_back_to_plan_prices_when_levels_partial(capsys):
    result = {
        "name": "平安银行", "emoji": "🟢", "advice": "持有",
        "three_levels": {"support": None, "resistance": None, "stop_loss": 9.60},
    }
    plan = {"entry_low": 9.90, "tp1": 13.10, "stop_loss": 9.40}
    finalize_successful_run(
        code="000001",
        result=result,
        plan=plan,
        score_total=53,
        chip_data={},
        run_log={"guard": {}},
        started=object(),
        kline_freshness=lambda chip: {"status": "ok", "detail": "d"},
        record_kline_freshness_guard=lambda log, fresh: log["guard"].update(
            {"kline_freshness": "ok: d"}
        ),
        finalize_run_log_timing=lambda log, s, n, t: log.update({"total_sec": 1.0}),
        emit=lambda c, n, p: {},
        now_fn=lambda: None,
        time_fn=lambda: 0.0,
    )
    out = capsys.readouterr().out
    # support/resistance fall back to plan prices, stop_loss uses the three_levels value
    assert "三价位(同源): 支撑=9.90 压力=13.10 止损=9.60" in out
    assert "4 候选支撑=[]" in out
    assert "3 候选压力=[]" in out


def test_only_present_artifact_paths_are_printed(run, capsys):
    run()
    out = capsys.readouterr().out
    assert "  MD: /out/a.md" in out
    assert "  JSON: /out/a.json" in out
    assert "  DOCX: /out/a.docx" in out
    assert "  RUN_LOG: /out/run_log.json" in out
    assert "  HTML: /out/a.html" not in out
    assert "  状态: html=ok  docx=failed" in out


def test_status_line_printed_even_when_status_missing(calls, run_log, result, capsys):
    finalize_successful_run(
        code="000001",
        result=result,
        plan=None,
        score_total=53,
        chip_data={},
        run_log=run_log,
        started=object(),
        kline_freshness=lambda chip: {"status": "ok", "detail": "d"},
        record_kline_freshness_guard=lambda log, fresh: log["guard"].update(
            {"kline_freshness": "ok: d"}
        ),
        finalize_run_log_timing=lambda log, s, n, t: log.update({"total_sec": 1.0}),
        emit=lambda c, n, p: {},
        now_fn=lambda: None,
        time_fn=lambda: 0.0,
    )
    out = capsys.readouterr().out
    assert "  状态: html=None  docx=None" in out
