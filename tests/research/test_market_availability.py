"""Offline contract tests for the S5 market-availability classifier.

Every provider, index, metric, date, and timestamp below is a **synthetic
contract fixture** invented to make the ordered classification table
observable.  Nothing here is a claim about any real exchange, index, provider,
trading session, or observed quote, and no test asserts what any live market is
doing.

No network, no clock, no provider call, and no production wiring is involved:
the module under test is pure and unconnected, and these tests drive it entirely
offline.  The fixtures deliberately include degenerate scalars (``0``, ``False``,
``Decimal("0")``) because "available" must never be confused with "truthy".
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal
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
from analysis.research.market_availability import (
    MarketAvailabilityDecision,
    MarketAvailabilityStatus,
    evaluate_market_availability,
)
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_state import MarketStateDecision, evaluate_market_state
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import ProviderSpec
from analysis.research.quality import CompletenessStatus, FreshnessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import TradingDayStatus

# --- synthetic contract fixtures -------------------------------------------

SYNTHETIC_CALENDAR_DATE: Final = "2026-09-14"
SYNTHETIC_FETCHED_AT: Final = "2026-09-14T14:59:30+08:00"
SYNTHETIC_DATA_AS_OF: Final = "2026-09-14T14:59:00+08:00"
SYNTHETIC_EVALUATION_TIME: Final = "2026-09-14T15:00:00+08:00"
SYNTHETIC_STALE_DATA_AS_OF: Final = "2026-09-11T15:00:00+08:00"

_ONE_DAY: Final = timedelta(days=1)
_OTHER_DAY: Final = timedelta(days=5)

_SYNTHETIC_SUBJECT: Final = IndexIdentity(
    index_id="synthetic.market.index",
    publisher=IndexPublisher.CSI,
    local_code="SYNTH0001",
)
_SYNTHETIC_PROVIDER: Final = ProviderSpec(
    provider_id="synthetic",
    display_name="Synthetic Provider",
    provider_family="synthetic",
)


def _time(
    *,
    data_as_of: str | None = SYNTHETIC_DATA_AS_OF,
    fetched_at: str = SYNTHETIC_FETCHED_AT,
    **extra: str,
) -> TimeMetadata:
    """Build a synthetic TimeMetadata; ``data_as_of=None`` means unknown."""

    return TimeMetadata(fetched_at=fetched_at, data_as_of=data_as_of, **extra)


def _quality(**overrides: Any) -> QualityMetadata:
    base: dict[str, Any] = {
        "freshness": FreshnessStatus.UNKNOWN,
        "completeness": CompletenessStatus.COMPLETE,
        "degraded": False,
        "quality_flags": (),
    }
    base.update(overrides)
    return QualityMetadata(**base)


def _evidence(**overrides: Any) -> MarketEvidence:
    """Build a synthetic OK observation; override per scenario."""

    base: dict[str, Any] = {
        "evidence_id": "synthetic-evidence-1",
        "subject": _SYNTHETIC_SUBJECT,
        "metric": "synthetic_metric",
        "observation": Decimal("1.5"),
        "provider": _SYNTHETIC_PROVIDER,
        "time": _time(),
        "quality": _quality(),
        "pit_status": PITStatus.ALLOW,
        "status": STATUS_OK,
    }
    base.update(overrides)
    return MarketEvidence(**base)


def _state(
    evidence: MarketEvidence,
    *,
    evaluation_time: str = SYNTHETIC_EVALUATION_TIME,
    policy: MaxAgePolicy | None = None,
) -> MarketStateDecision:
    """Compose a real S4 decision from ``evidence`` -- never hand-built.

    The calendar is deliberately ``None`` so the tests exercise availability
    without a calendar opinion; availability never reads the calendar status.
    """

    return evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=evidence.time,
        evaluation_time=evaluation_time,
        policy=policy if policy is not None else MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )


def _ok_evidence(**overrides: Any) -> MarketEvidence:
    """Build a synthetic OK/ALLOW observation; overrides pick the scenario.

    No helper here asserts a freshness outcome: the FRESH/STALE/UNKNOWN
    projection is whatever S4 computes from the explicit clock and policy.
    """

    return _evidence(**overrides)


def _classify(evidence: MarketEvidence, **state_kwargs: Any) -> MarketAvailabilityDecision:
    return evaluate_market_availability(evidence=evidence, state=_state(evidence, **state_kwargs))


# --- ordered classification table ------------------------------------------


def test_ok_allow_fresh_is_available() -> None:
    decision = _classify(_ok_evidence())

    assert decision.status is MarketAvailabilityStatus.AVAILABLE
    assert decision.reason == "observation_fresh"


def test_ok_allow_stale_is_delayed() -> None:
    evidence = _ok_evidence(time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF))
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.DELAYED
    assert decision.reason == "observation_stale"


def test_ok_allow_unknown_freshness_is_unknown() -> None:
    """``data_as_of=None`` makes S4 report UNKNOWN freshness, not STALE."""

    evidence = _evidence(time=_time(data_as_of=None))
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.UNKNOWN
    assert decision.reason == "observation_time_unknown"


def test_ok_pit_reject_is_unavailable() -> None:
    evidence = _ok_evidence(pit_status=PITStatus.REJECT)
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.UNAVAILABLE
    assert decision.reason == "pit_rejected"


def test_ok_pit_unknown_is_unknown() -> None:
    evidence = _ok_evidence(pit_status=PITStatus.UNKNOWN)
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.UNKNOWN
    assert decision.reason == "pit_unknown"


def test_empty_source_is_missing() -> None:
    evidence = _evidence(
        observation=None,
        quality=_quality(completeness=CompletenessStatus.EMPTY),
        status=STATUS_EMPTY,
    )
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.MISSING
    assert decision.reason == "source_empty"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (STATUS_ERROR, "source_error"),
        (STATUS_UNSUPPORTED, "provider_unsupported"),
    ],
)
def test_non_ok_source_reasons_are_distinct(status: str, reason: str) -> None:
    evidence = _evidence(
        observation=None,
        quality=_quality(completeness=CompletenessStatus.UNKNOWN),
        status=status,
    )
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.UNAVAILABLE
    assert decision.reason == reason


def test_non_ok_source_reasons_do_not_collide() -> None:
    """Three distinct causes share UNAVAILABLE but never share a reason."""

    def reason_for(status: str) -> str:
        evidence = _evidence(
            observation=None,
            quality=_quality(completeness=CompletenessStatus.UNKNOWN),
            status=status,
        )
        return _classify(evidence).reason

    reasons = {reason_for(s) for s in (STATUS_ERROR, STATUS_UNSUPPORTED)}
    reasons.add(_classify(_ok_evidence(pit_status=PITStatus.REJECT)).reason)

    assert reasons == {"source_error", "provider_unsupported", "pit_rejected"}


def test_source_status_outranks_pit_and_freshness() -> None:
    """EMPTY stays MISSING even with unknown clocks and a rejected PIT status."""

    evidence = _evidence(
        observation=None,
        time=_time(data_as_of=None),
        quality=_quality(completeness=CompletenessStatus.EMPTY),
        pit_status=PITStatus.REJECT,
        status=STATUS_EMPTY,
    )
    state = _state(evidence)
    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert decision.status is MarketAvailabilityStatus.MISSING
    assert decision.reason == "source_empty"
    # Precedence loses nothing: the original evidence is still fully readable.
    assert decision.evidence is evidence
    assert decision.state is state
    assert evidence.observation is None
    assert evidence.time.data_as_of is None
    assert state.freshness.status is FreshnessStatus.UNKNOWN
    assert decision.quality is state.quality


@pytest.mark.parametrize("status", [STATUS_ERROR, STATUS_UNSUPPORTED])
def test_non_ok_source_outranks_stale_freshness(status: str) -> None:
    """A stale clock must not turn a failed source into DELAYED."""

    evidence = _evidence(
        observation=None,
        time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF),
        quality=_quality(completeness=CompletenessStatus.UNKNOWN),
        status=status,
    )
    decision = _classify(evidence)

    assert decision.status is MarketAvailabilityStatus.UNAVAILABLE
    assert _state(evidence).freshness.status is FreshnessStatus.STALE


# --- PIT x freshness matrix -------------------------------------------------


@pytest.mark.parametrize(
    ("pit_status", "data_as_of", "expected_status", "expected_reason"),
    [
        (
            PITStatus.ALLOW,
            SYNTHETIC_DATA_AS_OF,
            MarketAvailabilityStatus.AVAILABLE,
            "observation_fresh",
        ),
        (
            PITStatus.ALLOW,
            SYNTHETIC_STALE_DATA_AS_OF,
            MarketAvailabilityStatus.DELAYED,
            "observation_stale",
        ),
        (
            PITStatus.ALLOW,
            None,
            MarketAvailabilityStatus.UNKNOWN,
            "observation_time_unknown",
        ),
        (PITStatus.REJECT, SYNTHETIC_DATA_AS_OF, MarketAvailabilityStatus.UNAVAILABLE, "pit_rejected"),
        (PITStatus.REJECT, SYNTHETIC_STALE_DATA_AS_OF, MarketAvailabilityStatus.UNAVAILABLE, "pit_rejected"),
        (PITStatus.REJECT, None, MarketAvailabilityStatus.UNAVAILABLE, "pit_rejected"),
        (PITStatus.UNKNOWN, SYNTHETIC_DATA_AS_OF, MarketAvailabilityStatus.UNKNOWN, "pit_unknown"),
        (PITStatus.UNKNOWN, SYNTHETIC_STALE_DATA_AS_OF, MarketAvailabilityStatus.UNKNOWN, "pit_unknown"),
        (PITStatus.UNKNOWN, None, MarketAvailabilityStatus.UNKNOWN, "pit_unknown"),
    ],
)
def test_pit_by_freshness_matrix(
    pit_status: PITStatus,
    data_as_of: str | None,
    expected_status: MarketAvailabilityStatus,
    expected_reason: str,
) -> None:
    """PIT is resolved before freshness for every OK observation."""

    evidence = _evidence(time=_time(data_as_of=data_as_of), pit_status=pit_status)
    decision = _classify(evidence)

    assert decision.status is expected_status
    assert decision.reason == expected_reason


# --- degenerate scalars, None, and unknown clocks ---------------------------


@pytest.mark.parametrize("observation", [0, False, Decimal("0"), 0.0, "0"])
def test_falsy_observations_stay_available(observation: Any) -> None:
    """Availability of a scalar never depends on the value being truthy."""

    decision = _classify(_ok_evidence(observation=observation))

    assert decision.status is MarketAvailabilityStatus.AVAILABLE
    assert decision.reason == "observation_fresh"
    assert decision.evidence.observation == observation


def test_explicit_none_is_only_valid_for_empty_evidence() -> None:
    """``None`` observation is legal for EMPTY and rejected elsewhere by S2."""

    empty = _evidence(
        observation=None,
        quality=_quality(completeness=CompletenessStatus.EMPTY),
        status=STATUS_EMPTY,
    )
    assert _classify(empty).status is MarketAvailabilityStatus.MISSING

    with pytest.raises(ValueError):
        _evidence(observation=None, status=STATUS_OK)


def test_unknown_time_fields_are_preserved_not_inferred() -> None:
    """Unknown clocks stay None; ``fetched_at`` never stands in for them."""

    time = _time(data_as_of=None)
    decision = _classify(_ok_evidence(time=time))

    # data_as_of is unknown, so freshness is unresolved rather than fresh or
    # stale -- even though fetched_at is known and recent.
    assert decision.status is MarketAvailabilityStatus.UNKNOWN
    assert decision.reason == "observation_time_unknown"
    assert decision.state.freshness.reason == "data_as_of_unknown"
    assert decision.evidence.time is time
    assert time.to_dict()["data_as_of"] is None
    assert decision.evidence.time.fetched_at == SYNTHETIC_FETCHED_AT


# --- completeness / degraded / flags are preserved -------------------------


@pytest.mark.parametrize(
    "completeness",
    [CompletenessStatus.PARTIAL, CompletenessStatus.UNKNOWN, CompletenessStatus.COMPLETE],
)
def test_completeness_is_never_rewritten(completeness: CompletenessStatus) -> None:
    evidence = _ok_evidence(quality=_quality(completeness=completeness))
    decision = _classify(evidence)

    assert decision.quality.completeness is completeness
    assert decision.quality is decision.state.quality


def test_degraded_and_flags_survive_availability_and_delay() -> None:
    flags = ("fallback_source", "manual_review")
    evidence = _ok_evidence(quality=_quality(degraded=True, quality_flags=flags))
    available = _classify(evidence)

    assert available.status is MarketAvailabilityStatus.AVAILABLE
    assert available.quality.degraded is True
    assert available.quality.quality_flags == flags

    delayed_evidence = _evidence(
        time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF),
        quality=_quality(degraded=True, quality_flags=flags),
    )
    delayed = _classify(delayed_evidence)

    assert delayed.status is MarketAvailabilityStatus.DELAYED
    assert delayed.quality.degraded is True
    assert delayed.quality.quality_flags == flags


def test_stale_and_missing_are_not_auto_marked_degraded() -> None:
    """Availability never invents degradation evidence."""

    stale = _classify(_ok_evidence(time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF)))
    missing = _classify(
        _evidence(
            observation=None,
            quality=_quality(completeness=CompletenessStatus.EMPTY),
            status=STATUS_EMPTY,
        )
    )

    assert stale.quality.degraded is False
    assert stale.quality.quality_flags == ()
    assert missing.quality.degraded is False
    assert missing.quality.quality_flags == ()


# --- immutability and non-interference -------------------------------------


def test_decision_and_inputs_are_frozen() -> None:
    evidence = _ok_evidence()
    decision = _classify(evidence)

    with pytest.raises(FrozenInstanceError):
        decision.status = MarketAvailabilityStatus.MISSING  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        evidence.observation = Decimal("9")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.state.calendar_date = "1999-01-01"  # type: ignore[misc]


def test_inputs_are_returned_unchanged() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)
    before_time = evidence.time.to_dict()
    before_quality = evidence.quality

    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert evidence.time.to_dict() == before_time
    assert evidence.quality == before_quality
    assert evidence.status == STATUS_OK
    assert evidence.observation == Decimal("1.5")
    assert state.freshness.status is FreshnessStatus.FRESH
    assert state.quality.freshness is FreshnessStatus.FRESH
    assert decision.evidence is evidence
    assert decision.state is state


def test_evaluation_is_deterministic() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)

    first = evaluate_market_availability(evidence=evidence, state=state)
    second = evaluate_market_availability(evidence=evidence, state=state)

    assert first == second
    assert first.status is second.status
    assert first.reason == second.reason


def test_calendar_status_never_changes_a_classification() -> None:
    """TradingDayStatus is not an input; S4's calendar answer is ignored."""

    evidence = _ok_evidence()
    state = _state(evidence)
    assert state.trading_day_status is TradingDayStatus.UNKNOWN

    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert decision.status is MarketAvailabilityStatus.AVAILABLE
    assert decision.state.trading_day_status is TradingDayStatus.UNKNOWN


