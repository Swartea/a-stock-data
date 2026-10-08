"""Pure JSON projection of one market snapshot and its linked decisions.

This module is the **S6-B** slice.  It converts an existing
:class:`~analysis.research.market_snapshot.MarketSnapshot`, a caller-supplied
sequence of :class:`~analysis.research.market_evidence.MarketEvidence` records, and
a caller-supplied sequence of
:class:`~analysis.research.market_availability.MarketAvailabilityDecision`
records into canonical JSON text -- and nothing else.

What it is
----------

A projection, not a computation.  Every value in the output is copied from an
input record that the caller already holds: the snapshot's identity spine, each
evidence record's scalar observation and its source/time/quality/PIT evidence,
and each S5 decision's S4 state plus its availability verdict.  The module never
fetches, never evaluates, never re-classifies, and never decides which provider,
metric, or observation is "the" one.

Deliberate non-behaviour
------------------------

* **No I/O of any kind.**  No file, no environment variable, no system clock, no
  network, no standard output.  The same inputs always produce the same bytes.
* **No defaults and no inference.**  All three arguments are keyword-only and
  required.  No threshold, policy, calendar, "now", or provider preference is
  supplied on the caller's behalf, and no absent clock is filled in from an
  adjacent field.
* **No re-evaluation.**  ``evaluate_market_state`` and
  ``evaluate_market_availability`` stay owned by S4/S5.  A decision is projected
  as the caller computed it; the module only checks that the decision's own
  linked evidence is really present in the supplied evidence sequence.
* **No new contract types and no production wiring.**  This is a fixed-field
  serializer with no registry, no manifest, no provider-symbol selection, and no
  call site outside tests.
* **No provenance manifest.**  There is no capture file, no SHA registry, and no
  per-field real-world provenance to project, so none is produced.
  ``provider_symbols`` is exactly the declared alias list of the snapshot; it
  does not claim which alias any observation actually used, and an index with no
  alias is not thereby an index whose observation is missing.

Three distinctions the wire shape preserves
-------------------------------------------

* **Absent evidence, explicit null, and caller-supplied ``EMPTY`` are three
  different claims.**  An index with no evidence row simply has no row -- no
  synthetic ``EMPTY``/``MISSING``/``UNKNOWN`` placeholder is manufactured for it.
  An evidence row with an explicit ``null`` observation keeps that ``null`` and
  its ``observation_type`` label.  An ``EMPTY`` status exists only because the
  caller supplied a legitimate S2 record saying so.
* **Scalar type is part of the value.**  ``False`` is not ``0``, ``Decimal("1.0")``
  is not ``1.0`` and is not ``"1"``; the exact decimal spelling, the exact float
  rendering, and the ``observation_type`` label all survive the round trip.
* **Independent observations stay independent.**  Different providers, clocks,
  metrics, and quality envelopes are never merged, never de-duplicated, and never
  collapsed to a "latest" row.  A row carries exactly the decisions that link to
  it, and nothing else.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

from analysis.research.index_registry import IndexIdentity
from analysis.research.market_availability import MarketAvailabilityDecision
from analysis.research.market_evidence import MarketEvidence
from analysis.research.market_snapshot import MarketSnapshot
from analysis.research.market_state import MarketStateDecision
from analysis.research.providers import ProviderSpec
from analysis.research.quality import QualityMetadata
from analysis.research.time_semantics import TimeMetadata

SCHEMA_VERSION = "s6.market_snapshot.v1"

# The seven S1/S2 clock fields, projected explicitly and in their contract order
# so a future dataclass field cannot silently change the wire shape.
_TIME_FIELDS = (
    "fetched_at",
    "data_as_of",
    "period_start",
    "period_end",
    "published_at",
    "effective_from",
    "effective_to",
)

_MICROSECONDS_PER_SECOND = 1_000_000


def _require_sequence(value: Any, *, name: str) -> Sequence[Any]:
    """Return ``value`` when it is an ordered sequence, else raise TypeError.

    ``str``/``bytes``/``bytearray`` are sequences but not collections of records,
    and mappings, sets, and generators have no defined order, so all of them are
    rejected here rather than being iterated somewhere less obvious.
    """

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of records, not text or bytes")
    if not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a concrete Sequence such as tuple or list")
    return value


def _canonical_json(value: Any) -> str:
    """Serialize with the one canonical settings tuple used for the wire text."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )


