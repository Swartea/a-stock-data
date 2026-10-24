"""Deterministic tests for the global-index daily-K research composition.

Every test is offline and fixture-isolated: provider calls are served by
explicit, labeled in-test stubs passed through ``providers=`` so no network and
no production fixture file is ever touched. Bars in ``_LABELED_*`` constants are
test data for this module only — they are never written to disk and never used
by production code.
"""

from __future__ import annotations

import pytest

from analysis.research import global_market_research as gmr
from analysis.research.global_daily_k_service import DailyKProvider
from analysis.research.global_indices import get_global_index, list_global_indices
from analysis.research.market_availability import MarketAvailability

# Labeled fixture: two valid CN bars for one index, the second carrying a
# supplied volume. Test data for this module only; never written to disk.
_LABELED_CN_ROWS = [
    {
        "index_id": "cn.index.sh_comp",
        "market": "cn",
        "symbol": "000001",
        "name": "上证指数",
        "date": "2026-09-24",
        "open": 3000.0,
        "high": 3050.0,
        "low": 2980.0,
        "close": 3040.0,
        "volume": None,
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "source": "tencent.daily_k",
    },
    {
        "index_id": "cn.index.sh_comp",
        "market": "cn",
        "symbol": "000001",
        "name": "上证指数",
        "date": "2026-09-25",
        "open": 3040.0,
        "high": 3090.0,
        "low": 3025.0,
        "close": 3075.5,
        "volume": None,
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "source": "tencent.daily_k",
    },
    # malformed: high below close fails the OHLC invariant
]


def _ok_envelope(rows, *, source="tencent.daily_k", scope="market"):
    """Return a strictly conforming labeled V1 ok envelope."""

    return {
        "status": "ok",
        "source": source,
        "scope": scope,
        "data": list(rows),
        "as_of": "2026-09-25",
        "fetched_at": "2026-09-25T15:30:00+08:00",
        "units": {"price": "index_points", "volume": "unavailable"},
        "error": None,
    }


def _stub_provider(envelope, calls=None):
    """Build a labeled offline provider stub that never touches the network."""

    def fetch(*args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        if isinstance(envelope, Exception):
            raise envelope
        return envelope

    return DailyKProvider("labeled-stub", "tencent.daily_k", fetch, "market")


def _boom_provider(calls):
    """Provider that fails the test if the caller ever reaches a provider."""

    def fetch(*args, **kwargs):
        calls.append(args)
        raise AssertionError("unproven market must not reach a provider")

    return DailyKProvider("never-called", "tencent.daily_k", fetch, "market")


def _stub_snapshot(**kwargs):
    """Labeled snapshot-builder stub; never touches the real Snapshot Service."""

    calls = []

    def builder(**call_kwargs):
        calls.append(call_kwargs)
        return None

    builder.calls = calls
    return builder


# --- registry selection -----------------------------------------------------


def test_choices_come_from_the_canonical_registry_only():
    choices = gmr.list_index_choices()
    assert [item["index_id"] for item in choices] == [
        spec.identity.index_id for spec in list_global_indices()
    ]
    assert all(item["proven"] == "yes" for item in choices)


def test_markets_are_derived_not_declared():
    assert gmr.list_research_markets() == ("cn", "hk", "us")
    assert [spec.market for spec in gmr.list_market_indices("cn")] == ["cn"] * 4
    assert gmr.list_market_indices("jp") == ()


def test_resolve_index_reuses_registry_rejections():
    assert gmr.resolve_index("cn.index.sh_comp").provider_symbol == "sh000001"
    with pytest.raises(ValueError):
        gmr.resolve_index("CN.INDEX.SH_COMP")
    with pytest.raises(KeyError):
        gmr.resolve_index("us.INX")


def test_provider_evidence_is_tracked_per_market_and_index():
    assert gmr.market_is_proven("cn") is True
    assert gmr.market_is_proven("hk") is True
    assert gmr.market_is_proven("us") is True
    assert gmr.market_is_proven("jp") is False


# --- composition over the existing services ---------------------------------


def test_service_composition_returns_normalized_bars():
    calls: list = []
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        evaluation_time="2026-09-25T15:30:00+08:00",
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS), calls)],
    )
    assert result.status == gmr.STATUS_OK
    assert result.availability is MarketAvailability.AVAILABLE
    assert result.bar_count == 2
    assert result.data_date == "2026-09-25"
    assert result.timezone == "Asia/Shanghai"
    assert result.trading_day_status == gmr.TRADING_DAY_STATUS_UNKNOWN
    assert result.provider_symbol == "sh000001"
    assert calls, "the daily-k service must have been called"


