"""Offline contract tests for the S6-B market-snapshot JSON projection.

Every provider, index, metric, identity, number, date, and timestamp below is a
**synthetic contract fixture** invented to make the projection rules observable.
None of it is a capture, a golden file, or a claim about any real exchange,
index, provider, trading session, or observed quote.

The module under test is pure and unconnected: it performs no I/O, reads no
clock or environment variable, and is wired into nothing.  These tests drive it
entirely offline.  Expected values are written out literally wherever a literal
is possible, so the assertions do not simply re-run the implementation's own
helpers to compute the answer.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from analysis.fetcher_contract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
)
from analysis.research.freshness import MaxAgePolicy
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_availability import (
    MarketAvailabilityDecision,
    evaluate_market_availability,
)
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_snapshot import MarketSnapshot
from analysis.research.market_snapshot_projection import (
    SCHEMA_VERSION,
    project_market_snapshot,
)
from analysis.research.market_state import MarketStateDecision, evaluate_market_state
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import ProviderSpec
from analysis.research.quality import (
    CompletenessStatus,
    FreshnessStatus,
    QualityMetadata,
)
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import (
    TradingCalendar,
    TradingCalendarDay,
    TradingDayStatus,
)

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]

# --- synthetic contract fixtures -------------------------------------------

SYNTHETIC_SNAPSHOT_ID: Final = "synthetic.market.snapshot"
SYNTHETIC_MARKET: Final = "synthetic-market"
SYNTHETIC_CALENDAR_DATE: Final = "2026-09-14"
SYNTHETIC_FETCHED_AT: Final = "2026-09-14T14:59:30+08:00"
SYNTHETIC_DATA_AS_OF: Final = "2026-09-14T14:59:00+08:00"
SYNTHETIC_EVALUATION_TIME: Final = "2026-09-14T15:00:00+08:00"
SYNTHETIC_STALE_DATA_AS_OF: Final = "2026-09-11T15:00:00+08:00"
SYNTHETIC_UTC_FETCHED_AT: Final = "2026-09-14T06:59:30+00:00"
SYNTHETIC_PERIOD_START: Final = "2026-09-01T00:00:00+08:00"
SYNTHETIC_PERIOD_END: Final = "2026-09-13T23:59:59+08:00"
SYNTHETIC_PUBLISHED_AT: Final = "2026-09-14T09:30:00+08:00"
SYNTHETIC_EFFECTIVE_FROM: Final = "2026-01-01T00:00:00+08:00"
SYNTHETIC_EFFECTIVE_TO: Final = "2026-12-31T23:59:59+08:00"

SUBJECT_CSI: Final = IndexIdentity(
    index_id="synthetic.index.csi",
    publisher=IndexPublisher.CSI,
    local_code="SYN000001",
)
SUBJECT_SZSE: Final = IndexIdentity(
    index_id="synthetic.index.szse",
    publisher=IndexPublisher.SZSE,
    local_code="SYN000002",
)
SUBJECT_CNI: Final = IndexIdentity(
    index_id="synthetic.index.cni",
    publisher=IndexPublisher.CNI,
    local_code="SYN000003",
)

PROVIDER: Final = ProviderSpec(
    provider_id="synthetic-provider",
    display_name="合成样例数据源",
    provider_family="synthetic-vendor",
    aliases=("syn", "合成别名", "synthetic_alias"),
)
PROVIDER_ALT: Final = ProviderSpec(
    provider_id="synthetic-provider-alt",
    display_name="Synthetic Alternate Source",
    provider_family="synthetic-vendor-alt",
)

ALIAS_CSI_PRIMARY: Final = IndexProviderSymbolAlias(
    index_id="synthetic.index.csi",
    provider_id="synthetic-provider",
    provider_symbol="SYN:000001",
)
ALIAS_CSI_SECONDARY: Final = IndexProviderSymbolAlias(
    index_id="synthetic.index.csi",
    provider_id="synthetic-provider-alt",
    provider_symbol="syn.csi.alt.000001",
)
ALIAS_SZSE: Final = IndexProviderSymbolAlias(
    index_id="synthetic.index.szse",
    provider_id="synthetic-provider",
    provider_symbol="SYN:000002",
)

ONE_DAY: Final = timedelta(days=1)
ONE_AND_HALF_SECOND: Final = timedelta(seconds=1, microseconds=500_000)
ONE_MICROSECOND: Final = timedelta(microseconds=1)
NEGATIVE_ONE_MICROSECOND: Final = timedelta(microseconds=-1)
ZERO: Final = timedelta(0)
LONG_DURATION: Final = timedelta(days=400, seconds=7, microseconds=8)

BASE_QUALITY: Final = QualityMetadata(
    freshness=FreshnessStatus.UNKNOWN,
    completeness=CompletenessStatus.UNKNOWN,
    degraded=False,
    quality_flags=(),
)


def _synthetic_snapshot(
    *,
    indexes: tuple[IndexIdentity, ...] = (SUBJECT_CSI, SUBJECT_SZSE),
    provider_symbols: tuple[IndexProviderSymbolAlias, ...] = (
        ALIAS_CSI_PRIMARY,
        ALIAS_CSI_SECONDARY,
        ALIAS_SZSE,
    ),
) -> MarketSnapshot:
    """Build a synthetic snapshot with a fixed, documented identity spine."""

    return MarketSnapshot(
        snapshot_id=SYNTHETIC_SNAPSHOT_ID,
        market=SYNTHETIC_MARKET,
        indexes=indexes,
        provider_symbols=provider_symbols,
    )


def _ok_time(**overrides: Any) -> TimeMetadata:
    """Return synthetic clocks with every other field explicitly ``None``."""

    base: dict[str, Any] = {
        "fetched_at": SYNTHETIC_FETCHED_AT,
        "data_as_of": SYNTHETIC_DATA_AS_OF,
    }
    base.update(overrides)
    return TimeMetadata(**base)


def _evidence(
    *,
    evidence_id: str = "synthetic-evidence-1",
    subject: IndexIdentity = SUBJECT_CSI,
    metric: str = "close",
    observation: Any = Decimal("3187.6500"),
    provider: ProviderSpec = PROVIDER,
    time: TimeMetadata | None = None,
    quality: QualityMetadata = BASE_QUALITY,
    pit_status: PITStatus = PITStatus.ALLOW,
    status: str = STATUS_OK,
) -> MarketEvidence:
    """Build one synthetic S2 evidence record."""

    return MarketEvidence(
        evidence_id=evidence_id,
        subject=subject,
        metric=metric,
        observation=observation,
        provider=provider,
        time=time if time is not None else _ok_time(),
        quality=quality,
        pit_status=pit_status,
        status=status,
    )


def _calendar(status: TradingDayStatus = TradingDayStatus.OPEN) -> TradingCalendar:
    """Return a one-row synthetic calendar for the synthetic calendar date."""

    return TradingCalendar(
        days=(TradingCalendarDay(date=SYNTHETIC_CALENDAR_DATE, status=status),)
    )


_DEFAULT_CALENDAR: Final = object()


def _compose(
    evidence: MarketEvidence,
    *,
    calendar: Any = _DEFAULT_CALENDAR,
    evaluation_time: str = SYNTHETIC_EVALUATION_TIME,
    policy: MaxAgePolicy = MaxAgePolicy(max_age=ONE_DAY),
) -> MarketAvailabilityDecision:
    """Compose a decision through the real S4 -> S5 path.

    The fixture never hand-builds a contradictory FRESH verdict: the calendar
    answer and the freshness verdict are whatever S4 computes from the supplied
    clocks and policy, and S5 classifies that.
    """

    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=_calendar() if calendar is _DEFAULT_CALENDAR else calendar,
        time=evidence.time,
        evaluation_time=evaluation_time,
        policy=policy,
        quality=evidence.quality,
    )
    return evaluate_market_availability(evidence=evidence, state=state)


def _project(**kwargs: Any) -> dict[str, Any]:
    """Return the parsed projection document for convenient field assertions."""

    return json.loads(project_market_snapshot(**kwargs))


def _evidence_row(document: dict[str, Any], evidence_id: str) -> dict[str, Any]:
    """Return one evidence row by id, failing loudly when it is absent."""

    rows = {row["evidence_id"]: row for row in document["evidence"]}
    assert evidence_id in rows, f"missing evidence row: {evidence_id}"
    return rows[evidence_id]


# --- top-level schema -------------------------------------------------------


def test_top_level_schema_is_exactly_five_keys() -> None:
    document = _project(snapshot=_synthetic_snapshot(), evidence=(), decisions=())

    assert list(document) == [
        "evidence",
        "indexes",
        "provider_symbols",
        "schema_version",
        "snapshot",
    ]
    assert document["schema_version"] == "s6.market_snapshot.v1"
    assert SCHEMA_VERSION == "s6.market_snapshot.v1"
    assert document["snapshot"] == {
        "snapshot_id": SYNTHETIC_SNAPSHOT_ID,
        "market": SYNTHETIC_MARKET,
    }
    assert document["evidence"] == []


def test_snapshot_block_has_no_as_of_or_other_clock() -> None:
    """The container carries no clock: inventing one would be a second truth."""

    document = _project(snapshot=_synthetic_snapshot(), evidence=(), decisions=())

    assert set(document["snapshot"]) == {"snapshot_id", "market"}


def test_indexes_and_provider_symbols_follow_snapshot_tuple_order() -> None:
    snapshot = _synthetic_snapshot(
        indexes=(SUBJECT_CNI, SUBJECT_SZSE, SUBJECT_CSI),
        provider_symbols=(ALIAS_SZSE, ALIAS_CSI_SECONDARY, ALIAS_CSI_PRIMARY),
    )

    document = _project(snapshot=snapshot, evidence=(), decisions=())

    assert document["indexes"] == [
        {"index_id": "synthetic.index.cni", "publisher": "cni", "local_code": "SYN000003"},
        {"index_id": "synthetic.index.szse", "publisher": "szse", "local_code": "SYN000002"},
        {"index_id": "synthetic.index.csi", "publisher": "csi", "local_code": "SYN000001"},
    ]
    assert document["provider_symbols"] == [
        {
            "index_id": "synthetic.index.szse",
            "provider_id": "synthetic-provider",
            "provider_symbol": "SYN:000002",
        },
        {
            "index_id": "synthetic.index.csi",
            "provider_id": "synthetic-provider-alt",
            "provider_symbol": "syn.csi.alt.000001",
        },
        {
            "index_id": "synthetic.index.csi",
            "provider_id": "synthetic-provider",
            "provider_symbol": "SYN:000001",
        },
    ]


def test_provider_symbols_are_declared_aliases_only_not_a_selection() -> None:
    """Two aliases for one index stay two entries; nothing says which was used."""

    evidence = _evidence()
    document = _project(snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=())

    assert len(document["provider_symbols"]) == 3
    assert document["evidence"][0]["provider"]["provider_id"] == "synthetic-provider"


# --- evidence row projection ------------------------------------------------


def test_full_evidence_row_round_trip_matches_literal_expectation() -> None:
    """Every projected evidence field is checked against a literal, not a helper."""

    time = TimeMetadata(
        fetched_at=SYNTHETIC_FETCHED_AT,
        data_as_of=SYNTHETIC_DATA_AS_OF,
        period_start=SYNTHETIC_PERIOD_START,
        period_end=SYNTHETIC_PERIOD_END,
        published_at=SYNTHETIC_PUBLISHED_AT,
        effective_from=SYNTHETIC_EFFECTIVE_FROM,
        effective_to=SYNTHETIC_EFFECTIVE_TO,
    )
    quality = QualityMetadata(
        freshness=FreshnessStatus.STALE,
        completeness=CompletenessStatus.PARTIAL,
        degraded=True,
        quality_flags=("stale_source", "cn_flag", "z_flag"),
    )
    evidence = _evidence(time=time, quality=quality)

    document = _project(snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=())

    assert document["evidence"] == [
        {
            "evidence_id": "synthetic-evidence-1",
            "subject": {
                "index_id": "synthetic.index.csi",
                "publisher": "csi",
                "local_code": "SYN000001",
            },
            "metric": "close",
            "observation": "3187.6500",
            "observation_type": "decimal",
            "provider": {
                "provider_id": "synthetic-provider",
                "display_name": "合成样例数据源",
                "provider_family": "synthetic-vendor",
                "aliases": ["syn", "合成别名", "synthetic_alias"],
            },
            "time": {
                "fetched_at": "2026-09-14T14:59:30+08:00",
                "data_as_of": "2026-09-14T14:59:00+08:00",
                "period_start": "2026-09-01T00:00:00+08:00",
                "period_end": "2026-09-13T23:59:59+08:00",
                "published_at": "2026-09-14T09:30:00+08:00",
                "effective_from": "2026-01-01T00:00:00+08:00",
                "effective_to": "2026-12-31T23:59:59+08:00",
            },
            "quality": {
                "freshness": "stale",
                "completeness": "partial",
                "degraded": True,
                "quality_flags": ["stale_source", "cn_flag", "z_flag"],
            },
            "pit_status": "allow",
            "status": "ok",
            "decisions": [],
        }
    ]


def test_six_optional_clocks_stay_null_and_are_never_interpolated() -> None:
    """Six nulls remain six nulls: no clock is copied from an adjacent field."""

    time = TimeMetadata(fetched_at=SYNTHETIC_FETCHED_AT, data_as_of=None)
    evidence = _evidence(time=time)

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )["evidence"][0]

    assert row["time"] == {
        "fetched_at": "2026-09-14T14:59:30+08:00",
        "data_as_of": None,
        "period_start": None,
        "period_end": None,
        "published_at": None,
        "effective_from": None,
        "effective_to": None,
    }
    assert len(row["time"]) == 7


def test_all_seven_clocks_keep_their_original_strings_and_offsets() -> None:
    time = TimeMetadata(
        fetched_at=SYNTHETIC_UTC_FETCHED_AT,
        data_as_of="2026-09-14T06:59:00+00:00",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-13T23:59:59+08:00",
        published_at="2026-09-14 09:30:00+08:00",
        effective_from="2026-01-01T00:00:00.500+08:00",
        effective_to="2026-12-31T23:59:59-05:00",
    )
    evidence = _evidence(time=time)

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )["evidence"][0]

    assert row["time"]["fetched_at"] == "2026-09-14T06:59:30+00:00"
    assert row["time"]["data_as_of"] == "2026-09-14T06:59:00+00:00"
    assert row["time"]["period_start"] == "2026-09-01T00:00:00Z"
    assert row["time"]["period_end"] == "2026-09-13T23:59:59+08:00"
    assert row["time"]["published_at"] == "2026-09-14 09:30:00+08:00"
    assert row["time"]["effective_from"] == "2026-01-01T00:00:00.500+08:00"
    assert row["time"]["effective_to"] == "2026-12-31T23:59:59-05:00"


# --- scalar encoding --------------------------------------------------------


@pytest.mark.parametrize(
    ("observation", "expected_value", "expected_type"),
    [
        (Decimal("3187.6500"), "3187.6500", "decimal"),
        (Decimal("0"), "0", "decimal"),
        (Decimal("-0.000"), "-0.000", "decimal"),
        (Decimal("1E+2"), "1E+2", "decimal"),
        (Decimal("1.5E-7"), "1.5E-7", "decimal"),
        (
            Decimal("123456789012345678901234567890.123456789012345678901234567890"),
            "123456789012345678901234567890.123456789012345678901234567890",
            "decimal",
        ),
        (3187.65, 3187.65, "float"),
        (-0.0, -0.0, "float"),
        (0.0, 0.0, "float"),
        (0, 0, "int"),
        (-42, -42, "int"),
        (True, True, "bool"),
        (False, False, "bool"),
        ("3187.65", "3187.65", "str"),
        (None, None, "null"),
    ],
)
def test_scalar_observation_types_and_representations(
    observation: Any, expected_value: Any, expected_type: str
) -> None:
    """Type labels and rendered values stay exact for every legal S2 scalar."""

    is_null = observation is None
    evidence = _evidence(
        observation=observation,
        status=STATUS_EMPTY if is_null else STATUS_OK,
        quality=QualityMetadata(completeness=CompletenessStatus.EMPTY)
        if is_null
        else BASE_QUALITY,
    )

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )["evidence"][0]

    assert row["observation_type"] == expected_type
    if expected_type == "float" and math.copysign(1.0, observation) < 0:
        # Negative zero must not be normalised to 0.0 by a truthiness test.
        assert str(row["observation"]) == "-0.0"
        assert row["observation"] == 0.0
    else:
        assert row["observation"] == expected_value


def test_bool_is_labelled_before_int() -> None:
    """``True`` is an int subclass; the label must still say ``bool``."""

    true_row = _project(
        snapshot=_synthetic_snapshot(), evidence=[_evidence(observation=True)], decisions=()
    )["evidence"][0]
    int_row = _project(
        snapshot=_synthetic_snapshot(), evidence=[_evidence(observation=1)], decisions=()
    )["evidence"][0]

    assert true_row["observation_type"] == "bool"
    assert int_row["observation_type"] == "int"


def test_bool_and_int_observations_are_not_interchangeable_on_the_wire() -> None:
    bool_text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[_evidence(observation=True)], decisions=()
    )
    int_text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[_evidence(observation=1)], decisions=()
    )

    assert bool_text != int_text
    assert '"observation": true' in bool_text
    assert '"observation": 1' in int_text


def test_decimal_trailing_zeros_and_exponent_are_preserved() -> None:
    cases = {
        "1.10": "1.10",
        "1.1": "1.1",
        "100": "100",
        "1E+2": "1E+2",
        "0.000000000000000000001": "1E-21",
    }
    for text, expected in cases.items():
        row = _project(
            snapshot=_synthetic_snapshot(),
            evidence=[_evidence(observation=Decimal(text))],
            decisions=(),
        )["evidence"][0]
        assert row["observation"] == expected
        assert row["observation_type"] == "decimal"


def test_float_is_a_json_number_not_a_string() -> None:
    text = project_market_snapshot(
        snapshot=_synthetic_snapshot(),
        evidence=[_evidence(observation=1.5)],
        decisions=(),
    )

    assert '"observation": 1.5' in text
    assert '"observation": "1.5"' not in text


def test_empty_observation_string_is_rejected_by_s2_not_manufactured() -> None:
    """An empty string is not a legal observation; test S2's own rejection."""

    with pytest.raises(ValueError, match="non-empty"):
        _evidence(observation="")


