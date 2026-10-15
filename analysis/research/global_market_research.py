"""Global-index daily-K research composition over the existing research services.

This module is the single research-service endpoint the local research page
browses. It reuses, and never redefines:

* :func:`analysis.research.global_indices.list_global_indices` — the one
  canonical registry of global indices (market, name, currency, timezone and
  the **exact** provider symbol);
* :class:`analysis.research.index_registry.IndexIdentity` — canonical identity;
* :func:`analysis.research.global_daily_k_service.fetch_global_daily_k_service`
  — the bounded (existing request timeout, **no retry**) Daily-K fetch with
  ordered provider fallback;
* :func:`analysis.research.market_snapshot_service.build_market_snapshot` — the
  existing Snapshot Service, used for the evidence-backed
  :class:`~analysis.research.market_state.MarketIndexObservation`
  (:class:`~analysis.research.market_availability.MarketAvailability` aware).

Scope boundaries kept on purpose:

* **No new registry.** Market/index selectors are derived from
  ``list_global_indices()``; a second symbol vocabulary would be a contract
  fork.
* **No hardcoded market data.** Prices only ever come from a provider result.
  Nothing here synthesizes bars, and no HK/US bar is invented.
* **Provider evidence is identity-specific.** Only identities in the explicit
  proven set are queried; adding a registry entry alone cannot create
  availability. Unproven identities resolve to ``unavailable`` without a
  provider call.
* **No guessed clock.** The payload carries the index timezone, the data date
  and an ``unknown`` trading-day status: absent exchange-calendar evidence
  stays unknown rather than being inferred from a date.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from analysis import fetcher_contract
from analysis.research.freshness import MaxAgePolicy
from analysis.research.global_daily_k_service import (
    DailyKProvider,
    fetch_global_daily_k_service,
)
from analysis.research.global_indices import (
    GlobalIndexSpec,
    get_global_index,
    list_global_indices,
)
from analysis.research.market_availability import MarketAvailability
from analysis.research.market_index_universe import MarketIndexUniverse
from analysis.research.market_snapshot_service import build_market_snapshot
from analysis.research.market_state import MarketIndexObservation
from analysis.research.trading_calendar import TradingCalendar

# Exact registered identities with validated daily-K provider evidence. A
# registry entry alone must not make an index appear available. HK/US entries
# were independently probed against Tencent on 2026-10-15 with bounded,
# single-attempt requests and valid normalized rows.
PROVEN_INDEX_IDS: frozenset[str] = frozenset(
    {
        "cn.index.sh_comp",
        "cn.index.sz_component",
        "cn.index.chinext",
        "cn.index.csi300",
        "hk.index.hang_seng.hsi",
        "hk.index.hang_seng.hstech",
        "us.index.sp_dji.sp500",
        "us.index.nasdaq.composite",
        "us.index.sp_dji.djia",
    }
)

# Payload status values. Deliberately small and stable for the view layer.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"

# No exchange-calendar evidence is attached to these series, so the trading
# day status stays explicitly unknown instead of being inferred.
TRADING_DAY_STATUS_UNKNOWN = "unknown"

_UNPROVEN_REASON = (
    "no verified daily-K provider evidence for this index; bars are not "
    "fabricated and availability stays unproven"
)
_EMPTY_REASON = "provider returned no daily bars for the requested window"
_UNAVAILABLE_REASON = "no daily-K data available for the requested window"


@dataclass(frozen=True)
class GlobalBar:
    """One normalized daily bar, or the reason it could not be normalized."""

    date: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    rejected_reason: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.rejected_reason is None and self.close is not None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }
        # Volume is emitted only when the provider actually supplied one.
        if self.volume is not None:
            payload["volume"] = self.volume
        return payload


@dataclass(frozen=True)
class GlobalMarketResearch:
    """View-ready payload for one global index daily-K research request."""

    index_id: str
    market: str
    name: str
    currency: str
    timezone: str
    provider_symbol: str
    publisher: str
    local_code: str
    status: str
    availability: MarketAvailability
    freshness: str
    data_date: str | None = None
    source: str | None = None
    provider_status: str | None = None
    degraded: bool = False
    failure_reason: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    evaluated_at: str | None = None
    trading_day_status: str = TRADING_DAY_STATUS_UNKNOWN
    units: Mapping[str, str] = field(
        default_factory=lambda: {"price": "index_points", "volume": "unavailable"}
    )
    bars: tuple[GlobalBar, ...] = ()
    unavailable_reason: str | None = None

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for the page's single endpoint."""

        return {
            "index_id": self.index_id,
            "market": self.market,
            "name": self.name,
            "currency": self.currency,
            "timezone": self.timezone,
            "provider_symbol": self.provider_symbol,
            "publisher": self.publisher,
            "local_code": self.local_code,
            "status": self.status,
            "availability": self.availability.value,
            "freshness": self.freshness,
            "data_date": self.data_date,
            "source": self.source,
            "provider_status": self.provider_status,
            "degraded": self.degraded,
            "failure_reason": self.failure_reason,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "evaluated_at": self.evaluated_at,
            "trading_day_status": self.trading_day_status,
            "units": dict(self.units),
            "bar_count": self.bar_count,
            "bars": [bar.as_dict() for bar in self.bars],
            "unavailable_reason": self.unavailable_reason,
        }


