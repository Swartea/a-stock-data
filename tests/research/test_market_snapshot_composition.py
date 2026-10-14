from __future__ import annotations

from analysis.research.global_daily_k_service import default_daily_k_providers
from analysis.research.global_indices import (
    build_global_index_symbol_registry,
    get_global_index,
)
from analysis.research.index_registry import A_SHARE_INDEX_IDENTITIES
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE

_TENCENT_SYMBOLS = {
    "cn.index.sh_comp": "sh000001",
    "cn.index.sz_component": "sz399001",
    "cn.index.chinext": "sz399006",
    "cn.index.csi300": "sh000300",
}


def test_every_universe_index_resolves_without_identity_translation() -> None:
    symbol_registry = build_global_index_symbol_registry()
    registry_ids = {identity.index_id for identity in A_SHARE_INDEX_IDENTITIES}
    assert A_SHARE_CORE_UNIVERSE.index_ids == tuple(
        identity.index_id for identity in A_SHARE_INDEX_IDENTITIES
    )
    for index_id in A_SHARE_CORE_UNIVERSE.index_ids:
        identity = A_SHARE_CORE_UNIVERSE.require_index(index_id)
        spec = get_global_index(index_id)
        assert spec.identity is identity
        assert spec.identity.index_id in registry_ids
        symbol = _TENCENT_SYMBOLS[index_id]
        assert spec.provider_symbol == symbol
        assert symbol_registry.resolve("tencent", symbol) == index_id
        assert default_daily_k_providers(index_id)
