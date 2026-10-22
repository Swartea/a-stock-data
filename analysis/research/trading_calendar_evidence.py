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

Market scoping
--------------

:class:`MarketScopedCalendarEvidence` is the immutable composition that maps
*explicit market tokens* onto the :class:`TradingCalendarEvidence` values that
already exist.  It introduces **no second market registry**: the tokens are the
ones the canonical global-index registry already uses, and callers resolve an
index to its market through that registry rather than through a table here.

The composition is deliberately conservative:

* a market that is absent from the composition resolves to ``None`` /
  ``UNKNOWN`` -- never to some other market's calendar;
* a date the market's calendar does not cover resolves to ``UNKNOWN`` --
  weekends and holidays are never inferred;
* the four-field :class:`TradingCalendarEvidence` contract
  (``calendar``/``provider``/``time``/``quality``) is returned untouched.
"""

from __future__ import annotations

import re
from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date as Date
from types import MappingProxyType
from typing import Any

from .providers import ProviderSpec, build_default_provider_registry
from .quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from .time_semantics import TimeMetadata
from .trading_calendar import TradingCalendar, TradingDayStatus
from .trading_calendar_szse import trading_calendar_from_szse_rows

# Canonical market-token shape.  The token vocabulary itself is owned by the
# canonical global-index registry; this pattern only rejects values that could
# never be a market token, so no second vocabulary is defined here.
_MARKET_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


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


def canonical_market_token(value: Any) -> str | None:
    """Return the canonical market token for ``value``, or ``None``.

    The canonical form is the lowercase token already used by the global-index
    registry (``cn``/``hk``/``us``).  Surrounding whitespace and casing are
    normalized the same way the existing market selectors normalize them; no
    new token vocabulary is introduced and unknown tokens stay unknown.
    """

    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if not token or not _MARKET_TOKEN_RE.fullmatch(token):
        return None
    return token


@dataclass(frozen=True)
class MarketScopedCalendarEvidence:
    """Immutable composition of market-scoped trading-calendar evidence.

    The composition maps *explicit market tokens* to the
    :class:`TradingCalendarEvidence` values that already exist.  It is a pure
    lookup surface: it stores evidence, it never creates evidence, and it
    never derives a calendar from a date.

    Resolution rules (all deliberately conservative):

    * **Missing market** -- :meth:`evidence_for` returns ``None`` and
      :meth:`status_on` returns ``UNKNOWN``.  A market without evidence never
      borrows another market's calendar.
    * **Uncovered date** -- :meth:`status_on` returns ``UNKNOWN`` because
      :meth:`TradingCalendar.status_on` only reports dates the source
      explicitly covered.  Weekends and holidays are never inferred.
    * **Untouched contract** -- the resolved :class:`TradingCalendarEvidence`
      keeps all four fields (``calendar``/``provider``/``time``/``quality``)
      exactly as the source adapter built them.

    The composition is immutable and deterministic: entries are normalized to a
    tuple ordered by market token, so iteration order never depends on the
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
                "entries must be a mapping of market token to TradingCalendarEvidence"
            )

        normalized: list[tuple[str, TradingCalendarEvidence]] = []
        seen: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise TypeError("entries must contain (market, evidence) pairs")
            market, evidence = pair
            token = canonical_market_token(market)
            if token is None:
                raise ValueError(
                    "market must be a canonical lowercase token "
                    "(for example 'cn', 'hk', 'us')"
                )
            if token in seen:
                raise ValueError(f"duplicate market in calendar evidence: {token!r}")
            if not isinstance(evidence, TradingCalendarEvidence):
                raise TypeError("calendar evidence must be TradingCalendarEvidence")
            seen.add(token)
            normalized.append((token, evidence))

        normalized.sort(key=lambda item: item[0])
        object.__setattr__(self, "entries", tuple(normalized))
        object.__setattr__(self, "_by_market", MappingProxyType(dict(normalized)))

    @classmethod
    def from_mapping(
        cls, markets: Mapping[str, TradingCalendarEvidence]
    ) -> "MarketScopedCalendarEvidence":
        """Build a composition from a ``{market token: evidence}`` mapping."""

        if not isinstance(markets, Mapping):
            raise TypeError("markets must be a mapping of market token to evidence")
        return cls(tuple(markets.items()))

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small market-scoping composition surface."""

        return tuple(field.name for field in fields(cls))

    @property
    def markets(self) -> tuple[str, ...]:
        """Return the covered market tokens in deterministic order."""

        return tuple(token for token, _ in self.entries)

    def evidence_for(self, market: Any) -> TradingCalendarEvidence | None:
        """Return the evidence registered for ``market``, or ``None``.

        ``None`` means "this market has no calendar evidence"; it never means
        "closed" and never falls back to another market.
        """

        token = canonical_market_token(market)
        if token is None:
            return None
        return self._by_market.get(token)

    def calendar_for(self, market: Any) -> TradingCalendar:
        """Return the calendar registered for ``market``.

        A market without evidence yields an **empty** calendar, which keeps
        every date status ``UNKNOWN`` instead of borrowing another market's
        sessions.
        """

        evidence = self.evidence_for(market)
        return evidence.calendar if evidence is not None else TradingCalendar()

    def status_on(self, market: Any, date: str) -> TradingDayStatus:
        """Return the explicit status of ``date`` in ``market``.

        Returns ``UNKNOWN`` for a missing market and for a date the market's
        calendar does not explicitly cover.  No weekend or holiday inference
        happens here.
        """

        evidence = self.evidence_for(market)
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