def list_research_markets() -> tuple[str, ...]:
    """Return market tokens present in the canonical global-index registry."""

    seen: list[str] = []
    for spec in list_global_indices():
        if spec.market not in seen:
            seen.append(spec.market)
    return tuple(seen)


def list_market_indices(market: str) -> tuple[GlobalIndexSpec, ...]:
    """Return registry specs for ``market`` in registration order."""

    if not isinstance(market, str) or not market.strip():
        raise ValueError("market must be a non-empty string")
    token = market.strip().lower()
    return tuple(spec for spec in list_global_indices() if spec.market == token)


def list_index_choices() -> tuple[dict[str, str], ...]:
    """Return the selector options the page renders, derived from the registry."""

    return tuple(
        {
            "index_id": spec.identity.index_id,
            "market": spec.market,
            "name": spec.name,
            "currency": spec.currency,
            "timezone": spec.timezone,
            "proven": "yes" if spec.identity.index_id in PROVEN_INDEX_IDS else "no",
        }
        for spec in list_global_indices()
    )


def market_is_proven(market: str) -> bool:
    """Return whether ``market`` has proven daily-K provider evidence."""
    specs = list_market_indices(market)
    return bool(specs) and all(spec.identity.index_id in PROVEN_INDEX_IDS for spec in specs)


def resolve_index(index_id: Any) -> GlobalIndexSpec:
    """Resolve ``index_id`` through the canonical registry only.

    Re-raises the registry's own distinction so callers can tell a malformed
    canonical id (bad casing) from an unknown symbol.
    """

    return get_global_index(index_id)


