"""Source, time, and quality evidence for Research Engine trading calendars.

This module composes the existing provider registry (A2), explicit time
semantics (A3), quality metadata (A4), and provider-neutral trading-calendar
contract (B1).  It does not fetch data, infer freshness, invent publication
timestamps, or wire calendars into the existing V3 pipeline.

The SZSE factory accepts already-fetched provider rows and delegates payload
normalization to :mod:`trading_calendar_szse`.  The requested month defines the
calendar coverage period; it does not imply when the exchange published that
calendar.  Therefore ``published_at`` and ``data_as_of`` remain unknown unless
a later source adapter can prove those clocks explicitly.

Identity scoping
----------------

:class:`IndexScopedCalendarEvidence` is the immutable composition that maps
*canonical index identities* (``index_id``) onto the
:class:`TradingCalendarEvidence` values that already exist.  It introduces **no
second registry**: identity resolution reuses the existing index registries in
:mod:`analysis.research.index_registry` (canonical ids and their historical
aliases) and :mod:`analysis.research.global_indices` (the V1 index universe).
Callers resolve an index to its calendar by its own identity, never by a
market token.

Scoping by identity is what keeps the evidence honest.  A Shenzhen (SZSE)
exchange calendar proves the sessions of the *SZSE-published* indices; it does
not prove the sessions of the SSE Composite or of the CSI 300, which are
published by different bodies.  Assigning SZSE evidence to those identities is
therefore an explicit, caller-owned act -- never an automatic consequence of
sharing a market token.

The composition is deliberately conservative:

* an identity that is absent from the composition resolves to ``None`` /
  ``UNKNOWN`` -- never to some other index's calendar;
* a market-level token (``cn``/``hk``/``us``) is **not** an identity and is
  rejected on construction and never resolves on lookup;
* a date the index's calendar does not cover resolves to ``UNKNOWN`` --
  weekends and holidays are never inferred;
* the four-field :class:`TradingCalendarEvidence` contract
  (``calendar``/``provider``/``time``/``quality``) is returned untouched.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date as Date
from types import MappingProxyType
from typing import Any

from .global_indices import list_global_indices
from .index_registry import A_SHARE_INDEX_BY_ID, canonical_index_id
from .providers import ProviderSpec, build_default_provider_registry
from .quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from .time_semantics import TimeMetadata
from .trading_calendar import TradingCalendar, TradingDayStatus
from .trading_calendar_szse import trading_calendar_from_szse_rows

# Canonical index identities known to the existing index registries.  Both
# sources already exist: ``index_registry`` owns the canonical A-share
# identities and their historical aliases, ``global_indices`` owns the V1
# global-index universe.  No new registry -- and in particular no new *market*
# registry -- is introduced here.
_KNOWN_INDEX_IDS: frozenset[str] = frozenset(
    set(A_SHARE_INDEX_BY_ID)
    | {spec.identity.index_id for spec in list_global_indices()}
)


@dataclass(frozen=True)
class TradingCalendarEvidence:
    """Immutable composition of one normalized calendar and its evidence.

    The four components intentionally stay separate.  Provider identity does
    not imply freshness; completeness does not imply degraded status; and fetch
    time never substitutes for publication or data-as-of time.
    """

    calendar: TradingCalendar
    provider: ProviderSpec
    time: TimeMetadata
    quality: QualityMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.calendar, TradingCalendar):
            raise TypeError("calendar must be TradingCalendar")
        if not isinstance(self.provider, ProviderSpec):
            raise TypeError("provider must be ProviderSpec")
        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")
        if not isinstance(self.quality, QualityMetadata):
            raise TypeError("quality must be QualityMetadata")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small B1 evidence surface."""

        return tuple(field.name for field in fields(cls))


def canonical_index_identity(value: Any) -> str | None:
    """Return the canonical index identity for ``value``, or ``None``.

    ``value`` must be a canonical lowercase ``index_id`` known to the existing
    index registries, or one of their historical aliases -- the same alias
    vocabulary :func:`analysis.research.index_registry.canonical_index_id`
    already accepts at API boundaries.  A market token such as ``cn`` is not
    an identity and therefore never resolves.
    """

    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token or token != token.lower():
        return None
    try:
        canonical = canonical_index_id(token)
    except TypeError:
        return None
    if canonical not in _KNOWN_INDEX_IDS:
        return None
    return canonical


