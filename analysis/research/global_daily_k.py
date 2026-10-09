"""Tencent-backed fetcher for the V1 global-index daily-K series.

This module is intentionally narrow. It owns:

* the Tencent ``web.ifzq.gtimg.cn`` ``appstock/app/fqkline/get`` endpoint and
  its ``param=<symbol>,day,<start>,<end>,640,`` request shape,
* an injectable transport (``requests_json_transport`` by default) so that
  tests can drive deterministic fixtures,
* row-level validation for the first six observed columns
  ``[date, open, close, high, low, provider_activity, ...]``,
* inclusive date-window filtering that conservatively drops any session whose
  local date is ``>=`` the supplied ``now`` (no same-day bar even after close),
* an output record shape of
  ``{index_id, market, symbol, name, date, open, high, low, close, volume, currency, timezone, source}``
  with ``volume=None`` for every V1 record and units
  ``{"price": "index_points", "volume": "unavailable"}``.

It explicitly does NOT:

* do retry / fallback / cache, or send more than one HTTP request per fetch,
* infer a provider symbol from a bare code — the caller must pass an
  ``index_id`` that the V1 registry in :mod:`analysis.research.global_indices`
  resolves,
* synthesize forward-filled weekends / holidays or use the Shanghai calendar
  for foreign markets,
* convert OHLC to currency-denominated price (it is already index points),
* parse or invent a volume figure from the provider's sixth column,
* wire into the legacy V3 pipeline.

The supported/unknown surface, the entrypoint name, and the result envelope
are all fixed by the V1 controller-decided contract. No UI, score, formula,
or report is touched.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import date as Date
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from analysis import fetcher_contract

from .global_indices import (
    GlobalIndexSpec,
    build_global_index_symbol_registry,
    get_global_index,
)

TENCENT_DAILY_K_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
)
TENCENT_DAILY_K_TIMEOUT: tuple[int, int] = (5, 15)
TENCENT_PROVIDER_ID = "tencent"
TENCENT_SCOPE = "market"
TENCENT_SOURCE = "tencent.daily_k"

# Maximum inclusive window the fetcher will accept. Larger windows are
# rejected up front rather than silently truncated so callers cannot mistake a
# partial result for a complete one.
_MAX_WINDOW_CALENDAR_DAYS = 366

# Strict YYYY-MM-DD gate. ``date.fromisoformat`` on Python 3.11+ accepts the
# compact ``YYYYMMDD`` form and ISO week-date forms (``2026-W39-6``), which the
# V1 contract forbids for both call-site inputs and provider row dates.
_STRICT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

JSONTransport = Callable[..., Any]


class GlobalDailyKError(RuntimeError):
    """Stable boundary error for transport or malformed provider payloads."""


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def requests_json_transport(
    url: str,
    *,
    params: Mapping[str, str],
    timeout: tuple[int, int] = TENCENT_DAILY_K_TIMEOUT,
) -> Any:
    """Default transport: one bounded ``requests.get`` and a JSON decode.

    TLS verification is enabled by ``requests``' default. The HTTP status is
    checked and any non-2xx response raises so that the caller can map it to a
    stable error code. JSON decoding errors surface as :class:`ValueError` so
    the caller can return ``PARSE`` without leaking provider internals.
    """

    if not isinstance(url, str) or not url:
        raise TypeError("url must be a non-empty string")
    if not isinstance(timeout, tuple) or len(timeout) != 2:
        raise TypeError("timeout must be a (connect, read) tuple")
    response = requests.get(
        url,
        params=dict(params),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _parse_strict_date(value: str, *, field: str) -> Date:
    """Parse one strict ``YYYY-MM-DD`` string into a :class:`datetime.date`.

    Compact (``YYYYMMDD``) and ISO week-date (``YYYY-Www-D``) forms are rejected
    even though :meth:`datetime.date.fromisoformat` accepts them on Python 3.11+.
    The fetcher contract requires strict ``YYYY-MM-DD`` for every date-like
    field on both the input boundary and the provider-row boundary.
    """

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty YYYY-MM-DD string")
    if not _STRICT_DATE_RE.fullmatch(value):
        raise ValueError(
            f"{field} must match strict YYYY-MM-DD; got {value!r}"
        )
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field} is not a valid calendar date: {value!r}"
        ) from exc


def _validate_inputs(
    index_id: str,
    start_date: str,
    end_date: str,
    transport: Any,
    now: Any,
) -> None:
    if not isinstance(index_id, str) or not index_id:
        raise ValueError("index_id must be a non-empty string")

    parsed_start = _parse_strict_date(start_date, field="start_date")
    parsed_end = _parse_strict_date(end_date, field="end_date")
    if parsed_start > parsed_end:
        raise ValueError("start_date must be <= end_date")
    if (parsed_end - parsed_start).days + 1 > _MAX_WINDOW_CALENDAR_DAYS:
        raise ValueError(
            "date window exceeds 366 inclusive calendar days"
        )

    if not callable(transport):
        raise ValueError("transport must be callable")

    if now is not None:
        if isinstance(now, bool) or not isinstance(now, datetime):
            raise ValueError("now must be an aware datetime or None")
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("now must be timezone-aware")


def _normalize_now(now: Any) -> datetime:
    if now is None:
        return datetime.now(tz=timezone.utc)
    return now


def _coerce_finite_number(value: Any, *, field: str) -> float:
    """Coerce one OHLC value to a finite ``float``.

    ``bool`` is rejected explicitly because Python treats it as an ``int`` and
    would otherwise be accepted silently. NaN, infinities, and numeric values
    that overflow ``float`` (e.g. ``10**1000``) are also rejected so that the
    boundary never crashes the caller. Strings are accepted only if they parse
    to a finite real decimal.
    """

    if isinstance(value, bool):
        raise ValueError(f"{field} must not be a bool")
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{field} must be a finite real number") from exc
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{field} must be a finite decimal string") from exc
    else:
        raise ValueError(f"{field} must be a finite real number")
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"{field} must be finite")
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _parse_row(
    row: Any,
    *,
    provider_symbol: str,
) -> dict[str, Any]:
    """Validate one provider row and return a normalized record dict.

    The Tencent shape is ``[date, open, close, high, low, activity, ...]``.
    Extra trailing fields are ignored; missing fields raise. OHLC must satisfy
    ``low <= open, close <= high``. The sixth column is read but never
    surfaced — its unit semantics are unverified.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, list):
        raise ValueError("row must be a list")
    if len(row) < 6:
        raise ValueError(
            f"row for {provider_symbol} must have at least 6 fields"
        )

    raw_date = row[0]
    parsed_date = _parse_strict_date(raw_date, field="row date")

    open_px = _coerce_finite_number(row[1], field="open")
    close_px = _coerce_finite_number(row[2], field="close")
    high_px = _coerce_finite_number(row[3], field="high")
    low_px = _coerce_finite_number(row[4], field="low")
    # Sixth column is provider activity / turnover-like and is intentionally
    # ignored — heterogeneous units, no comparable volume label.

    if low_px > high_px:
        raise ValueError("low must be <= high")
    if low_px > open_px or low_px > close_px:
        raise ValueError("low must be <= open and close")
    if high_px < open_px or high_px < close_px:
        raise ValueError("high must be >= open and close")

    return {
        "date": parsed_date,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": close_px,
    }


