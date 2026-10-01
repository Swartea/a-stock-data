"""Focused tests for the V3 V2 invocation entry boundary (Phase 1H-3).

These tests exercise ``analysis.orchestration.v2_entry`` directly through
injected fakes, so they need no network access and never import
``quant_analyzer_v2``.  They pin the contracts the extraction had to
preserve: the single timer patch, the three-attempt time box, the per-attempt
recorder reset, the retry line plus the sleep that happens after *every*
error (including the last), unconditional timer restoration, and the exact
arguments handed to the injected seams.
"""

import pytest

from analysis.orchestration.v2_entry import (
    MAX_ATTEMPTS,
    RETRY_DELAY_SECONDS,
    run_v2_entry,
)


# --------------------------------------------------------------- fixtures

class FakeV2:
    """Stand-in for the ``quant_analyzer_v2`` module attribute holder."""

    def __init__(self, script, calls):
        self._script = list(script)
        self._calls = calls

    def analyze_single(self, code, name, output_md=False):
        self._calls.append(
            ("analyze_single", code, name, output_md, len(self._calls))
        )
        if not self._script:
            raise AssertionError("analyze_single called more times than scripted")
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def calls():
    """Ordered record of every injected side effect."""
    return []


@pytest.fixture
def recorder(calls):
    """Minimal shared recorder with a tracked ``clear``."""

    class _Recorder(dict):
        def clear(self):
            calls.append(("clear",))
            super().clear()

    return _Recorder()


def _ok(score=53):
    return {
        "code": "600693",
        "quote": {"price": 12.34},
        "score": {"total": score},
    }


def _err(msg="行情失败"):
    return {"error": msg}


def _invoke(
    script,
    calls,
    recorder,
    *,
    patch_result=None,
    patch_raises=None,
    max_attempts=None,
    retry_delay=None,
):
    """Call the stage with recording fakes; returns the ``V2EntryResult``."""
    saved_marker = {"patched": True}

    def patch_timers(v2_module, rec, fmt_time):
        calls.append(("patch_timers", v2_module, rec, fmt_time))
        if patch_raises is not None:
            raise patch_raises
        return saved_marker if patch_result is None else patch_result

    def restore_timers(v2_module, saved):
        calls.append(("restore_timers", v2_module, saved))

    def sleep(seconds):
        calls.append(("sleep", seconds))

    kwargs = {}
    if max_attempts is not None:
        kwargs["max_attempts"] = max_attempts
    if retry_delay is not None:
        kwargs["retry_delay"] = retry_delay

    return run_v2_entry(
        code="600693",
        name="东百集团",
        v2_module=FakeV2(script, calls),
        recorder=recorder,
        patch_timers=patch_timers,
        restore_timers=restore_timers,
        fmt_time=lambda t: "2026-09-16T00:00:00+00:00",
        sleep=sleep,
        **kwargs,
    )


# ----------------------------------------------------------------- tests

# --- first-attempt success -------------------------------------------------

def test_first_attempt_success_runs_v2_once_and_never_sleeps(calls, recorder):
    result = _invoke([_ok()], calls, recorder)
    assert [c[0] for c in calls].count("analyze_single") == 1
    assert [c for c in calls if c[0] == "sleep"] == []


def test_first_attempt_success_returns_base_result_and_no_fatal(calls, recorder):
    base = _ok()
    result = _invoke([base], calls, recorder)
    # identity: the caller keeps the exact dict V2 produced
    assert result.base_result is base
    assert result.fatal is None


def test_timers_are_patched_once_before_the_first_attempt(calls, recorder):
    _invoke([_ok()], calls, recorder)
    kinds = [c[0] for c in calls]
    assert kinds.count("patch_timers") == 1
    assert kinds.index("patch_timers") < kinds.index("analyze_single")


# --- retry then success ----------------------------------------------------

