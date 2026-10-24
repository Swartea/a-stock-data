"""Aggregate A-share daily-K service results into evidence-backed snapshots.

Calendar inputs
---------------

The snapshot accepts exactly one of two calendar sources:

* ``calendar`` -- the existing single :class:`TradingCalendar` argument.  Its
  behavior is unchanged for every caller that does not supply the new
  composition: one calendar is applied to the whole snapshot, exactly as
  before.
* ``calendar_evidence`` -- the new optional
  :class:`~analysis.research.trading_calendar_evidence.IndexScopedCalendarEvidence`
  composition, which resolves evidence per **canonical index identity**.

The two inputs are **mutually exclusive**: supplying both is rejected with a
``ValueError`` instead of silently preferring one.  When the composition is
supplied it is the single authoritative source, and the per-identity rules are:

* an index whose identity has evidence uses that index's own calendar;
* an index whose identity has **no** evidence uses an **empty** calendar, so its
  status stays ``UNKNOWN`` rather than borrowing a sibling index's sessions
  (an SZSE calendar never silently applies to the SSE Composite or the
  CSI 300);
* the snapshot's single public ``trading_day_status`` is reported only when
  every covered identity agrees on that date; a multi-market snapshot or
  disagreeing calendars report ``UNKNOWN`` because the public model has only
  one status field and asserting one calendar for all indices would state a
  fact nobody proved.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from analysis import fetcher_contract
from analysis.research.freshness import MaxAgePolicy, evaluate_freshness
from analysis.research.global_daily_k_service import (
    DailyKProvider,
    default_daily_k_providers,
    fetch_global_daily_k_service,
)
from analysis.research.global_indices import get_global_index
from analysis.research.index_registry import A_SHARE_INDEX_IDENTITIES
from analysis.research.index_symbols import IndexProviderSymbolRegistry
from analysis.research.market_availability import MarketAvailability
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE, MarketIndexUniverse
from analysis.research.market_snapshot import MarketSnapshot
from analysis.research.market_state import MarketIndexObservation
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import (
    ProviderRegistry,
    ProviderSpec,
    build_default_provider_registry,
)
from analysis.research.quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import TradingCalendar, TradingDayStatus
from analysis.research.trading_calendar_evidence import IndexScopedCalendarEvidence

_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Snapshot market tokens for the cases where the covered markets are not a
# single known market.
_MARKET_MULTI = "multi"
_MARKET_UNKNOWN = "unknown"


def _parse_aware(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("evaluation_time must be an aware ISO timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("evaluation_time must be an aware ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("evaluation_time must include a timezone")
    return result


def _date_timestamp(day: str, identity: Any) -> str:
    """Represent date-only closes at 15:00 in the index's exchange timezone."""
    try:
        zone = ZoneInfo(get_global_index(identity.index_id).timezone)
    except (KeyError, ValueError):
        zone = _SHANGHAI
    return datetime.combine(date.fromisoformat(day), time(15), zone).isoformat()


def _name(identity: Any) -> str:
    try:
        return get_global_index(identity.index_id).name
    except (KeyError, ValueError):
        return identity.index_id


def _unavailable(identity: Any, reason: str) -> MarketIndexObservation:
    return MarketIndexObservation(identity, _name(identity), availability=MarketAvailability.UNAVAILABLE, reason=reason)


def _ordered_provider(provider: DailyKProvider) -> DailyKProvider:
    """Normalize valid row ordering before Daily-K's strict envelope check."""
    def fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        envelope = provider.fetch(*args, **kwargs)
        if isinstance(envelope, Mapping) and envelope.get("status") == fetcher_contract.STATUS_OK:
            rows = envelope.get("data")
            index_name = None
            if args and isinstance(args[0], str):
                with suppress(KeyError, ValueError):
                    index_name = get_global_index(args[0]).name
            if isinstance(rows, list) and all(
                isinstance(row, Mapping) and isinstance(row.get("date"), str)
                and _valid_iso_day(row["date"])
                for row in rows
            ):
                envelope = dict(envelope)
                normalized_rows = [dict(row, **({"name": index_name} if index_name else {})) for row in rows]
                envelope["data"] = sorted(normalized_rows, key=lambda row: str(row["date"]))
        return envelope

    return DailyKProvider(provider.name, provider.source, fetch, provider.scope)


