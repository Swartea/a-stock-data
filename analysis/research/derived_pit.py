"""Point-in-time provenance for derived Research Engine features.

A derived value cannot be available before every required input was itself
available.  This module records that constraint without fetching data,
recomputing formulas, or wiring into the existing V3 pipeline.

``available_at`` has a deliberately narrow meaning: the earliest time at which
an already PIT-validated input could lawfully be used.  Callers must not pass
``fetched_at`` or ``period_end`` merely because those timestamps are known.
Unknown input availability stays unknown; it is never inferred from siblings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from analysis.research.pit_guard import PITDecision, PITStatus


@dataclass(frozen=True)
class DerivedInputAvailability:
    """Availability metadata for one required derived-feature input."""

    input_id: str
    available_at: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.input_id, str) or not self.input_id.strip():
            raise ValueError("input_id must be a non-empty string")
        if self.available_at is not None and (
            not isinstance(self.available_at, str) or not self.available_at.strip()
        ):
            raise ValueError("available_at must be a non-empty timestamp string or None")


@dataclass(frozen=True)
class DerivedPITMetadata:
    """PIT availability and provenance carried by a derived feature."""

    available_at: Optional[str]
    derived_from: tuple[str, ...]
    formula_version: str

    def __post_init__(self) -> None:
        if self.available_at is not None and (
            not isinstance(self.available_at, str) or not self.available_at.strip()
        ):
            raise ValueError("available_at must be a non-empty timestamp string or None")
        if not isinstance(self.derived_from, tuple) or not self.derived_from:
            raise ValueError("derived_from must be a non-empty tuple")
        if any(not isinstance(item, str) or not item.strip() for item in self.derived_from):
            raise ValueError("derived_from entries must be non-empty strings")
        normalized_ids = [item.strip().casefold() for item in self.derived_from]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("derived_from entries must be unique")
        if not isinstance(self.formula_version, str) or not self.formula_version.strip():
            raise ValueError("formula_version must be a non-empty string")


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO timestamp string")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp string") from exc


def _require_compatible_timezones(values: tuple[datetime, ...], *, context: str) -> None:
    awareness = {value.tzinfo is not None for value in values}
    if len(awareness) > 1:
        raise ValueError(f"{context} must use compatible timezone semantics")


def build_derived_pit(
    inputs: tuple[DerivedInputAvailability, ...],
    *,
    formula_version: str,
) -> DerivedPITMetadata:
    """Build immutable PIT provenance for a derived feature.

    The derived feature's availability is the latest availability among all
    required inputs.  If even one required input has unknown availability, the
    derived availability is unknown as well.  No known sibling timestamp may
    substitute for that missing evidence.
    """
    if not isinstance(inputs, tuple) or not inputs:
        raise ValueError("inputs must be a non-empty tuple")
    if not isinstance(formula_version, str) or not formula_version.strip():
        raise ValueError("formula_version must be a non-empty string")
    if any(not isinstance(item, DerivedInputAvailability) for item in inputs):
        raise TypeError("inputs must contain DerivedInputAvailability values")

    derived_from = tuple(item.input_id for item in inputs)
    normalized_ids = [item.strip().casefold() for item in derived_from]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("input_id values must be unique")

    if any(item.available_at is None for item in inputs):
        return DerivedPITMetadata(
            available_at=None,
            derived_from=derived_from,
            formula_version=formula_version,
        )

    parsed = tuple(
        _parse_timestamp(item.available_at, field_name=f"available_at[{item.input_id}]")
        for item in inputs
        if item.available_at is not None
    )
    _require_compatible_timezones(parsed, context="derived input availability timestamps")

    latest_index = max(range(len(parsed)), key=parsed.__getitem__)
    latest_available_at = inputs[latest_index].available_at

    return DerivedPITMetadata(
        available_at=latest_available_at,
        derived_from=derived_from,
        formula_version=formula_version,
    )


def evaluate_derived_pit(
    metadata: DerivedPITMetadata,
    decision_time: str,
) -> PITDecision:
    """Evaluate a derived feature against a decision time."""
    if not isinstance(metadata, DerivedPITMetadata):
        raise TypeError("metadata must be DerivedPITMetadata")

    decision_dt = _parse_timestamp(decision_time, field_name="decision_time")
    if metadata.available_at is None:
        return PITDecision(PITStatus.UNKNOWN, "derived_availability_unknown")

    available_dt = _parse_timestamp(metadata.available_at, field_name="available_at")
    _require_compatible_timezones(
        (available_dt, decision_dt),
        context="available_at and decision_time",
    )

    if available_dt > decision_dt:
        return PITDecision(PITStatus.REJECT, "derived_available_after_decision")
    return PITDecision(PITStatus.ALLOW, "derived_allowed")