def test_quality_property_is_read_only() -> None:
    decision = _classify(_ok_evidence())

    with pytest.raises(AttributeError):
        decision.quality = _quality()  # type: ignore[misc]

    assert isinstance(decision.quality, QualityMetadata)


def test_same_value_distinct_time_metadata_is_accepted() -> None:
    """A freshly built but equal TimeMetadata is not a mismatch."""

    evidence = _ok_evidence()
    twin = _time()
    assert twin is not evidence.time
    assert twin == evidence.time

    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=twin,
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )
    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert decision.status is MarketAvailabilityStatus.AVAILABLE
    assert decision.state.time == evidence.time
    assert decision.state.time is not evidence.time


# --- contract shape ---------------------------------------------------------


def test_signature_is_keyword_only_and_has_no_defaults() -> None:
    signature = inspect.signature(evaluate_market_availability)

    assert list(signature.parameters) == ["evidence", "state"]
    for parameter in signature.parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
        assert parameter.annotation is not inspect.Parameter.empty


def test_status_enum_is_distinct_from_other_status_contracts() -> None:
    assert issubclass(MarketAvailabilityStatus, str)
    assert MarketAvailabilityStatus.AVAILABLE.value == "available"
    assert MarketAvailabilityStatus.MISSING.value == "missing"
    assert MarketAvailabilityStatus.DELAYED.value == "delayed"
    assert MarketAvailabilityStatus.UNAVAILABLE.value == "unavailable"
    assert MarketAvailabilityStatus.UNKNOWN.value == "unknown"
    assert MarketAvailabilityStatus is not TradingDayStatus
    assert MarketAvailabilityStatus.AVAILABLE.value not in {
        STATUS_OK,
        STATUS_EMPTY,
        STATUS_ERROR,
        STATUS_UNSUPPORTED,
    }


