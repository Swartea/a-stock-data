"""Aggregate A-share daily-K service results into evidence-backed snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from analysis import fetcher_contract
from analysis.research.freshness import MaxAgePolicy, evaluate_freshness
from analysis.research.global_daily_k_service import DailyKProvider, default_daily_k_providers, fetch_global_daily_k_service
from analysis.research.global_indices import get_global_index
from analysis.research.index_symbols import IndexProviderSymbolRegistry
from analysis.research.index_registry import A_SHARE_INDEX_IDENTITIES
from analysis.research.market_availability import MarketAvailability
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE, MarketIndexUniverse
from analysis.research.market_snapshot import MarketSnapshot
from analysis.research.market_state import MarketIndexObservation
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import ProviderRegistry, ProviderSpec, build_default_provider_registry
from analysis.research.quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import TradingCalendar, TradingDayStatus

_SHANGHAI = ZoneInfo("Asia/Shanghai")


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


def _date_timestamp(day: str) -> str:
    """Treat date-only A-share bars as the 15:00 Asia/Shanghai session close."""
    return datetime.combine(date.fromisoformat(day), time(15), _SHANGHAI).isoformat()


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
                try:
                    index_name = get_global_index(args[0]).name
                except (KeyError, ValueError):
                    pass
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
) -> MarketSnapshot:
    """Fetch and assess each universe member independently.

    Invalid caller dates/times are rejected before invoking any provider. Daily
    bars remain ``index.daily_k`` observations, never realtime quotes.
    """
    evaluation = _parse_aware(evaluation_time)
    if not isinstance(calendar, TradingCalendar):
        raise TypeError("calendar must be TradingCalendar")
    if not isinstance(max_age_policy, MaxAgePolicy):
        raise TypeError("max_age_policy must be MaxAgePolicy")
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
                try:
                    registry.register(ProviderSpec(item.name, item.source, item.name))
                except (TypeError, ValueError):
                    # Invalid injected identity must fail closed during resolution.
                    pass
    aliases = IndexProviderSymbolRegistry(universe.aliases)
    observations: list[MarketIndexObservation] = []
    for identity in universe.identities:
        try:
            declared = universe.aliases_for(identity.index_id)
            if not declared:
                observations.append(_unavailable(identity, "provider_mapping_missing"))
                continue
            configured = configured_all if providers is not None else default_daily_k_providers(identity.index_id)
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
            bar_time = _date_timestamp(latest_day.isoformat())
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
            if len(dated) >= 2 and _confirmed_adjacent(dated[-2][0], latest_day, calendar):
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
    day_status = calendar.status_on(max(usable_days)) if usable_days else TradingDayStatus.UNKNOWN
    return MarketSnapshot(snapshot_id, "cn", universe.identities, universe.aliases, frozen_observations, day_status)


create_market_snapshot = build_market_snapshot
