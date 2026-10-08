"""Point-in-time availability classification for market evidence.

This module is the **S5** slice.  It answers one narrow question: given an
existing :class:`~analysis.research.market_evidence.MarketEvidence` record and
the :class:`~analysis.research.market_state.MarketStateDecision` that was derived
from it, is that observation *available* for use right now -- and if not, why?

It adds no facts of its own.  Every input it needs is already carried by the two
records it is handed, and it never manufactures an ``EMPTY`` evidence record to
represent a missing observation: the caller must supply evidence that exists.

Ordered classification
----------------------

The table is applied in exactly this order, and the first matching row wins:

===========================  ======================  ===========================
condition                    status                  reason
===========================  ======================  ===========================
``STATUS_EMPTY``             ``MISSING``             ``source_empty``
``STATUS_ERROR``             ``UNAVAILABLE``         ``source_error``
``STATUS_UNSUPPORTED``       ``UNAVAILABLE``         ``provider_unsupported``
``STATUS_OK`` + PIT REJECT   ``UNAVAILABLE``         ``pit_rejected``
``STATUS_OK`` + PIT UNKNOWN  ``UNKNOWN``             ``pit_unknown``
``STATUS_OK`` + ALLOW/FRESH  ``AVAILABLE``           ``observation_fresh``
``STATUS_OK`` + ALLOW/STALE  ``DELAYED``             ``observation_stale``
``STATUS_OK`` + ALLOW/UNKN   ``UNKNOWN``             ``observation_time_unknown``
===========================  ======================  ===========================

Source status is therefore resolved *before* point-in-time and freshness, which
is why an ``EMPTY`` observation with an unknown clock stays ``MISSING`` rather
than degrading into an unknown-freshness verdict.

Deliberate non-behaviour
------------------------

* **No inference and no new facts.**  ``calendar_date``,
  ``TradingDayStatus``, the current clock, ``fetched_at``, and any previous
  observation never influence the outcome.  Availability is a statement about
  the supplied records only, not about "the market right now".
* **No rewriting of evidence.**  The observation, ``data_as_of``, the freshness
  decision, the max-age policy, the PIT status, and the source status are
  retained verbatim.  A classification never copies, normalizes, substitutes,
  or clears them.
* **Availability is not completeness.**  A scalar observation being available
  says nothing about how complete the payload is.  ``PARTIAL``/``UNKNOWN``
  completeness, ``degraded``, and ``quality_flags`` pass through untouched, and
  stale or missing data is never automatically marked degraded.
* **Consistency before classification.**  ``evidence.time`` must equal
  ``state.time`` across the whole ``TimeMetadata`` value, and the evidence
  quality's ``completeness``/``degraded``/``quality_flags`` must equal the
  state's.  ``freshness`` is deliberately excluded from that comparison because
  S4 recomputes it into ``state.quality`` from its own decision.
* **Pure and unconnected.**  No I/O, no clock, no defaults, no fallback, no
  production wiring.  Both arguments are keyword-only and required.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from analysis.fetcher_contract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
)
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_state import MarketStateDecision
from analysis.research.pit_guard import PITStatus
from analysis.research.quality import FreshnessStatus, QualityMetadata

# Stable machine-readable reasons.  They are part of the contract: a consumer
# may switch on them, so they are named once here and never recomputed.
REASON_SOURCE_EMPTY = "source_empty"
REASON_SOURCE_ERROR = "source_error"
REASON_PROVIDER_UNSUPPORTED = "provider_unsupported"
REASON_PIT_REJECTED = "pit_rejected"
REASON_PIT_UNKNOWN = "pit_unknown"
REASON_OBSERVATION_FRESH = "observation_fresh"
REASON_OBSERVATION_STALE = "observation_stale"
REASON_OBSERVATION_TIME_UNKNOWN = "observation_time_unknown"


class MarketAvailabilityStatus(str, Enum):
    """Whether a market observation is usable, and if not, in what way.

    This enum is distinct from the fetcher status strings (``ok``/``empty``/
    ``error``/``unsupported``) and from
    :class:`~analysis.research.trading_calendar.TradingDayStatus`: it answers a
    different question about a different subject.  In particular ``UNKNOWN``
    here means "the supplied evidence cannot settle availability", not "the
    market is unknown".
    """

    AVAILABLE = "available"
    MISSING = "missing"
    DELAYED = "delayed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# Every reason that may legally accompany each status, so a decision can never
# pair a status with a reason describing a different outcome.  Three statuses
# have more than one cause -- UNAVAILABLE has three (source error, unsupported
# provider, rejected point-in-time) and UNKNOWN has two (an unresolved PIT check
# and an unresolved observation clock) -- and those causes stay distinguishable
# by reason even though they share a status.
_REASONS_BY_STATUS: dict[MarketAvailabilityStatus, frozenset[str]] = {
    MarketAvailabilityStatus.AVAILABLE: frozenset({REASON_OBSERVATION_FRESH}),
    MarketAvailabilityStatus.MISSING: frozenset({REASON_SOURCE_EMPTY}),
    MarketAvailabilityStatus.DELAYED: frozenset({REASON_OBSERVATION_STALE}),
    MarketAvailabilityStatus.UNAVAILABLE: frozenset(
        {
            REASON_SOURCE_ERROR,
            REASON_PROVIDER_UNSUPPORTED,
            REASON_PIT_REJECTED,
        }
    ),
    MarketAvailabilityStatus.UNKNOWN: frozenset(
        {
            REASON_PIT_UNKNOWN,
            REASON_OBSERVATION_TIME_UNKNOWN,
        }
    ),
}


def _valid_reasons(status: MarketAvailabilityStatus) -> frozenset[str]:
    """Return every reason code that may legally accompany ``status``."""

    return _REASONS_BY_STATUS[status]


def _check_consistency(evidence: MarketEvidence, state: MarketStateDecision) -> None:
    """Reject evidence/state pairs that cannot describe the same observation.

    ``freshness`` is intentionally not compared: S4 recomputes it into
    ``state.quality`` from its own freshness decision, so the two records are
    expected to disagree there and only there.
    """

    if evidence.time != state.time:
        raise ValueError(
            "evidence.time must equal state.time across every TimeMetadata field"
        )

    evidence_quality = evidence.quality
    state_quality = state.quality
    if (
        evidence_quality.completeness != state_quality.completeness
        or evidence_quality.degraded != state_quality.degraded
        or evidence_quality.quality_flags != state_quality.quality_flags
    ):
        raise ValueError(
            "evidence.quality completeness, degraded, and quality_flags must equal "
            "state.quality"
        )


def _classify_ok(
    evidence: MarketEvidence,
    state: MarketStateDecision,
) -> tuple[MarketAvailabilityStatus, str]:
    """Classify an ``STATUS_OK`` observation: point-in-time, then freshness."""

    if evidence.pit_status is PITStatus.REJECT:
        return MarketAvailabilityStatus.UNAVAILABLE, REASON_PIT_REJECTED
    if evidence.pit_status is PITStatus.UNKNOWN:
        return MarketAvailabilityStatus.UNKNOWN, REASON_PIT_UNKNOWN

    freshness_status = state.freshness.status
    if freshness_status is FreshnessStatus.FRESH:
        return MarketAvailabilityStatus.AVAILABLE, REASON_OBSERVATION_FRESH
    if freshness_status is FreshnessStatus.STALE:
        return MarketAvailabilityStatus.DELAYED, REASON_OBSERVATION_STALE
    return MarketAvailabilityStatus.UNKNOWN, REASON_OBSERVATION_TIME_UNKNOWN


def _classify(
    evidence: MarketEvidence,
    state: MarketStateDecision,
) -> tuple[MarketAvailabilityStatus, str]:
    """Return the ordered-table verdict for a consistent evidence/state pair."""

    # Source status first: a provider that returned nothing, errored, or cannot
    # serve the metric answers before PIT or freshness are ever consulted.
    if evidence.status == STATUS_EMPTY:
        return MarketAvailabilityStatus.MISSING, REASON_SOURCE_EMPTY
    if evidence.status == STATUS_ERROR:
        return MarketAvailabilityStatus.UNAVAILABLE, REASON_SOURCE_ERROR
    if evidence.status == STATUS_UNSUPPORTED:
        return MarketAvailabilityStatus.UNAVAILABLE, REASON_PROVIDER_UNSUPPORTED

    if evidence.status != STATUS_OK:
        # Unreachable through a validated MarketEvidence, which only accepts a
        # fetcher status from VALID_STATUSES.  Guarded rather than assumed so an
        # unknown status can never fall through into the OK rows by accident.
        raise ValueError(f"unclassifiable source status: {evidence.status!r}")

    return _classify_ok(evidence, state)


@dataclass(frozen=True)
class MarketAvailabilityDecision:
    """One availability verdict that keeps both of its inputs intact.

    ``evidence`` and ``state`` are retained by reference and are never copied,
    normalized, or replaced, so a reader can re-derive the verdict from the
    original observation, clocks, policy, and PIT status.  ``quality`` is a
    read-only projection of ``state.quality``: availability says nothing about
    completeness, so completeness, ``degraded``, and ``quality_flags`` pass
    through exactly as S4 composed them.

    Construction is validated in both directions -- the types must be right
    (``TypeError``) and the status/reason pair must be the one the ordered table
    yields for these very inputs (``ValueError``).  A hand-built decision can
    therefore not claim an outcome its own evidence contradicts.
    """

    evidence: MarketEvidence
    state: MarketStateDecision
    status: MarketAvailabilityStatus
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, MarketEvidence):
            raise TypeError("evidence must be MarketEvidence")
        if not isinstance(self.state, MarketStateDecision):
            raise TypeError("state must be MarketStateDecision")
        if not isinstance(self.status, MarketAvailabilityStatus):
            raise TypeError("status must be MarketAvailabilityStatus")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("reason must be a non-empty trimmed string")

        if self.reason not in _valid_reasons(self.status):
            raise ValueError(
                f"{self.status.value} requires one of the reasons "
                f"{sorted(_valid_reasons(self.status))}"
            )

        _check_consistency(self.evidence, self.state)

        expected_status, expected_reason = _classify(self.evidence, self.state)
        if self.status is not expected_status or self.reason != expected_reason:
            raise ValueError(
                "status and reason must match the classification of the linked "
                f"evidence and state ({expected_status.value}/{expected_reason})"
            )

    @property
    def quality(self) -> QualityMetadata:
        """Return the state-derived quality envelope, unchanged."""

        return self.state.quality

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the stable S5 decision surface."""

        return tuple(field.name for field in fields(cls))