def test_contract_fields_surface() -> None:
    assert MarketAvailabilityDecision.contract_fields() == (
        "evidence",
        "state",
        "status",
        "reason",
    )


# --- argument and consistency validation ------------------------------------


@pytest.mark.parametrize(
    "evidence",
    [None, "evidence", 42, object(), _state, QualityMetadata()],
)
def test_wrong_evidence_type_raises_type_error(evidence: Any) -> None:
    state = _state(_ok_evidence())

    with pytest.raises(TypeError):
        evaluate_market_availability(evidence=evidence, state=state)


@pytest.mark.parametrize(
    "state",
    [None, "state", 42, object(), QualityMetadata()],
)
def test_wrong_state_type_raises_type_error(state: Any) -> None:
    evidence = _ok_evidence()

    with pytest.raises(TypeError):
        evaluate_market_availability(evidence=evidence, state=state)


def test_missing_keyword_argument_raises_type_error() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)

    with pytest.raises(TypeError):
        evaluate_market_availability(evidence=evidence)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_market_availability(state=state)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_market_availability()  # type: ignore[call-arg]


def test_positional_arguments_are_rejected() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)

    with pytest.raises(TypeError):
        evaluate_market_availability(evidence, state)  # type: ignore[misc]


def test_time_mismatch_raises_value_error() -> None:
    evidence = _ok_evidence()
    other = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF),
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )

    with pytest.raises(ValueError, match="evidence.time must equal state.time"):
        evaluate_market_availability(evidence=evidence, state=other)


