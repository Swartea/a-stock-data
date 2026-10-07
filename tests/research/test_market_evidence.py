"""Offline contract tests for the S2 MarketEvidence record."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from analysis.fetcher_contract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
)
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.market_evidence import MarketEvidence
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import build_default_provider_registry
from analysis.research.quality import (
    CompletenessStatus,
    FreshnessStatus,
    QualityMetadata,
)
from analysis.research.time_semantics import TimeMetadata

CSI_300 = IndexIdentity("csi.300", IndexPublisher.CSI, "000300")
EASTMONEY = build_default_provider_registry().require("eastmoney")


def _evidence(**overrides) -> MarketEvidence:
    values = {
        "evidence_id": "evidence-csi300-close-20261007",
        "subject": CSI_300,
        "metric": "close",
        "observation": Decimal("3900.25"),
        "provider": EASTMONEY,
        "time": TimeMetadata(
            fetched_at="2026-10-07T15:01:00+08:00",
            data_as_of="2026-10-07T15:00:00+08:00",
        ),
        "quality": QualityMetadata(
            freshness=FreshnessStatus.UNKNOWN,
            completeness=CompletenessStatus.COMPLETE,
        ),
        "pit_status": PITStatus.UNKNOWN,
        "status": STATUS_OK,
    }
    values.update(overrides)
    return MarketEvidence(**values)


def test_contract_surface_composes_existing_research_metadata():
    assert MarketEvidence.contract_fields() == (
        "evidence_id",
        "subject",
        "metric",
        "observation",
        "provider",
        "time",
        "quality",
        "pit_status",
        "status",
    )


def test_evidence_keeps_record_and_subject_identity_separate():
    evidence = _evidence()

    assert evidence.evidence_id == "evidence-csi300-close-20261007"
    assert evidence.subject is CSI_300
    assert evidence.subject.index_id == "csi.300"
    assert evidence.provider is EASTMONEY
    assert evidence.provider.provider_id == "eastmoney"


def test_data_time_and_fetch_time_remain_separate():
    evidence = _evidence()

    assert evidence.time.data_as_of == "2026-10-07T15:00:00+08:00"
    assert evidence.time.fetched_at == "2026-10-07T15:01:00+08:00"


def test_unknown_data_time_quality_and_pit_status_are_preserved():
    evidence = _evidence(
        time=TimeMetadata(fetched_at="2026-10-07T15:01:00+08:00"),
        quality=QualityMetadata(),
        pit_status=PITStatus.UNKNOWN,
    )

    assert evidence.time.data_as_of is None
    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN
    assert evidence.quality.completeness is CompletenessStatus.UNKNOWN
    assert evidence.pit_status is PITStatus.UNKNOWN
    assert evidence.status == STATUS_OK


@pytest.mark.parametrize("value", [0, 0.0, Decimal("0"), "flat", True])
def test_zero_and_other_scalar_values_are_not_treated_as_missing(value):
    evidence = _evidence(observation=value)

    assert evidence.observation == value
    assert evidence.status == STATUS_OK


def test_explicit_empty_observation_is_none_not_zero():
    evidence = _evidence(
        observation=None,
        status=STATUS_EMPTY,
        quality=QualityMetadata(completeness=CompletenessStatus.EMPTY),
    )

    assert evidence.observation is None
    assert evidence.status == STATUS_EMPTY
    assert evidence.quality.completeness is CompletenessStatus.EMPTY


@pytest.mark.parametrize("status", [STATUS_ERROR, STATUS_UNSUPPORTED])
def test_error_and_unsupported_preserve_missing_observation(status):
    evidence = _evidence(
        observation=None,
        status=status,
        quality=QualityMetadata(),
    )

    assert evidence.observation is None
    assert evidence.status == status
    assert evidence.quality.completeness is CompletenessStatus.UNKNOWN


def test_ok_status_requires_an_observation():
    with pytest.raises(ValueError, match="ok evidence must carry an observation"):
        _evidence(observation=None)


@pytest.mark.parametrize("status", [STATUS_EMPTY, STATUS_ERROR, STATUS_UNSUPPORTED])
def test_non_ok_status_rejects_an_observation(status):
    with pytest.raises(ValueError, match="non-ok evidence must not carry an observation"):
        _evidence(status=status)


def test_empty_status_requires_empty_quality():
    with pytest.raises(ValueError, match="empty evidence must have empty completeness"):
        _evidence(
            observation=None,
            status=STATUS_EMPTY,
            quality=QualityMetadata(),
        )


@pytest.mark.parametrize("status", [STATUS_ERROR, STATUS_UNSUPPORTED])
@pytest.mark.parametrize(
    "completeness",
    [CompletenessStatus.COMPLETE, CompletenessStatus.PARTIAL, CompletenessStatus.EMPTY],
)
def test_error_and_unsupported_require_unknown_completeness(status, completeness):
    with pytest.raises(
        ValueError,
        match="error or unsupported evidence must have unknown completeness",
    ):
        _evidence(
            observation=None,
            status=status,
            quality=QualityMetadata(completeness=completeness),
        )


@pytest.mark.parametrize(
    "completeness",
    [
        CompletenessStatus.COMPLETE,
        CompletenessStatus.PARTIAL,
        CompletenessStatus.UNKNOWN,
    ],
)
def test_ok_status_accepts_every_non_empty_completeness(completeness):
    evidence = _evidence(quality=QualityMetadata(completeness=completeness))

    assert evidence.status == STATUS_OK
    assert evidence.quality.completeness is completeness
    assert evidence.observation == Decimal("3900.25")


def test_ok_status_cannot_claim_empty_quality():
    with pytest.raises(ValueError, match="ok evidence cannot have empty completeness"):
        _evidence(
            quality=QualityMetadata(completeness=CompletenessStatus.EMPTY),
        )


def test_unknown_fetch_status_is_rejected():
    with pytest.raises(ValueError, match="fetcher statuses"):
        _evidence(status="unknown")


@pytest.mark.parametrize("field_name", ["evidence_id", "metric"])
@pytest.mark.parametrize("value", ["", "   ", " padded "])
def test_record_id_and_metric_must_be_non_empty_trimmed_strings(field_name, value):
    with pytest.raises(ValueError, match="non-empty trimmed string"):
        _evidence(**{field_name: value})


@pytest.mark.parametrize("value", [[], {}, object()])
def test_observation_must_be_a_scalar(value):
    with pytest.raises(TypeError, match="scalar value or None"):
        _evidence(observation=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN")])
def test_non_finite_numeric_observations_are_rejected(value):
    with pytest.raises(ValueError, match="must be finite"):
        _evidence(observation=value)


@pytest.mark.parametrize("value", ["", " padded "])
def test_string_observations_must_be_non_empty_and_trimmed(value):
    with pytest.raises(ValueError, match="observation string"):
        _evidence(observation=value)


def test_existing_identity_and_metadata_types_are_required():
    with pytest.raises(TypeError, match="subject must be IndexIdentity"):
        _evidence(subject="csi.300")
    with pytest.raises(TypeError, match="provider must be ProviderSpec"):
        _evidence(provider="eastmoney")
    with pytest.raises(TypeError, match="time must be TimeMetadata"):
        _evidence(time={"fetched_at": "2026-10-07T15:01:00+08:00"})
    with pytest.raises(TypeError, match="quality must be QualityMetadata"):
        _evidence(quality={})
    with pytest.raises(TypeError, match="pit_status must be PITStatus"):
        _evidence(pit_status="unknown")


def test_evidence_is_immutable():
    evidence = _evidence()

    with pytest.raises(FrozenInstanceError):
        evidence.observation = 0  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        evidence.subject = IndexIdentity("sse.composite", IndexPublisher.SSE, "000001")  # type: ignore[misc]