def test_chinese_text_survives_as_real_characters() -> None:
    evidence = _evidence(observation="合成收盘价")
    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )["evidence"][0]

    assert row["observation"] == "合成收盘价"
    assert row["observation_type"] == "str"
    assert "合成收盘价" in project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )


# --- durations --------------------------------------------------------------


def _with_age(decision: MarketAvailabilityDecision, age: timedelta) -> MarketAvailabilityDecision:
    """Return ``decision`` with its S4 freshness age replaced by ``age``.

    Only used to reach durations S4's own evaluation cannot produce (a negative
    age, a multi-day span); the surrounding record stays a valid S5 decision, so
    the test exercises the encoding of a legal contract value rather than a
    fabricated one.
    """

    state = decision.state
    freshness = type(state.freshness)(status=state.freshness.status, reason=state.freshness.reason, age=age)
    quality = replace(state.quality, freshness=freshness.status)
    return replace(decision, state=replace(state, freshness=freshness, quality=quality))


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (ZERO, "0.000000"),
        (ONE_MICROSECOND, "0.000001"),
        (NEGATIVE_ONE_MICROSECOND, "-0.000001"),
        (ONE_AND_HALF_SECOND, "1.500000"),
        (ONE_DAY, "86400.000000"),
        (LONG_DURATION, "34560007.000008"),
        (timedelta(seconds=-90, microseconds=-1), "-90.000001"),
        (timedelta(days=-1), "-86400.000000"),
    ],
)
def test_freshness_age_is_an_exact_signed_seconds_string(age: timedelta, expected: str) -> None:
    """Ages are integer microsecond totals: fixed six decimals, never exponent."""

    evidence = _evidence()
    decision = _with_age(_compose(evidence), age)

    entry = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]["decisions"][0]
    projected = entry["state"]["freshness"]["age_seconds"]

    assert projected == expected
    assert "e" not in projected.lower()
    assert len(projected.split(".")[1]) == 6