def _canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 bytes of a projected sub-object."""

    return _canonical_json(value).encode("utf-8")


def _format_duration(value: timedelta) -> str:
    """Return an exact signed seconds string with six fixed decimals.

    The microsecond total is computed from the integer ``days``/``seconds``/
    ``microseconds`` components only.  ``total_seconds()`` and float arithmetic
    are both forbidden here because a sub-microsecond-scale float round trip could
    render ``0.000001`` as ``1e-06`` or lose the last digit of a long age.
    """

    total = (
        value.days * 86_400 + value.seconds
    ) * _MICROSECONDS_PER_SECOND + value.microseconds
    sign = "-" if total < 0 else ""
    magnitude = abs(total)
    whole, fraction = divmod(magnitude, _MICROSECONDS_PER_SECOND)
    return f"{sign}{whole}.{fraction:06d}"


def _project_index(index: IndexIdentity) -> dict[str, Any]:
    """Project one index identity as its three explicit fields."""

    return {
        "index_id": index.index_id,
        "publisher": index.publisher.value,
        "local_code": index.local_code,
    }


def _project_provider_symbol(alias: Any) -> dict[str, Any]:
    """Project one declared provider-symbol alias, preserving snapshot order."""

    return {
        "index_id": alias.index_id,
        "provider_id": alias.provider_id,
        "provider_symbol": alias.provider_symbol,
    }


def _project_time(time: TimeMetadata) -> dict[str, Any]:
    """Project all seven clocks verbatim; ``None`` stays ``None``."""

    return {name: getattr(time, name) for name in _TIME_FIELDS}


def _project_quality(quality: QualityMetadata) -> dict[str, Any]:
    """Project the four quality fields, keeping flag tuple order intact."""

    return {
        "freshness": quality.freshness.value,
        "completeness": quality.completeness.value,
        "degraded": quality.degraded,
        "quality_flags": list(quality.quality_flags),
    }


def _project_provider(provider: ProviderSpec) -> dict[str, Any]:
    """Project the four provider fields, keeping alias tuple order intact."""

    return {
        "provider_id": provider.provider_id,
        "display_name": provider.display_name,
        "provider_family": provider.provider_family,
        "aliases": list(provider.aliases),
    }


def _encode_observation(value: Any) -> tuple[Any, str]:
    """Return the JSON value for an observation plus its ``observation_type``.

    The type label is derived from the runtime type only -- it is never inferred
    from the rendered text -- and ``bool`` is checked before ``int`` so ``True``
    is labelled ``bool`` rather than ``int``.  A ``Decimal`` is encoded through
    ``str(value)`` so trailing zeros, exponent form, and precision survive
    exactly; a finite ``float`` stays a JSON number; and ``0``, ``False``,
    negative zero, and the empty side of a null are never collapsed by a
    truthiness test.
    """

    if isinstance(value, bool):
        return value, "bool"
    if isinstance(value, int):
        return value, "int"
    if isinstance(value, Decimal):
        return str(value), "decimal"
    if isinstance(value, float):
        return value, "float"
    if isinstance(value, str):
        return value, "str"
    if value is None:
        return None, "null"
    raise TypeError(
        "observation must be a scalar value or None supported by S2: "
        f"{type(value).__name__}"
    )


def _project_evidence_body(evidence: MarketEvidence) -> dict[str, Any]:
    """Project one evidence record without its ``decisions`` array.

    This is the comparison body used both for the wire row (minus the array) and
    for the byte-exact link check between a decision and its evidence, so a
    decision can never be linked to an evidence row that merely compares equal by
    ``False == 0`` or ``Decimal("1.0") == 1.0``.
    """

    observation, observation_type = _encode_observation(evidence.observation)
    return {
        "evidence_id": evidence.evidence_id,
        "subject": _project_index(evidence.subject),
        "metric": evidence.metric,
        "observation": observation,
        "observation_type": observation_type,
        "provider": _project_provider(evidence.provider),
        "time": _project_time(evidence.time),
        "quality": _project_quality(evidence.quality),
        "pit_status": evidence.pit_status.value,
        "status": evidence.status,
    }


def _project_state(state: MarketStateDecision) -> dict[str, Any]:
    """Project the eight S4 state fields of a decision, verbatim.

    ``policy.max_age`` and ``freshness.age_seconds`` are the two wire names fixed
    by the S6 schema; the projected freshness block is exactly ``status``,
    ``reason``, and ``age_seconds``, and ``age_seconds`` stays ``null`` when S4
    reported no age.
    """

    freshness_age = state.freshness.age
    return {
        "calendar_date": state.calendar_date,
        "trading_day_status": state.trading_day_status.value,
        "calendar_reason": state.calendar_reason,
        "time": _project_time(state.time),
        "evaluation_time": state.evaluation_time,
        "policy": {"max_age": _format_duration(state.policy.max_age)},
        "freshness": {
            "status": state.freshness.status.value,
            "reason": state.freshness.reason,
            "age_seconds": None if freshness_age is None else _format_duration(freshness_age),
        },
        "quality": _project_quality(state.quality),
    }


def _project_decision(decision: MarketAvailabilityDecision) -> dict[str, Any]:
    """Project one decision as exactly ``{"state", "availability"}``.

    Neither half invents an ``index_id``, concatenates a second state, or
    re-runs an ``evaluate_*`` call: ``availability.quality`` is the same quality
    envelope S4 composed and S5 exposes.
    """

    return {
        "state": _project_state(decision.state),
        "availability": {
            "status": decision.status.value,
            "reason": decision.reason,
            "quality": _project_quality(decision.quality),
        },
    }


def _validate_evidence_against_snapshot(
    evidence_items: list[MarketEvidence],
    snapshot: MarketSnapshot,
) -> dict[str, IndexIdentity]:
    """Check unique ids and full subject identity; return the id -> identity map."""

    identity_by_id = {index.index_id: index for index in snapshot.indexes}
    seen: dict[str, MarketEvidence] = {}
    for item in evidence_items:
        evidence_id = item.evidence_id
        if evidence_id in seen:
            raise ValueError(f"duplicate evidence_id in evidence: {evidence_id!r}")
        seen[evidence_id] = item
        expected = identity_by_id.get(item.subject.index_id)
        if expected is None:
            raise ValueError(
                "evidence subject index_id is not covered by this snapshot: "
                f"{item.subject.index_id!r}"
            )
        if expected != item.subject:
            raise ValueError(
                "evidence subject must equal the snapshot IndexIdentity for "
                f"{item.subject.index_id!r}"
            )
    return identity_by_id


def _link_decisions(
    decision_items: list[MarketAvailabilityDecision],
    evidence_by_id: dict[str, bytes],
) -> dict[str, list[dict[str, Any]]]:
    """Return evidence_id -> projected decisions, verifying every link by bytes.

    The lookup is by ``evidence_id`` first and by the canonical bytes of the
    complete no-``decisions`` evidence projection second.  Dataclass equality is
    not enough on its own: ``False == 0`` and ``Decimal("1.0") == 1.0`` both
    compare equal while meaning something different on the wire, so scalar type
    and exact decimal/float rendering are part of the link.
    """

    projected_by_id: dict[str, list[dict[str, Any]]] = {key: [] for key in evidence_by_id}
    for decision in decision_items:
        linked = decision.evidence
        if not isinstance(linked, MarketEvidence):  # pragma: no cover - S5 guarantees it
            raise TypeError("decision.evidence must be MarketEvidence")
        evidence_id = linked.evidence_id
        if evidence_id not in evidence_by_id:
            raise ValueError(
                "decision links to evidence_id that was not supplied: "
                f"{evidence_id!r}"
            )
        if _canonical_bytes(_project_evidence_body(linked)) != evidence_by_id[evidence_id]:
            raise ValueError(
                "decision.evidence does not match the supplied evidence row: "
                f"{evidence_id!r}"
            )
        projected_by_id[evidence_id].append(_project_decision(decision))
    return projected_by_id


def project_market_snapshot(
    *,
    snapshot: MarketSnapshot,
    evidence: Sequence[MarketEvidence],
    decisions: Sequence[MarketAvailabilityDecision],
) -> str:
    """Project a snapshot, its evidence, and its decisions into canonical JSON.

    All three arguments are keyword-only and required: no caller can inherit a
    default calendar, policy, clock, or empty decision list.

    Rules:

    * ``evidence`` and ``decisions`` must be concrete ordered sequences (tuple or
      list at minimum).  Text, bytes, mappings, sets, generators, and ``None``
      are rejected with :class:`TypeError`, as are elements of the wrong type.
    * ``evidence_id`` must be unique across ``evidence`` (:class:`ValueError`),
      and every ``evidence.subject`` must equal the snapshot's
      :class:`~analysis.research.index_registry.IndexIdentity` for that
      ``index_id`` over *all three* identity fields.
    * Every decision must link to exactly one supplied evidence row: matched
      first by ``evidence_id`` and then by the canonical bytes of the complete
      no-``decisions`` evidence projection, so an equal-valued but
      differently-typed or differently-spelled observation is rejected.
    * Evidence rows are sorted by ``(subject.index_id, metric, evidence_id)``.
      Each row's ``decisions`` array is sorted by the canonical JSON bytes of
      the complete ``{"state", "availability"}`` projection, keeping identical
      duplicates rather than collapsing them.
    * An index with no evidence keeps its identity in ``indexes`` and simply has
      no row; an evidence row with no supplied decision carries ``"decisions":
      []``.  Neither case is filled in with a synthetic ``EMPTY``/``MISSING``/
      ``UNKNOWN`` record.
    * The result is ``json.dumps(..., ensure_ascii=False, sort_keys=True,
      indent=2, allow_nan=False)`` plus exactly one trailing ``"\\n"``.  Errors
      are raised before anything is returned; there is no partial output.
    """

    if not isinstance(snapshot, MarketSnapshot):
        raise TypeError("snapshot must be MarketSnapshot")

    evidence_items = _materialize(
        _require_sequence(evidence, name="evidence"),
        expected=MarketEvidence,
        name="evidence",
    )
    decision_items = _materialize(
        _require_sequence(decisions, name="decisions"),
        expected=MarketAvailabilityDecision,
        name="decisions",
    )

    _validate_evidence_against_snapshot(evidence_items, snapshot)

    evidence_by_id = {
        item.evidence_id: _canonical_bytes(_project_evidence_body(item))
        for item in evidence_items
    }
    projected_decisions = _link_decisions(decision_items, evidence_by_id)

    rows: list[dict[str, Any]] = []
    for item in evidence_items:
        linked = projected_decisions[item.evidence_id]
        row = _project_evidence_body(item)
        row["decisions"] = sorted(linked, key=_canonical_bytes)
        rows.append(row)
    rows.sort(key=lambda row: (row["subject"]["index_id"], row["metric"], row["evidence_id"]))

    document = {
        "schema_version": SCHEMA_VERSION,
        "snapshot": {"snapshot_id": snapshot.snapshot_id, "market": snapshot.market},
        "indexes": [_project_index(index) for index in snapshot.indexes],
        "provider_symbols": [
            _project_provider_symbol(alias) for alias in snapshot.provider_symbols
        ],
        "evidence": rows,
    }
    return f"{_canonical_json(document)}\n"


def _materialize(items: Sequence[Any], *, expected: type, name: str) -> list[Any]:
    """Copy an ordered sequence into a list, rejecting wrong element types.

    The caller's sequence is only read; materializing it keeps the rest of the
    module free of any assumption about what a Sequence may do on a second pass.
    """

    materialized: list[Any] = []
    for item in items:
        if not isinstance(item, expected):
            raise TypeError(
                f"{name} must contain {expected.__name__} values, "
                f"got {type(item).__name__}"
            )
        materialized.append(item)
    return materialized


__all__ = ["SCHEMA_VERSION", "project_market_snapshot"]
