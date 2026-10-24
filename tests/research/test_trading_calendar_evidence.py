from calendar import monthrange
from dataclasses import FrozenInstanceError

import pytest

from analysis.research.quality import CompletenessStatus, FreshnessStatus
from analysis.research.trading_calendar import TradingDayStatus
from analysis.research.trading_calendar_evidence import (
    IndexScopedCalendarEvidence,
    TradingCalendarEvidence,
    canonical_index_identity,
    trading_calendar_evidence_from_szse_rows,
)


def _rows(year: int = 2024, month: int = 2):
    count = monthrange(year, month)[1]
    return [
        {
            "jyrq": f"{year:04d}-{month:02d}-{day:02d}",
            "jybz": "0" if day == 19 else "1",
        }
        for day in range(1, count + 1)
    ]


def _szse_evidence(year: int = 2024, month: int = 2, closed_days=(19,)):
    """Return one SZSE calendar evidence value for the given month."""

    count = monthrange(year, month)[1]
    rows = [
        {
            "jyrq": f"{year:04d}-{month:02d}-{day:02d}",
            "jybz": "0" if day in closed_days else "1",
        }
        for day in range(1, count + 1)
    ]
    return trading_calendar_evidence_from_szse_rows(
        rows,
        year=year,
        month=month,
        fetched_at=f"{year:04d}-{month:02d}-01T09:30:00+08:00",
    )


def test_evidence_contract_surface_is_small_and_compositional():
    assert TradingCalendarEvidence.contract_fields() == (
        "calendar",
        "provider",
        "time",
        "quality",
    )


def test_complete_szse_month_gets_canonical_provider_and_complete_quality():
    evidence = trading_calendar_evidence_from_szse_rows(
        _rows(),
        year=2024,
        month=2,
        fetched_at="2024-01-25T09:30:00+08:00",
    )

    assert evidence.provider.provider_id == "szse"
    assert evidence.provider.provider_family == "szse"
    assert evidence.provider.display_name == "深圳证券交易所"
    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN
    assert evidence.quality.completeness is CompletenessStatus.COMPLETE
    assert evidence.quality.degraded is False
    assert evidence.quality.quality_flags == ()
    assert len(evidence.calendar.days) == 29
    assert evidence.calendar.status_on("2024-02-19") is TradingDayStatus.CLOSED


def test_requested_month_defines_period_without_inventing_other_clocks():
    evidence = trading_calendar_evidence_from_szse_rows(
        _rows(),
        year=2024,
        month=2,
        fetched_at="2024-01-25T09:30:00+08:00",
    )

    assert evidence.time.fetched_at == "2024-01-25T09:30:00+08:00"
    assert evidence.time.period_start == "2024-02-01"
    assert evidence.time.period_end == "2024-02-29"
    assert evidence.time.data_as_of is None
    assert evidence.time.published_at is None
    assert evidence.time.effective_from is None
    assert evidence.time.effective_to is None


def test_empty_szse_payload_is_empty_quality_not_synthetic_closed_calendar():
    evidence = trading_calendar_evidence_from_szse_rows(
        [],
        year=2026,
        month=12,
        fetched_at="2026-11-01T00:00:00+08:00",
    )

    assert evidence.quality.completeness is CompletenessStatus.EMPTY
    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN
    assert evidence.quality.degraded is False
    assert evidence.calendar.days == ()
    assert evidence.calendar.status_on("2026-12-01") is TradingDayStatus.UNKNOWN
    assert evidence.time.period_start == "2026-12-01"
    assert evidence.time.period_end == "2026-12-31"


def test_official_provider_identity_does_not_imply_freshness_or_publication_time():
    evidence = trading_calendar_evidence_from_szse_rows(
        _rows(),
        year=2024,
        month=2,
        fetched_at="2025-01-01T00:00:00+08:00",
    )

    assert evidence.provider.provider_id == "szse"
    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN
    assert evidence.time.published_at is None
    assert evidence.time.data_as_of is None


def test_invalid_provider_payload_is_rejected_by_underlying_szse_contract():
    rows = _rows()
    rows.pop()

    with pytest.raises(ValueError, match="cover every date"):
        trading_calendar_evidence_from_szse_rows(
            rows,
            year=2024,
            month=2,
            fetched_at="2024-01-25T09:30:00+08:00",
        )


