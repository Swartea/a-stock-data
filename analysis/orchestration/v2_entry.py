"""V2 invocation entry stage for the V3 orchestration pipeline.

Phase 1H-3 extracts only the opening block of ``analyze_single_v3``: the V2
full-chain call, the network retry time box, and the lifetime of the V2 timer
monkey-patch that wraps it.

Everything else stays in ``analysis.pipeline``: the fatal run-log
finalization, the 申万 TLS handling, the trading plan / three-level model, the
fetch stage, the result builder and the successful finalization.  The caller
still owns the ``"error" in base_result`` decision and the run-log it writes.

Every side effect is preserved exactly as before:

* patch lifetime — the V2 timers are patched **once**, before the first
  attempt, and restored from a ``finally`` block, so an unexpected exception
  raised by V2 cannot leave the module patched;
* attempt budget — at most ``MAX_ATTEMPTS`` (3) attempts, the loop breaking
  on the first result without an ``"error"`` key;
* recorder resets — the shared source recorder is cleared *before each*
  attempt, so per-attempt metadata never leaks between attempts;
* retry reporting — the retry line is printed and ``sleep(3)`` is taken after
  **every** error, including the last one, which is what the current
  pipeline does;
* V2 call shape — ``v2.analyze_single(code, name, output_md=False)``;
* return contract — the ``base_result`` dict produced by V2 is handed back
  unchanged (never copied or rebuilt) together with the last ``fatal`` string.

The four pipeline-level callables (``patch_timers`` / ``restore_timers`` /
``fmt_time`` / ``sleep``) plus the V2 module and the shared recorder are
injected by ``analysis.pipeline`` at call time rather than imported here.
That keeps this module free of import-time coupling to ``quant_analyzer_v2``
and ``time``, and preserves the existing monkeypatch surface on
``analysis.pipeline``.
"""

from collections.abc import Callable, MutableMapping
from typing import Any, NamedTuple

__all__ = [
    "MAX_ATTEMPTS",
    "RETRY_DELAY_SECONDS",
    "V2EntryResult",
    "run_v2_entry",
]

# 网络重试时间盒 3 次 (与拆分前 pipeline 硬编码一致)
MAX_ATTEMPTS = 3
# 每次失败后的等待秒数 (拆分前为 time.sleep(3))
RETRY_DELAY_SECONDS = 3


class V2EntryResult(NamedTuple):
    """Outcome of the V2 entry stage.

    ``base_result`` is the very dict V2 returned on its last attempt (``{}``
    only if the loop somehow never ran), and ``fatal`` is the error string of
    that last attempt, or ``None`` when V2 succeeded.  The caller decides
    what is fatal; this stage only reports what happened.
    """

    base_result: dict[str, Any]
    fatal: Any


def run_v2_entry(
    *,
    code: str,
    name: str,
    v2_module: Any,
    recorder: MutableMapping[str, Any],
    patch_timers: Callable[[Any, MutableMapping[str, Any], Callable[[Any], str]], Any],
    restore_timers: Callable[[Any, Any], Any],
    fmt_time: Callable[[Any], str],
    sleep: Callable[[float], Any],
    max_attempts: int = MAX_ATTEMPTS,
    retry_delay: float = RETRY_DELAY_SECONDS,
) -> V2EntryResult:
    """Run the V2 full chain under the retry time box and return its result.

    ``patch_timers`` is called once, before any attempt, and ``restore_timers``
    always runs afterwards in a ``finally`` block.  Both are injected so the
    caller keeps control of the monkeypatch surface.
    """
    saved = patch_timers(v2_module, recorder, fmt_time)
    base_result: dict[str, Any] = {}
    fatal: Any = None
    try:
        for attempt in range(1, max_attempts + 1):        # 网络重试时间盒 3 次
            recorder.clear()
            base_result = v2_module.analyze_single(code, name, output_md=False)
            if "error" not in base_result:
                break
            fatal = base_result["error"]
            print(f"[v3] 第 {attempt} 次尝试失败: {fatal}, {retry_delay:g} 秒后重试…")
            sleep(retry_delay)
    finally:
        restore_timers(v2_module, saved)
    return V2EntryResult(base_result=base_result, fatal=fatal)