def test_single_differing_time_field_is_a_mismatch() -> None:
    """Every TimeMetadata field participates, not just ``data_as_of``."""

    evidence = _ok_evidence()
    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=_time(published_at="2026-09-14T10:00:00+08:00"),
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )

    with pytest.raises(ValueError):
        evaluate_market_availability(evidence=evidence, state=state)


@pytest.mark.parametrize(
    "evidence_quality",
    [
        _quality(completeness=CompletenessStatus.PARTIAL),
        _quality(degraded=True),
        _quality(quality_flags=("synthetic_flag",)),
    ],
)
def test_quality_mismatch_raises_value_error(evidence_quality: QualityMetadata) -> None:
    evidence = _ok_evidence(quality=evidence_quality)
    state = _state(_ok_evidence())  # state composed from *different* quality

    assert evidence.time == state.time  # only the quality envelope differs
    with pytest.raises(ValueError, match="must equal"):
        evaluate_market_availability(evidence=evidence, state=state)


def test_freshness_difference_alone_is_not_a_mismatch() -> None:
    """S4 recomputes freshness, so a differing freshness field is expected."""

    evidence = _ok_evidence(quality=_quality(freshness=FreshnessStatus.UNKNOWN))
    state = _state(evidence)

    assert evidence.quality.freshness is FreshnessStatus.UNKNOWN
    assert state.quality.freshness is FreshnessStatus.FRESH
    assert decision_status(evidence, state) is MarketAvailabilityStatus.AVAILABLE