@pytest.mark.parametrize(
    ("policy_age", "expected"),
    [
        (ZERO, "0.000000"),
        (ONE_MICROSECOND, "0.000001"),
        (ONE_AND_HALF_SECOND, "1.500000"),
        (ONE_DAY, "86400.000000"),
        (LONG_DURATION, "34560007.000008"),
    ],
)
def test_policy_max_age_is_an_exact_non_negative_seconds_string(
    policy_age: timedelta, expected: str
) -> None:
    """The policy is echoed, never defaulted and never recomputed."""

    evidence = _evidence()
    policy = MaxAgePolicy(max_age=policy_age)
    base = _compose(evidence, policy=policy)
    decision = replace(base, state=replace(base.state, policy=policy))

    entry = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]["decisions"][0]

    assert entry["state"]["policy"] == {"max_age": expected}


def test_negative_zero_duration_keeps_its_signed_zero_form() -> None:
    """A zero age is ``0.000000`` and a zero max_age is never invented as null."""

    evidence = _evidence()
    zero_policy = MaxAgePolicy(max_age=ZERO)
    base = _compose(evidence, policy=zero_policy)
    decision = replace(base, state=replace(base.state, policy=zero_policy))

    entry = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]["decisions"][0]

    assert entry["state"]["policy"]["max_age"] == "0.000000"
    assert entry["state"]["freshness"]["age_seconds"] == "60.000000"


def test_freshness_age_is_none_when_data_as_of_is_unknown() -> None:
    """An unknown clock stays ``null``; no policy default is invented for it."""

    evidence = _evidence(time=TimeMetadata(fetched_at=SYNTHETIC_FETCHED_AT, data_as_of=None))
    decision = _compose(evidence)
    assert decision.state.freshness.age is None

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]

    assert row["decisions"][0]["state"]["freshness"]["age_seconds"] is None
    assert row["decisions"][0]["state"]["policy"]["max_age"] == "86400.000000"


