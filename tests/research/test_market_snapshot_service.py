from datetime import timedelta

import pytest

from analysis.research.freshness import MaxAgePolicy
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE
from analysis.research.market_snapshot_service import build_market_snapshot
from analysis.research.trading_calendar import TradingCalendar, TradingCalendarDay, TradingDayStatus


def test_invalid_evaluation_time_rejected_before_provider_invocation():
    with pytest.raises(ValueError, match="evaluation_time"):
        build_market_snapshot(
            evaluation_time="2026-10-14T10:00:00",
            start_date="2026-09-01",
            end_date="2026-10-14",
            calendar=TradingCalendar(),
            max_age_policy=MaxAgePolicy(timedelta(days=3)),
        )


def test_missing_universe_mapping_is_unavailable_without_numeric_values():
    from analysis.research.market_index_universe import MarketIndexUniverse

    universe = MarketIndexUniverse(identities=(A_SHARE_CORE_UNIVERSE.identities[0],))
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-09-01",
        end_date="2026-10-14",
        calendar=TradingCalendar(),
        max_age_policy=MaxAgePolicy(timedelta(days=3)),
        universe=universe,
    )
    assert snapshot.observations[0].close is None


def test_unknown_custom_identity_does_not_break_market_snapshot():
    from analysis.research.index_registry import IndexIdentity, IndexPublisher
    from analysis.research.market_index_universe import MarketIndexUniverse

    identity = IndexIdentity("test.index.unregistered", IndexPublisher.CSI, "TEST")
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13",
        end_date="2026-10-14",
        calendar=TradingCalendar(),
        max_age_policy=MaxAgePolicy(timedelta(days=1)),
        universe=MarketIndexUniverse((identity,)),
    )
    assert snapshot.market == "unknown"
    assert snapshot.observations[0].availability.value == "unavailable"


def _provider(*, reverse=False, row_days=None, payload_name=None):
    from analysis import fetcher_contract
    from analysis.research.global_daily_k_service import DailyKProvider
    from analysis.research.global_indices import get_global_index

    def fetch(index_id, start_date, end_date, **kwargs):
        spec = get_global_index(index_id)
        days = row_days or [("2026-10-13", 100.0), ("2026-10-14", 105.0)]
        if reverse:
            days.reverse()
        rows = [
            {
                "index_id": index_id, "market": spec.market,
                "symbol": spec.identity.local_code, "name": payload_name or spec.name,
                "date": day, "open": close, "high": close + 1,
                "low": close - 1, "close": close, "volume": None,
                "currency": spec.currency, "timezone": spec.timezone,
                "source": "wire",
            }
            for day, close in days
        ]
        return fetcher_contract.make_ok(
            rows, source="wire", as_of="2026-10-14", scope="market",
            units={"price": "index_points"},
        )

    return DailyKProvider("tencent", "Tencent", fetch)


def test_unordered_daily_bars_choose_latest_and_explicit_adjacent_change():
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar((TradingCalendarDay("2026-10-13", TradingDayStatus.OPEN), TradingCalendarDay("2026-10-14", TradingDayStatus.OPEN))),
        max_age_policy=MaxAgePolicy(timedelta(days=1)), providers=(_provider(reverse=True),),
    )
    obs = snapshot.observations[0]
    assert obs.data_date == "2026-10-14"
    assert obs.close == 105.0
    assert obs.change == 5.0
    assert obs.change_percent == 5.0
    assert obs.availability.value == "available"
    assert obs.freshness.value == "fresh"
    assert snapshot.trading_day_status is TradingDayStatus.OPEN


def test_change_requires_all_calendar_dates_and_consecutive_open_sessions():
    days = tuple(TradingCalendarDay(day, TradingDayStatus.OPEN if day in ("2026-10-13", "2026-10-14") else TradingDayStatus.CLOSED)
                 for day in ("2026-10-12", "2026-10-13", "2026-10-14"))
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(days), max_age_policy=MaxAgePolicy(timedelta(days=1)), providers=(_provider(),),
    )
    assert snapshot.observations[0].change == 5.0


