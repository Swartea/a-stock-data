"""V2 全链路阶段 (Phase 1J).

1H 抽走 build / finalize、1I 抽走 fetch 之后, ``analyze_single_v3`` 里**最后一段内联
编排**就是本模块负责的第 1 步: V2 全链路的 3 次重试时间盒、fatal 中止收尾, 以及
包住二者的 ``try/finally`` V2 计时恢复。

⚠️ **注入口纪律与 1H / 1I 相同**: 本阶段**不绑定任何自身模块级符号**。V2 模块对象、
计时 patch / restore、时点与时钟函数、run_log 落盘全部由
``pipeline.analyze_single_v3`` 显式传入。否则既有契约测试里
``monkeypatch.setattr(pipeline, "_patch_v2_timers" / "_restore_v2" / ...)`` 与
``monkeypatch.setattr(pipeline.v2, "analyze_single", ...)`` 会全部失效, 端到端测试
将退化成真实抓取 + 真实落盘。
``tests/orchestration/test_v2_stage_wiring.py`` 锁定该约束。

本模块只搬边界, 不改口径。以下历史行为**逐字保留**(有测试钉死, 不要"顺手修"):

- 重试固定 3 次(``range(1, 4)``), 每次调用前 ``recorder.clear()``;
- **最后一次失败后仍然 sleep** —— 原实现如此(``test_fatal_run_log_timing_contract``
  断言 ``sleeps == [3, 3, 3]``), 收窄会改变端到端耗时;
- fatal 文案、run_log ``fatal`` 键、落盘与返回 dict 的形状均不变;
- ``finally`` 保证 fatal 返回路径也会恢复 V2 计时器;
- V2 抛异常时**不吞**(原实现无 ``except``, 异常向上传播)。
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

__all__ = [
    "V2_ATTEMPTS",
    "V2_RETRY_SLEEP_SEC",
    "V2StageResult",
    "run_v2_stage",
]

# 网络重试时间盒: 3 次。
V2_ATTEMPTS = 3
# 每次失败后的固定退避(含最后一次)。
V2_RETRY_SLEEP_SEC = 3


class V2StageResult(NamedTuple):
    """Return shape of :func:`run_v2_stage`.

    ``base_result`` 是 V2 全链路的返回值(失败时为最后一次带 ``error`` 的 dict)。
    ``abort`` 非 ``None`` 时表示 V2 链路彻底失败: 此时 run_log 的 fatal 字段已写入、
    时点已收尾、run_log 已落盘, 且控制台已打印中止提示 —— ``pipeline`` 必须**原样返回**
    ``abort``, 不得再做任何后处理。
    """

    base_result: dict[str, Any]
    abort: dict[str, Any] | None


def run_v2_stage(
    code: str,
    name: str,
    run_log: dict[str, Any],
    started: Any,
    recorder: Any,
    v2: Any,
    patch_timers: Callable[..., Any],
    restore_v2: Callable[..., Any],
    finalize_timing: Callable[..., Any],
    dump_run_log: Callable[..., None],
    sleep: Callable[[float], Any],
    time_fn: Callable[[], float],
    now_fn: Callable[[], Any],
    analyze_single: Callable[..., dict[str, Any]],
    fmt_time: Callable[[float], str],
) -> V2StageResult:
    """Run the V2 chain with its historical retry and abort semantics.

    顺序与副作用全部照搬原内联实现: 先给 V2 装计时 wrapper(同时给 recorder 播种
    四键元数据), 再进入 3 次重试循环, 失败则写 fatal / 收尾时点 / 落 run_log /
    打印中止并返回 abort dict, 全程由 ``finally`` 恢复 V2。

    Returns ``V2StageResult(base_result, abort)``; ``abort`` is ``None`` on success.
    """
    saved = patch_timers(v2, recorder, fmt_time)
    base_result: dict[str, Any] = {}
    fatal = None
    try:
        for attempt in range(1, V2_ATTEMPTS + 1):        # 网络重试时间盒 3 次
            recorder.clear()
            base_result = analyze_single(code, name, output_md=False)
            if "error" not in base_result:
                break
            fatal = base_result["error"]
            print(f"[v3] 第 {attempt} 次尝试失败: {fatal}, 3 秒后重试…")
            # 含最后一次: 原实现如此, 不要改成"最后一次不睡"
            sleep(V2_RETRY_SLEEP_SEC)
        if "error" in base_result:
            run_log["fatal"] = (
                f"V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底): {fatal}"
            )
            finalize_timing(run_log, started, now_fn, time_fn)
            dump_run_log(code, name, run_log)
            print(f"\n[✗] 分析中止: {run_log['fatal']}")
            return V2StageResult(base_result, {"error": run_log["fatal"], "run_log": run_log})
    finally:
        restore_v2(v2, saved)
    return V2StageResult(base_result, None)