def test_stale_evidence_keeps_its_exact_positive_age() -> None:
    time = _ok_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF)
    evidence = _evidence(time=time)
    decision = _compose(evidence)
    assert decision.state.freshness.status is FreshnessStatus.STALE

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]

    # 2026-09-11T15:00:00+08:00 -> 2026-09-14T15:00:00+08:00 is exactly 3 days.
    assert row["decisions"][0]["state"]["freshness"]["age_seconds"] == "259200.000000"


def test_subsecond_policy_is_encoded_with_fixed_six_decimals() -> None:
    evidence = _evidence()
    decision = _compose(evidence, policy=MaxAgePolicy(max_age=ONE_AND_HALF_SECOND))
    state = replace(decision.state, policy=MaxAgePolicy(max_age=ONE_AND_HALF_SECOND))

    row = _project(
        snapshot=_synthetic_snapshot(),
        evidence=[evidence],
        decisions=[replace(decision, state=state)],
    )["evidence"][0]

    assert row["decisions"][0]["state"]["policy"]["max_age"] == "1.500000"


def test_zero_age_is_distinct_from_missing_age() -> None:
    evidence = _evidence()
    decision = _compose(evidence, evaluation_time=SYNTHETIC_DATA_AS_OF)
    state = replace(
        decision.state,
        freshness=type(decision.state.freshness)(
            status=FreshnessStatus.FRESH,
            reason=decision.state.freshness.reason,
            age=ZERO,
        ),
    )

    row = _project(
        snapshot=_synthetic_snapshot(),
        evidence=[evidence],
        decisions=[replace(decision, state=state)],
    )["evidence"][0]

    assert row["decisions"][0]["state"]["freshness"]["age_seconds"] == "0.000000"


# --- decision projection ----------------------------------------------------


def test_decision_has_exactly_state_and_availability_keys() -> None:
    evidence = _evidence()
    decision = _compose(evidence)

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]

    assert set(row["decisions"][0]) == {"state", "availability"}
    assert set(row["decisions"][0]["state"]) == {
        "calendar_date",
        "trading_day_status",
        "calendar_reason",
        "time",
        "evaluation_time",
        "policy",
        "freshness",
        "quality",
    }
    assert set(row["decisions"][0]["state"]["freshness"]) == {
        "status",
        "reason",
        "age_seconds",
    }
    assert "age" not in row["decisions"][0]["state"]["freshness"]
    assert set(row["decisions"][0]["state"]["policy"]) == {"max_age"}
    assert set(row["decisions"][0]["availability"]) == {"status", "reason", "quality"}
    assert set(row["decisions"][0]["availability"]["quality"]) == {
        "freshness",
        "completeness",
        "degraded",
        "quality_flags",
    }
    assert len(row["decisions"][0]["state"]["time"]) == 7


def test_state_and_availability_quality_are_the_same_envelope() -> None:
    evidence = _evidence()
    decision = _compose(evidence)

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]
    entry = row["decisions"][0]

    assert entry["availability"]["quality"] == entry["state"]["quality"]
    assert entry["state"]["quality"]["freshness"] == entry["state"]["freshness"]["status"]


def test_no_index_id_is_invented_inside_a_decision() -> None:
    evidence = _evidence()
    decision = _compose(evidence)

    text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )
    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]

    assert "synthetic.index.csi" in text  # the identity exists once, on the row
    assert "index_id" not in row["decisions"][0]["state"]
    assert "index_id" not in row["decisions"][0]["availability"]


def test_unknown_calendar_and_unknown_clock_stay_explicit() -> None:
    evidence = _evidence(time=TimeMetadata(fetched_at=SYNTHETIC_FETCHED_AT))
    decision = _compose(evidence, calendar=None)

    entry = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]["decisions"][0]

    assert entry["state"]["trading_day_status"] == "unknown"
    assert entry["state"]["calendar_reason"] == "calendar_not_supplied"
    assert entry["state"]["freshness"]["status"] == "unknown"
    assert entry["state"]["freshness"]["age_seconds"] is None
    assert entry["availability"] == {
        "status": "unknown",
        "reason": "observation_time_unknown",
        "quality": {
            "freshness": "unknown",
            "completeness": "unknown",
            "degraded": False,
            "quality_flags": [],
        },
    }


def test_four_unknown_calendar_causes_stay_distinguishable() -> None:
    empty_calendar = TradingCalendar(days=())
    other_date_calendar = TradingCalendar(
        days=(
            TradingCalendarDay(date="2026-09-11", status=TradingDayStatus.OPEN),
        )
    )
    unknown_row_calendar = TradingCalendar(
        days=(
            TradingCalendarDay(
                date=SYNTHETIC_CALENDAR_DATE, status=TradingDayStatus.UNKNOWN
            ),
        )
    )
    evidence = _evidence()

    reasons = []
    for calendar in (None, empty_calendar, other_date_calendar, unknown_row_calendar):
        decision = _compose(evidence, calendar=calendar)
        entry = _project(
            snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
        )["evidence"][0]["decisions"][0]
        reasons.append((entry["state"]["trading_day_status"], entry["state"]["calendar_reason"]))

    assert reasons == [
        ("unknown", "calendar_not_supplied"),
        ("unknown", "calendar_has_no_observations"),
        ("unknown", "calendar_date_not_observed"),
        ("unknown", "calendar_row_explicitly_unknown"),
    ]


@pytest.mark.parametrize(
    ("calendar_status", "expected_availability", "expected_reason", "expected_reason_row"),
    [
        (
            TradingDayStatus.OPEN,
            "available",
            "observation_fresh",
            "calendar_row_explicitly_open",
        ),
        (
            TradingDayStatus.CLOSED,
            "available",
            "observation_fresh",
            "calendar_row_explicitly_closed",
        ),
        (None, "available", "observation_fresh", "calendar_not_supplied"),
    ],
)
def test_calendar_status_does_not_change_availability(
    calendar_status: TradingDayStatus | None,
    expected_availability: str,
    expected_reason: str,
    expected_reason_row: str,
) -> None:
    """Calendar state and availability are separate dimensions, not merged."""

    evidence = _evidence()
    calendar = None if calendar_status is None else _calendar(calendar_status)
    decision = _compose(evidence, calendar=calendar)

    entry = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
    )["evidence"][0]["decisions"][0]

    assert entry["availability"]["status"] == expected_availability
    assert entry["availability"]["reason"] == expected_reason
    assert entry["state"]["calendar_reason"] == expected_reason_row


