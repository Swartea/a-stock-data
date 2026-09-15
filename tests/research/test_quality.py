from dataclasses import FrozenInstanceError

import pytest

from analysis.research.quality import (
    CompletenessStatus,
    FreshnessStatus,
    QualityMetadata,
)


def test_quality_contract_surface_is_exact_and_small():
    assert QualityMetadata.contract_fields() == (
        "freshness",
        "completeness",
        "degraded",
        "quality_flags",
    )


def test_quality_enum_values_are_stable():
    assert tuple(item.value for item in FreshnessStatus) == (
        "fresh",
        "stale",
        "unknown",
    )
    assert tuple(item.value for item in CompletenessStatus) == (
        "complete",
        "partial",
        "empty",
        "unknown",
    )


def test_quality_defaults_preserve_unknown_instead_of_guessing():
    quality = QualityMetadata()

    assert quality.freshness is FreshnessStatus.UNKNOWN
    assert quality.completeness is CompletenessStatus.UNKNOWN
    assert quality.degraded is False
    assert quality.quality_flags == ()


def test_explicit_quality_metadata_is_preserved_verbatim():
    quality = QualityMetadata(
        freshness=FreshnessStatus.STALE,
        completeness=CompletenessStatus.PARTIAL,
        degraded=True,
        quality_flags=("fallback_used", "partial_history"),
    )

    assert quality.freshness is FreshnessStatus.STALE
    assert quality.completeness is CompletenessStatus.PARTIAL
    assert quality.degraded is True
    assert quality.quality_flags == ("fallback_used", "partial_history")


def test_quality_metadata_is_immutable():
    quality = QualityMetadata()

    with pytest.raises(FrozenInstanceError):
        quality.degraded = True  # type: ignore[misc]


def test_raw_strings_are_not_silently_coerced_to_enum_values():
    with pytest.raises(TypeError, match="FreshnessStatus"):
        QualityMetadata(freshness="fresh")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="CompletenessStatus"):
        QualityMetadata(completeness="complete")  # type: ignore[arg-type]


def test_degraded_must_be_boolean():
    with pytest.raises(TypeError, match="degraded must be bool"):
        QualityMetadata(degraded=1)  # type: ignore[arg-type]


def test_quality_flags_must_be_immutable_tuple():
    with pytest.raises(TypeError, match="quality_flags must be a tuple"):
        QualityMetadata(quality_flags=["fallback_used"])  # type: ignore[arg-type]


def test_quality_flags_are_canonical_stable_tokens():
    invalid = (
        "",
        "Fallback_Used",
        " fallback_used",
        "fallback_used ",
        "fallback used",
        "fallback/used",
        "fallback..used",
    )

    for flag in invalid:
        with pytest.raises(ValueError):
            QualityMetadata(quality_flags=(flag,))


def test_duplicate_quality_flags_are_rejected():
    with pytest.raises(ValueError, match="duplicate quality flag"):
        QualityMetadata(quality_flags=("fallback_used", "fallback_used"))


def test_degraded_is_independent_from_freshness_and_completeness():
    stale_partial = QualityMetadata(
        freshness=FreshnessStatus.STALE,
        completeness=CompletenessStatus.PARTIAL,
        degraded=False,
    )
    fallback_but_complete = QualityMetadata(
        freshness=FreshnessStatus.FRESH,
        completeness=CompletenessStatus.COMPLETE,
        degraded=True,
        quality_flags=("fallback_used",),
    )

    assert stale_partial.degraded is False
    assert fallback_but_complete.degraded is True


def test_quality_contract_contains_no_scoring_or_provider_policy():
    quality = QualityMetadata()

    for forbidden in (
        "score",
        "weight",
        "provider",
        "provider_id",
        "source",
        "freshness_threshold",
        "max_age",
    ):
        assert not hasattr(quality, forbidden)