def test_weekend_wall_clock_gap_does_not_mark_friday_bars_delayed():
    friday_rows = [dict(_LABELED_CN_ROWS[-1], date="2026-09-25")]
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-25",
        "2026-09-28",
        evaluation_time="2026-09-28T10:00:00+08:00",
        providers=[_stub_provider(_ok_envelope(friday_rows))],
    )
    assert result.freshness == "fresh"
    assert result.availability is MarketAvailability.AVAILABLE


def test_volume_is_reported_only_when_supplied():
    # V1 daily-K rows always carry volume=None, so the service path emits no
    # volume key at all. A labeled row that *does* supply one keeps it.
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS))],
    )
    assert all("volume" not in bar.as_dict() for bar in result.bars)

    with_volume, rejected = gmr.normalize_daily_rows(
        [dict(_LABELED_CN_ROWS[1], volume=1234567.0)]
    )
    assert rejected == 0
    assert with_volume[0].as_dict()["volume"] == pytest.approx(1234567.0)


def test_unproven_registry_index_is_unavailable_without_provider_call(monkeypatch):
    calls: list = []
    monkeypatch.setattr(gmr, "PROVEN_INDEX_IDS", frozenset())
    result = gmr.build_global_market_research(
        "us.index.sp_dji.sp500",
        "2026-09-01",
        "2026-09-30",
        providers=[_boom_provider(calls)],
    )
    assert result.status == gmr.STATUS_UNAVAILABLE
    assert result.availability is MarketAvailability.UNAVAILABLE
    assert result.bars == ()
    assert result.unavailable_reason
    assert calls == [], "no provider may be invoked for an unproven registry identity"


def test_empty_window_is_explicit():
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-02",
        providers=[_stub_provider(_ok_envelope([]))],
    )
    assert result.status == gmr.STATUS_EMPTY
    assert result.bar_count == 0
    assert result.availability is MarketAvailability.UNAVAILABLE
    assert result.unavailable_reason


def test_provider_error_is_degraded_not_raised():
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        providers=[_stub_provider(RuntimeError("boom"))],
    )
    assert result.status == gmr.STATUS_ERROR
    assert result.bar_count == 0
    assert result.failure_reason
    assert "boom" not in result.failure_reason


def test_invalid_dates_never_reach_a_provider():
    calls: list = []
    for start, end in (("2026-9-1", "2026-09-30"), ("2026-09-30", "2026-09-01"), ("", "2026-09-30")):
        result = gmr.build_global_market_research(
            "cn.index.sh_comp",
            start,
            end,
            providers=[_boom_provider(calls)],
        )
        assert result.status == gmr.STATUS_ERROR
        assert "VALIDATION" in (result.failure_reason or "")
    assert calls == []


def test_snapshot_service_is_reused_when_calendar_evidence_is_supplied():
    builder = _stub_snapshot()
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        evaluation_time="2026-09-25T15:30:00+08:00",
        calendar=object(),
        max_age_policy=object(),
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS))],
        snapshot_builder=builder,
    )
    assert builder.calls and builder.calls[0]["index_id"] == "cn.index.sh_comp"
    assert result.evaluated_at == "2026-09-25T15:30:00+08:00"


