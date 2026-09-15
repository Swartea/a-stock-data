from calendar import monthrange
from dataclasses import FrozenInstanceError

import pytest

from analysis.research.quality import CompletenessStatus, FreshnessStatus
from analysis.research.trading_calendar import TradingDayStatus
from analysis.research.trading_calendar_evidence import (
    TradingCalendarEvidence,
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