def decision_status(evidence: MarketEvidence, state: MarketStateDecision) -> MarketAvailabilityStatus:
    return evaluate_market_availability(evidence=evidence, state=state).status


# --- direct construction validation ----------------------------------------


def test_direct_construction_matches_evaluation() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)
    evaluated = evaluate_market_availability(evidence=evidence, state=state)

    built = MarketAvailabilityDecision(
        evidence=evidence,
        state=state,
        status=evaluated.status,
        reason=evaluated.reason,
    )

    assert built == evaluated
    assert built.quality is state.quality


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("available", "observation_fresh"),
        (STATUS_OK, "observation_fresh"),
        (MarketAvailabilityStatus.AVAILABLE, " source_fresh"),
        (MarketAvailabilityStatus.AVAILABLE, ""),
        (MarketAvailabilityStatus.MISSING, "provider_unsupported"),
        (MarketAvailabilityStatus.DELAYED, "observation_fresh"),
        (MarketAvailabilityStatus.UNKNOWN, "pit_rejected"),
        (MarketAvailabilityStatus.AVAILABLE, "source_error"),
    ],
)
def test_direct_construction_rejects_bad_reason_pairs(status: Any, reason: str) -> None:
    evidence = _ok_evidence()
    state = _state(evidence)

    with pytest.raises((TypeError, ValueError)):
        MarketAvailabilityDecision(evidence=evidence, state=state, status=status, reason=reason)


def test_direct_construction_rejects_contradictory_status() -> None:
    """A hand-built verdict cannot contradict the linked records."""

    evidence = _ok_evidence()
    state = _state(evidence)

    with pytest.raises(ValueError):
        MarketAvailabilityDecision(
            evidence=evidence,
            state=state,
            status=MarketAvailabilityStatus.MISSING,
            reason="source_empty",
        )
    with pytest.raises(ValueError):
        MarketAvailabilityDecision(
            evidence=evidence,
            state=state,
            status=MarketAvailabilityStatus.AVAILABLE,
            reason="observation_stale",
        )


