"""Pure normalized-comparison computation for the V2.1 cross-market workbench.

This module owns the *math* and the *evidence bookkeeping* of the
"市场比较" feature and nothing else.  It is a pure function library: no
provider call, no HTTP, no UI, no file access, no global state.

Why normalization exists
------------------------
Index levels of different markets are not comparable in absolute terms.
"上证指数 3000 点" and "S&P 500 6000 点" carry no shared unit, so the
comparison uses a common base of 100 on the earliest common valid trading
day inside the requested range:

    normalized100      = close / base_close * 100
    cumulative_return_pct = (close / base_close - 1) * 100

The base close is per series (each index has its own point value) but the
base *date* is shared by every compared series.

Public API
----------
:func:`build_comparison`
    Build the whole comparison payload from per-index daily-bar payloads.
:func:`normalize_close_series`
    Pure per-series normalization helper (base-100 + cumulative percent).

Contract of :func:`build_comparison`
------------------------------------
``build_comparison(payloads, start_date=None, end_date=None) -> dict``

``payloads``
    A sequence of 2~4 per-index mappings.  Each mapping accepts:

    ``index_id`` (required)
        Canonical index id, or a known historical alias.  Normalized through
        the existing identity layer
        (:func:`analysis.research.index_registry.canonical_index_id`) and
        validated against the frozen V1 registry
        (:func:`analysis.research.global_indices.get_global_index`).  Display
        name and market always come from that registry, never from the
        payload.
    ``bars`` / ``data`` (one of them)
        Sequence of daily-bar mappings, each with a strict ``date``
        (``YYYY-MM-DD``) and a numeric ``close``.
    ``status`` (optional)
        ``"ok"`` (default) or any other fetcher status such as ``"error"`` /
        ``"empty"`` / ``"unsupported"`` — a non-ok status excludes that index
        with an individual reason.
    ``error`` (optional)
        Extra failure detail (string or mapping) attached to the exclusion.
    ``source`` (optional)
        Data source label echoed back for the legend / data-provenance UI.

``start_date`` / ``end_date``
    Optional inclusive bounds, strict ``YYYY-MM-DD``.  Rows outside the range
    are dropped before any aggregation happens.

Returned mapping (JSON serializable, plain ``dict`` / ``list`` / scalar only):

``status``
    ``"ok"`` when a comparison was produced, ``"error"`` otherwise.
``error``
    ``None`` on success, otherwise ``{"code": ..., "message": ...}``.
``product``
    Always ``"Swartea Market Research"``.
``base_date`` / ``base_value``
    The shared base date and the base level (always ``100.0``).
``dates``
    Sorted union of every compared series' valid dates.  This is the shared
    time axis; a date that one series lacks stays a *gap* on that series.
``series``
    One entry per compared index::

        {
          "index_id": "cn.index.csi300",
          "name": "沪深300",
          "market": "cn",
          "source": "tencent.daily_k",
          "base_close": 4100.0,
          "first_date": "2026-01-05",
          "last_date": "2026-01-09",
          "data_points": 3,
          "close": [4100.0, 4150.0, None],          # aligned with "dates"
          "normalized100": [100.0, 101.219512, None],
          "cumulative_return_pct": [0.0, 1.219512, None],
          "issues": [{"code": "duplicate_date", "count": 1, "detail": "..."}],
        }

    The three value lists are aligned to ``dates``; ``None`` marks a date the
    series does not have (a gap, never an interpolated or forward-filled
    value).
``excluded``
    One entry per index that could not take part, each with an individual
    ``reason``::

        {"index_id": ..., "name": ..., "reason": ..., "detail": ...}

    Reason codes: ``invalid_payload``, ``unknown_index``,
    ``invalid_index_id``, ``duplicate_index``, ``index_unavailable``,
    ``no_bars``, ``no_valid_rows``, ``insufficient_dates``,
    ``no_common_base``.
``notes``
    Human-readable limitation statements shown next to the chart.
``calendar_status``
    Always ``"unknown"`` — this module has no trading-calendar evidence and
    never infers one from a local clock.

Top-level error codes: ``invalid_request``, ``too_few_indices``,
``too_many_indices``, ``insufficient_usable_indices``, ``no_common_base``.

Deterministic rules
-------------------
* **Identity.** Payload ids are normalized through the existing alias map and
  validated against the V1 registry.  Two payloads that resolve to the same
  canonical id are deduplicated: the first one wins, the later one is
  reported as ``duplicate_index``.  No parallel registry is created.
* **Rows.** Only strict ``YYYY-MM-DD`` dates and finite positive numeric
  closes are usable.  A row with a bad date or a bad close is counted as an
  invalid row and never becomes a data point.  A date whose close is
  non-finite, zero or negative is a gap for that series, never a zero value.
* **Duplicates.** When one series carries the same date more than once, the
  duplicated date is excluded entirely (both rows are dropped) instead of
  picking an arbitrary winner.  The remaining dates stay usable.
* **Ordering.** Input order never matters: rows are sorted by date, and the
  union axis is sorted ascending.
* **Base selection.** Every usable selected series must share a valid date.
  The earliest such date is the base. No common date means no comparison;
  series are never silently dropped to manufacture a shared base.
* **Minimum history.** A series needs at least two valid dates to take part;
  a single-day series is explicitly reported as ``insufficient_dates``.
* **No fabrication.** Nothing is interpolated, forward-filled, carried over
  from a previous close, or invented for a missing session.  A missing date
  is a missing date.

Known limitations (surfaced in ``notes``)
-----------------------------------------
* Each series keeps its **own local trading dates**.  Different markets
  trade on different local calendars, so the shared date axis is a *calendar
  axis*, not a synchronous realtime timeline.
* The curves are **price returns**, not total returns: dividends and other
  distributions are not added back.
* The curves are **not FX adjusted**: a CNY index and a USD index are
  compared as local index points rebased to 100, not as converted returns.
* ``calendar_status`` stays ``"unknown"`` unless a caller with real
  calendar evidence renders its own state elsewhere.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any

from analysis.fetcher_contract import STATUS_ERROR, STATUS_OK

from .global_indices import get_global_index
from .index_registry import canonical_index_id

COMPARISON_PRODUCT_NAME = "Swartea Market Research"
MIN_COMPARISON_INDICES = 2
MAX_COMPARISON_INDICES = 4
BASE_VALUE = 100.0

# Strict YYYY-MM-DD gate. ``date.fromisoformat`` on Python 3.11+ also accepts
# the compact ``YYYYMMDD`` and ISO week-date forms; both are rejected here.
_STRICT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Rounding applied to every emitted float so the JSON payload stays compact
# and stable across platforms.
_ROUND_DIGITS = 6

# Limitation statements shown next to the comparison chart.
COMPARISON_NOTES: tuple[str, ...] = (
    "各指数使用各自市场的本地交易日期，跨市场日期轴只表示日历对齐，不代表同一时间点的同步行情。",
    "曲线为收盘价价格收益率，不含分红派息等总回报成分，也未做汇率调整。",
    "缺失日期不做插值、前向填充或结转，缺口即为该市场当日无有效收盘数据。",
    "本模块只使用调用方提供的历史日线收盘价，不请求任何行情源，也不生成实时价格。",
    "未提供交易日历证据，交易日历状态保持 unknown，不按本地时钟推断开闭市。",
)


@dataclass(frozen=True)
class _NormalizedSeries:
    """One index reduced to a canonical id plus its usable daily closes."""

    index_id: str
    name: str
    market: str
    source: str | None
    closes: dict[str, float] = field(default_factory=dict)
    issues: tuple[dict[str, Any], ...] = ()


# ---------------------------------------------------------------------------
# Low-level validation helpers
# ---------------------------------------------------------------------------


def _parse_strict_date(value: Any, *, field_name: str) -> Date:
    """Parse one strict ``YYYY-MM-DD`` string into a :class:`datetime.date`."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not _STRICT_DATE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must use the strict YYYY-MM-DD form")
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a real calendar date") from exc


