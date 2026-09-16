"""Isolated HTTP boundary for the official SZSE monthly trading calendar.

This module is intentionally narrow.  It knows the official SZSE endpoint and
how to validate the top-level JSON response, but it delegates calendar-row
normalization and source/time/quality composition to the existing B1 adapters.
It does not wire the calendar into the legacy V3 pipeline.

The transport is injectable so contract tests never need live network access.
The default transport uses ``requests`` and returns decoded JSON only; callers
may replace it with any callable that follows the same boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date as Date
from typing import Any

import requests

from .trading_calendar_evidence import (
    TradingCalendarEvidence,
    trading_calendar_evidence_from_szse_rows,
)


SZSE_TRADING_CALENDAR_URL = (
    "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
)
SZSE_TRADING_CALENDAR_REFERER = "https://www.szse.cn/"
SZSE_TRADING_CALENDAR_TIMEOUT = (10, 40)

JSONTransport = Callable[..., object]


class SZSECalendarFetchError(RuntimeError):
    """Stable boundary error for transport or malformed SZSE JSON responses."""


def _validate_year_month(year: int, month: int) -> None:
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("year must be an integer")
    if isinstance(month, bool) or not isinstance(month, int):
        raise TypeError("month must be an integer")
    try:
        Date(year, month, 1)
    except ValueError as exc:
        raise ValueError("year/month must identify a valid calendar month") from exc


def requests_json_transport(
    url: str,
    *,
    params: Mapping[str, str],
    timeout: tuple[int, int] = SZSE_TRADING_CALENDAR_TIMEOUT,
) -> object:
    """Fetch and decode one official SZSE JSON response using ``requests``."""

    response = requests.get(
        url,
        params=dict(params),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": SZSE_TRADING_CALENDAR_REFERER,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _extract_rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        raise SZSECalendarFetchError("SZSE calendar response must be a mapping")
    if "data" not in payload:
        raise SZSECalendarFetchError("SZSE calendar response must contain data")

    data = payload["data"]
    if not isinstance(data, list):
        raise SZSECalendarFetchError("SZSE calendar data must be a list")

    rows: list[Mapping[str, object]] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise SZSECalendarFetchError("SZSE calendar data rows must be mappings")
        rows.append(item)
    return rows


def fetch_szse_trading_calendar(
    year: int,
    month: int,
    *,
    fetched_at: str,
    transport: JSONTransport = requests_json_transport,
) -> TradingCalendarEvidence:
    """Fetch one official SZSE month and return normalized B1 evidence.

    ``data=[]`` is a valid empty result and becomes ``CompletenessStatus.EMPTY``
    through the evidence adapter, preserving UNKNOWN date semantics.  Transport
    failures are wrapped as :class:`SZSECalendarFetchError`; malformed business
    rows continue to fail in the existing strict SZSE row adapter.
    """

    _validate_year_month(year, month)
    if not callable(transport):
        raise TypeError("transport must be callable")

    params = {"month": f"{year}-{month}"}
    try:
        payload = transport(
            SZSE_TRADING_CALENDAR_URL,
            params=params,
            timeout=SZSE_TRADING_CALENDAR_TIMEOUT,
        )
    except SZSECalendarFetchError:
        raise
    except Exception as exc:
        raise SZSECalendarFetchError("SZSE calendar transport failed") from exc

    rows = _extract_rows(payload)
    return trading_calendar_evidence_from_szse_rows(
        rows,
        year=year,
        month=month,
        fetched_at=fetched_at,
    )
