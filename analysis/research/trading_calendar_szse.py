"""Pure adapter for Shenzhen Stock Exchange monthly trading-calendar rows.

This module normalizes already-fetched SZSE calendar payload rows into the
provider-neutral :class:`TradingCalendar` contract.  It deliberately performs
no HTTP requests and does not wire the calendar into the existing V3 pipeline.

SZSE publishes one row per Gregorian calendar date for a requested month using
``jyrq`` (date) and ``jybz`` (``"1"`` open, ``"0"`` closed).  A non-empty
payload must therefore cover the requested month exactly once.  An empty
payload remains an empty calendar so callers retain ``UNKNOWN`` semantics; it
is never expanded into synthetic closed days.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from datetime import date as Date

from .trading_calendar import TradingCalendar, TradingCalendarDay, TradingDayStatus


def _validate_year_month(year: int, month: int) -> None:
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("year must be an integer")
    if isinstance(month, bool) or not isinstance(month, int):
        raise TypeError("month must be an integer")

    try:
        Date(year, month, 1)
    except ValueError as exc:
        raise ValueError("year/month must identify a valid calendar month") from exc


def _parse_szse_date(value: object) -> Date:
    if not isinstance(value, str) or not value:
        raise ValueError("SZSE jyrq must be a non-empty ISO date string")
    if value != value.strip():
        raise ValueError("SZSE jyrq must be a canonical ISO date string")

    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("SZSE jyrq must be an ISO date string") from exc

    if parsed.isoformat() != value:
        raise ValueError("SZSE jyrq must use canonical YYYY-MM-DD format")
    return parsed


def _parse_szse_status(value: object) -> TradingDayStatus:
    if value == "1":
        return TradingDayStatus.OPEN
    if value == "0":
        return TradingDayStatus.CLOSED
    raise ValueError('SZSE jybz must be exactly "0" or "1"')


def trading_calendar_from_szse_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    year: int,
    month: int,
) -> TradingCalendar:
    """Normalize a complete SZSE monthly payload into ``TradingCalendar``.

    Empty input is intentionally accepted and returns an empty calendar.  This
    represents absence of calendar evidence (for example, an as-yet unpublished
    month) without manufacturing ``CLOSED`` rows.

    Once any row is present, the payload must contain every Gregorian date in
    the requested month exactly once.  Partial, duplicate, wrong-month, or
    unknown-flag payloads are rejected rather than silently normalized.
    """

    _validate_year_month(year, month)
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise TypeError("rows must be a sequence of mappings")
    if not rows:
        return TradingCalendar()

    normalized: dict[str, TradingDayStatus] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("each SZSE calendar row must be a mapping")
        if "jyrq" not in row or "jybz" not in row:
            raise ValueError("SZSE calendar row must contain jyrq and jybz")

        parsed_date = _parse_szse_date(row["jyrq"])
        if parsed_date.year != year or parsed_date.month != month:
            raise ValueError("SZSE calendar row falls outside requested month")

        canonical_date = parsed_date.isoformat()
        if canonical_date in normalized:
            raise ValueError("SZSE calendar contains duplicate dates")
        normalized[canonical_date] = _parse_szse_status(row["jybz"])

    expected_count = monthrange(year, month)[1]
    expected_dates = tuple(
        Date(year, month, day).isoformat() for day in range(1, expected_count + 1)
    )
    actual_dates = tuple(sorted(normalized))
    if actual_dates != expected_dates:
        raise ValueError("SZSE calendar must cover every date in requested month")

    return TradingCalendar(
        days=tuple(
            TradingCalendarDay(date=value, status=normalized[value])
            for value in expected_dates
        )
    )