def _valid_iso_day(value: str) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _confirmed_adjacent(previous: date, current: date, calendar: TradingCalendar) -> bool:
    """Confirm consecutive open sessions only when every intervening date is known."""
    if previous >= current or calendar.status_on(previous.isoformat()) is not TradingDayStatus.OPEN:
        return False
    cursor = previous + timedelta(days=1)
    while cursor <= current:
        status = calendar.status_on(cursor.isoformat())
        if status is TradingDayStatus.UNKNOWN:
            return False
        if cursor == current:
            return status is TradingDayStatus.OPEN
        if status is TradingDayStatus.OPEN:
            return False
        cursor += timedelta(days=1)
    return False


def _identity_index_id(identity: Any) -> str | None:
    """Return the canonical index id of ``identity``.

    The id comes from the identity itself, so the existing index registry stays
    the one place that decides who an index is.  An identity without a usable
    ``index_id`` yields ``None`` instead of a guessed market.
    """

    index_id = getattr(identity, "index_id", None)
    if not isinstance(index_id, str) or not index_id:
        return None
    return index_id


def _calendar_for_identity(
    identity: Any,
    calendar: TradingCalendar,
    calendar_evidence: IndexScopedCalendarEvidence | None,
) -> TradingCalendar:
    """Return the calendar that may be used for ``identity``.

    Without the composition the legacy single calendar is returned unchanged.
    With the composition the identity's own evidence decides, and an identity
    without evidence yields an empty calendar so nothing is borrowed from a
    sibling index that merely shares a market.
    """

    if calendar_evidence is None:
        return calendar
    index_id = _identity_index_id(identity)
    if index_id is None:
        return TradingCalendar()
    return calendar_evidence.calendar_for(index_id)


def _snapshot_trading_day_status(
    *,
    calendar: TradingCalendar,
    calendar_evidence: IndexScopedCalendarEvidence | None,
    market: str,
    identities: Sequence[Any],
    usable_days: Sequence[str],
) -> TradingDayStatus:
    """Resolve the snapshot's single public trading-day status.

    The legacy single-calendar path is preserved exactly.  The identity-scoped
    path reports a status only when **every** covered identity proves the same
    explicit status on the latest usable day; a multi-market snapshot, an
    identity without evidence, and disagreeing calendars all report
    ``UNKNOWN``.  The public model carries a single status, so borrowing one
    index's calendar for every index would state a fact that was never proven.
    """

    if not usable_days:
        return TradingDayStatus.UNKNOWN
    latest = max(usable_days)
    if calendar_evidence is None:
        return calendar.status_on(latest)
    if market in (_MARKET_MULTI, _MARKET_UNKNOWN):
        return TradingDayStatus.UNKNOWN
    statuses: set[TradingDayStatus] = set()
    for identity in identities:
        statuses.add(
            calendar_evidence.status_on(_identity_index_id(identity), latest)
        )
    if len(statuses) != 1:
        return TradingDayStatus.UNKNOWN
    only = statuses.pop()
    if only is TradingDayStatus.UNKNOWN:
        return TradingDayStatus.UNKNOWN
    return only


