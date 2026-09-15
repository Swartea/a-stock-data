from dataclasses import FrozenInstanceError

import pytest

from analysis.research.time_semantics import (
    TIME_FIELDS,
    TIME_FIELD_SEMANTICS,
    TimeMetadata,
)


def test_time_contract_has_seven_distinct_semantics():
    assert TIME_FIELDS == (
        "fetched_at",
        "data_as_of",
        "period_start",
        "period_end",
        "published_at",
        "effective_from",
        "effective_to",
    )
    assert set(TIME_FIELD_SEMANTICS) == set(TIME_FIELDS)


def test_all_time_fields_are_preserved_independently():
    metadata = TimeMetadata(
        fetched_at="2026-09-15T16:30:00+08:00",
        data_as_of="2026-09-14",
        period_start="2026-04-01",
        period_end="2026-06-30",
        published_at="2026-08-28T18:02:00+08:00",
        effective_from="2026-09-01",
        effective_to="2026-12-31",
    )

    assert metadata.to_dict() == {
        "fetched_at": "2026-09-15T16:30:00+08:00",
        "data_as_of": "2026-09-14",
        "period_start": "2026-04-01",
        "period_end": "2026-06-30",
        "published_at": "2026-08-28T18:02:00+08:00",
        "effective_from": "2026-09-01",
        "effective_to": "2026-12-31",
    }


def test_unknown_time_fields_stay_unknown():
    metadata = TimeMetadata(fetched_at="2026-09-15T16:30:00+08:00")

    assert metadata.data_as_of is None
    assert metadata.period_start is None
    assert metadata.period_end is None
    assert metadata.published_at is None
    assert metadata.effective_from is None
    assert metadata.effective_to is None


def test_legacy_as_of_maps_only_to_data_as_of():
    metadata = TimeMetadata.from_legacy(
        fetched_at="2026-09-15T16:30:00+08:00",
        as_of="2026-09-12",
    )

    assert metadata.data_as_of == "2026-09-12"
    assert metadata.period_start is None
    assert metadata.period_end is None
    assert metadata.published_at is None
    assert metadata.effective_from is None
    assert metadata.effective_to is None


def test_period_end_does_not_imply_publication_time():
    metadata = TimeMetadata(
        fetched_at="2026-09-15T16:30:00+08:00",
        period_end="2026-06-30",
    )

    assert metadata.period_end == "2026-06-30"
    assert metadata.published_at is None


def test_effective_time_does_not_imply_data_as_of():
    metadata = TimeMetadata(
        fetched_at="2026-09-15T16:30:00+08:00",
        effective_from="2026-09-01",
    )

    assert metadata.effective_from == "2026-09-01"
    assert metadata.data_as_of is None


def test_fetched_at_is_required_and_non_empty():
    with pytest.raises(ValueError, match="fetched_at"):
        TimeMetadata(fetched_at="")


def test_optional_time_field_rejects_blank_string():
    with pytest.raises(ValueError, match="published_at"):
        TimeMetadata(
            fetched_at="2026-09-15T16:30:00+08:00",
            published_at="   ",
        )


def test_time_metadata_is_immutable():
    metadata = TimeMetadata(fetched_at="2026-09-15T16:30:00+08:00")

    with pytest.raises(FrozenInstanceError):
        metadata.data_as_of = "2026-09-14"  # type: ignore[misc]
