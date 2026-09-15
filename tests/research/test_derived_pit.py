from dataclasses import FrozenInstanceError

import pytest

from analysis.research.derived_pit import (
    DerivedInputAvailability,
    DerivedPITMetadata,
    build_derived_pit,
    evaluate_derived_pit,
)
from analysis.research.pit_guard import PITStatus


def test_latest_required_input_controls_derived_availability():
    inputs = (
        DerivedInputAvailability("market.close", "2026-04-30T15:00:00+08:00"),
        DerivedInputAvailability("industry.membership", "2026-04-30T15:20:00+08:00"),
        DerivedInputAvailability("financial.release", "2026-04-30T18:00:00+08:00"),
    )

    metadata = build_derived_pit(inputs, formula_version="stock_context_v1")

    assert metadata.available_at == "2026-04-30T18:00:00+08:00"
    assert metadata.derived_from == (
        "market.close",
        "industry.membership",
        "financial.release",
    )
    assert metadata.formula_version == "stock_context_v1"


def test_unknown_required_input_keeps_derived_availability_unknown():
    inputs = (
        DerivedInputAvailability("market.close", "2026-04-30T15:00:00+08:00"),
        DerivedInputAvailability("financial.release", None),
    )

    metadata = build_derived_pit(inputs, formula_version="feature_v1")
    decision = evaluate_derived_pit(metadata, "2026-04-30T20:00:00+08:00")

    assert metadata.available_at is None
    assert metadata.derived_from == ("market.close", "financial.release")
    assert decision.status is PITStatus.UNKNOWN
    assert decision.reason == "derived_availability_unknown"


def test_derived_feature_available_after_decision_is_rejected():
    metadata = DerivedPITMetadata(
        available_at="2026-04-30T18:00:00+08:00",
        derived_from=("input.a", "input.b"),
        formula_version="feature_v1",
    )

    decision = evaluate_derived_pit(metadata, "2026-04-30T17:59:59+08:00")

    assert decision.status is PITStatus.REJECT
    assert decision.reason == "derived_available_after_decision"
    assert decision.allowed is False


def test_derived_feature_is_allowed_at_exact_availability_time():
    metadata = DerivedPITMetadata(
        available_at="2026-04-30T18:00:00+08:00",
        derived_from=("input.a",),
        formula_version="feature_v1",
    )

    decision = evaluate_derived_pit(metadata, "2026-04-30T18:00:00+08:00")

    assert decision.status is PITStatus.ALLOW
    assert decision.reason == "derived_allowed"
    assert decision.allowed is True


def test_timezone_aware_inputs_compare_by_actual_instant():
    inputs = (
        DerivedInputAvailability("input.a", "2026-04-30T08:00:00+08:00"),
        DerivedInputAvailability("input.b", "2026-04-30T00:30:00Z"),
    )

    metadata = build_derived_pit(inputs, formula_version="feature_v1")

    assert metadata.available_at == "2026-04-30T00:30:00Z"


def test_mixed_aware_and_naive_input_timestamps_are_rejected():
    inputs = (
        DerivedInputAvailability("input.a", "2026-04-30T08:00:00+08:00"),
        DerivedInputAvailability("input.b", "2026-04-30T09:00:00"),
    )

    with pytest.raises(ValueError, match="compatible timezone semantics"):
        build_derived_pit(inputs, formula_version="feature_v1")


def test_decision_time_timezone_must_match_derived_availability_semantics():
    metadata = DerivedPITMetadata(
        available_at="2026-04-30T18:00:00+08:00",
        derived_from=("input.a",),
        formula_version="feature_v1",
    )

    with pytest.raises(ValueError, match="compatible timezone semantics"):
        evaluate_derived_pit(metadata, "2026-04-30T18:00:00")


def test_duplicate_input_ids_are_rejected_case_insensitively():
    inputs = (
        DerivedInputAvailability("Market.Close", "2026-04-30T15:00:00"),
        DerivedInputAvailability("market.close", "2026-04-30T15:01:00"),
    )

    with pytest.raises(ValueError, match="input_id values must be unique"):
        build_derived_pit(inputs, formula_version="feature_v1")


def test_empty_or_non_tuple_inputs_are_rejected():
    with pytest.raises(ValueError, match="non-empty tuple"):
        build_derived_pit((), formula_version="feature_v1")

    with pytest.raises(ValueError, match="non-empty tuple"):
        build_derived_pit([], formula_version="feature_v1")  # type: ignore[arg-type]


def test_invalid_input_item_or_timestamp_is_rejected():
    with pytest.raises(TypeError, match="DerivedInputAvailability"):
        build_derived_pit((object(),), formula_version="feature_v1")  # type: ignore[arg-type]

    inputs = (DerivedInputAvailability("input.a", "not-a-timestamp"),)
    with pytest.raises(ValueError, match="ISO timestamp"):
        build_derived_pit(inputs, formula_version="feature_v1")


def test_formula_version_and_input_identity_are_required():
    with pytest.raises(ValueError, match="input_id"):
        DerivedInputAvailability(" ", "2026-04-30")

    inputs = (DerivedInputAvailability("input.a", "2026-04-30"),)
    with pytest.raises(ValueError, match="formula_version"):
        build_derived_pit(inputs, formula_version=" ")


def test_derived_metadata_is_immutable_and_provenance_is_a_tuple():
    metadata = build_derived_pit(
        (DerivedInputAvailability("input.a", "2026-04-30"),),
        formula_version="feature_v1",
    )

    assert isinstance(metadata.derived_from, tuple)
    with pytest.raises(FrozenInstanceError):
        metadata.formula_version = "feature_v2"  # type: ignore[misc]