@pytest.mark.parametrize("row_days,calendar_days", [
    ([ ("2026-09-30", 100.0), ("2026-10-14", 105.0) ],
     (TradingCalendarDay("2026-09-30", TradingDayStatus.OPEN), TradingCalendarDay("2026-10-14", TradingDayStatus.OPEN))),
    ([ ("2026-10-12", 100.0), ("2026-10-14", 105.0) ],
     (TradingCalendarDay("2026-10-12", TradingDayStatus.OPEN), TradingCalendarDay("2026-10-13", TradingDayStatus.OPEN), TradingCalendarDay("2026-10-14", TradingDayStatus.OPEN))),
    ([ ("2026-10-13", 100.0), ("2026-10-14", 105.0) ], ()),
])
def test_change_omitted_for_multiweek_gap_intervening_open_or_unknown(row_days, calendar_days):
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-09-30", end_date="2026-10-14",
        calendar=TradingCalendar(calendar_days), max_age_policy=MaxAgePolicy(timedelta(days=30)),
        providers=(_provider(row_days=row_days),),
    )
    assert snapshot.observations[0].change is None
    assert snapshot.observations[0].change_percent is None


@pytest.mark.parametrize("close", ["bad", float("nan"), float("inf"), float("-inf")])
def test_invalid_close_never_becomes_available(close):
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(hours=12)),
        providers=(_provider(row_days=[("2026-10-14", close)]),),
    )
    assert snapshot.observations[0].availability.value == "unavailable"
    assert snapshot.observations[0].close is None


def test_same_day_freshness_uses_time_and_non_utc_offset():
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T00:30:00-07:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(hours=12)),
        providers=(_provider(row_days=[("2026-10-14", 105.0)]),),
    )
    obs = snapshot.observations[0]
    assert obs.freshness.value == "fresh"
    assert obs.availability.value == "available"


def test_payload_name_is_derived_from_canonical_identity():
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(_provider(row_days=[("2026-10-14", 105.0)], payload_name="spoofed"),),
    )
    assert snapshot.observations[0].name != "spoofed"  # provider fixture payload names are not authoritative


def test_custom_injected_provider_identity_and_symbol_mapping_resolve_evidence():
    from analysis.research.global_daily_k_service import DailyKProvider
    from analysis.research.index_symbols import IndexProviderSymbolAlias
    from analysis.research.market_index_universe import MarketIndexUniverse

    identity = A_SHARE_CORE_UNIVERSE.identities[0]
    symbol = identity.local_code
    provider = DailyKProvider("customfeed", "Custom Feed", _provider().fetch)
    universe = MarketIndexUniverse((identity,), (IndexProviderSymbolAlias(identity.index_id, "customfeed", symbol),))
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(provider,), universe=universe,
    )
    assert snapshot.observations[0].provider == "customfeed"
    assert snapshot.observations[0].evidence[0].provider.provider_id == "customfeed"


def test_unsupported_mapping_and_empty_data_are_unavailable_without_evidence():
    from analysis import fetcher_contract
    from analysis.research.global_daily_k_service import DailyKProvider
    from analysis.research.market_index_universe import MarketIndexUniverse

    identity = A_SHARE_CORE_UNIVERSE.identities[0]
    unsupported_universe = MarketIndexUniverse((identity,))
    unsupported = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(_provider(),), universe=unsupported_universe,
    )
    assert unsupported.observations[0].availability.value == "unavailable"
    assert unsupported.observations[0].evidence == ()
    empty = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00", start_date="2026-10-14", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(DailyKProvider("tencent", "Tencent", lambda *a, **k: fetcher_contract.make_empty(source="Tencent", scope="market")),),
    )
    assert all(obs.close is None and obs.evidence == () for obs in empty.observations)


