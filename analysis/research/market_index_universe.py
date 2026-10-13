"""Explicit A-share core index universe for the Research Engine.

This module is slice **S3** of the stage-1 plan: a frozen, purely declarative
container that names *which* indexes the A-share market view covers and *which*
provider symbols are explicitly known for them. It is a declaration, not a
lookup service and not a data source.

Scope boundary for this slice
-----------------------------

:class:`MarketIndexUniverse` holds two immutable tuples and nothing else:

* ``identities`` -- ordered :class:`IndexIdentity` values, in declaration order;
* ``aliases`` -- ordered :class:`IndexProviderSymbolAlias` values.

What this module deliberately does **not** do:

* **No quotes, no clocks, no calendar, no freshness, no market state.** Those
  belong to evidence, transport, and later slices. A universe has no ``as_of``,
  no ``status``, and no provider-availability flag: declaring an alias says the
  *mapping* is explicit, never that a provider currently answers or is reachable.
* **No derived identities.** ``index_id`` is a fixed stable token chosen here and
  is never computed from ``local_code`` or from any provider symbol. Reusing a
  publisher-local code as an internal id is exactly the conflation this codebase
  keeps refusing (see :mod:`analysis.research.market_snapshot`).
* **No guessed provider symbols.** An absent alias is meaningful and is preserved
  as an empty tuple. Absent is never silently filled in, and ``provider_id`` is
  never assumed to equal ``provider_symbol``.
* **No second validation scheme and no retained state.** ``IndexIdentity`` and
  ``IndexProviderSymbolAlias`` do their own field validation; provider-symbol
  collision semantics are reused verbatim from
  :class:`~analysis.research.index_symbols.IndexProviderSymbolRegistry`. The
  registry instance used for the collision check is transient and is **not**
  stored on the frozen object, so the universe keeps no mutable cache that could
  drift from its declared tuples.
* **No A-share-only branch in the constructor.** The public constructor accepts
  any caller-supplied compatible identity tuples, so a later consumer can hand a
  different universe (another market, a narrower basket) to the same contract
  without editing this class.

Identity evidence for :data:`A_SHARE_CORE_UNIVERSE`
---------------------------------------------------

The four core indexes, their publishers, and their publisher-local codes follow
the official publisher/index-provider sources:

* SSE Composite (上证综指) -- SSE official index list,
  https://www.sse.com.cn/market/sseindex/indexlist/index.shtml?classid=010202
* Shenzhen Component (深证成指) -- SZSE component index methodology,
  https://www.szse.cn/marketServices/message/index/project/P020190201581531457526.pdf
* ChiNext (创业板指) -- SZSE ChiNext index description,
  https://investor.szse.cn/video/t20100707_538280.html
* CSI 300 (沪深300) -- CSI 300 index methodology,
  https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf

Publisher assignments agree with :class:`~analysis.research.index_registry.IndexPublisher`
and with the identity examples already used by the S1 contract fixtures.

Provider aliases in this module are **repository contract examples** carried over
from the S1 fixtures (see ``tests/research/test_market_snapshot.py``). They record
which mapping is explicit in this repository; they are *not* a claim of live
provider availability, freshness, or a reachable endpoint. SZSE Component and
ChiNext intentionally have no alias until a provider mapping is verified -- a
guessed symbol would be worse than an honest empty tuple.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import (
    IndexProviderSymbolAlias,
    IndexProviderSymbolRegistry,
)


@dataclass(frozen=True)
class MarketIndexUniverse:
    """Frozen, ordered declaration of one index universe.

    The universe is *explicit*: an index is in scope because a caller listed its
    identity, and a provider symbol is in scope because a caller listed the
    exact mapping. Order is meaningful on both tuples and is preserved verbatim.
    """

    identities: tuple[IndexIdentity, ...]
    aliases: tuple[IndexProviderSymbolAlias, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identities, tuple):
            raise TypeError("identities must be a tuple")
        if not self.identities:
            raise ValueError("identities must not be empty")

        known_index_ids: set[str] = set()
        for identity in self.identities:
            if not isinstance(identity, IndexIdentity):
                raise TypeError("identities must contain IndexIdentity values")
            index_id = identity.index_id
            if index_id in known_index_ids:
                raise ValueError(f"duplicate index_id in universe: {index_id!r}")
            known_index_ids.add(index_id)

        if not isinstance(self.aliases, tuple):
            raise TypeError("aliases must be a tuple")

        # Transient collision check reusing IndexProviderSymbolRegistry semantics
        # verbatim. It is intentionally not retained: a frozen declaration must
        # not keep a mutable lookup cache that could drift from these tuples.
        collision_check = IndexProviderSymbolRegistry()
        for alias in self.aliases:
            if not isinstance(alias, IndexProviderSymbolAlias):
                raise TypeError("aliases must contain IndexProviderSymbolAlias values")
            if alias.index_id not in known_index_ids:
                raise ValueError(f"alias index outside universe: {alias.index_id!r}")
            collision_check.register(alias)

    @property
    def index_ids(self) -> tuple[str, ...]:
        """Return covered index ids in declaration order."""

        return tuple(identity.index_id for identity in self.identities)

    def require_index(self, index_id: str) -> IndexIdentity:
        """Return the exact covered identity or fail loudly.

        Gating is exact: no case folding, no whitespace trimming, no prefix match,
        and no nearest-neighbour fallback.
        """

        if not isinstance(index_id, str):
            raise TypeError("index_id must be a string")
        for identity in self.identities:
            if identity.index_id == index_id:
                return identity
        raise KeyError(f"index outside universe: {index_id!r}")

    def aliases_for(self, index_id: str) -> tuple[IndexProviderSymbolAlias, ...]:
        """Return aliases for a covered index in declaration order.

        A covered index with no verified alias returns an empty tuple -- absence
        is a real, explicit state. An index outside the universe raises
        :class:`KeyError` instead, because that is a caller mistake, not a gap in
        the provider mapping.
        """

        self.require_index(index_id)
        return tuple(alias for alias in self.aliases if alias.index_id == index_id)

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small universe surface."""

        return tuple(field.name for field in fields(cls))


# Fixed stable ids and publisher-local codes. The index_id values are chosen
# here and never derived from local_code (e.g. local_code "000001" belongs to the
# SSE Composite, and its internal id "sse.composite" says so explicitly).
_SSE_COMPOSITE = IndexIdentity("sse.composite", IndexPublisher.SSE, "000001")
_SZSE_COMPONENT = IndexIdentity("szse.component", IndexPublisher.SZSE, "399001")
_SZSE_CHINEXT = IndexIdentity("szse.chinext", IndexPublisher.SZSE, "399006")
_CSI_300 = IndexIdentity("csi.300", IndexPublisher.CSI, "000300")

# Declaration order follows docs/12: 上证指数、深证成指、创业板指、沪深 300.
#
# Only the two provider mappings already carried by the current-main S1 contract
# fixtures are included. SZSE Component and ChiNext stay alias-free until verified;
# provider_id is never assumed to equal provider_symbol.
A_SHARE_CORE_UNIVERSE = MarketIndexUniverse(
    identities=(
        _SSE_COMPOSITE,
        _SZSE_COMPONENT,
        _SZSE_CHINEXT,
        _CSI_300,
    ),
    aliases=(
        IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
        IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300"),
    ),
)