def test_evidence_is_immutable():
    evidence = trading_calendar_evidence_from_szse_rows(
        [],
        year=2026,
        month=12,
        fetched_at="2026-11-01T00:00:00+08:00",
    )

    with pytest.raises(FrozenInstanceError):
        evidence.calendar = None  # type: ignore[misc]


# --- identity scoping -------------------------------------------------------


def test_index_scoped_contract_surface_is_small():
    assert IndexScopedCalendarEvidence.contract_fields() == ("entries",)


def test_market_level_token_is_not_an_identity():
    assert canonical_index_identity("cn") is None
    assert canonical_index_identity("hk") is None
    assert canonical_index_identity("us") is None
    assert canonical_index_identity("CN") is None
    assert canonical_index_identity(None) is None


def test_market_level_token_is_rejected_when_the_composition_is_built():
    with pytest.raises(ValueError, match="canonical index identity"):
        IndexScopedCalendarEvidence.from_mapping({"cn": _szse_evidence()})


def test_market_level_token_never_resolves_on_lookup():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )

    assert composition.evidence_for("cn") is None
    assert composition.calendar_for("cn").days == ()
    assert composition.status_on("cn", "2024-02-19") is TradingDayStatus.UNKNOWN


def test_evidence_is_isolated_to_the_identity_it_is_assigned_to():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )

    # The SZSE calendar proves the Shenzhen Component sessions only.
    assert composition.evidence_for("cn.index.sz_component") is not None
    assert composition.status_on("cn.index.sz_component", "2024-02-19") is TradingDayStatus.CLOSED

    # The SSE Composite and the CSI 300 are published by other bodies: their
    # sessions are simply not proven by an SZSE calendar.
    assert composition.evidence_for("cn.index.sh_comp") is None
    assert composition.evidence_for("cn.index.csi300") is None
    assert composition.calendar_for("cn.index.sh_comp").days == ()
    assert composition.status_on("cn.index.sh_comp", "2024-02-19") is TradingDayStatus.UNKNOWN
    assert composition.status_on("cn.index.csi300", "2024-02-19") is TradingDayStatus.UNKNOWN


def test_uncovered_dates_stay_unknown():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )

    # A date outside the covered month is never inferred.
    assert composition.status_on("cn.index.sz_component", "2024-03-01") is TradingDayStatus.UNKNOWN
    assert composition.status_on("cn.index.sz_component", "2024-02-19") is TradingDayStatus.CLOSED


def test_historical_alias_resolves_to_the_single_canonical_identity():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sse.000001": _szse_evidence()}
    )

    assert composition.index_ids == ("cn.index.sh_comp",)
    assert composition.evidence_for("cn.index.sh_comp") is not None
    assert composition.evidence_for("cn.index.sse.000001") is not None


def test_unknown_identity_is_rejected_and_never_resolves():
    with pytest.raises(ValueError, match="canonical index identity"):
        IndexScopedCalendarEvidence.from_mapping({"cn.index.not_real": _szse_evidence()})

    composition = IndexScopedCalendarEvidence()
    assert composition.evidence_for("cn.index.not_real") is None
    assert composition.status_on("cn.index.not_real", "2024-02-19") is TradingDayStatus.UNKNOWN


def test_composition_is_immutable_and_deterministically_ordered():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {
            "cn.index.sz_component": _szse_evidence(),
            "cn.index.sh_comp": _szse_evidence(),
        }
    )

    assert composition.index_ids == ("cn.index.sh_comp", "cn.index.sz_component")
    assert isinstance(composition.entries, tuple)

    with pytest.raises(FrozenInstanceError):
        composition.entries = ()  # type: ignore[misc]


def test_resolved_evidence_keeps_the_four_field_contract():
    composition = IndexScopedCalendarEvidence.from_mapping(
        {"cn.index.sz_component": _szse_evidence()}
    )

    resolved = composition.evidence_for("cn.index.sz_component")
    assert resolved is not None
    assert TradingCalendarEvidence.contract_fields() == (
        "calendar",
        "provider",
        "time",
        "quality",
    )
    assert resolved.provider.provider_id == "szse"
    assert resolved.quality.completeness is CompletenessStatus.COMPLETE
    assert resolved.quality.freshness is FreshnessStatus.UNKNOWN
    assert resolved.time.data_as_of is None