def test_real_snapshot_service_consumes_the_same_single_provider_result():
    calls: list = []
    labeled_hk = [
        {
            **_LABELED_CN_ROWS[-1],
            "index_id": "hk.index.hang_seng.hsi",
            "market": "hk",
            "symbol": "HSI",
            "name": "恒生指数",
            "currency": "HKD",
            "timezone": "Asia/Hong_Kong",
        }
    ]
    provider = _stub_provider(_ok_envelope(labeled_hk), calls)
    result = gmr.build_global_market_research(
        "hk.index.hang_seng.hsi",
        "2026-09-24",
        "2026-09-25",
        evaluation_time="2026-09-25T15:30:00+08:00",
        providers=[provider],
    )
    assert result.status == gmr.STATUS_OK
    assert result.availability is MarketAvailability.AVAILABLE
    assert result.freshness == "fresh"
    assert result.source == "labeled-stub"
    assert len(calls) == 1, "snapshot composition must reuse bars already fetched"


def test_snapshot_observation_uses_the_index_exchange_timezone():
    calls: list = []
    us_rows = [
        {
            **_LABELED_CN_ROWS[-1],
            "index_id": "us.index.sp_dji.sp500",
            "market": "us",
            "symbol": "SP500",
            "name": "S&P 500",
            "currency": "USD",
            "timezone": "America/New_York",
        }
    ]
    result = gmr.build_global_market_research(
        "us.index.sp_dji.sp500",
        "2026-09-25",
        "2026-09-25",
        evaluation_time="2026-09-25T16:00:00-04:00",
        providers=[_stub_provider(_ok_envelope(us_rows), calls)],
    )
    assert result.availability is MarketAvailability.AVAILABLE
    # The close evidence belongs to New York's 15:00 session, not Shanghai.
    from analysis.research.global_indices import get_global_index
    from analysis.research.market_snapshot_service import _date_timestamp

    assert _date_timestamp("2026-09-25", get_global_index("us.index.sp_dji.sp500").identity).endswith("-04:00")


def test_incomplete_exchange_calendar_keeps_state_unknown():
    result = gmr.build_global_market_research(
        "hk.index.hang_seng.hsi",
        "2026-09-24",
        "2026-09-25",
        evaluation_time="2026-09-25T15:30:00+08:00",
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS))],
    )
    assert result.trading_day_status == "unknown"


def test_snapshot_failure_never_breaks_the_page():
    def exploding_builder(**kwargs):
        raise RuntimeError("sensitive/path/token calendar unavailable")

    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        evaluation_time="2026-09-25T15:30:00+08:00",
        calendar=object(),
        max_age_policy=object(),
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS))],
        snapshot_builder=exploding_builder,
    )
    assert result.status == gmr.STATUS_OK
    assert result.bar_count == 2
    assert "sensitive/path/token" not in (result.failure_reason or "")


# --- fixture isolation ------------------------------------------------------


def test_malformed_rows_never_render_as_bars():
    broken = [dict(_LABELED_CN_ROWS[0], high=1.0), dict(_LABELED_CN_ROWS[1], close=None)]
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        providers=[_stub_provider(_ok_envelope(broken))],
    )
    assert result.bars == ()
    assert result.status in (gmr.STATUS_ERROR, gmr.STATUS_EMPTY)
    assert result.bar_count == 0


def test_normalizer_is_pure_and_order_independent():
    rows, rejected = gmr.normalize_daily_rows(list(reversed(_LABELED_CN_ROWS)))
    assert [bar.date for bar in rows] == ["2026-09-24", "2026-09-25"]
    assert rejected == 0
    # The fixture list itself is never mutated.
    assert _LABELED_CN_ROWS[0]["date"] == "2026-09-24"


def test_normalizer_survives_hostile_rows():
    rows, rejected = gmr.normalize_daily_rows(
        [None, "nope", {}, {"date": "bad"}, {"date": "2026-01-02", "open": "1"}]
    )
    assert rows == ()
    assert rejected == 5
    assert gmr.normalize_daily_rows(None) == ((), 0)


def test_duplicate_dates_are_rejected_without_selecting_an_arbitrary_row():
    duplicate = dict(_LABELED_CN_ROWS[0])
    rows, rejected = gmr.normalize_daily_rows([_LABELED_CN_ROWS[0], duplicate])
    assert rejected == 2
    assert rows == ()