def _coerce_close(value: Any) -> float | None:
    """Return a finite positive float for ``value`` or ``None`` when unusable.

    ``bool`` is rejected on purpose: ``True`` is not a price.  Numeric strings
    are rejected as well so that a malformed provider row cannot silently
    become a data point.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _round(value: float | None) -> float | None:
    """Round one float to the payload precision, keeping ``None`` as ``None``."""

    if value is None:
        return None
    return round(value, _ROUND_DIGITS)


def _error_detail(value: Any) -> str | None:
    """Extract a short human-readable detail from a payload ``error`` field."""

    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, Mapping):
        for key in ("message", "detail", "reason", "code"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _issue(code: str, count: int, detail: str) -> dict[str, Any]:
    """Build one compact per-series issue record."""

    return {"code": code, "count": count, "detail": detail}


# ---------------------------------------------------------------------------
# Public pure helper
# ---------------------------------------------------------------------------


def normalize_close_series(
    closes: Mapping[str, float],
    base_date: str,
    *,
    axis: Sequence[str] | None = None,
) -> dict[str, list[float | None]]:
    """Normalize one series against a shared base date.

    ``closes`` maps strict ``YYYY-MM-DD`` dates to finite positive closes.
    ``base_date`` must exist in ``closes`` and hold a finite positive close.
    ``axis`` defines the output alignment; it defaults to the sorted dates of
    ``closes``.  Dates that are absent from ``closes`` yield ``None`` — a
    gap, never an interpolated value.

    Returns ``{"close": [...], "normalized100": [...],
    "cumulative_return_pct": [...]}``, all aligned with the axis.
    """

    if not isinstance(closes, Mapping):
        raise TypeError("closes must be a mapping")
    base_close = _coerce_close(closes.get(base_date))
    if base_close is None:
        raise ValueError("base_date must map to a finite positive close")

    dates = list(axis) if axis is not None else sorted(closes)
    close_values: list[float | None] = []
    normalized: list[float | None] = []
    percent: list[float | None] = []

    for day in dates:
        close = _coerce_close(closes.get(day))
        close_values.append(_round(close))
        if close is None:
            normalized.append(None)
            percent.append(None)
            continue
        ratio = close / base_close
        if not math.isfinite(ratio):
            normalized.append(None)
            percent.append(None)
            continue
        level = ratio * BASE_VALUE
        normalized.append(_round(level) if math.isfinite(level) else None)
        cumulative = (ratio - 1.0) * 100.0
        percent.append(_round(cumulative) if math.isfinite(cumulative) else None)

    return {
        "close": close_values,
        "normalized100": normalized,
        "cumulative_return_pct": percent,
    }


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------


def _resolve_index(payload: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
    """Resolve the canonical id, display name and market of one payload.

    Returns ``(index_id, name, market, source)``.  Raises ``ValueError`` with
    a stable reason code embedded in the message for unknown or
    non-canonical ids.
    """

    raw_id = payload.get("index_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError("invalid_index_id|payload.index_id must be a non-empty string")

    canonical = canonical_index_id(raw_id.strip())
    try:
        spec = get_global_index(canonical)
    except KeyError as exc:
        raise ValueError(f"unknown_index|unknown index id: {raw_id.strip()!r}") from exc
    except ValueError as exc:
        raise ValueError(
            f"invalid_index_id|index id must use the canonical lowercase form: {raw_id.strip()!r}"
        ) from exc

    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        source = None
    return spec.identity.index_id, spec.name, spec.market, source


def _extract_rows(payload: Mapping[str, Any]) -> Any:
    """Return the raw bar sequence of one payload (``bars`` or ``data``)."""

    rows = payload.get("bars")
    if rows is None:
        rows = payload.get("data")
    return rows


def _normalize_payload(
    payload: Any,
    *,
    start: Date | None,
    end: Date | None,
) -> tuple[_NormalizedSeries | None, dict[str, Any] | None]:
    """Reduce one payload to a usable series or to an exclusion record."""

    if not isinstance(payload, Mapping):
        return None, {
            "index_id": None,
            "name": None,
            "reason": "invalid_payload",
            "detail": "payload must be a mapping",
        }

    try:
        index_id, name, market, source = _resolve_index(payload)
    except ValueError as exc:
        raw_id = payload.get("index_id")
        reason, _, detail = str(exc).partition("|")
        return None, {
            "index_id": raw_id if isinstance(raw_id, str) else None,
            "name": None,
            "reason": reason or "invalid_payload",
            "detail": detail or None,
        }

    status = payload.get("status")
    if status is not None:
        if not isinstance(status, str):
            return None, {
                "index_id": index_id,
                "name": name,
                "reason": "invalid_payload",
                "detail": "payload.status must be a string",
            }
        if status.strip().lower() != STATUS_OK:
            detail = _error_detail(payload.get("error"))
            if detail is None:
                detail = f"index payload status is {status!r}"
            return None, {
                "index_id": index_id,
                "name": name,
                "reason": "index_unavailable",
                "detail": detail,
            }

    rows = _extract_rows(payload)
    if rows is None:
        return None, {
            "index_id": index_id,
            "name": name,
            "reason": "no_bars",
            "detail": "payload carries neither bars nor data",
        }
    if isinstance(rows, (str, bytes, Mapping)) or not isinstance(rows, Sequence):
        return None, {
            "index_id": index_id,
            "name": name,
            "reason": "invalid_payload",
            "detail": "bars must be a sequence of row mappings",
        }
    if not rows:
        return None, {
            "index_id": index_id,
            "name": name,
            "reason": "no_bars",
            "detail": "payload carries no daily bars",
        }

    # date -> list of close values seen for that date (None == malformed close)
    per_date: dict[str, list[float | None]] = {}
    invalid_rows = 0
    for row in rows:
        if not isinstance(row, Mapping):
            invalid_rows += 1
            continue
        raw_date = row.get("date")
        try:
            parsed = _parse_strict_date(raw_date, field_name="row date")
        except (TypeError, ValueError):
            invalid_rows += 1
            continue
        if start is not None and parsed < start:
            continue
        if end is not None and parsed > end:
            continue
        close = _coerce_close(row.get("close"))
        per_date.setdefault(raw_date, []).append(close)

    closes: dict[str, float] = {}
    duplicate_dates: list[str] = []
    invalid_close_dates: list[str] = []
    for day in sorted(per_date):
        values = per_date[day]
        if len(values) > 1:
            duplicate_dates.append(day)
            continue
        single = values[0]
        if single is None:
            invalid_close_dates.append(day)
            continue
        closes[day] = single

    issues: list[dict[str, Any]] = []
    if invalid_rows:
        issues.append(
            _issue(
                "invalid_row",
                invalid_rows,
                "rows with a malformed date or a non-numeric close were dropped",
            )
        )
    if duplicate_dates:
        issues.append(
            _issue(
                "duplicate_date",
                len(duplicate_dates),
                "duplicated dates were excluded entirely instead of picking a winner: "
                + ", ".join(duplicate_dates),
            )
        )
    if invalid_close_dates:
        issues.append(
            _issue(
                "invalid_close",
                len(invalid_close_dates),
                "dates with a non-finite or non-positive close were dropped: "
                + ", ".join(invalid_close_dates),
            )
        )

    if not closes:
        reason = "no_valid_rows" if per_date or invalid_rows else "no_bars"
        return None, {
            "index_id": index_id,
            "name": name,
            "reason": reason,
            "detail": "no usable daily close inside the requested range",
        }
    if len(closes) < 2:
        return None, {
            "index_id": index_id,
            "name": name,
            "reason": "insufficient_dates",
            "detail": (
                f"at least 2 valid dates are required for a meaningful comparison, got {len(closes)}"
            ),
        }

    return (
        _NormalizedSeries(
            index_id=index_id,
            name=name,
            market=market,
            source=source,
            closes=closes,
            issues=tuple(issues),
        ),
        None,
    )


def _normalize_payloads(
    payloads: Sequence[Any],
    *,
    start: Date | None,
    end: Date | None,
) -> tuple[list[_NormalizedSeries], list[dict[str, Any]]]:
    """Normalize every payload, applying canonical dedup in input order."""

    series: list[_NormalizedSeries] = []
    excluded: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for payload in payloads:
        normalized, exclusion = _normalize_payload(payload, start=start, end=end)
        if normalized is None:
            if exclusion is not None:
                excluded.append(exclusion)
            continue
        if normalized.index_id in seen:
            excluded.append(
                {
                    "index_id": normalized.index_id,
                    "name": normalized.name,
                    "reason": "duplicate_index",
                    "detail": (
                        f"same canonical index as an earlier selection ({normalized.index_id})"
                    ),
                }
            )
            continue
        seen[normalized.index_id] = normalized.name
        series.append(normalized)

    return series, excluded


# ---------------------------------------------------------------------------
# Request validation and result assembly
# ---------------------------------------------------------------------------


def _validate_request(
    payloads: Any,
    start_date: Any,
    end_date: Any,
) -> tuple[Date | None, Date | None, dict[str, Any] | None]:
    """Validate the request shape and the optional inclusive date bounds."""

    if isinstance(payloads, (str, bytes, Mapping)) or not isinstance(payloads, Sequence):
        return None, None, {
            "code": "invalid_request",
            "message": "payloads must be a sequence of per-index payloads",
        }
    if len(payloads) < MIN_COMPARISON_INDICES:
        return None, None, {
            "code": "too_few_indices",
            "message": (
                f"a comparison needs at least {MIN_COMPARISON_INDICES} indices, "
                f"got {len(payloads)}"
            ),
        }
    if len(payloads) > MAX_COMPARISON_INDICES:
        return None, None, {
            "code": "too_many_indices",
            "message": (
                f"a comparison supports at most {MAX_COMPARISON_INDICES} indices, "
                f"got {len(payloads)}"
            ),
        }

    start: Date | None = None
    end: Date | None = None
    for value, field_name in ((start_date, "start_date"), (end_date, "end_date")):
        if value is None:
            continue
        try:
            parsed = _parse_strict_date(value, field_name=field_name)
        except (TypeError, ValueError):
            return None, None, {
                "code": "invalid_request",
                "message": f"{field_name} must use the strict YYYY-MM-DD form",
            }
        if field_name == "start_date":
            start = parsed
        else:
            end = parsed

    if start is not None and end is not None and start > end:
        return None, None, {
            "code": "invalid_request",
            "message": "start_date must not be later than end_date",
        }

    return start, end, None


def _base_result(
    *,
    status: str,
    error: dict[str, Any] | None,
    base_date: str | None,
    base_value: float | None,
    dates: list[str],
    series: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the stable, JSON-serializable comparison envelope."""

    return {
        "product": COMPARISON_PRODUCT_NAME,
        "status": status,
        "error": error,
        "base_date": base_date,
        "base_value": base_value,
        "dates": dates,
        "series": series,
        "excluded": excluded,
        "notes": list(COMPARISON_NOTES),
        "calendar_status": "unknown",
    }


