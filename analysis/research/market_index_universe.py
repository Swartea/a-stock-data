"""A-share core index universe for the Research Engine.

This module is slice **S3 (part 1)** of
``docs/14-智能市场研究-阶段1-MarketSnapshot-plan.md``: the index universe that the
daily-quote boundary in :mod:`analysis.research.market_quote_source` requires as an
explicit input.

Scope boundary for this slice
-----------------------------
The universe declares **only which indexes a market contains and which provider
symbols are already known for them**.  It carries no quote, no price, no calendar,
no freshness, no quality policy and no snapshot.  A number cannot be expressed
here at all.

Adding a market adds **data**, never contract:

* ``market`` is a plain verbatim label with no grammar of its own, not an
  A-share enum;
* every index reuses :class:`~analysis.research.index_registry.IndexIdentity`;
* every provider symbol reuses
  :class:`~analysis.research.index_symbols.IndexProviderSymbolAlias`;
* no index-id grammar is introduced here.  The identity contract already validates
  ``index_id`` and ``local_code`` in ``IndexIdentity.__post_init__``, and this
  module never re-implements, loosens or bypasses that check;
* **no market-label grammar is introduced here either.**  ``market`` is checked
  only for being a non-empty string and is otherwise stored verbatim.  A private
  token regex would be exactly the forbidden "second ID lexicon": it would invent
  a canonical form for a value no existing contract owns, and it would silently
  reject the future market whose label this slice is explicitly reserving room
  for.  ``IndexIdentity`` and ``IndexProviderSymbolAlias`` are the only two token
  contracts in this module, and neither of them describes a market.

No retained resolver state
--------------------------
The universe is frozen in the strong sense, not just the decorator sense.  It
stores exactly its three contract fields and **no mutable registry is retained**
on the instance: ``IndexProviderSymbolRegistry`` is built once in
``__post_init__`` purely to validate the aliases, then discarded, and each
resolver builds a throwaway registry from the immutable ``aliases`` tuple.

That distinction is load-bearing.  A cached registry attribute would be a
hidden write channel through an otherwise immutable contract:
``universe._registry.register(alias)`` would silently rewrite
``resolve_provider_symbol`` and ``require_index`` for every later reader, so a
caller's quote path could answer a question its universe never declared.  There
is no such attribute to reach, resolution is a pure function of the declared
data, and repeated calls are guaranteed to agree.

Alias evidence is deliberately narrow
--------------------------------------
Only provider symbols that already exist elsewhere in this repository are
recorded; nothing here claims that a provider is reachable, licensed, or even
online (see ``docs/14`` §U4: provider availability is UNVERIFIED until a live
probe is authorized).

* ``csi.300`` -> ``csi``/``000300`` (``tests/research/test_index_symbols.py:100``),
  ``eastmoney``/``1.000300`` (``tests/research/test_index_symbols.py:101``,
  ``tests/research/test_market_snapshot.py:21``),
  ``sina``/``sh000300`` (``tests/research/test_index_symbols.py:102``).
* ``sse.composite`` -> ``tencent``/``sh000001``
  (``tests/research/test_market_snapshot.py:22``).
* ``szse.component`` and ``szse.chinext`` intentionally carry **no** alias.  The
  repository holds no provider-symbol evidence for ``399001``/``399006``, and
  inventing one would be a fabricated source mapping.  "No known provider symbol"
  stays a legal, expressible state and is what the quote boundary reports as
  ``unsupported`` instead of guessing a symbol.

Known limitation (S3, reported not worked around)
-------------------------------------------------
:class:`~analysis.research.index_registry.IndexPublisher` enumerates only
``CSI``/``SSE``/``SZSE``/``CNI``.  A genuine Hong Kong or US index publisher
therefore **cannot be expressed** with the current identity contract, because
``IndexIdentity.__post_init__`` rejects a non-:class:`IndexPublisher` value.
Widening that enum is out of scope for this slice (``index_registry.py`` is a
forbidden file), so this module keeps ``market`` data-driven and provider-neutral
and reports the gap rather than faking a publisher.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Iterable, Optional

from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import (
    IndexProviderSymbolAlias,
    IndexProviderSymbolRegistry,
)

A_SHARE_MARKET = "a-share"


@dataclass(frozen=True)
class MarketIndexUniverse:
    """Immutable index universe for one market.

    The universe is the mandatory, explicit input of every quote-fetch
    operation: without a universe there is no legal target index, and therefore
    no legal fetch.  It is data-driven — ``market`` is a verbatim label, not a
    hard-coded China-only branch — so a later market is added by passing another
    instance, not by changing this contract.
    """

    market: str
    indexes: tuple[IndexIdentity, ...]
    aliases: tuple[IndexProviderSymbolAlias, ...]

    def __post_init__(self) -> None:
        # A plain verbatim label, not an A-share enum: another market must add
        # data, never change the contract.  Only type and non-emptiness are
        # checked — no token grammar, no lower-casing, no trimming.  A label is
        # whatever the caller declares, and it is stored back byte-for-byte.
        if not isinstance(self.market, str):
            raise TypeError("market must be a string")
        if not self.market:
            raise ValueError("market must not be empty")

        if not isinstance(self.indexes, tuple):
            raise TypeError("indexes must be a tuple")
        if not self.indexes:
            raise ValueError("indexes must not be empty")

        known_index_ids: set[str] = set()
        for index in self.indexes:
            if not isinstance(index, IndexIdentity):
                raise TypeError("indexes must contain IndexIdentity values")
            if index.index_id in known_index_ids:
                raise ValueError(f"duplicate index in universe: {index.index_id!r}")
            known_index_ids.add(index.index_id)

        if not isinstance(self.aliases, tuple):
            raise TypeError("aliases must be a tuple")

        seen_providers: set[tuple[str, str]] = set()
        for alias in self.aliases:
            if not isinstance(alias, IndexProviderSymbolAlias):
                raise TypeError("aliases must contain IndexProviderSymbolAlias values")
            # An alias for an index this universe does not contain is a
            # mis-mapping, not a detail.
            if alias.index_id not in known_index_ids:
                raise ValueError(
                    "aliases must only map indexes in this universe: "
                    f"{alias.index_id!r} is not in market {self.market!r}"
                )
            # One provider speaks once per index: two symbols for the same
            # provider would leave "the" provider symbol ambiguous.
            provider_key = (alias.index_id, alias.provider_id)
            if provider_key in seen_providers:
                raise ValueError(
                    "one alias per provider per index: "
                    f"{alias.index_id!r} already has a {alias.provider_id!r} alias"
                )
            seen_providers.add(provider_key)

        # Provider-symbol collisions are rejected by the existing registry
        # contract rather than by a second private rule here.  The registry is
        # built, used to validate, and dropped: a universe keeps no mutable
        # resolver state behind its back (see ``_symbol_registry``).
        IndexProviderSymbolRegistry(self.aliases)

    def _symbol_registry(self) -> IndexProviderSymbolRegistry:
        """Build a throwaway registry over the frozen ``aliases`` tuple.

        The registry is deliberately **not** stored on the instance.  A retained
        one would be mutable state reachable through an attribute, and a caller
        could then rewrite resolution for every later reader with
        ``universe._registry.register(...)`` — a hidden write channel through a
        contract that promises an immutable universe.  Rebuilding costs one
        short pass over an immutable tuple and keeps every lookup a pure
        function of the declared fields, with no cache to drift.
        """

        return IndexProviderSymbolRegistry(self.aliases)

    @property
    def index_ids(self) -> tuple[str, ...]:
        """Return covered index identities in universe order."""

        return tuple(index.index_id for index in self.indexes)

    def __contains__(self, index_id: object) -> bool:
        """Report whether ``index_id`` belongs to this universe."""

        if not isinstance(index_id, str):
            return False
        return index_id in self.index_ids

    def require_index(self, index_id: str) -> IndexIdentity:
        """Return the exact identity for one index id or fail explicitly.

        Canonicality is decided by the existing ``IndexProviderSymbolRegistry``
        contract rather than by a private grammar here: a wrong type raises
        ``TypeError``, a non-canonical token raises ``ValueError``, and a
        canonical-but-unknown id raises ``KeyError``.  This module adds no
        index-id grammar of its own.
        """

        # The registry owns the canonical index-id grammar; asking it first
        # keeps one definition of "canonical" in the repository.  It is a
        # throwaway instance: nothing mutable is retained by this universe.
        self._symbol_registry().aliases_for(index_id)

        for index in self.indexes:
            if index.index_id == index_id:
                return index
        raise KeyError(f"unknown index in market {self.market!r} universe: {index_id!r}")

    def aliases_for(self, index_id: str) -> tuple[IndexProviderSymbolAlias, ...]:
        """Return every known provider alias for one index, in universe order.

        An index with no known provider symbol returns an empty tuple rather
        than a guess: "no source" stays expressible without inventing one.
        """

        if not isinstance(index_id, str):
            raise TypeError("index_id lookup value must be a string")
        return tuple(alias for alias in self.aliases if alias.index_id == index_id)

    def alias_for(
        self,
        index_id: str,
        provider_id: str,
    ) -> Optional[IndexProviderSymbolAlias]:
        """Return the exact provider alias, or ``None`` when unknown.

        Lookups stay exact: provider ids and provider symbols are never
        case-normalized or guessed, matching ``index_symbols`` semantics.
        """

        for alias in self.aliases:
            if alias.index_id == index_id and alias.provider_id == provider_id:
                return alias
        return None

    def require_alias(self, index_id: str, provider_id: str) -> IndexProviderSymbolAlias:
        """Return the exact provider alias or fail explicitly."""

        alias = self.alias_for(index_id, provider_id)
        if alias is None:
            raise KeyError(
                f"no provider alias for index {index_id!r} at provider {provider_id!r}"
            )
        return alias

    def resolve_provider_symbol(self, provider_id: str, provider_symbol: str) -> Optional[str]:
        """Resolve an exact provider symbol back to a stable index id.

        The lookup is rebuilt from the immutable ``aliases`` tuple on every
        call, so the answer depends only on declared data: no alias registered
        anywhere else — and no attribute assigned onto this instance — can
        change what an existing universe resolves.
        """

        return self._symbol_registry().resolve(provider_id, provider_symbol)

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small universe surface."""

        return tuple(field.name for field in fields(cls))