def test_direct_construction_rejects_wrong_types_and_inconsistent_links() -> None:
    evidence = _ok_evidence()
    state = _state(evidence)

    with pytest.raises(TypeError):
        MarketAvailabilityDecision(
            evidence="evidence",
            state=state,
            status=MarketAvailabilityStatus.AVAILABLE,
            reason="observation_fresh",
        )
    with pytest.raises(TypeError):
        MarketAvailabilityDecision(
            evidence=evidence,
            state=None,
            status=MarketAvailabilityStatus.AVAILABLE,
            reason="observation_fresh",
        )
    with pytest.raises(ValueError):
        MarketAvailabilityDecision(
            evidence=evidence,
            state=_state(_ok_evidence(time=_time(data_as_of=SYNTHETIC_STALE_DATA_AS_OF))),
            status=MarketAvailabilityStatus.DELAYED,
            reason="observation_stale",
        )


# --- offline S4 integration -------------------------------------------------


def test_integration_with_real_s4_state_fresh_projection() -> None:
    """Drive S4 with explicit dual clocks, then feed its decision to S5.

    ``evaluation_time`` and ``MaxAgePolicy`` are supplied explicitly, so the
    FRESH/UNKNOWN outcomes below are S4's projection, not a hand-built state.
    """

    policy = MaxAgePolicy(max_age=_ONE_DAY)
    evidence = _evidence(
        time=TimeMetadata(
            fetched_at=SYNTHETIC_FETCHED_AT,
            data_as_of=SYNTHETIC_DATA_AS_OF,
            published_at=SYNTHETIC_DATA_AS_OF,
        ),
        quality=_quality(completeness=CompletenessStatus.PARTIAL, degraded=True),
    )
    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=evidence.time,
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=policy,
        quality=evidence.quality,
    )
    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert state.freshness.status is FreshnessStatus.FRESH
    assert state.freshness.reason == "within_max_age"
    assert state.policy is policy
    assert state.evaluation_time == SYNTHETIC_EVALUATION_TIME
    assert decision.status is MarketAvailabilityStatus.AVAILABLE
    assert decision.reason == "observation_fresh"
    assert decision.quality.freshness is FreshnessStatus.FRESH
    assert decision.quality.completeness is CompletenessStatus.PARTIAL
    assert decision.quality.degraded is True


def test_integration_policy_boundary_flips_fresh_to_stale() -> None:
    """The same S4 evidence classifies differently under a different policy."""

    evidence = _ok_evidence()

    def classify(max_age: timedelta) -> MarketAvailabilityStatus:
        state = evaluate_market_state(
            calendar_date=SYNTHETIC_CALENDAR_DATE,
            calendar=None,
            time=evidence.time,
            evaluation_time=SYNTHETIC_EVALUATION_TIME,
            policy=MaxAgePolicy(max_age=max_age),
            quality=evidence.quality,
        )
        return evaluate_market_availability(evidence=evidence, state=state).status

    assert classify(_ONE_DAY) is MarketAvailabilityStatus.AVAILABLE
    assert classify(timedelta(0)) is MarketAvailabilityStatus.DELAYED
    assert classify(_OTHER_DAY) is MarketAvailabilityStatus.AVAILABLE


def test_integration_unknown_clock_projects_to_unknown() -> None:
    evidence = _evidence(time=_time(data_as_of=None))
    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=evidence.time,
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )
    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert state.freshness.status is FreshnessStatus.UNKNOWN
    assert state.freshness.reason == "data_as_of_unknown"
    assert decision.status is MarketAvailabilityStatus.UNKNOWN
    assert decision.reason == "observation_time_unknown"


def test_integration_rejected_pit_overrides_fresh_s4_state() -> None:
    evidence = _ok_evidence(pit_status=PITStatus.REJECT)
    state = evaluate_market_state(
        calendar_date=SYNTHETIC_CALENDAR_DATE,
        calendar=None,
        time=evidence.time,
        evaluation_time=SYNTHETIC_EVALUATION_TIME,
        policy=MaxAgePolicy(max_age=_ONE_DAY),
        quality=evidence.quality,
    )
    decision = evaluate_market_availability(evidence=evidence, state=state)

    assert state.freshness.status is FreshnessStatus.FRESH
    assert decision.status is MarketAvailabilityStatus.UNAVAILABLE
    assert decision.reason == "pit_rejected"
