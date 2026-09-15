from copy import deepcopy

import pytest

from analysis.fetcher_contract import make_result
from analysis.research.time_adapter import time_metadata_from_fetcher_result


def test_current_fetcher_contract_maps_only_certified_time_fields():
    result = make_result(
        status="ok",
        data={"value": 1},
        source="fixture.endpoint",
        as_of="2026-09-12",
        fetched_at="2026-09-15T17:30:00+08:00",
    )

    metadata = time_metadata_from_fetcher_result(result)

    assert metadata.fetched_at == "2026-09-15T17:30:00+08:00"
    assert metadata.data_as_of == "2026-09-12"
    assert metadata.period_start is None
    assert metadata.period_end is None
    assert metadata.published_at is None
    assert metadata.effective_from is None
    assert metadata.effective_to is None


def test_adapter_does_not_mutate_fetcher_result():
    result = make_result(
        status="ok",
        data={"rows": [1, 2, 3]},
        as_of="2026-09-12",
        fetched_at="2026-09-15T17:30:00+08:00",
    )
    before = deepcopy(result)

    time_metadata_from_fetcher_result(result)

    assert result == before


def test_uncontracted_future_named_keys_are_not_trusted():
    result = make_result(
        status="ok",
        data={},
        as_of="2026-09-12",
        fetched_at="2026-09-15T17:30:00+08:00",
    )
    result.update(
        {
            "period_end": "2026-06-30",
            "published_at": "2026-08-28T18:02:00+08:00",
            "effective_from": "2026-09-01",
        }
    )

    metadata = time_metadata_from_fetcher_result(result)

    assert metadata.data_as_of == "2026-09-12"
    assert metadata.period_end is None
    assert metadata.published_at is None
    assert metadata.effective_from is None


def test_unknown_legacy_as_of_remains_unknown():
    result = make_result(
        status="empty",
        data=None,
        as_of=None,
        fetched_at="2026-09-15T17:30:00+08:00",
    )

    metadata = time_metadata_from_fetcher_result(result)

    assert metadata.data_as_of is None


def test_missing_fetch_time_is_rejected_instead_of_inferred():
    with pytest.raises(ValueError, match="fetched_at"):
        time_metadata_from_fetcher_result({"as_of": "2026-09-12"})


def test_none_fetch_time_is_rejected_instead_of_inferred():
    with pytest.raises(ValueError, match="fetched_at"):
        time_metadata_from_fetcher_result(
            {"as_of": "2026-09-12", "fetched_at": None}
        )


def test_non_mapping_input_is_rejected():
    with pytest.raises(TypeError, match="mapping"):
        time_metadata_from_fetcher_result(None)  # type: ignore[arg-type]
