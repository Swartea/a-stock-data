"""Source-status state boundary for the V3 pipeline.

Phase 1E-A intentionally keeps the existing ``_src_meta`` semantics:
metadata is sparse, entries are mutated incrementally, and callers may attach
source-specific extra keys.  This module adds ownership around that state
without normalizing or changing the run-log contract.
"""

from collections.abc import Iterator, MutableMapping
from typing import Any

SourceMeta = dict[str, Any]


class SourceStatusRecorder(MutableMapping[str, SourceMeta]):
    """Minimal dict-compatible owner for per-source metadata.

    The compatibility surface is deliberately small.  ``MutableMapping``
    preserves the operations currently used by ``pipeline.py`` (indexing,
    ``setdefault``, ``get``, ``clear`` and iteration) while ``snapshot`` gives
    future call sites an explicit detached view for serialization.

    No default fields are injected here.  The current pipeline has multiple
    valid shapes, including ``{"ms": ...}``, the four-key V2 timer seed, and
    entries with source-specific keys such as ``tls_recommendation``.
    """

    def __init__(self) -> None:
        self._data: dict[str, SourceMeta] = {}

    def __getitem__(self, label: str) -> SourceMeta:
        return self._data[label]

    def __setitem__(self, label: str, meta: SourceMeta) -> None:
        self._data[label] = meta

    def __delitem__(self, label: str) -> None:
        del self._data[label]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def snapshot(self) -> dict[str, SourceMeta]:
        """Return a detached copy suitable for run-log serialization."""
        return {label: dict(meta) for label, meta in self._data.items()}


def _record_v2_source_statuses(results, recorder, run_log, field_of, source_desc):
    """Project legacy V2 result shapes into the existing run-log status contract.

    This intentionally preserves the pipeline's current sparse metadata and
    status wording.  The recorder itself is not normalized or enriched with
    ``status``/``detail``; run-log receives a detached shallow copy instead.
    """
    for lab, field in field_of.items():
        data = results.get(field)
        meta = recorder.get(lab, {})
        if isinstance(data, dict) and "error" in data:
            status = f"error:{str(data['error'])[:60]}, {meta.get('ms','?')}ms"
        elif lab == "行情" and not data:
            status = f"error:行情为空, {meta.get('ms','?')}ms"
        elif lab == "概念板块" and isinstance(data, list) and any(
            isinstance(item, dict) and "error" in item for item in data
        ):
            status = f"error:接口异常, {meta.get('ms','?')}ms"
        elif lab == "概念板块" and isinstance(data, list) and not data:
            status = f"fallback:接口返回0条(可能风控), {meta.get('ms','?')}ms"
        elif lab == "当日资金流" and isinstance(data, dict) and not data.get("klines"):
            status = f"fallback:当日无成交或分钟数据, {meta.get('ms','?')}ms"
        elif lab == "宏观底色" and isinstance(data, dict) and not any(
            data.get(key) for key in ("hsgt", "industries", "hot_stocks")
        ):
            status = f"error:北向/行业/强势股子源全空, {meta.get('ms','?')}ms"
        else:
            status = f"ok, {meta.get('ms','?')}ms"

        projected_meta = dict(meta)
        projected_meta["status"] = status
        projected_meta["detail"] = source_desc.get(lab, lab)
        run_log["sources"][lab] = status
        run_log["source_meta"][lab] = projected_meta
        if not status.startswith("ok"):
            run_log["fallback_chain"].append(f"{lab}: {status}")