def test_current_session_close_is_pit_observation_before_close():
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T14:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar((TradingCalendarDay("2026-10-14", TradingDayStatus.OPEN),)),
        max_age_policy=MaxAgePolicy(timedelta(days=1)), providers=(_provider(),),
    )
    obs = snapshot.observations[0]
    assert obs.data_date == "2026-10-14"
    assert obs.reason == "future_session_close"
    assert obs.availability.value == "unknown"
    assert obs.evidence[0].pit_status.value == "reject"
    assert snapshot.trading_day_status is TradingDayStatus.UNKNOWN


def test_closed_calendar_date_is_explicit_and_missing_date_stays_unknown():
    closed = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar((TradingCalendarDay("2026-10-14", TradingDayStatus.CLOSED),)),
        max_age_policy=MaxAgePolicy(timedelta(days=1)), providers=(_provider(),),
    )
    assert closed.trading_day_status is TradingDayStatus.CLOSED
    unknown = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(_provider(),),
    )
    assert unknown.trading_day_status is TradingDayStatus.UNKNOWN


def test_primary_error_fallback_success_is_degraded_with_provider_evidence():
    from analysis import fetcher_contract
    from analysis.research.global_daily_k_service import DailyKProvider

    primary = DailyKProvider(
        "tencent", "Tencent",
        lambda *args, **kwargs: fetcher_contract.make_error_result("NETWORK", "offline", source="Tencent", scope="market"),
    )
    fallback = DailyKProvider("baostock", "Baostock", _provider().fetch)
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(primary, fallback),
    )
    obs = snapshot.observations[0]
    assert obs.provider == "baostock"
    assert obs.degraded is True
    assert obs.evidence[0].provider.provider_id == "baostock"


def test_bad_date_input_never_calls_provider():
    calls = []
    original = _provider()

    def fetch(*args, **kwargs):
        calls.append(1)
        return original.fetch(*args, **kwargs)

    from analysis.research.global_daily_k_service import DailyKProvider
    provider = DailyKProvider("tencent", "Tencent", fetch)
    with pytest.raises(ValueError, match="start_date"):
        build_market_snapshot(
            evaluation_time="2026-10-14T16:00:00+08:00",
            start_date="2026-02-30", end_date="2026-10-14",
            calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
            providers=(provider,),
        )
    assert calls == []


@pytest.mark.parametrize(
    "row_days",
    [
        [("2026-10-14", 105.0), ("2026-10-14", 106.0)],
        [("not-a-date", 105.0)],
    ],
)
def test_malformed_or_duplicate_bar_dates_are_unavailable(row_days):
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(_provider(row_days=row_days),),
    )
    assert snapshot.observations[0].close is None
    assert snapshot.observations[0].availability.value == "unavailable"


def test_mixed_provider_results_keep_usable_indices_and_isolate_errors():
    from analysis import fetcher_contract
    from analysis.research.global_daily_k_service import DailyKProvider

    base = _provider()

    def fetch(index_id, *args, **kwargs):
        if index_id == "cn.index.sh_comp":
            return base.fetch(index_id, *args, **kwargs)
        return fetcher_contract.make_error_result("OFFLINE", "offline", source="Tencent", scope="market")

    provider = DailyKProvider("tencent", "Tencent", fetch)
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(provider,),
    )
    assert snapshot.observations[0].close == 105.0
    assert all(item.close is None for item in snapshot.observations[1:])
    assert snapshot.trading_day_status is TradingDayStatus.UNKNOWN


def test_empty_provider_result_is_not_encoded_as_zero():
    from analysis import fetcher_contract
    from analysis.research.global_daily_k_service import DailyKProvider

    provider = DailyKProvider(
        "tencent", "Tencent",
        lambda *args, **kwargs: fetcher_contract.make_empty(source="Tencent", scope="market"),
    )
    snapshot = build_market_snapshot(
        evaluation_time="2026-10-14T16:00:00+08:00",
        start_date="2026-10-13", end_date="2026-10-14",
        calendar=TradingCalendar(), max_age_policy=MaxAgePolicy(timedelta(days=1)),
        providers=(provider,),
    )
    assert all(item.close is None for item in snapshot.observations)
    assert snapshot.trading_day_status is TradingDayStatus.UNKNOWN
