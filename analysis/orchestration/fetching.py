"""Fetching orchestration primitives for the V3 pipeline.

Phase 1G keeps the existing retry semantics intact while making the source
status recorder an explicit dependency.  Higher-level status interpretation,
fallback-chain updates, and run-log assembly remain in ``pipeline.py``.
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
