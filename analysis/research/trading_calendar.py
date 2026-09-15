"""Provider-neutral trading-calendar contract for the Research Engine.

The contract records explicit exchange-calendar evidence only.  It deliberately
never infers a market closure from weekends, public-holiday heuristics, missing
rows, or the current system clock.  If a date is not represented, its status is
``UNKNOWN`` until a calendar source proves otherwise.

Provider/source metadata and fetch wiring belong to later adapters/DataEnvelope
layers.  This module also does not replace the existing V3
``_latest_trading_day`` helper yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from enum import Enum


class TradingDayStatus(str, Enum):
    """Explicit trading status for one calendar date."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


def _parse_iso_date(value: str, *, field_name: str = "date") -> Date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty ISO date string")
    if value != value.strip():
        raise ValueError(f"{field_name} must be a canonical ISO date string")

    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc

    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use canonical YYYY-MM-DD format")
    return parsed


@dataclass(frozen=True)
class TradingCalendarDay:
    """One explicit calendar observation.

    ``UNKNOWN`` is a first-class status because some normalized sources may
    expose a date while leaving its trading flag unresolved.  ``is_open`` keeps
    callers from coercing ``UNKNOWN`` to ``False``.
    """

    date: str
    status: TradingDayStatus

    def __post_init__(self) -> None:
        _parse_iso_date(self.date)
        if not isinstance(self.status, TradingDayStatus):
            raise TypeError("status must be TradingDayStatus")

    @property
    def is_open(self) -> bool | None:
        if self.status is TradingDayStatus.OPEN:
            return True
        if self.status is TradingDayStatus.CLOSED:
            return False
        return None


@dataclass(frozen=True)
class TradingCalendar:
    """Ordered explicit trading-calendar observations.

    The tuple may be empty or partial.  Missing dates remain ``UNKNOWN`` rather
    than being inferred closed.  Adapters that claim complete monthly coverage
    must validate that completeness before constructing/returning their final
    normalized result; this domain object does not manufacture missing rows.
    """

    days: tuple[TradingCalendarDay, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.days, tuple):
            raise TypeError("days must be a tuple")

        previous: Date | None = None
        for item in self.days:
            if not isinstance(item, TradingCalendarDay):
                raise TypeError("days must contain TradingCalendarDay values")
            current = _parse_iso_date(item.date)
            if previous is not None and current <= previous:
                raise ValueError("calendar days must be unique and strictly ascending")
            previous = current

    def status_on(self, date: str) -> TradingDayStatus:
        """Return explicit status, or ``UNKNOWN`` when the date is absent."""

        target = _parse_iso_date(date)
        for item in self.days:
            current = _parse_iso_date(item.date)
            if current == target:
                return item.status
            if current > target:
                break
        return TradingDayStatus.UNKNOWN

    def is_open_on(self, date: str) -> bool | None:
        """Return True/False only for known status; unknown remains ``None``."""

        status = self.status_on(date)
        if status is TradingDayStatus.OPEN:
            return True
        if status is TradingDayStatus.CLOSED:
            return False
        return None