def test_retry_then_success_stops_on_the_first_clean_result(calls, recorder):
    good = _ok(score=61)
    result = _invoke([_err("第一次超时"), good], calls, recorder)
    assert [c[0] for c in calls].count("analyze_single") == 2
    assert result.base_result is good
    assert result.fatal == "第一次超时"  # last error seen, not returned as fatal by caller


def test_retry_then_success_sleeps_once_and_prints_retry_line(calls, recorder, capsys):
    _invoke([_err("第一次超时"), _ok()], calls, recorder)
    assert [c[1] for c in calls if c[0] == "sleep"] == [3]
    out = capsys.readouterr().out
    assert out == "[v3] 第 1 次尝试失败: 第一次超时, 3 秒后重试…\n"


def test_recorder_is_cleared_before_every_attempt(calls, recorder):
    _invoke([_err(), _err(), _ok()], calls, recorder)
    kinds = [c[0] for c in calls]
    assert kinds.count("clear") == 3
    for idx, kind in enumerate(kinds):
        if kind == "analyze_single":
            assert kinds[idx - 1] == "clear"


def test_recorder_is_emptied_before_each_attempt(calls, recorder):
    """Metadata written during attempt N must not survive into attempt N+1."""
    seen = []

    class _RecordingV2:
        def analyze_single(self, code, name, output_md=False):
            seen.append(dict(recorder))           # snapshot before this attempt writes
            recorder["行情"] = {"ms": len(seen)}  # simulate a V2 fetch timing write
            return _err(f"第{len(seen)}次")

    run_v2_entry(
        code="600693",
        name="东百集团",
        v2_module=_RecordingV2(),
        recorder=recorder,
        patch_timers=lambda *_a: {},
        restore_timers=lambda *_a: None,
        fmt_time=lambda t: "t",
        sleep=lambda _s: None,
        max_attempts=2,
    )
    assert seen == [{}, {}]


# --- all attempts fail -----------------------------------------------------

def test_all_attempts_error_stops_after_three_attempts(calls, recorder):
    result = _invoke([_err(f"第{i}次") for i in range(1, 4)], calls, recorder)
    assert [c[0] for c in calls].count("analyze_single") == MAX_ATTEMPTS == 3
    assert result.fatal == "第3次"


def test_all_attempts_error_sleeps_after_every_error_including_the_last(calls, recorder):
    _invoke([_err("行情失败"), _err("行情失败"), _err("行情失败")], calls, recorder)
    # the third sleep happens even though no fourth attempt follows
    assert [c[1] for c in calls if c[0] == "sleep"] == [3, 3, 3]


def test_all_attempts_error_prints_the_retry_line_for_every_attempt(capsys, calls, recorder):
    _invoke([_err("行情失败"), _err("行情失败"), _err("行情失败")], calls, recorder)
    assert capsys.readouterr().out == (
        "[v3] 第 1 次尝试失败: 行情失败, 3 秒后重试…\n"
        "[v3] 第 2 次尝试失败: 行情失败, 3 秒后重试…\n"
        "[v3] 第 3 次尝试失败: 行情失败, 3 秒后重试…\n"
    )


def test_all_attempts_error_clears_the_recorder_three_times(calls, recorder):
    _invoke([_err(), _err(), _err()], calls, recorder)
    assert [c[0] for c in calls].count("clear") == 3


def test_all_attempts_error_returns_the_last_error_payload(calls, recorder):
    last = _err("最后一次失败")
    result = _invoke([_err("a"), _err("b"), last], calls, recorder)
    assert result.base_result is last
    assert result.fatal == "最后一次失败"


# --- timer restoration -----------------------------------------------------

def test_timers_are_restored_after_a_successful_run(calls, recorder):
    _invoke([_ok()], calls, recorder)
    kinds = [c[0] for c in calls]
    assert kinds.index("restore_timers") > kinds.index("analyze_single")


def test_timers_are_restored_after_all_attempts_fail(calls, recorder):
    _invoke([_err(), _err(), _err()], calls, recorder)
    kinds = [c[0] for c in calls]
    assert kinds.index("restore_timers") > kinds.index("analyze_single")


