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
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date as Date

from .providers import ProviderSpec, build_default_provider_registry
from .quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from .time_semantics import TimeMetadata
from .trading_calendar import TradingCalendar
from .trading_calendar_szse import trading_calendar_from_szse_rows


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
