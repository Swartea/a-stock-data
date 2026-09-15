"""Fetching orchestration primitives for the V3 pipeline.

Phase 1G keeps the existing retry and new-fetcher status semantics intact while
making runtime state explicit.  The helpers here do not import ``pipeline`` or
own a second source-status recorder.
"""

import time
from typing import Any, Callable

from analysis.orchestration.source_status import SourceStatusRecorder


def _retry_call(
    recorder: SourceStatusRecorder,
    label: str,
    fn: Callable[..., Any],
    *args: Any,
    tries: int = 3,
    timeout: int = 60,
    **kwargs: Any,
) -> tuple[Any, int, str | None]:
    """Call ``fn`` with the pipeline's existing retry behavior.

    ``timeout`` is intentionally retained as a compatibility parameter but is
    currently inert, matching the historical pipeline implementation.
    """
    last_exc = None
    for attempt in range(1, tries + 1):
        started = time.time()
        try:
            value = fn(*args, **kwargs)
            recorder.setdefault(label, {})["ms"] = round((time.time() - started) * 1000)
            return value, attempt, None
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(1.0)
    return None, tries, str(last_exc)


def _call_new(
    recorder: SourceStatusRecorder,
    run_log: dict[str, Any],
    new_imports: dict[str, dict[str, Any]],
    src_desc: dict[str, str],
    status_of_fn: Callable[[Any], str | None],
    src_label: str,
    mod_key: str,
    *args: Any,
    tries: int = 3,
    **kwargs: Any,
) -> Any:
    """Call one optional V3 fetcher and preserve the existing run-log contract.

    Import failures, retry exhaustion, error/empty status handling, actual-source
    reporting, and fallback-chain wording intentionally match the former nested
    ``pipeline._call_new`` implementation.  ``unsupported`` also intentionally
    keeps its historical fall-through behavior during this extraction phase.
    """
    mod = new_imports.get(mod_key)
    if mod is None:
        return None

    lab = src_label
    if not mod["ok"]:
        status = f"error:{mod['err'][:60]}, 0ms"
        run_log["sources"][lab] = status
        run_log["source_meta"][lab] = {
            "ms": 0,
            "at": None,
            "status": status,
            "detail": src_desc.get(lab, ""),
        }
        run_log["fallback_chain"].append(f"{lab}: {mod['err']}")
        return None

    fn = mod["fn"]
    value, attempt_count, exc = _retry_call(
        recorder,
        lab,
        fn,
        *args,
        tries=tries,
        **kwargs,
    )
    meta = recorder.get(lab, {})
    status_value = status_of_fn(value) if value is not None else "error"

    if exc:
        status = f"error:调用异常 {exc[:80]}, {meta.get('ms','?')}ms"
        run_log["fallback_chain"].append(
            f"{lab}: 第{attempt_count}次后仍失败 — {exc}"
        )
    elif status_value == "error":
        err_msg = ""
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict) and "message" in error:
                err_msg = str(error["message"])
            elif isinstance(error, str):
                err_msg = error
        status = f"error:{err_msg[:60]}, {meta.get('ms','?')}ms"
        run_log["fallback_chain"].append(f"{lab}: {err_msg[:100]}")
    elif status_value == "empty":
        status = f"empty:无记录, {meta.get('ms','?')}ms"
    elif isinstance(value, dict) and value.get("source"):
        status = f"ok:{value['source']}, {meta.get('ms','?')}ms"
    else:
        status = f"ok, {meta.get('ms','?')}ms"

    meta["status"] = status
    meta["detail"] = src_desc.get(lab, "")
    run_log["sources"][lab] = status
    run_log["source_meta"][lab] = meta
    return value


def _fetch_margin(
    run_log: dict[str, Any],
    src_desc: dict[str, str],
    fmt_time: Callable[[float], str],
    fetcher: Callable[[str], Any],
    code: str,
) -> Any:
    """Fetch margin trading data with the pipeline's historical semantics.

    Only raised exceptions trigger retries.  Returned ``{"error": ...}`` values
    are not retried, ``None`` still falls through to the historical success
    status, elapsed milliseconds cover the whole retry loop including sleeps,
    and the final failed attempt still sleeps once before status is recorded.
    """
    label = "融资融券"
    started = time.time()
    margin = None

    for _ in range(3):
        try:
            margin = fetcher(code)
            break
        except Exception as exc:  # noqa: BLE001
            margin = {"error": str(exc)}
            time.sleep(1.0)

    ms = round((time.time() - started) * 1000)
    if margin and isinstance(margin, dict) and "error" in margin:
        status = f"error:{str(margin['error'])[:60]}, {ms}ms"
        run_log["fallback_chain"].append(f"{label}: {margin['error']}")
    else:
        status = f"ok:eastmoney-datacenter, {ms}ms"

    run_log["sources"][label] = status
    run_log["source_meta"][label] = {
        "ms": ms,
        "at": fmt_time(time.time()),
        "status": status,
        "detail": src_desc[label],
    }
    return margin