@dataclass(frozen=True)
class IndexScopedCalendarEvidence:
    """Immutable composition of identity-scoped trading-calendar evidence.

    The composition maps *canonical index identities* to the
    :class:`TradingCalendarEvidence` values that already exist.  It is a pure
    lookup surface: it stores evidence, it never creates evidence, and it
    never derives a calendar from a date.

    Resolution rules (all deliberately conservative):

    * **Missing identity** -- :meth:`evidence_for` returns ``None`` and
      :meth:`status_on` returns ``UNKNOWN``.  An index without evidence never
      borrows another index's calendar, and one index's calendar never
      applies to a sibling index merely because both live in the same market.
    * **Market-level token** -- ``cn`` / ``hk`` / ``us`` are not identities:
      they are rejected when the composition is built and never resolve on
      lookup.
    * **Uncovered date** -- :meth:`status_on` returns ``UNKNOWN`` because
      :meth:`TradingCalendar.status_on` only reports dates the source
      explicitly covered.  Weekends and holidays are never inferred.
    * **Untouched contract** -- the resolved :class:`TradingCalendarEvidence`
      keeps all four fields (``calendar``/``provider``/``time``/``quality``)
      exactly as the source adapter built them.

    The composition is immutable and deterministic: entries are normalized to a
    tuple ordered by index id, so iteration order never depends on the
    caller's insertion order.
    """

    entries: tuple[tuple[str, TradingCalendarEvidence], ...] = ()

    def __post_init__(self) -> None:
        raw = self.entries
        if isinstance(raw, Mapping):
            pairs: tuple[Any, ...] = tuple(raw.items())
        elif isinstance(raw, (tuple, list)):
            pairs = tuple(raw)
        else:
            raise TypeError(
                "entries must be a mapping of index id to TradingCalendarEvidence"
            )

        normalized: list[tuple[str, TradingCalendarEvidence]] = []
        seen: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise TypeError("entries must contain (index_id, evidence) pairs")
            index_id, evidence = pair
            canonical = canonical_index_identity(index_id)
            if canonical is None:
                raise ValueError(
                    "index_id must be a canonical index identity known to the "
                    "index registry (for example 'cn.index.sz_component'); "
                    "market-level tokens such as 'cn' are not identities"
                )
            if canonical in seen:
                raise ValueError(f"duplicate index in calendar evidence: {canonical!r}")
            if not isinstance(evidence, TradingCalendarEvidence):
                raise TypeError("calendar evidence must be TradingCalendarEvidence")
            seen.add(canonical)
            normalized.append((canonical, evidence))

        normalized.sort(key=lambda item: item[0])
        object.__setattr__(self, "entries", tuple(normalized))
        object.__setattr__(self, "_by_index", MappingProxyType(dict(normalized)))

    @classmethod
    def from_mapping(
        cls, index_ids: Mapping[str, TradingCalendarEvidence]
    ) -> "IndexScopedCalendarEvidence":
        """Build a composition from an ``{index id: evidence}`` mapping."""

        if not isinstance(index_ids, Mapping):
            raise TypeError("index_ids must be a mapping of index id to evidence")
        return cls(tuple(index_ids.items()))

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small identity-scoping composition surface."""

        return tuple(field.name for field in fields(cls))

    @property
    def index_ids(self) -> tuple[str, ...]:
        """Return the covered index identities in deterministic order."""

        return tuple(index_id for index_id, _ in self.entries)

    def evidence_for(self, index_id: Any) -> TradingCalendarEvidence | None:
        """Return the evidence registered for ``index_id``, or ``None``.

        ``None`` means "this index has no calendar evidence"; it never means
        "closed" and never falls back to another index.
        """

        canonical = canonical_index_identity(index_id)
        if canonical is None:
            return None
        return self._by_index.get(canonical)

    def calendar_for(self, index_id: Any) -> TradingCalendar:
        """Return the calendar registered for ``index_id``.

        An index without evidence yields an **empty** calendar, which keeps
        every date status ``UNKNOWN`` instead of borrowing another index's
        sessions.
        """

        evidence = self.evidence_for(index_id)
        return evidence.calendar if evidence is not None else TradingCalendar()

    def status_on(self, index_id: Any, date: str) -> TradingDayStatus:
        """Return the explicit status of ``date`` for ``index_id``.

        Returns ``UNKNOWN`` for an index without evidence and for a date the
        index's calendar does not explicitly cover.  No weekend or holiday
        inference happens here.
        """

        evidence = self.evidence_for(index_id)
        if evidence is None:
            return TradingDayStatus.UNKNOWN
        return evidence.calendar.status_on(date)


def trading_calendar_evidence_from_szse_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    year: int,
    month: int,
    fetched_at: str,
) -> TradingCalendarEvidence:
    """Normalize SZSE rows and attach explicit source/time/quality evidence.

    Non-empty SZSE payloads have already been validated by the underlying
    adapter to cover every Gregorian date in the requested month, so their
    completeness is ``COMPLETE``.  Empty payloads remain ``EMPTY`` and preserve
    the calendar contract's unknown-date semantics.

    Freshness stays ``UNKNOWN`` because B1 has no age policy.  The official
    provider identity also does not imply freshness or publication time.

    The returned evidence carries no index scope of its own: the caller
    decides which canonical index identity it is explicitly assigned to.
    """

    calendar = trading_calendar_from_szse_rows(rows, year=year, month=month)
    last_day = monthrange(year, month)[1]
    period_start = Date(year, month, 1).isoformat()
    period_end = Date(year, month, last_day).isoformat()

    provider = build_default_provider_registry().require("szse")
    time = TimeMetadata(
        fetched_at=fetched_at,
        period_start=period_start,
        period_end=period_end,
    )
    quality = QualityMetadata(
        freshness=FreshnessStatus.UNKNOWN,
        completeness=(
            CompletenessStatus.COMPLETE
            if calendar.days
            else CompletenessStatus.EMPTY
        ),
        degraded=False,
        quality_flags=(),
    )

    return TradingCalendarEvidence(
        calendar=calendar,
        provider=provider,
        time=time,
        quality=quality,
    )