def build_comparison(
    payloads: Sequence[Mapping[str, Any]],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Build a normalized cross-market index comparison.

    See the module docstring for the full payload contract.  The function is
    pure: it never calls a provider, never touches the network, and always
    returns a JSON-serializable mapping.
    """

    start, end, request_error = _validate_request(payloads, start_date, end_date)
    if request_error is not None:
        return _base_result(
            status=STATUS_ERROR,
            error=request_error,
            base_date=None,
            base_value=None,
            dates=[],
            series=[],
            excluded=[],
        )

    series, excluded = _normalize_payloads(payloads, start=start, end=end)
    if len(series) < MIN_COMPARISON_INDICES:
        return _base_result(
            status=STATUS_ERROR,
            error={
                "code": "insufficient_usable_indices",
                "message": (
                    f"at least {MIN_COMPARISON_INDICES} usable indices are required, "
                    f"got {len(series)}"
                ),
            },
            base_date=None,
            base_value=None,
            dates=[],
            series=[],
            excluded=excluded,
        )

    common = set.intersection(*(set(item.closes) for item in series))
    if not common:
        return _base_result(
            status=STATUS_ERROR,
            error={"code": "no_common_base", "message": "所选指数在区间内没有共同有效基准日，请调整区间或移除指数。"},
            base_date=None, base_value=None, dates=[], series=[],
            excluded=excluded + [
                {"index_id": item.index_id, "name": item.name, "reason": "no_common_base",
                 "detail": f"own range {min(item.closes)}..{max(item.closes)}"}
                for item in series
            ],
        )
    base_date = min(common)
    compared = series

    axis = sorted({day for item in compared for day in item.closes})
    out_series: list[dict[str, Any]] = []
    for item in compared:
        values = normalize_close_series(item.closes, base_date, axis=axis)
        out_series.append(
            {
                "index_id": item.index_id,
                "name": item.name,
                "market": item.market,
                "source": item.source,
                "base_close": _round(item.closes[base_date]),
                "first_date": min(item.closes),
                "last_date": max(item.closes),
                "data_points": len(item.closes),
                "close": values["close"],
                "normalized100": values["normalized100"],
                "cumulative_return_pct": values["cumulative_return_pct"],
                "issues": [dict(issue) for issue in item.issues],
            }
        )

    return _base_result(
        status=STATUS_OK,
        error=None,
        base_date=base_date,
        base_value=BASE_VALUE,
        dates=axis,
        series=out_series,
        excluded=excluded,
    )
