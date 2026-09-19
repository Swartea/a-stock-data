"""Additive bridge from the existing fetcher contract to research time metadata.

This adapter deliberately understands only the time fields guaranteed by
``analysis.fetcher_contract`` today: ``fetched_at`` and ``as_of``.

It does not mutate the fetcher result and it does not trust or infer future
research time fields such as ``published_at`` or ``effective_from`` merely
because similarly named keys happen to be present in an input mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from analysis.research.time_semantics import TimeMetadata


def time_metadata_from_fetcher_result(result: Mapping[str, Any]) -> TimeMetadata:
    """Convert current fetcher time fields into ``TimeMetadata`` safely.

    Mapping rules are intentionally narrow:

    - ``fetched_at`` -> ``fetched_at``
    - ``as_of`` -> ``data_as_of``
    - all other research time semantics remain unknown

    ``fetched_at`` is required because the normalized fetcher contract promises
    a retrieval timestamp.  If a caller passes an incomplete ad-hoc mapping,
    fail explicitly rather than manufacturing a timestamp in the research
    layer.
    """
    if not isinstance(result, Mapping):
        raise TypeError("fetcher result must be a mapping")

    if "fetched_at" not in result or result.get("fetched_at") is None:
        raise ValueError("fetcher result must contain fetched_at")

    return TimeMetadata.from_legacy(
        fetched_at=result["fetched_at"],
        as_of=result.get("as_of"),
    )