def test_all_five_availability_results_carry_their_own_reason() -> None:
    """Five statuses, eight reasons, all produced through the real S4 -> S5 path."""

    empty_quality = QualityMetadata(
        completeness=CompletenessStatus.EMPTY, quality_flags=("no_rows",)
    )
    error_quality = QualityMetadata(
        completeness=CompletenessStatus.UNKNOWN, quality_flags=("provider_timeout",)
    )
    partial_quality = QualityMetadata(
        completeness=CompletenessStatus.PARTIAL,
        degraded=True,
        quality_flags=("partial_rows", "cn_flag"),
    )

    cases = [
        (
            _evidence(observation=Decimal("1.0"), pit_status=PITStatus.ALLOW),
            "available",
            "observation_fresh",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-empty",
                observation=None,
                status=STATUS_EMPTY,
                quality=empty_quality,
            ),
            "missing",
            "source_empty",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-error",
                observation=None,
                status=STATUS_ERROR,
                quality=error_quality,
            ),
            "unavailable",
            "source_error",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-unsupported",
                observation=None,
                status=STATUS_UNSUPPORTED,
                quality=error_quality,
            ),
            "unavailable",
            "provider_unsupported",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-pit-reject",
                observation=Decimal("2.5"),
                pit_status=PITStatus.REJECT,
                quality=partial_quality,
            ),
            "unavailable",
            "pit_rejected",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-pit-unknown",
                observation=Decimal("2.5"),
                pit_status=PITStatus.UNKNOWN,
                quality=partial_quality,
            ),
            "unknown",
            "pit_unknown",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-stale",
                time=_ok_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF),
                quality=partial_quality,
            ),
            "delayed",
            "observation_stale",
        ),
        (
            _evidence(
                evidence_id="synthetic-evidence-clock-unknown",
                time=TimeMetadata(fetched_at=SYNTHETIC_FETCHED_AT),
            ),
            "unknown",
            "observation_time_unknown",
        ),
    ]

    observed: dict[str, set[str]] = {}
    for evidence, expected_status, expected_reason in cases:
        decision = _compose(evidence)
        row = _evidence_row(
            _project(
                snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
            ),
            evidence.evidence_id,
        )
        entry = row["decisions"][0]
        assert entry["availability"]["status"] == expected_status
        assert entry["availability"]["reason"] == expected_reason
        observed.setdefault(expected_status, set()).add(expected_reason)

    assert observed == {
        "available": {"observation_fresh"},
        "missing": {"source_empty"},
        "delayed": {"observation_stale"},
        "unavailable": {"source_error", "provider_unsupported", "pit_rejected"},
        "unknown": {"pit_unknown", "observation_time_unknown"},
    }


def test_source_pit_freshness_dimensions_stay_independent() -> None:
    """A stale observation stays AVAILABLE-shaped in PIT but DELAYED in time."""

    evidence = _evidence(
        time=_ok_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF),
        pit_status=PITStatus.REJECT,
    )
    decision = _compose(evidence)

    row = _evidence_row(
        _project(snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]),
        evidence.evidence_id,
    )

    assert row["status"] == "ok"
    assert row["pit_status"] == "reject"
    assert row["decisions"][0]["state"]["freshness"]["status"] == "stale"
    assert row["decisions"][0]["availability"] == {
        "status": "unavailable",
        "reason": "pit_rejected",
        "quality": {
            "freshness": "stale",
            "completeness": "unknown",
            "degraded": False,
            "quality_flags": [],
        },
    }


def test_missing_and_stale_values_are_preserved_verbatim() -> None:
    """A MISSING verdict keeps its EMPTY source status and its flags."""

    quality = QualityMetadata(
        completeness=CompletenessStatus.EMPTY, quality_flags=("no_rows", "cn_missing")
    )
    evidence = _evidence(
        evidence_id="synthetic-evidence-empty-flags",
        observation=None,
        status=STATUS_EMPTY,
        quality=quality,
        time=TimeMetadata(fetched_at=SYNTHETIC_FETCHED_AT),
    )
    decision = _compose(evidence)

    row = _evidence_row(
        _project(snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]),
        evidence.evidence_id,
    )

    assert row["observation"] is None
    assert row["observation_type"] == "null"
    assert row["status"] == "empty"
    assert row["quality"]["quality_flags"] == ["no_rows", "cn_missing"]
    assert row["decisions"][0]["availability"]["status"] == "missing"
    assert row["decisions"][0]["availability"]["reason"] == "source_empty"


def test_quality_flags_and_provider_alias_order_are_preserved() -> None:
    flags = ("z_first", "a_second", "c_third", "d_fourth")
    provider = ProviderSpec(
        provider_id="synthetic-order-provider",
        display_name="Synthetic Ordering Source",
        provider_family="synthetic-order",
        aliases=("zeta", "alpha", "alias_zh", "mid"),
    )
    evidence = _evidence(
        observation=Decimal("1"),
        provider=provider,
        quality=QualityMetadata(quality_flags=flags),
    )

    document = _project(
        snapshot=_synthetic_snapshot(indexes=(SUBJECT_CSI,), provider_symbols=()),
        evidence=[evidence],
        decisions=(),
    )

    assert document["evidence"][0]["quality"]["quality_flags"] == list(flags)
    assert document["evidence"][0]["provider"]["aliases"] == list(provider.aliases)


# --- absent / null / EMPTY distinctions -------------------------------------


def test_identity_only_index_keeps_identity_without_any_row() -> None:
    """An uncovered evidence gap is not backfilled with a synthetic record."""

    snapshot = _synthetic_snapshot(indexes=(SUBJECT_CSI, SUBJECT_SZSE))

    document = _project(snapshot=snapshot, evidence=(), decisions=())

    assert [index["index_id"] for index in document["indexes"]] == [
        "synthetic.index.csi",
        "synthetic.index.szse",
    ]
    assert document["evidence"] == []
    assert "empty" not in json.dumps(document, ensure_ascii=False)
    assert "missing" not in json.dumps(document, ensure_ascii=False)


def test_evidence_without_decision_has_an_empty_decisions_array() -> None:
    evidence = _evidence()

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )["evidence"][0]

    assert row["decisions"] == []


def test_absent_explicit_null_and_caller_supplied_empty_stay_three_claims() -> None:
    null_evidence = _evidence(
        evidence_id="synthetic-evidence-null",
        observation=None,
        status=STATUS_EMPTY,
        quality=QualityMetadata(completeness=CompletenessStatus.EMPTY),
    )
    empty_quality = QualityMetadata(completeness=CompletenessStatus.EMPTY)
    empty_evidence = _evidence(
        evidence_id="synthetic-evidence-explicit-empty",
        observation=None,
        status=STATUS_EMPTY,
        quality=empty_quality,
    )
    plain_evidence = _evidence(evidence_id="synthetic-evidence-value")

    document = _project(
        snapshot=_synthetic_snapshot(indexes=(SUBJECT_CSI,), provider_symbols=()),
        evidence=[plain_evidence, empty_evidence, null_evidence],
        decisions=(),
    )
    rows = {row["evidence_id"]: row for row in document["evidence"]}

    assert set(rows) == {
        "synthetic-evidence-value",
        "synthetic-evidence-null",
        "synthetic-evidence-explicit-empty",
    }
    assert rows["synthetic-evidence-value"]["observation"] == "3187.6500"
    assert rows["synthetic-evidence-null"]["observation"] is None
    assert rows["synthetic-evidence-null"]["observation_type"] == "null"
    assert rows["synthetic-evidence-explicit-empty"]["observation"] is None
    assert (
        rows["synthetic-evidence-explicit-empty"]["quality"]["completeness"] == "empty"
    )