def _canonical_day(value: Any, *, label: str) -> str | None:
    """Return canonical ``YYYY-MM-DD`` for ``value`` or ``None`` when invalid."""

    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def _finite_positive(value: Any) -> float | None:
    """Return ``value`` as a finite positive float, else ``None``."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _finite_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def normalize_daily_rows(rows: Any) -> tuple[tuple[GlobalBar, ...], int]:
    """Normalize provider rows into usable bars plus a malformed-row count.

    Defensive by construction: a malformed provider row degrades into a counted
    rejection instead of raising into the page.
    """

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return (), 0
    bars: list[GlobalBar] = []
    rejected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        day = _canonical_day(row.get("date"), label="date")
        if day is None:
            rejected += 1
            continue
        open_px = _finite_positive(row.get("open"))
        high_px = _finite_positive(row.get("high"))
        low_px = _finite_positive(row.get("low"))
        close_px = _finite_positive(row.get("close"))
        if None in (open_px, high_px, low_px, close_px):
            rejected += 1
            continue
        assert open_px is not None and high_px is not None  # narrowed above
        assert low_px is not None and close_px is not None
        if low_px > high_px or low_px > open_px or low_px > close_px:
            rejected += 1
            continue
        if high_px < open_px or high_px < close_px:
            rejected += 1
            continue
        raw_volume = row.get("volume")
        if raw_volume is not None and _finite_nonnegative(raw_volume) is None:
            rejected += 1
            continue
        bars.append(
            GlobalBar(
                date=day,
                open=open_px,
                high=high_px,
                low=low_px,
                close=close_px,
                volume=_finite_nonnegative(raw_volume) if raw_volume is not None else None,
            )
        )
    bars.sort(key=lambda bar: str(bar.date))
    deduped: list[GlobalBar] = []
    index = 0
    while index < len(bars):
        next_index = index + 1
        while next_index < len(bars) and bars[next_index].date == bars[index].date:
            next_index += 1
        if next_index == index + 1:
            deduped.append(bars[index])
        else:
            rejected += next_index - index
        index = next_index
    return tuple(deduped), rejected


def _observation_lookup(
    snapshot: Any, index_id: str
) -> MarketIndexObservation | None:
    """Return the observation for ``index_id`` from an existing snapshot."""

    if snapshot is None:
        return None
    observations = getattr(snapshot, "observations", ())
    for observation in observations or ():
        identity = getattr(observation, "identity", None)
        if identity is not None and identity.index_id == index_id:
            return observation
    return None


def _default_snapshot_builder(
    *,
    index_id: str,
    evaluation_time: str,
    start_date: str,
    end_date: str,
    calendar: Any,
    max_age_policy: Any,
    providers: Sequence[DailyKProvider] | None,
    transport: Any,
    universe: MarketIndexUniverse,
    daily_k_results: Mapping[str, Mapping[str, Any]],
) -> Any:
    """Call the shared Snapshot Service using the already fetched bars."""

    return build_market_snapshot(
        evaluation_time=evaluation_time,
        start_date=start_date,
        end_date=end_date,
        calendar=calendar,
        max_age_policy=max_age_policy,
        providers=providers,
        transport=transport,
        universe=universe,
        daily_k_results=daily_k_results,
    )


def _error_payload(
    spec: GlobalIndexSpec,
    *,
    start_date: str | None,
    end_date: str | None,
    failure_reason: str,
    evaluated_at: str | None = None,
) -> GlobalMarketResearch:
    return GlobalMarketResearch(
        index_id=spec.identity.index_id,
        market=spec.market,
        name=spec.name,
        currency=spec.currency,
        timezone=spec.timezone,
        provider_symbol=spec.provider_symbol,
        publisher=str(spec.identity.publisher.value)
        if hasattr(spec.identity.publisher, "value")
        else str(spec.identity.publisher),
        local_code=spec.identity.local_code,
        status=STATUS_ERROR,
        availability=MarketAvailability.UNKNOWN,
        freshness="unknown",
        failure_reason=failure_reason,
        start_date=start_date,
        end_date=end_date,
        evaluated_at=evaluated_at,
    )


def build_global_market_research(
    index_id: str,
    start_date: str,
    end_date: str,
    *,
    evaluation_time: str | None = None,
    calendar: Any = None,
    max_age_policy: Any = None,
    providers: Sequence[DailyKProvider] | None = None,
    transport: Any = None,
    snapshot_builder: Any = _default_snapshot_builder,
    now: datetime | None = None,
) -> GlobalMarketResearch:
    """Compose normalized daily bars plus an evidence-backed observation.

    Ordering is deliberate: the window is validated *before* any provider or
    snapshot call, unproven indexes short-circuit to ``unavailable`` without a
    provider call, and every downstream failure degrades into an explicit
    status rather than an exception.
    """

    try:
        spec = resolve_index(index_id)
    except TypeError as exc:
        raise TypeError("index_id must be a string") from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    except KeyError as exc:
        raise KeyError(str(exc)) from exc

    canonical_start = _canonical_day(start_date, label="start_date")
    canonical_end = _canonical_day(end_date, label="end_date")
    if canonical_start is None:
        return _error_payload(
            spec,
            start_date=None,
            end_date=canonical_end,
            failure_reason="VALIDATION: start_date must be a canonical YYYY-MM-DD day",
        )
    if canonical_end is None:
        return _error_payload(
            spec,
            start_date=canonical_start,
            end_date=None,
            failure_reason="VALIDATION: end_date must be a canonical YYYY-MM-DD day",
        )
    if canonical_start > canonical_end:
        return _error_payload(
            spec,
            start_date=canonical_start,
            end_date=canonical_end,
            failure_reason="VALIDATION: start_date must not be after end_date",
        )

    try:
        evaluation = now or datetime.now(timezone.utc)
        if evaluation_time is not None:
            raw_evaluation = evaluation_time[:-1] + "+00:00" if evaluation_time.endswith("Z") else evaluation_time
            evaluation = datetime.fromisoformat(raw_evaluation)
        if evaluation.tzinfo is None or evaluation.utcoffset() is None:
            raise ValueError("evaluation_time must include a timezone")
        evaluated_at = evaluation.isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        return _error_payload(
            spec,
            start_date=canonical_start,
            end_date=canonical_end,
            failure_reason=f"VALIDATION: invalid evaluation_time ({exc})",
        )

    if spec.identity.index_id not in PROVEN_INDEX_IDS:
        # No provider call: an unproven index must not reach the provider and
        # must never be backfilled with invented bars.
        return GlobalMarketResearch(
            index_id=spec.identity.index_id,
            market=spec.market,
            name=spec.name,
            currency=spec.currency,
            timezone=spec.timezone,
            provider_symbol=spec.provider_symbol,
            publisher=str(spec.identity.publisher.value)
            if hasattr(spec.identity.publisher, "value")
            else str(spec.identity.publisher),
            local_code=spec.identity.local_code,
            status=STATUS_UNAVAILABLE,
            availability=MarketAvailability.UNAVAILABLE,
            freshness="unknown",
            start_date=canonical_start,
            end_date=canonical_end,
            evaluated_at=evaluated_at,
            unavailable_reason=_UNPROVEN_REASON,
        )

    try:
        envelope = fetch_global_daily_k_service(
            spec.identity.index_id,
            canonical_start,
            canonical_end,
            providers=providers,
            transport=transport,
            now=evaluation,
        )
    except Exception as exc:
        envelope = {
            "status": fetcher_contract.STATUS_ERROR,
            "data": None,
            "error": {"message": f"{type(exc).__name__}: {exc}"},
            "source": None,
            "provider_status": "failed",
        }

    snapshot: Any = None
    snapshot_error: str | None = None
    if snapshot_builder is not None:
        try:
            snapshot = snapshot_builder(
                index_id=spec.identity.index_id,
                evaluation_time=evaluated_at,
                start_date=canonical_start,
                end_date=canonical_end,
                calendar=calendar if calendar is not None else TradingCalendar(),
                max_age_policy=(
                    max_age_policy
                    if max_age_policy is not None
                    else MaxAgePolicy(timedelta(hours=48))
                ),
                providers=providers,
                transport=transport,
                universe=MarketIndexUniverse((spec.identity,), spec.provider_aliases),
                daily_k_results={spec.identity.index_id: envelope},
            )
        except Exception as exc:  # snapshot is advisory, never fatal
            snapshot_error = f"{type(exc).__name__}: {exc}"
    observation = _observation_lookup(snapshot, spec.identity.index_id)
    snapshot_calendar_status = getattr(snapshot, "trading_day_status", None)
    snapshot_calendar_status = getattr(snapshot_calendar_status, "value", snapshot_calendar_status)

    publisher = (
        str(spec.identity.publisher.value)
        if hasattr(spec.identity.publisher, "value")
        else str(spec.identity.publisher)
    )
    common = {
        "index_id": spec.identity.index_id,
        "market": spec.market,
        "name": spec.name,
        "currency": spec.currency,
        "timezone": spec.timezone,
        "provider_symbol": spec.provider_symbol,
        "publisher": publisher,
        "local_code": spec.identity.local_code,
        "start_date": canonical_start,
        "end_date": canonical_end,
        "evaluated_at": evaluated_at,
        "degraded": bool(envelope.get("degraded", False)),
        "provider_status": envelope.get("provider_status"),
        "trading_day_status": snapshot_calendar_status or TRADING_DAY_STATUS_UNKNOWN,
    }

    if envelope.get("status") == fetcher_contract.STATUS_EMPTY:
        # The Daily-K service classifies "ok envelope with zero rows" as empty;
        # the page renders that as an explicit empty state, never as bars.
        return GlobalMarketResearch(
            status=STATUS_EMPTY,
            availability=(
                observation.availability
                if observation is not None
                else MarketAvailability.UNKNOWN
            ),
            freshness=(
                observation.freshness.value
                if observation is not None
                else "unknown"
            ),
            source=envelope.get("source_used") or envelope.get("source"),
            unavailable_reason=_EMPTY_REASON,
            **common,
        )

    if envelope.get("status") != fetcher_contract.STATUS_OK:
        error = envelope.get("error")
        reason = envelope.get("failure_reason") or snapshot_error
        if isinstance(error, Mapping):
            reason = error.get("message") or reason
        return GlobalMarketResearch(
            status=STATUS_ERROR,
            availability=(
                observation.availability
                if observation is not None
                else MarketAvailability.UNKNOWN
            ),
            freshness=(
                observation.freshness.value
                if observation is not None
                else "unknown"
            ),
            failure_reason=reason or "daily-K fetch failed",
            source=envelope.get("source"),
            unavailable_reason=_UNAVAILABLE_REASON,
            **common,
        )

    bars, rejected = normalize_daily_rows(envelope.get("data"))
    availability = (
        observation.availability
        if observation is not None
        else MarketAvailability.UNKNOWN
    )
    data_date = bars[-1].date if bars else None
    failure_reason = envelope.get("failure_reason")
    if rejected:
        failure_reason = (
            f"{failure_reason}; skipped {rejected} malformed row(s)"
            if failure_reason
            else f"skipped {rejected} malformed row(s)"
        )

    return GlobalMarketResearch(
        status=STATUS_OK if bars else STATUS_EMPTY,
        availability=availability,
        freshness=observation.freshness.value if observation is not None else "unknown",
        data_date=data_date,
        source=envelope.get("source_used") or envelope.get("source"),
        failure_reason=failure_reason or snapshot_error,
        bars=bars,
        unavailable_reason=None if bars else _EMPTY_REASON,
        **common,
    )


def default_window(now: datetime | None = None, days: int = 30) -> tuple[str, str]:
    """Return a canonical default ``(start_date, end_date)`` window."""

    anchor = (now or datetime.now()).date()
    start = anchor - timedelta(days=max(1, int(days)))
    return start.isoformat(), anchor.isoformat()