def evaluate_market_availability(
    *,
    evidence: MarketEvidence,
    state: MarketStateDecision,
) -> MarketAvailabilityDecision:
    """Classify whether ``evidence`` is available under ``state``.

    Rules:

    * ``evidence`` must be an existing
      :class:`~analysis.research.market_evidence.MarketEvidence`; this function
      never manufactures an ``EMPTY`` record to stand in for missing data;
    * ``evidence.time`` must equal ``state.time`` over the complete
      ``TimeMetadata`` value, and the evidence quality's ``completeness``,
      ``degraded``, and ``quality_flags`` must equal ``state.quality`` -- a
      mismatch raises ``ValueError`` before any classification happens;
    * source status is resolved first, then PIT status, then freshness, per the
      ordered table in the module docstring;
    * nothing is rewritten: the observation, ``data_as_of``, ``fetched_at``,
      freshness, policy, PIT status, completeness, ``degraded``, and
      ``quality_flags`` are all returned exactly as supplied.

    Both arguments are keyword-only and required, so no caller can inherit a
    default clock, policy, or evidence record.
    """

    if not isinstance(evidence, MarketEvidence):
        raise TypeError("evidence must be MarketEvidence")
    if not isinstance(state, MarketStateDecision):
        raise TypeError("state must be MarketStateDecision")

    _check_consistency(evidence, state)
    status, reason = _classify(evidence, state)

    return MarketAvailabilityDecision(
        evidence=evidence,
        state=state,
        status=status,
        reason=reason,
    )
