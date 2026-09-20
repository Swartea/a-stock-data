"""Fetching orchestration primitives for the V3 pipeline.

Phase 1G keeps the existing retry and new-fetcher status semantics intact while
making runtime state explicit.  The helpers here do not import ``pipeline`` or
own a second source-status recorder.
"""

import threading
import time
from typing import Any, Callable

_NEW_FETCH_TIMEOUT_SEC = 20.0
_MARGIN_TIMEOUT_SEC = 20.0
_SUPPLEMENT_TIMEOUT_SEC = 20.0
_DEFAULT_SECTION_TIMEOUT_SEC = 20.0
_SECTION_TIMEOUTS_SEC = {
    "holders": 35.0,
    "board": 20.0,
    "dragon_market": 20.0,
    "irm": 20.0,
    "dividend": 20.0,
}


def _call_with_timeout(
    label: str,
    fn: Callable[..., Any],
    *args: Any,
    timeout: float | int,
    **kwargs: Any,
) -> Any:
    """Run one read-only fetch behind an orchestration deadline.

    The worker is daemonized so a stuck provider cannot hold the pipeline or
    interpreter open after the deadline. Python cannot safely kill a running
    thread; a timed-out provider may finish in the background, but its result is
    discarded and the caller observes TimeoutError at the configured bound.
    """
    if timeout <= 0:
        return fn(*args, **kwargs)

    done = threading.Event()
    box: list[tuple[bool, Any]] = []

    def _runner() -> None:
        try:
            box.append((True, fn(*args, **kwargs)))
        except BaseException as exc:
            box.append((False, exc))
        finally:
            done.set()

    worker = threading.Thread(
        target=_runner,
        name=f"fetch-timeout-{label}",
        daemon=True,
    )
    worker.start()
    if not done.wait(float(timeout)):
        raise TimeoutError(f"{label} 调用超时({float(timeout):g}s)")

    ok, payload = box[0]
    if ok:
        return payload
    raise payload

from analysis.orchestration.source_status import SourceStatusRecorder


def _retry_call(
    recorder: SourceStatusRecorder,
    label: str,
    fn: Callable[..., Any],
    *args: Any,
    tries: int = 3,
    timeout: float | int = 60,
    **kwargs: Any,
) -> tuple[Any, int, str | None]:
    """Call fn with the existing retry behavior plus a per-attempt deadline.

    Retry count and 1-second backoff semantics stay unchanged. Total worst-case
    time is bounded by tries * timeout plus the existing retry sleeps.
    """
    last_exc = None
    for attempt in range(1, tries + 1):
        started = time.time()
        try:
            value = _call_with_timeout(
                label,
                fn,
                *args,
                timeout=timeout,
                **kwargs,
            )
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
    retry_timeout = kwargs.pop("timeout", _NEW_FETCH_TIMEOUT_SEC)
    value, attempt_count, exc = _retry_call(
        recorder,
        lab,
        fn,
        *args,
        tries=tries,
        timeout=retry_timeout,
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
            margin = _call_with_timeout(
                label,
                fetcher,
                code,
                timeout=_MARGIN_TIMEOUT_SEC,
            )
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


def _fetch_supplements(
    recorder: SourceStatusRecorder,
    run_log: dict[str, Any],
    fetched: dict[str, Any],
    src_desc: dict[str, str],
    fmt_time: Callable[[float], str],
    code: str,
    blocks: Any,
    fund_flow_fetcher: Callable[..., Any],
    margin_history_fetcher: Callable[..., Any],
    peers_fetcher: Callable[..., Any],
) -> None:
    """Populate the three legacy supplement fetches without changing semantics.

    Fund-flow and peer error dictionaries retry once after 1.5 seconds, while
    margin-history error dictionaries do not retry. Raised exceptions are not
    retried. A second error dictionary intentionally leaves the first error
    payload in place, matching the former inline pipeline loop.
    """
    run_log["supplements"] = {}
    for key, label, fetcher, args in (
        ("fund_daily5", "资金面-5日主力", fund_flow_fetcher, (code,)),
        ("margin_hist", "两融历史", margin_history_fetcher, (code,)),
        ("peers", "同业对比", peers_fetcher, (code, blocks)),
    ):
        started = time.time()
        try:
            value = _call_with_timeout(
                label,
                fetcher,
                *args,
                timeout=_SUPPLEMENT_TIMEOUT_SEC,
            )
            if isinstance(value, dict) and "error" in value and key != "margin_hist":
                time.sleep(1.5)
                retry_value = _call_with_timeout(
                    label,
                    fetcher,
                    *args,
                    timeout=_SUPPLEMENT_TIMEOUT_SEC,
                )
                if not (isinstance(retry_value, dict) and "error" in retry_value):
                    value = retry_value
        except Exception as exc:  # noqa: BLE001
            value = {"error": str(exc)}

        meta = recorder.setdefault(label, {"at": fmt_time(time.time())})
        meta["ms"] = round((time.time() - started) * 1000)
        if isinstance(value, dict) and "error" in value:
            meta["status"] = f"error:{str(value['error'])[:80]}, {meta['ms']}ms"
        else:
            meta["status"] = f"ok, {meta['ms']}ms"
        meta["detail"] = src_desc.get(label, label)
        run_log["source_meta"][label] = meta
        run_log["supplements"][label] = meta["status"]
        fetched[key] = value


def _fetch_sections(
    run_log: dict[str, Any],
    sections: Any,
    code: str,
    base_result: dict[str, Any],
) -> dict[str, Any]:
    """Execute enabled report sections with the pipeline's existing semantics."""
    sections_data: dict[str, Any] = {}
    run_log["sections_count"] = 0

    for section in sections:
        started = time.time()
        try:
            timeout = _SECTION_TIMEOUTS_SEC.get(
                section.label,
                _DEFAULT_SECTION_TIMEOUT_SEC,
            )
            sections_data[section.label] = _call_with_timeout(
                section.label,
                section.fetch,
                code,
                base_result,
                timeout=timeout,
            )
            ms = int((time.time() - started) * 1000)
            run_log["sources"][section.label] = f"ok, {ms}ms"
            run_log["sections_count"] += 1
        except Exception as exc:  # noqa: BLE001
            sections_data[section.label] = {"error": str(exc)}
            run_log["sources"][section.label] = f"error: {exc}"
            run_log.setdefault("fallback_chain", []).append(
                f"{section.label}: {exc}"
            )

    return sections_data
