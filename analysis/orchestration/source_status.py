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
