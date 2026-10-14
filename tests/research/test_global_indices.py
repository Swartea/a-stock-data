from __future__ import annotations

import pytest

from analysis.research.global_indices import (
    build_global_index_symbol_registry,
    get_global_index,
    list_global_indices,
)
from analysis.research.index_registry import A_SHARE_INDEX_IDENTITIES


def test_a_share_specs_share_canonical_identity_objects_and_exact_tencent_symbols() -> None:
    specs = list_global_indices()[:4]
    assert tuple(spec.identity for spec in specs) == A_SHARE_INDEX_IDENTITIES
    registry = build_global_index_symbol_registry()
    expected = {
        "sh000001": "cn.index.sh_comp",
        "sz399001": "cn.index.sz_component",
        "sz399006": "cn.index.chinext",
        "sh000300": "cn.index.csi300",
    }
    assert {symbol: registry.require("tencent", symbol) for symbol in expected} == expected
    assert len(tuple(alias for spec in specs for alias in spec.provider_aliases)) == 5
    assert registry.require("eastmoney", "1.000300") == "cn.index.csi300"


@pytest.mark.parametrize(
    "legacy_id", ("cn.index.sse.000001", "cn.index.szse.399001", "cn.index.szse.399006", "cn.index.csi.000300")
)
def test_legacy_ids_are_rejected_by_public_lookup(legacy_id: str) -> None:
    with pytest.raises(KeyError):
        get_global_index(legacy_id)