def test_different_providers_and_times_stay_independent_rows() -> None:
    first = _evidence(
        evidence_id="synthetic-evidence-provider-a",
        provider=PROVIDER,
        time=_ok_time(),
    )
    second = _evidence(
        evidence_id="synthetic-evidence-provider-b",
        provider=PROVIDER_ALT,
        time=_ok_time(data_as_of=SYNTHETIC_UTC_FETCHED_AT),
    )

    document = _project(
        snapshot=_synthetic_snapshot(indexes=(SUBJECT_CSI,), provider_symbols=()),
        evidence=[second, first],
        decisions=(),
    )

    assert len(document["evidence"]) == 2
    rows = {row["evidence_id"]: row for row in document["evidence"]}
    assert rows["synthetic-evidence-provider-a"]["provider"]["provider_id"] == (
        "synthetic-provider"
    )
    assert rows["synthetic-evidence-provider-b"]["provider"]["provider_id"] == (
        "synthetic-provider-alt"
    )
    assert rows["synthetic-evidence-provider-a"]["time"]["data_as_of"] != (
        rows["synthetic-evidence-provider-b"]["time"]["data_as_of"]
    )
    assert rows["synthetic-evidence-provider-a"]["observation"] == "3187.6500"
    assert rows["synthetic-evidence-provider-b"]["observation"] == "3187.6500"


# --- ordering ---------------------------------------------------------------


def test_evidence_is_sorted_by_index_metric_then_evidence_id() -> None:
    first = _evidence(evidence_id="synthetic-a", subject=SUBJECT_CSI, metric="open")
    second = _evidence(evidence_id="synthetic-b", subject=SUBJECT_CSI, metric="close")
    third = _evidence(evidence_id="synthetic-c", subject=SUBJECT_SZSE, metric="volume")
    fourth = _evidence(evidence_id="synthetic-d", subject=SUBJECT_CSI, metric="close")

    document = _project(
        snapshot=_synthetic_snapshot(),
        evidence=[third, second, fourth, first],
        decisions=(),
    )

    assert [(row["subject"]["index_id"], row["metric"], row["evidence_id"]) for row in
            document["evidence"]] == [
        ("synthetic.index.csi", "close", "synthetic-b"),
        ("synthetic.index.csi", "close", "synthetic-d"),
        ("synthetic.index.csi", "open", "synthetic-a"),
        ("synthetic.index.szse", "volume", "synthetic-c"),
    ]


def test_identical_duplicated_decisions_are_preserved_not_deduplicated() -> None:
    evidence = _evidence()
    first = _compose(evidence)
    duplicate = replace(first)

    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[first, duplicate]
    )["evidence"][0]

    assert len(row["decisions"]) == 2
    assert row["decisions"][0] == row["decisions"][1]


def test_decisions_are_sorted_by_canonical_bytes_with_duplicates_kept() -> None:
    evidence = _evidence()
    open_decision = _compose(evidence, calendar=_calendar(TradingDayStatus.OPEN))
    closed_decision = _compose(evidence, calendar=_calendar(TradingDayStatus.CLOSED))

    forward = _project(
        snapshot=_synthetic_snapshot(),
        evidence=[evidence],
        decisions=[open_decision, closed_decision, open_decision],
    )["evidence"][0]
    backward = _project(
        snapshot=_synthetic_snapshot(),
        evidence=[evidence],
        decisions=[open_decision, closed_decision, open_decision][::-1],
    )["evidence"][0]

    assert forward == backward
    assert len(forward["decisions"]) == 3
    assert forward["decisions"][0]["state"]["calendar_reason"] == (
        "calendar_row_explicitly_closed"
    )
    assert forward["decisions"][1]["state"]["calendar_reason"] == (
        "calendar_row_explicitly_open"
    )


def test_reordered_inputs_produce_identical_bytes() -> None:
    snapshot = _synthetic_snapshot()
    csi_close = _evidence(evidence_id="synthetic-c", subject=SUBJECT_CSI, metric="close")
    csi_open = _evidence(evidence_id="synthetic-a", subject=SUBJECT_CSI, metric="open")
    szse = _evidence(
        evidence_id="synthetic-z",
        subject=SUBJECT_SZSE,
        metric="close",
        provider=PROVIDER_ALT,
    )
    decisions = [_compose(csi_close), _compose(csi_open), _compose(szse)]

    first = project_market_snapshot(
        snapshot=snapshot,
        evidence=[csi_close, csi_open, szse],
        decisions=decisions,
    )
    second = project_market_snapshot(
        snapshot=snapshot,
        evidence=(szse, csi_open, csi_close),
        decisions=tuple(reversed(decisions)),
    )

    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_equal_but_independent_evidence_objects_are_rejected_as_duplicates() -> None:
    """Equal-valued instances still share an id, so ids must stay unique."""

    first = _evidence(evidence_id="synthetic-evidence-1")
    second = _evidence(evidence_id="synthetic-evidence-1")

    assert first is not second
    assert first == second
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[first, second], decisions=()
        )


def test_equal_valued_distinct_ids_remain_two_independent_rows() -> None:
    """Same metric, provider, clocks, and value under two ids: two rows."""

    first = _evidence(evidence_id="synthetic-evidence-1")
    second = _evidence(evidence_id="synthetic-evidence-2")

    document = _project(
        snapshot=_synthetic_snapshot(), evidence=[first, second], decisions=()
    )

    assert len(document["evidence"]) == 2
    assert [row["evidence_id"] for row in document["evidence"]] == [
        "synthetic-evidence-1",
        "synthetic-evidence-2",
    ]
    assert document["evidence"][0]["observation"] == document["evidence"][1]["observation"]


# --- canonical serialization ------------------------------------------------


def test_canonical_text_uses_exact_json_settings_and_one_trailing_newline() -> None:
    text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=(), decisions=()
    )

    assert text.endswith("}\n")
    assert not text.endswith("\n\n")
    assert text.count("\n\n") == 0
    assert '"schema_version"' in text
    assert "\\u" not in text
    assert "\r" not in text
    reparsed = json.loads(text)
    assert json.dumps(
        reparsed, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n" == text


def test_chinese_keys_and_values_are_not_escaped_in_the_text() -> None:
    quality = QualityMetadata(quality_flags=("cn_flag",))
    evidence = _evidence(
        observation="合成值", provider=PROVIDER, quality=quality
    )

    text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )

    assert "合成值" in text
    assert "合成样例数据源" in text
    assert "\\u5408" not in text


def test_text_is_deterministically_utf8_encodable() -> None:
    evidence = _evidence(observation="合成", provider=PROVIDER)

    text = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
    )

    assert isinstance(text, str)
    assert text.encode("utf-8").decode("utf-8") == text


# --- parameter validation ---------------------------------------------------


@pytest.mark.parametrize("name", ["snapshot", "evidence", "decisions"])
def test_all_arguments_are_keyword_only_and_required(name: str) -> None:
    evidence = _evidence()
    valid: dict[str, Any] = {
        "snapshot": _synthetic_snapshot(),
        "evidence": [evidence],
        "decisions": [],
    }

    with pytest.raises(TypeError):
        project_market_snapshot(**{key: value for key, value in valid.items() if key != name})
    with pytest.raises(TypeError):
        project_market_snapshot(_synthetic_snapshot(), evidence, [])


@pytest.mark.parametrize(
    "bad_evidence",
    ["synthetic-evidence-1", b"synthetic-evidence-1", bytearray(b"x"), {"id": "x"}, {"a"}, {1, 2}],
)
def test_invalid_evidence_container_types_are_rejected(bad_evidence: Any) -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=bad_evidence, decisions=()
        )


@pytest.mark.parametrize(
    "bad_decisions",
    ["decisions", b"decisions", {"state": "x"}, {"state"}, {1, 2}],
)
def test_invalid_decisions_container_types_are_rejected(bad_decisions: Any) -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[], decisions=bad_decisions
        )