def a_share_core_universe() -> MarketIndexUniverse:
    """Return the A-share core index universe in a fixed, deterministic order.

    Order is part of the contract: SSE Composite, SZSE Component, ChiNext, then
    CSI 300.  The function rebuilds an equivalent immutable instance on every
    call rather than sharing one mutable global.
    """

    indexes = (
        IndexIdentity("sse.composite", IndexPublisher.SSE, "000001"),
        IndexIdentity("szse.component", IndexPublisher.SZSE, "399001"),
        IndexIdentity("szse.chinext", IndexPublisher.SZSE, "399006"),
        IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),
    )
    aliases = (
        # Repository evidence only; see the module docstring for exact sources.
        IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
        IndexProviderSymbolAlias("csi.300", "csi", "000300"),
        IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300"),
        IndexProviderSymbolAlias("csi.300", "sina", "sh000300"),
    )
    return MarketIndexUniverse(market=A_SHARE_MARKET, indexes=indexes, aliases=aliases)


def build_universe(
    *,
    market: str,
    indexes: Iterable[IndexIdentity],
    aliases: Iterable[IndexProviderSymbolAlias] = (),
) -> MarketIndexUniverse:
    """Build a universe for any market from explicit data.

    This is the only supported way to introduce another market: pass different
    data, not a changed contract.  It is also what lets a caller express a
    market whose publisher set the current ``IndexPublisher`` enum cannot yet
    name — see the module docstring's known limitation.
    """

    return MarketIndexUniverse(
        market=market,
        indexes=tuple(indexes),
        aliases=tuple(aliases),
    )