def test_payload_is_json_serializable():
    import json

    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-01",
        "2026-09-30",
        providers=[_stub_provider(_ok_envelope(_LABELED_CN_ROWS))],
    )
    payload = json.loads(json.dumps(result.as_dict(), ensure_ascii=False))
    assert payload["index_id"] == "cn.index.sh_comp"
    assert payload["bars"][0]["date"] == "2026-09-24"
    assert payload["units"]["price"] == "index_points"


def test_registry_identity_is_not_redefined():
    spec = get_global_index("cn.index.csi300")
    result = gmr.build_global_market_research(
        "cn.index.csi300", "2026-09-01", "2026-09-30", providers=[_boom_provider([])]
    )
    assert result.index_id == spec.identity.index_id
    assert result.provider_symbol == spec.provider_symbol
    assert result.market == spec.market


# --- identity-scoped calendar evidence --------------------------------------

# Labeled fixture: September 2026 SZSE calendar rows.  Test data for this
# module only; never written to disk and never fetched.
_LABELED_SZSE_SEPTEMBER_ROWS = [
    {
        "jyrq": f"2026-09-{day:02d}",
        "jybz": "0" if day == 25 else "1",
    }
    for day in range(1, 31)
]


def _szse_evidence():
    """Return one labeled SZSE calendar evidence value."""

    from analysis.research.trading_calendar_evidence import (
        trading_calendar_evidence_from_szse_rows,
    )

    return trading_calendar_evidence_from_szse_rows(
        _LABELED_SZSE_SEPTEMBER_ROWS,
        year=2026,
        month=9,
        fetched_at="2026-08-25T09:30:00+08:00",
    )


def _rows_for(index_id):
    """Return labeled rows bound to one index id."""

    spec = get_global_index(index_id)
    return [
        dict(
            row,
            index_id=index_id,
            market=spec.market,
            symbol=spec.identity.local_code,
            name=spec.name,
            currency=spec.currency,
            timezone=spec.timezone,
        )
        for row in _LABELED_CN_ROWS
    ]


def test_calendar_evidence_resolves_through_the_requested_index_identity():
    from analysis.research.trading_calendar_evidence import (
        IndexScopedCalendarEvidence,
    )

    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )
    result = gmr.build_global_market_research(
        "cn.index.sz_component",
        "2026-09-24",
        "2026-09-25",
        evaluation_time="2026-09-25T15:30:00+08:00",
        providers=[_stub_provider(_ok_envelope(_rows_for("cn.index.sz_component")))],
        calendar_evidence=composition,
    )
    # The SZSE calendar explicitly closes 2026-09-25 for the index it is
    # assigned to, so the proven status is reported.
    assert result.trading_day_status == "closed"


def test_calendar_evidence_never_leaks_to_a_sibling_index():
    from analysis.research.trading_calendar_evidence import (
        IndexScopedCalendarEvidence,
    )

    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )
    result = gmr.build_global_market_research(
        "cn.index.sh_comp",
        "2026-09-24",
        "2026-09-25",
        evaluation_time="2026-09-25T15:30:00+08:00",
        providers=[_stub_provider(_ok_envelope(_rows_for("cn.index.sh_comp")))],
        calendar_evidence=composition,
    )
    # The SSE Composite has no evidence of its own, so its status stays
    # unknown instead of borrowing the Shenzhen Component's sessions.
    assert result.trading_day_status == "unknown"


def test_market_level_calendar_evidence_cannot_be_built():
    from analysis.research.trading_calendar_evidence import (
        IndexScopedCalendarEvidence,
    )

    with pytest.raises(ValueError, match="canonical index identity"):
        IndexScopedCalendarEvidence.from_mapping({"cn": _szse_evidence()})


def test_calendar_and_calendar_evidence_are_mutually_exclusive():
    from analysis.research.trading_calendar_evidence import (
        IndexScopedCalendarEvidence,
    )

    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        gmr.build_global_market_research(
            "cn.index.sz_component",
            "2026-09-24",
            "2026-09-25",
            evaluation_time="2026-09-25T15:30:00+08:00",
            calendar=object(),
            providers=[_stub_provider(_ok_envelope(_rows_for("cn.index.sz_component")))],
            calendar_evidence=composition,
        )