def build_market_snapshot(
    *,
    evaluation_time: str,
    start_date: str,
    end_date: str,
    calendar: TradingCalendar,
    max_age_policy: MaxAgePolicy,
    universe: MarketIndexUniverse = A_SHARE_CORE_UNIVERSE,
    snapshot_id: str = "market-snapshot",
    providers: Sequence[DailyKProvider] | None = None,
    transport: Any = None,
    provider_registry: ProviderRegistry | None = None,
    daily_k_results: Mapping[str, Mapping[str, Any]] | None = None,
    calendar_evidence: IndexScopedCalendarEvidence | None = None,
) -> MarketSnapshot:
    """Fetch and assess each universe member independently.

    Invalid caller dates/times are rejected before invoking any provider. Daily
    bars remain ``index.daily_k`` observations, never realtime quotes.

    ``calendar_evidence`` is the optional identity-scoped calendar composition.
    It is mutually exclusive with a non-empty ``calendar``: supplying both
    raises ``ValueError`` rather than silently preferring one.  Without it the
    legacy single-calendar behavior is unchanged.
    """
    evaluation = _parse_aware(evaluation_time)
    if not isinstance(calendar, TradingCalendar):
        raise TypeError("calendar must be TradingCalendar")
    if not isinstance(max_age_policy, MaxAgePolicy):
        raise TypeError("max_age_policy must be MaxAgePolicy")
    if calendar_evidence is not None and not isinstance(
        calendar_evidence, IndexScopedCalendarEvidence
    ):
        raise TypeError("calendar_evidence must be IndexScopedCalendarEvidence or None")
    if calendar_evidence is not None and calendar.days:
        raise ValueError(
            "calendar and calendar_evidence are mutually exclusive; supply an "
            "empty TradingCalendar() when using the market-scoped composition"
        )
    if daily_k_results is not None and not isinstance(daily_k_results, Mapping):
        raise TypeError("daily_k_results must be a mapping or None")
    for label, raw in (("start_date", start_date), ("end_date", end_date)):
        try:
            parsed = date.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be canonical YYYY-MM-DD") from exc
        if parsed.isoformat() != raw:
            raise ValueError(f"{label} must be canonical YYYY-MM-DD")
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("start_date must be <= end_date")

    # The historical S3 singleton may lag the canonical provider-facing V1 ids.
    # Build its compatibility view from the existing provider specs, avoiding a
    # second set of hand-maintained alias declarations.
    if universe is A_SHARE_CORE_UNIVERSE and any(
        identity.index_id not in {item.index_id for item in A_SHARE_INDEX_IDENTITIES}
        for identity in universe.identities
    ):
        aliases_from_specs = tuple(
            alias
            for identity in A_SHARE_INDEX_IDENTITIES
            for alias in get_global_index(identity.index_id).provider_aliases
        )
        universe = MarketIndexUniverse(A_SHARE_INDEX_IDENTITIES, aliases_from_specs)

    registry = provider_registry or build_default_provider_registry()
    configured_all = tuple(providers) if providers is not None else ()
    if providers is not None:
        for item in configured_all:
            if registry.resolve(item.name) is None:
                with suppress(TypeError, ValueError):
                    registry.register(ProviderSpec(item.name, item.source, item.name))
    aliases = IndexProviderSymbolRegistry(universe.aliases)
    observations: list[MarketIndexObservation] = []
    for identity in universe.identities:
        try:
            declared = universe.aliases_for(identity.index_id)
            if not declared:
                observations.append(_unavailable(identity, "provider_mapping_missing"))
                continue
            configured = configured_all if providers is not None else default_daily_k_providers(identity.index_id)
            if daily_k_results is not None:
                supplied = daily_k_results.get(identity.index_id)
                result = supplied if isinstance(supplied, Mapping) else {
                    "status": fetcher_contract.STATUS_ERROR,
                    "failure_reason": "pre-fetched daily-K result missing",
                }
            else:
                result = fetch_global_daily_k_service(identity.index_id, start_date, end_date, now=evaluation, transport=transport, providers=tuple(_ordered_provider(item) for item in configured))
            if result.get("status") != fetcher_contract.STATUS_OK:
                observations.append(_unavailable(identity, str(result.get("failure_reason") or result.get("status") or "provider_error")))
                continue
            rows = result.get("data")
            if not isinstance(rows, list) or not rows:
                observations.append(_unavailable(identity, "empty"))
                continue
            provider_id = result.get("source_used")
            provider = registry.resolve(provider_id) if isinstance(provider_id, str) else None
            # The source actually used may be a fallback with a separate
            # provider mapping held by DailyK service. The provider attempt and
            # ProviderSpec establish provenance; the universe's canonical
            # aliases gate whether this index is supported at all.
            # The requested index is already canonicalized by Daily-K service;
            # this mapping gate asserts the universe explicitly supports it.
            # Fallback providers need not have a separate symbol alias when
            # their result is for the same requested canonical identity.
            if provider is None or not any(aliases.resolve(a.provider_id, a.provider_symbol) == identity.index_id for a in declared):
                observations.append(_unavailable(identity, "provider_evidence_unmapped"))
                continue

            dated: list[tuple[date, Mapping[str, Any]]] = []
            valid = True
            for row in rows:
                if not isinstance(row, Mapping) or not isinstance(row.get("date"), str):
                    valid = False
                    break
                try:
                    bar_day = date.fromisoformat(row["date"])
                except ValueError:
                    valid = False
                    break
                close = row.get("close")
                if bar_day.isoformat() != row["date"] or isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close):
                    valid = False
                    break
                dated.append((bar_day, row))
            if not valid or len({d for d, _ in dated}) != len(dated):
                observations.append(_unavailable(identity, "malformed_or_duplicate_dates"))
                continue
            dated.sort(key=lambda item: item[0])
            latest_day, latest_row = dated[-1]
            latest_close = float(latest_row["close"])
            bar_time = _date_timestamp(latest_day.isoformat(), identity)
            future = datetime.fromisoformat(bar_time).astimezone(evaluation.tzinfo) > evaluation
            metadata = TimeMetadata(fetched_at=evaluation_time, data_as_of=bar_time)
            try:
                freshness = evaluate_freshness(metadata, evaluation_time, policy=max_age_policy).status
            except ValueError:
                # A date-only current-session bar has a 15:00 observation clock;
                # before that close it is retained as a future PIT observation.
                if not future:
                    raise
                freshness = FreshnessStatus.UNKNOWN
            availability = MarketAvailability.UNKNOWN if future else {
                FreshnessStatus.FRESH: MarketAvailability.AVAILABLE,
                FreshnessStatus.STALE: MarketAvailability.DELAYED,
                FreshnessStatus.UNKNOWN: MarketAvailability.UNKNOWN,
            }[freshness]
            change = change_percent = None
            identity_calendar = _calendar_for_identity(identity, calendar, calendar_evidence)
            if len(dated) >= 2 and _confirmed_adjacent(dated[-2][0], latest_day, identity_calendar):
                previous_close = dated[-2][1].get("close")
                if isinstance(previous_close, (int, float)) and not isinstance(previous_close, bool) and math.isfinite(previous_close) and previous_close != 0:
                    change = latest_close - float(previous_close)
                    change_percent = change / float(previous_close) * 100
            degraded = result.get("degraded") is True
            quality = QualityMetadata(freshness=freshness, completeness=CompletenessStatus.COMPLETE, degraded=degraded)
            evidence = MarketEvidence(
                f"{identity.index_id}:daily-close:{latest_day.isoformat()}", identity, "daily_close", latest_close,
                provider, metadata, quality, PITStatus.REJECT if future else PITStatus.ALLOW,
                fetcher_contract.STATUS_OK,
            )
            observations.append(MarketIndexObservation(
                identity, _name(identity), latest_close, change, change_percent,
                latest_day.isoformat(), provider_id, degraded, availability,
                freshness, (evidence,), "future_session_close" if future else None,
            ))
        except Exception as exc:  # isolate malformed provider/mapping behavior to this index
            observations.append(_unavailable(identity, f"aggregation_error:{type(exc).__name__}"))

    frozen_observations = tuple(observations)
    usable_days = [
        item.data_date for item in frozen_observations
        if item.data_date is not None and item.close is not None and item.evidence
        and item.availability in (MarketAvailability.AVAILABLE, MarketAvailability.DELAYED)
    ]
    markets: set[str] = set()
    known_market_count = 0
    for identity in universe.identities:
        try:
            markets.add(get_global_index(identity.index_id).market)
        except (KeyError, ValueError):
            continue
        else:
            known_market_count += 1
    if not markets:
        market = _MARKET_UNKNOWN
    elif len(markets) == 1 and known_market_count == len(universe.identities):
        market = next(iter(markets))
    else:
        market = _MARKET_MULTI
    day_status = _snapshot_trading_day_status(
        calendar=calendar,
        calendar_evidence=calendar_evidence,
        market=market,
        identities=universe.identities,
        usable_days=usable_days,
    )
    return MarketSnapshot(snapshot_id, market, universe.identities, universe.aliases, frozen_observations, day_status)


create_market_snapshot = build_market_snapshot
