"""Phase 1J V2 阶段契约: run_v2_stage 的重试/中止/恢复语义逐字锁定。

这些断言锁的是**原内联实现的行为**, 不是新实现自己的行为 —— 抽离只搬边界,
不改口径。若将来有人收窄重试次数、去掉最后一次 sleep、改 fatal 文案或让异常被吞,
这里必须先被改。

端到端侧另有 tests/orchestration/test_fatal_run_log_timing_contract.py 走
pipeline.analyze_single_v3 全链路覆盖同一条 fatal 路径。
"""

import pytest

from analysis.orchestration.source_status import SourceStatusRecorder
from analysis.orchestration.v2_stage import (
    V2_ATTEMPTS,
    V2_RETRY_SLEEP_SEC,
    V2StageResult,
    run_v2_stage,
)


class _Clock:
    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def time(self):
        return 1000.0


def _seams(results, *, raises=None):
    """Build a full seam set driving ``analyze_single`` from ``results``."""
    clock = _Clock()
    calls = {"analyze": 0, "patch": 0, "restore": 0, "dump": [], "timing": []}
    state = {"clears": 0}

    class _Recorder(SourceStatusRecorder):
        def clear(self):
            state["clears"] += 1
            super().clear()

    def analyze_single(code, name, output_md=True):
        calls["analyze"] += 1
        if raises is not None and calls["analyze"] == raises:
            raise RuntimeError("v2 boom")
        return results[min(calls["analyze"], len(results)) - 1]

    seams = {
        "recorder": _Recorder(),
        "v2": object(),
        "patch_timers": lambda *_a, **_kw: calls.__setitem__("patch", calls["patch"] + 1) or {"saved": True},
        "restore_v2": lambda *_a, **_kw: calls.__setitem__("restore", calls["restore"] + 1),
        "finalize_timing": lambda run_log, started, now_fn, time_fn: calls["timing"].append(
            (run_log, started, now_fn, time_fn)
        ),
        "dump_run_log": lambda code, name, run_log: calls["dump"].append((code, name, dict(run_log))),
        "sleep": clock.sleep,
        "time_fn": clock.time,
        "now_fn": lambda: "NOW",
        "analyze_single": analyze_single,
        "fmt_time": lambda ts: "12:00:00",
    }
    return seams, calls, clock, state


def _run(results, *, raises=None):
    seams, calls, clock, state = _seams(results, raises=raises)
    run_log = {"sources": {}, "source_meta": {}, "fallback_chain": [], "fatal": None}
    out = run_v2_stage(
        "600693",
        "东百集团",
        run_log,
        "STARTED",
        **seams,
    )
    return out, calls, clock, state, run_log


# ============================================================
# 成功路径
# ============================================================


def test_first_attempt_success_skips_retry_and_abort():
    base = {"code": "600693", "quote": {"price": 9.9}}
    out, calls, clock, _, run_log = _run([base])

    assert out.abort is None
    assert out.base_result is base
    assert calls["analyze"] == 1
    assert clock.sleeps == []
    assert calls["dump"] == []
    assert calls["timing"] == []
    assert run_log["fatal"] is None


def test_success_path_patches_then_restores_v2():
    _, calls, _, _, _ = _run([{"code": "600693"}])

    assert calls["patch"] == 1
    assert calls["restore"] == 1


def test_recorder_is_cleared_once_per_attempt():
    out, calls, _, state, _ = _run([{"error": "e1"}, {"code": "600693"}])

    assert out.abort is None
    assert calls["analyze"] == 2
    assert state["clears"] == 2, "每次调用 V2 前必须 clear 一次 recorder"


def test_retry_stops_at_first_success():
    out, calls, clock, _, _ = _run([{"error": "e1"}, {"code": "600693"}, {"code": "600693"}])

    assert out.abort is None
    assert calls["analyze"] == 2, "第 2 次成功即 break, 不得再跑第 3 次"
    assert clock.sleeps == [V2_RETRY_SLEEP_SEC]


# ============================================================
# fatal 中止路径
# ============================================================


def test_fatal_path_attempts_three_times_and_sleeps_three_times():
    out, calls, clock, _, run_log = _run([{"error": "行情失败"}])

    assert calls["analyze"] == V2_ATTEMPTS == 3
    # 关键历史行为: 最后一次失败后仍然 sleep(原内联实现如此)
    assert clock.sleeps == [V2_RETRY_SLEEP_SEC] * 3
    assert out.abort is not None


def test_fatal_abort_dict_and_wording_are_verbatim():
    out, _, _, _, run_log = _run([{"error": "行情失败"}])

    assert out.abort == {
        "error": "V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底): 行情失败",
        "run_log": run_log,
    }
    assert run_log["fatal"] == out.abort["error"]


def test_fatal_path_finalizes_timing_then_dumps_then_restores():
    _, calls, _, _, run_log = _run([{"error": "行情失败"}])

    assert len(calls["timing"]) == 1
    run_log_arg, started, now_fn, time_fn = calls["timing"][0]
    assert run_log_arg is run_log
    assert started == "STARTED"
    assert now_fn() == "NOW"
    assert time_fn() == 1000.0

    assert len(calls["dump"]) == 1
    code, name, dumped = calls["dump"][0]
    assert (code, name) == ("600693", "东百集团")
    assert dumped["fatal"] == run_log["fatal"]
    # finally 必须覆盖 fatal 返回路径
    assert calls["restore"] == 1


def test_fatal_uses_last_attempt_error():
    out, calls, _, _, _ = _run([{"error": "第一次"}, {"error": "第二次"}, {"error": "最后一次"}])

    assert calls["analyze"] == 3
    assert out.abort["error"].endswith(": 最后一次"), "fatal 必须取最后一次的 error"


# ============================================================
# 异常不被吞 + 返回形状
# ============================================================


def test_v2_exception_propagates_and_still_restores():
    """原实现无 except: V2 抛异常必须向上传播, 但 finally 仍要恢复计时器。"""
    seams, calls, _clock, _state = _seams([{"code": "600693"}], raises=1)
    run_log = {"sources": {}, "source_meta": {}, "fallback_chain": [], "fatal": None}

    with pytest.raises(RuntimeError, match="v2 boom"):
        run_v2_stage("600693", "东百集团", run_log, "STARTED", **seams)

    assert calls["restore"] == 1, "异常路径也必须经 finally 恢复 V2 计时器"
    assert calls["dump"] == [], "异常不是 fatal, 不得走 fatal 落盘路径"
    assert run_log["fatal"] is None


def test_stage_returns_named_tuple_fields():
    assert V2StageResult._fields == ("base_result", "abort")


def test_analyze_single_called_with_output_md_false():
    seen = []
    seams, *_ = _seams([{"code": "600693"}])
    original = seams["analyze_single"]

    def spy(code, name, output_md=True):
        seen.append((code, name, output_md))
        return original(code, name, output_md=output_md)

    seams["analyze_single"] = spy
    run_v2_stage(
        "600693",
        "东百集团",
        {"sources": {}, "source_meta": {}, "fallback_chain": [], "fatal": None},
        "STARTED",
        **seams,
    )

    assert seen == [("600693", "东百集团", False)], "V2 调用必须仍传 output_md=False"
