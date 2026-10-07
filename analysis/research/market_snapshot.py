"""Market-level snapshot container for the Research Engine.

This module is slice **S1** of
``docs/14-智能市场研究-阶段1-MarketSnapshot-plan.md``: one pure container class,
no fetching, no rendering, no calendar, no quality policy.

Scope boundary for this slice
-----------------------------
:class:`MarketSnapshot` here is deliberately **empty of numbers**.  Every
observable value arrives together with the evidence record that supports it, and
that record is a later slice.  Because the container exposes no numeric field at
all, a number without evidence cannot even be expressed, let alone constructed.

What this module does hold is the identity spine of a snapshot:

* which market it describes (a plain token, not an A-share enum);
* which indices it covers (:class:`IndexIdentity`);
* which provider symbols serve them
  (:class:`IndexProviderSymbolAlias`).

Three code spaces stay separate and none is derived from another:

* ``IndexIdentity.index_id``  -- the Research Engine's own stable id;
* ``IndexIdentity.local_code`` -- the exchange/publisher-local code;
* ``IndexProviderSymbolAlias.provider_symbol`` -- the data-source code.

Rules this module follows on purpose:

* **No second identity scheme.**  It reuses
  :mod:`analysis.research.index_registry` and
  :mod:`analysis.research.index_symbols` verbatim; it defines no new id
  vocabulary and normalizes nothing.
* **No guessed time.**  The snapshot has no ``as_of`` field.  The data date
  belongs to evidence and the trading-day state belongs to explicit calendar
  evidence, both later slices.  A container-level clock would be a second,
  conflicting source of truth.
* **No global thresholds, no policies.**  Freshness stays caller-supplied via
  :class:`~analysis.research.freshness.MaxAgePolicy`; this module stores none.

Later slices add the evidence record, the A-share index universe, the quote
transport, the market state, and the available/delayed/unavailable three-state
expression.  Nothing here anticipates their field-level shape beyond keeping the
container extensible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

from analysis.research.index_registry import IndexIdentity
from analysis.research.index_symbols import IndexProviderSymbolAlias

_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_INDEX_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable container for one market snapshot.

    The container carries **no numbers and no clocks**.  It records *what* the
    snapshot covers and *from where* those values would come, so that later
    evidence records can attach numbers without inventing a parallel identity or
    time source here.
    """

    snapshot_id: str
    market: str
    indexes: tuple[IndexIdentity, ...]
    provider_symbols: tuple[IndexProviderSymbolAlias, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str):
            raise TypeError("snapshot_id must be a string")
        if not _TOKEN_RE.fullmatch(self.snapshot_id):
            raise ValueError("snapshot_id must be a canonical lowercase token")

        # A plain token, not an A-share enum: another market must add data,
        # never change the contract.
        if not isinstance(self.market, str):
            raise TypeError("market must be a string")
        if not _TOKEN_RE.fullmatch(self.market):
            raise ValueError("market must be a canonical lowercase token")

        if not isinstance(self.indexes, tuple):
            raise TypeError("indexes must be a tuple")
        if not self.indexes:
            raise ValueError("indexes must not be empty")

        known_index_ids: set[str] = set()
        for item in self.indexes:
            if not isinstance(item, IndexIdentity):
                raise TypeError("indexes must contain IndexIdentity values")
            index_id = item.index_id
            if index_id in known_index_ids:
                raise ValueError(f"duplicate index in snapshot: {index_id!r}")
            known_index_ids.add(index_id)

        if not isinstance(self.provider_symbols, tuple):
            raise TypeError("provider_symbols must be a tuple")

        seen_symbols: set[tuple[str, str]] = set()
        for alias in self.provider_symbols:
            if not isinstance(alias, IndexProviderSymbolAlias):
                raise TypeError("provider_symbols must contain IndexProviderSymbolAlias values")
            # An alias for an index the snapshot does not cover is a mis-mapping,
            # not a detail.
            if alias.index_id not in known_index_ids:
                raise ValueError(
                    "provider_symbols must only map covered indexes: "
                    f"{alias.index_id!r} is not in this snapshot"
                )
            key = (alias.provider_id, alias.provider_symbol)
            if key in seen_symbols:
                raise ValueError(
                    f"duplicate provider symbol: {alias.provider_id!r}:{alias.provider_symbol!r}"
                )
            seen_symbols.add(key)

    @property
    def index_ids(self) -> tuple[str, ...]:
        """Return covered index identities in snapshot order."""

        return tuple(item.index_id for item in self.indexes)

    def symbols_for(self, index_id: str) -> tuple[IndexProviderSymbolAlias, ...]:
        """Return provider symbols for one index id in snapshot order.

        An index with no known provider symbol returns an empty tuple rather
        than a guess: "no source" stays expressible without inventing one.
        """

        if not isinstance(index_id, str) or not _INDEX_ID_RE.fullmatch(index_id):
            raise ValueError("index_id lookup value must be a canonical token")
        return tuple(
            alias
            for alias in self.provider_symbols
            if alias.index_id == index_id
        )

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small snapshot container surface."""

        return tuple(field.name for field in fields(cls))