def test_generators_are_rejected_as_unordered_containers() -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(),
            evidence=(item for item in [_evidence()]),
            decisions=(),
        )
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(),
            evidence=(),
            decisions=(item for item in []),
        )


def test_none_sequences_are_rejected() -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(snapshot=_synthetic_snapshot(), evidence=None, decisions=())
    with pytest.raises(TypeError):
        project_market_snapshot(snapshot=_synthetic_snapshot(), evidence=[], decisions=None)


def test_wrong_element_types_are_rejected() -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[_synthetic_snapshot()], decisions=()
        )
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[_evidence(), "not-evidence"], decisions=()
        )
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(),
            evidence=[],
            decisions=[_synthetic_snapshot()],
        )


def test_non_snapshot_snapshot_argument_is_rejected() -> None:
    with pytest.raises(TypeError):
        project_market_snapshot(
            snapshot="synthetic.market.snapshot", evidence=[], decisions=()
        )


def test_tuple_and_list_inputs_are_both_accepted() -> None:
    evidence = _evidence()

    from_tuple = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=(evidence,), decisions=()
    )
    from_list = project_market_snapshot(
        snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[]
    )

    assert from_tuple == from_list


# --- association and consistency errors -------------------------------------


def test_duplicate_evidence_ids_raise_value_error() -> None:
    first = _evidence(evidence_id="synthetic-duplicate")
    second = _evidence(evidence_id="synthetic-duplicate", metric="open")

    with pytest.raises(ValueError, match="duplicate evidence_id"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[first, second], decisions=()
        )


def test_evidence_subject_with_unknown_index_id_is_rejected() -> None:
    evidence = _evidence(subject=SUBJECT_CNI)

    with pytest.raises(ValueError, match="not covered"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=()
        )


def test_evidence_subject_identity_mismatch_is_rejected() -> None:
    """Same index_id but a different publisher/local_code is a different index."""

    snapshot = _synthetic_snapshot(indexes=(SUBJECT_CSI,), provider_symbols=())
    mismatched = IndexIdentity(
        index_id="synthetic.index.csi",
        publisher=IndexPublisher.SZSE,
        local_code="SYN000002",
    )
    evidence = _evidence(subject=mismatched)

    with pytest.raises(ValueError, match="must equal the snapshot IndexIdentity"):
        project_market_snapshot(snapshot=snapshot, evidence=[evidence], decisions=())


def test_decision_linking_unsupplied_evidence_is_rejected() -> None:
    evidence = _evidence()
    other = _evidence(evidence_id="synthetic-evidence-2")
    decision = _compose(other)

    with pytest.raises(ValueError, match="not supplied"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[evidence], decisions=[decision]
        )


def test_decision_link_matches_an_equal_independent_evidence_object() -> None:
    """A separate instance with the same complete value still links."""

    evidence = _evidence()
    twin = _evidence()
    decision = _compose(evidence)

    assert evidence is not twin
    row = _project(
        snapshot=_synthetic_snapshot(), evidence=[twin], decisions=[decision]
    )["evidence"][0]

    assert len(row["decisions"]) == 1


def test_decision_link_rejects_decimal_representation_mismatch() -> None:
    """``1.0`` and ``1.00`` compare equal but are different wire values."""

    decision_evidence = _evidence(observation=Decimal("1.0"))
    supplied = _evidence(observation=Decimal("1.00"))
    decision = _compose(decision_evidence)

    assert decision_evidence == supplied
    with pytest.raises(ValueError, match="does not match the supplied evidence row"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[supplied], decisions=[decision]
        )


def test_decision_link_rejects_bool_versus_int_mismatch() -> None:
    """``True == 1`` in Python; the projection refuses to conflate them."""

    decision_evidence = _evidence(observation=True)
    supplied = _evidence(observation=1)
    decision = _compose(decision_evidence)

    assert decision_evidence == supplied
    with pytest.raises(ValueError, match="does not match the supplied evidence row"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[supplied], decisions=[decision]
        )


def test_decision_link_rejects_int_versus_float_mismatch() -> None:
    decision_evidence = _evidence(observation=1)
    supplied = _evidence(observation=1.0)
    decision = _compose(decision_evidence)

    assert decision_evidence == supplied
    with pytest.raises(ValueError, match="does not match the supplied evidence row"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[supplied], decisions=[decision]
        )


def test_decision_link_rejects_mismatched_metric_under_the_same_id() -> None:
    decision_evidence = _evidence(metric="close")
    supplied = _evidence(metric="open")
    decision = _compose(decision_evidence)

    with pytest.raises(ValueError, match="does not match the supplied evidence row"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[supplied], decisions=[decision]
        )


def test_decision_link_rejects_mismatched_quality_flag_order() -> None:
    quality = QualityMetadata(quality_flags=("a", "b"))
    other_quality = QualityMetadata(quality_flags=("b", "a"))
    decision_evidence = _evidence(quality=quality)
    supplied = _evidence(quality=other_quality)
    decision = _compose(decision_evidence)

    with pytest.raises(ValueError, match="does not match the supplied evidence row"):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[supplied], decisions=[decision]
        )


def test_errors_never_return_partial_output() -> None:
    first = _evidence(evidence_id="synthetic-evidence-1")
    broken = _evidence(evidence_id="synthetic-evidence-1", metric="open")

    with pytest.raises(ValueError):
        project_market_snapshot(
            snapshot=_synthetic_snapshot(), evidence=[first, broken], decisions=()
        )


# --- purity and immutability ------------------------------------------------


def test_inputs_are_not_mutated_by_projection() -> None:
    snapshot = _synthetic_snapshot()
    evidence = _evidence()
    decision = _compose(evidence)
    snapshot_before = (snapshot.snapshot_id, snapshot.indexes, snapshot.provider_symbols)
    evidence_before = (
        evidence.evidence_id,
        evidence.subject,
        evidence.observation,
        evidence.quality.quality_flags,
    )
    decision_before = (decision.status, decision.reason, decision.state.evaluation_time)
    provider_aliases_before = evidence.provider.aliases

    project_market_snapshot(
        snapshot=snapshot, evidence=[evidence], decisions=[decision]
    )

    assert (snapshot.snapshot_id, snapshot.indexes, snapshot.provider_symbols) == snapshot_before
    assert (
        evidence.evidence_id,
        evidence.subject,
        evidence.observation,
        evidence.quality.quality_flags,
    ) == evidence_before
    assert (decision.status, decision.reason, decision.state.evaluation_time) == decision_before
    assert evidence.provider.aliases == provider_aliases_before


def test_contract_records_are_frozen() -> None:
    evidence = _evidence()
    snapshot = _synthetic_snapshot()

    with pytest.raises(FrozenInstanceError):
        evidence.metric = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.market = "changed"  # type: ignore[misc]


def test_module_has_no_io_environment_or_clock_paths() -> None:
    """Static check: the production module must import nothing ambient."""

    module_path = (
        _PROJECT_ROOT / "analysis" / "research" / "market_snapshot_projection.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    # ``datetime`` is imported only for the ``timedelta`` type; the module must
    # not reach for a clock, a file, the environment, or the network.
    forbidden = {"os", "sys", "socket", "pathlib", "time", "random", "subprocess", "http"}
    assert not (imported & forbidden)
    assert imported <= {
        "json",
        "collections",
        "decimal",
        "datetime",
        "typing",
        "__future__",
        "analysis",
    }

    # Only executable code is scanned: the module docstring legitimately says
    # "no environment variable", which must not fail the check.
    source = module_path.read_text(encoding="utf-8")
    executable: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.Expr, ast.Constant)):
            continue  # prose, including every docstring, is not executable code
        executable.append(ast.get_source_segment(source, node) or "")
    code = "\n".join(executable)
    for token in ("open(", "environ", "print(", "datetime.now", "utcnow", "today("):
        assert token not in code