def test_timers_are_restored_when_v2_raises(calls, recorder):
    boom = RuntimeError("unexpected")
    with pytest.raises(RuntimeError, match="unexpected"):
        _invoke([boom], calls, recorder)
    assert [c[0] for c in calls].count("restore_timers") == 1


def test_unexpected_exception_propagates_and_skips_further_attempts(calls, recorder):
    with pytest.raises(ValueError, match="网络库炸了"):
        _invoke([ValueError("网络库炸了"), _ok()], calls, recorder)
    assert [c[0] for c in calls].count("analyze_single") == 1
    assert [c[0] for c in calls].count("sleep") == 0


def test_patch_failure_propagates_without_restoring(calls, recorder):
    with pytest.raises(RuntimeError, match="patch 失败"):
        _invoke([_ok()], calls, recorder, patch_raises=RuntimeError("patch 失败"))
    # the patch happens outside the try, so a failed patch must not restore
    assert [c[0] for c in calls].count("restore_timers") == 0
    assert [c[0] for c in calls].count("analyze_single") == 0


# --- injected seam contracts ----------------------------------------------

def test_v2_is_called_with_code_name_and_output_md_false(calls, recorder):
    _invoke([_ok()], calls, recorder)
    call = next(c for c in calls if c[0] == "analyze_single")
    assert call[1:4] == ("600693", "东百集团", False)


def test_patch_receives_the_v2_module_recorder_and_time_formatter(calls, recorder):
    _invoke([_ok()], calls, recorder)
    patch = next(c for c in calls if c[0] == "patch_timers")
    assert patch[2] is recorder
    assert callable(patch[3])
    assert patch[3](0) == "2026-09-16T00:00:00+00:00"


def test_restore_receives_the_v2_module_and_the_saved_mapping(calls, recorder):
    saved = {"fetch_tencent_quote": "<original>"}
    _invoke([_ok()], calls, recorder, patch_result=saved)
    patch = next(c for c in calls if c[0] == "patch_timers")
    restore = next(c for c in calls if c[0] == "restore_timers")
    assert restore[1] is patch[1]          # same v2 module object
    assert restore[2] is saved             # same saved mapping patch returned


def test_injected_sleep_seam_is_used_instead_of_the_time_module(calls, recorder, monkeypatch):
    import time as real_time

    def boom(_seconds):
        raise AssertionError("stage must not sleep through the time module")

    monkeypatch.setattr(real_time, "sleep", boom)
    _invoke([_err(), _ok()], calls, recorder)
    assert [c[1] for c in calls if c[0] == "sleep"] == [RETRY_DELAY_SECONDS]


def test_stage_uses_only_its_injected_arguments(capsys, calls, recorder):
    # A module-like holder and a plain dict recorder are enough: the stage
    # imports neither quant_analyzer_v2 nor time, so nothing here can touch
    # the network or leak state between calls.
    ok = {"code": "000001", "quote": {"price": 10.5}}
    out = run_v2_entry(
        code="000001",
        name="平安银行",
        v2_module=FakeV2([ok], calls),
        recorder=recorder,
        patch_timers=lambda *_a: {},
        restore_timers=lambda *_a: None,
        fmt_time=lambda t: "t",
        sleep=lambda _s: None,
    )
    assert out.base_result is ok
    assert out.fatal is None
    assert capsys.readouterr().out == ""


def test_attempt_budget_and_delay_are_configurable(calls, recorder):
    result = _invoke(
        [_err("a"), _err("b")], calls, recorder, max_attempts=2, retry_delay=7
    )
    assert [c[0] for c in calls].count("analyze_single") == 2
    assert [c[1] for c in calls if c[0] == "sleep"] == [7, 7]
    assert result.fatal == "b"


def test_defaults_match_the_pre_extraction_constants():
    assert MAX_ATTEMPTS == 3
    assert RETRY_DELAY_SECONDS == 3