def _resolve_tz(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise GlobalDailyKError(
            f"unknown timezone: {timezone_name!r}"
        ) from exc


def _extract_payload_day_list(payload: Any, provider_symbol: str) -> list[Any]:
    if not isinstance(payload, Mapping):
        raise GlobalDailyKError("Tencent payload must be a mapping")

    code = payload.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        raise GlobalDailyKError("Tencent payload code must be an integer")
    if code != 0:
        raise GlobalDailyKError(
            "Tencent payload code must be exactly zero"
        )

    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise GlobalDailyKError("Tencent payload must contain data mapping")

    symbol_section = data.get(provider_symbol)
    if symbol_section is None:
        raise GlobalDailyKError(
            f"Tencent payload missing symbol section: {provider_symbol}"
        )
    if not isinstance(symbol_section, Mapping):
        raise GlobalDailyKError(
            f"Tencent symbol section must be a mapping: {provider_symbol}"
        )

    day_field = symbol_section.get("day")
    if day_field is None:
        raise GlobalDailyKError(
            f"Tencent symbol section missing day list: {provider_symbol}"
        )
    if not isinstance(day_field, list):
        raise GlobalDailyKError(
            f"Tencent day list must be a list: {provider_symbol}"
        )
    return day_field


def _coalesce_duplicates(
    parsed_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge same-date rows that normalize to identical OHLC.

    Conflicting OHLC for the same normalized session date is an error —
    we never silently keep the first or last occurrence. Rows are returned
    sorted by date in ascending order.
    """

    merged: dict[Date, dict[str, Any]] = {}
    for parsed in parsed_rows:
        session = parsed["date"]
        existing = merged.get(session)
        if existing is None:
            merged[session] = parsed
            continue
        for field in ("open", "high", "low", "close"):
            if existing[field] != parsed[field]:
                raise GlobalDailyKError(
                    "conflicting OHLC for duplicate session date "
                    f"{session.isoformat()}"
                )
    return [merged[key] for key in sorted(merged)]


def _filter_window(
    rows: list[dict[str, Any]],
    *,
    start: Date,
    end: Date,
    cutoff_local: Date,
) -> list[dict[str, Any]]:
    """Apply the inclusive request window and the conservative same-day cut.

    ``cutoff_local`` is the local-date representation of ``now`` in the spec's
    timezone. Any row whose session date is ``>= cutoff_local`` is dropped so
    that callers do not see a possibly-incomplete current-local-day bar.
    """

    kept: list[dict[str, Any]] = []
    for parsed in rows:
        session = parsed["date"]
        if session < start or session > end:
            continue
        if session >= cutoff_local:
            continue
        kept.append(parsed)
    return kept


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def fetch_global_daily_k(
    index_id: str,
    start_date: str,
    end_date: str,
    *,
    transport: JSONTransport = requests_json_transport,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one V1-supported global-index daily-K series.

    Returns the standard :mod:`analysis.fetcher_contract` dict:

    * ``status`` is ``ok`` when the request, payload, and validation succeed,
      ``empty`` when the filtered result is empty, ``unsupported`` when the
      ``index_id`` is unknown, and ``error`` for any other failure.
    * ``data`` is a list of normalized records (or ``None`` on non-ok).
    * ``source`` is ``"tencent.daily_k"``, ``scope`` is ``"market"``.
    * ``units`` is ``{"price": "index_points", "volume": "unavailable"}``.
    * ``as_of`` is the latest returned session date, or ``None`` if empty.
    * ``fetched_at`` is the aware retrieval instant — never a data timestamp.

    Invalid input — including a naive ``now``, a non-callable transport, a bad
    date string, ``start > end``, or a window larger than 366 inclusive days
    — returns ``status=error`` with ``code=VALIDATION, retryable=False`` and
    never calls the transport.
    """

    # Step 1: validate inputs without touching the transport.
    try:
        _validate_inputs(index_id, start_date, end_date, transport, now)
    except (TypeError, ValueError) as exc:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_VALIDATION,
            str(exc),
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    # Step 2: resolve index_id -> spec via the V1 registry.
    try:
        spec: GlobalIndexSpec = get_global_index(index_id)
    except KeyError as exc:
        return fetcher_contract.make_unsupported(
            source=TENCENT_SOURCE,
            scope=TENCENT_SCOPE,
            reason=str(exc),
        )
    except (TypeError, ValueError) as exc:
        # Non-canonical (e.g. uppercase / empty / non-string) index_id is an
        # input-shape error, not an unsupported index.
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_VALIDATION,
            str(exc),
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    # Step 3: call the transport exactly once. Errors map to stable codes.
    params = {
        "param": f"{spec.provider_symbol},day,{start_date},{end_date},640,",
    }
    try:
        payload = transport(
            TENCENT_DAILY_K_URL,
            params=params,
            timeout=TENCENT_DAILY_K_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_TIMEOUT,
            "Tencent daily-K request timed out",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )
    except requests.exceptions.SSLError:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_SSL,
            "Tencent daily-K TLS error",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )
    except requests.exceptions.ConnectionError:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_CONN,
            "Tencent daily-K connection error",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )
    except requests.exceptions.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int) and 400 <= status < 500:
            if status == 429:
                return fetcher_contract.make_error_result(
                    fetcher_contract.ERR_NET_RATELIMIT,
                    "Tencent daily-K rate limited",
                    source=TENCENT_SOURCE,
                    retryable=True,
                    scope=TENCENT_SCOPE,
                )
            return fetcher_contract.make_error_result(
                fetcher_contract.ERR_NET_4XX,
                "Tencent daily-K client error",
                source=TENCENT_SOURCE,
                retryable=False,
                scope=TENCENT_SCOPE,
            )
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_5XX,
            "Tencent daily-K server error",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )
    except ValueError:
        # ``requests.exceptions.JSONDecodeError`` inherits from both
        # ``ValueError`` and ``requests.exceptions.RequestException``. It must be
        # classified as ``PARSE`` (non-retryable) before the catch-all request
        # handler runs; otherwise it would surface as ``UNKNOWN retryable=true``
        # and hide a real decode failure behind a transport retry.
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_PARSE,
            "Tencent daily-K response not valid JSON",
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )
    except requests.exceptions.RequestException:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            "Tencent daily-K request failed",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )
    except Exception:
        # Last-resort boundary guard for ordinary exceptions that escape the
        # injected transport (e.g. ``RuntimeError`` from a misbehaving test
        # double). ``KeyboardInterrupt`` and ``SystemExit`` derive from
        # ``BaseException`` and intentionally fall through. The message is
        # generic so we never leak credentials or provider internals here.
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            "Tencent daily-K transport raised an unexpected error",
            source=TENCENT_SOURCE,
            retryable=True,
            scope=TENCENT_SCOPE,
        )

    # Step 4: extract the day list and validate rows.
    try:
        day_rows = _extract_payload_day_list(payload, spec.provider_symbol)
    except GlobalDailyKError:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_PARSE,
            "Tencent daily-K payload structure invalid",
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    parsed_rows: list[dict[str, Any]] = []
    for row in day_rows:
        try:
            parsed_rows.append(
                _parse_row(row, provider_symbol=spec.provider_symbol)
            )
        except ValueError as exc:
            return fetcher_contract.make_error_result(
                fetcher_contract.ERR_PARSE,
                str(exc),
                source=TENCENT_SOURCE,
                retryable=False,
                scope=TENCENT_SCOPE,
            )

    try:
        coalesced = _coalesce_duplicates(parsed_rows)
    except GlobalDailyKError as exc:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_PARSE,
            str(exc),
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    # Step 5: filter to the inclusive window and conservative same-day cut.
    try:
        local_zone = _resolve_tz(spec.timezone)
    except GlobalDailyKError as exc:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            str(exc),
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    now_aware = _normalize_now(now)
    cutoff_local = now_aware.astimezone(local_zone).date()
    # Input dates were already strict-YYYY-MM-DD gated in _validate_inputs, so
    # this re-parse only guards against the (impossible here) ValueError surface
    # of Date.fromisoformat on the strict form.
    try:
        start_d = _parse_strict_date(start_date, field="start_date")
        end_d = _parse_strict_date(end_date, field="end_date")
    except ValueError as exc:
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_VALIDATION,
            str(exc),
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )

    kept = _filter_window(
        coalesced,
        start=start_d,
        end=end_d,
        cutoff_local=cutoff_local,
    )

    # Step 6: build output records and the standard envelope.
    records: list[dict[str, Any]] = []
    for parsed in kept:
        records.append(
            {
                "index_id": spec.identity.index_id,
                "market": spec.market,
                "symbol": spec.identity.local_code,
                "name": spec.name,
                "date": parsed["date"].isoformat(),
                "open": parsed["open"],
                "high": parsed["high"],
                "low": parsed["low"],
                "close": parsed["close"],
                "volume": None,
                "currency": spec.currency,
                "timezone": spec.timezone,
                "source": TENCENT_SOURCE,
            }
        )

    as_of = records[-1]["date"] if records else None
    units = {"price": "index_points", "volume": "unavailable"}
    if records:
        return fetcher_contract.make_ok(
            records,
            source=TENCENT_SOURCE,
            as_of=as_of,
            scope=TENCENT_SCOPE,
            units=units,
        )
    return fetcher_contract.make_empty(
        source=TENCENT_SOURCE,
        as_of=None,
        scope=TENCENT_SCOPE,
        reason="no daily-K rows in window",
    )


# ---------------------------------------------------------------------------
# Re-exports for tests and downstream lookups (kept narrow on purpose).
# ---------------------------------------------------------------------------

__all__ = [
    "fetch_global_daily_k",
    "requests_json_transport",
    "build_global_index_symbol_registry",
    "GlobalDailyKError",
    "TENCENT_DAILY_K_URL",
    "TENCENT_DAILY_K_TIMEOUT",
    "TENCENT_PROVIDER_ID",
    "TENCENT_SCOPE",
    "TENCENT_SOURCE",
]