def test_only_one_public_function_is_exposed() -> None:
    from analysis.research import market_snapshot_projection as projection

    assert projection.__all__ == ["SCHEMA_VERSION", "project_market_snapshot"]
    assert not hasattr(projection, "evaluate_market_state")
    assert not hasattr(projection, "evaluate_market_availability")


# --- cross-process determinism ----------------------------------------------


_CHILD_SCRIPT: Final = r'''
"""Synthetic child process: guards the network, then projects one fixed sample.

The deny guard is installed before any project module is imported, so the
project code cannot have captured a socket reference beforehand.
"""

import json
import socket
import sys

OUTBOUND = []


def _deny(what):
    def guard(*args, **kwargs):
        OUTBOUND.append(what)
        raise OSError("outbound network denied by synthetic test guard: %s" % what)

    return guard


socket.socket.connect = _deny("socket.connect")
socket.socket.connect_ex = _deny("socket.connect_ex")
socket.create_connection = _deny("socket.create_connection")
socket.getaddrinfo = _deny("socket.getaddrinfo")
socket.gethostbyname = _deny("socket.gethostbyname")
socket.getnameinfo = _deny("socket.getnameinfo")

sys.path.insert(0, sys.argv[1])

from datetime import timedelta
from decimal import Decimal

from analysis.research.freshness import MaxAgePolicy
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_availability import evaluate_market_availability
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_snapshot import MarketSnapshot
from analysis.research.market_snapshot_projection import project_market_snapshot
from analysis.research.market_state import evaluate_market_state
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import ProviderSpec
from analysis.research.quality import CompletenessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import (
    TradingCalendar,
    TradingCalendarDay,
    TradingDayStatus,
)

subject_a = IndexIdentity(
    index_id="synthetic.index.csi",
    publisher=IndexPublisher.CSI,
    local_code="SYN000001",
)
subject_b = IndexIdentity(
    index_id="synthetic.index.szse",
    publisher=IndexPublisher.SZSE,
    local_code="SYN000002",
)
provider = ProviderSpec(
    provider_id="synthetic-provider",
    display_name="合成样例数据源",
    provider_family="synthetic-vendor",
    aliases=("syn", "合成别名"),
)
snapshot = MarketSnapshot(
    snapshot_id="synthetic.market.snapshot",
    market="synthetic-market",
    indexes=(subject_a, subject_b),
    provider_symbols=(
        IndexProviderSymbolAlias(
            index_id="synthetic.index.csi",
            provider_id="synthetic-provider",
            provider_symbol="SYN:000001",
        ),
    ),
)
calendar = TradingCalendar(
    days=(
        TradingCalendarDay(date="2026-09-11", status=TradingDayStatus.CLOSED),
        TradingCalendarDay(date="2026-09-14", status=TradingDayStatus.OPEN),
    )
)


def build(evidence_id, subject, metric, observation, pit, status, quality, time):
    return MarketEvidence(
        evidence_id=evidence_id,
        subject=subject,
        metric=metric,
        observation=observation,
        provider=provider,
        time=time,
        quality=quality,
        pit_status=pit,
        status=status,
    )


fresh_time = TimeMetadata(
    fetched_at="2026-09-14T14:59:30+08:00",
    data_as_of="2026-09-14T14:59:00+08:00",
)
unknown_time = TimeMetadata(fetched_at="2026-09-14T14:59:30+08:00")

records = [
    build(
        "synthetic-evidence-z",
        subject_b,
        "合成指标",
        Decimal("1E+3"),
        PITStatus.UNKNOWN,
        "ok",
        QualityMetadata(
            completeness=CompletenessStatus.PARTIAL, quality_flags=("b", "a")
        ),
        fresh_time,
    ),
    build(
        "synthetic-evidence-a",
        subject_a,
        "close",
        Decimal("3187.6500"),
        PITStatus.ALLOW,
        "ok",
        QualityMetadata(quality_flags=("cn_flag",)),
        fresh_time,
    ),
    build(
        "synthetic-evidence-m",
        subject_a,
        "close",
        None,
        PITStatus.ALLOW,
        "empty",
        QualityMetadata(
            completeness=CompletenessStatus.EMPTY, quality_flags=("no_rows",)
        ),
        unknown_time,
    ),
    build(
        "synthetic-evidence-c",
        subject_a,
        "close",
        -0.0,
        PITStatus.ALLOW,
        "ok",
        QualityMetadata(),
        fresh_time,
    ),
]
decisions = []
for record in records:
    state = evaluate_market_state(
        calendar_date="2026-09-14",
        calendar=calendar,
        time=record.time,
        evaluation_time="2026-09-14T15:00:00+08:00",
        policy=MaxAgePolicy(max_age=timedelta(days=1, microseconds=1)),
        quality=record.quality,
    )
    decisions.append(evaluate_market_availability(evidence=record, state=state))

text = project_market_snapshot(
    snapshot=snapshot, evidence=records, decisions=tuple(reversed(decisions))
)

with open(sys.argv[2], "wb") as handle:
    handle.write(text.encode("utf-8"))
with open(sys.argv[3], "w", encoding="utf-8") as handle:
    json.dump({"outbound": OUTBOUND, "count": len(OUTBOUND)}, handle)
'''


def _run_child(tmp_path: Path, *, hash_seed: str, tag: str) -> tuple[bytes, dict[str, Any]]:
    script_path = tmp_path / f"child_{tag}.py"
    script_path.write_text(_CHILD_SCRIPT, encoding="utf-8")
    payload_path = tmp_path / f"payload_{tag}.json"
    report_path = tmp_path / f"report_{tag}.json"
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-B",
            str(script_path),
            str(_PROJECT_ROOT),
            str(payload_path),
            str(report_path),
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    return (
        payload_path.read_bytes(),
        json.loads(report_path.read_text(encoding="utf-8")),
    )


def test_two_processes_with_different_hash_seeds_produce_identical_bytes(
    tmp_path: Path,
) -> None:
    """Cross-process determinism, guarded, with zero outbound attempts."""

    first_bytes, first_report = _run_child(tmp_path, hash_seed="0", tag="first")
    second_bytes, second_report = _run_child(tmp_path, hash_seed="524287", tag="second")

    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()
    assert first_report["count"] == 0
    assert second_report["count"] == 0
    assert first_report["outbound"] == []

    document = json.loads(first_bytes.decode("utf-8"))
    assert document["schema_version"] == "s6.market_snapshot.v1"
    assert [row["evidence_id"] for row in document["evidence"]] == [
        "synthetic-evidence-a",
        "synthetic-evidence-c",
        "synthetic-evidence-m",
        "synthetic-evidence-z",
    ]
    observations = {row["evidence_id"]: row for row in document["evidence"]}
    assert observations["synthetic-evidence-z"]["observation"] == "1E+3"
    assert observations["synthetic-evidence-m"]["observation"] is None
    assert observations["synthetic-evidence-z"]["metric"] == "合成指标"
    assert first_bytes.decode("utf-8").endswith("}\n")
