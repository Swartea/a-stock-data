"""Market observations with explicit source, time, and quality evidence.

This is the S2 MarketEvidence contract. It is a passive, immutable record: it
does not fetch data, evaluate freshness or point-in-time rules, aggregate market
state, or choose a provider. Existing research contracts supply the subject,
provider, clocks, quality, and PIT status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from decimal import Decimal

from analysis.fetcher_contract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    VALID_STATUSES,
)
from analysis.research.index_registry import IndexIdentity
from analysis.research.pit_guard import PITStatus
from analysis.research.providers import ProviderSpec
from analysis.research.quality import CompletenessStatus, QualityMetadata
from analysis.research.time_semantics import TimeMetadata

ObservationValue = bool | Decimal | float | int | str


@dataclass(frozen=True)
class MarketEvidence:
    """One indexed market observation and the evidence that qualifies it.

    ``evidence_id`` identifies this evidence record; ``subject`` continues to
    use the Research Engine's existing ``IndexIdentity``. ``observation`` is a
    scalar value (including an explicit ``None`` when unavailable), while
    ``metric`` names what that value represents. Unknown clocks and judgments
    remain explicit in ``time``, ``quality``, and ``pit_status``.
    """

    evidence_id: str
    subject: IndexIdentity
    metric: str
    observation: ObservationValue | None
    provider: ProviderSpec
    time: TimeMetadata
    quality: QualityMetadata
    pit_status: PITStatus
    status: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str):
            raise TypeError("evidence_id must be a string")
        if not self.evidence_id or self.evidence_id != self.evidence_id.strip():
            raise ValueError("evidence_id must be a non-empty trimmed string")

        if not isinstance(self.subject, IndexIdentity):
            raise TypeError("subject must be IndexIdentity")

        if not isinstance(self.metric, str):
            raise TypeError("metric must be a string")
        if not self.metric or self.metric != self.metric.strip():
            raise ValueError("metric must be a non-empty trimmed string")

        if not isinstance(self.provider, ProviderSpec):
            raise TypeError("provider must be ProviderSpec")
        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")
        if not isinstance(self.quality, QualityMetadata):
            raise TypeError("quality must be QualityMetadata")
        if not isinstance(self.pit_status, PITStatus):
            raise TypeError("pit_status must be PITStatus")

        self._validate_observation(self.observation)

        if not isinstance(self.status, str):
            raise TypeError("status must be a string")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"status must be one of the fetcher statuses: {sorted(VALID_STATUSES)}")

        if self.status == STATUS_OK:
            if self.observation is None:
                raise ValueError("ok evidence must carry an observation")
            if self.quality.completeness is CompletenessStatus.EMPTY:
                raise ValueError("ok evidence cannot have empty completeness")
        elif self.observation is not None:
            raise ValueError("non-ok evidence must not carry an observation")

        if (
            self.status == STATUS_EMPTY
            and self.quality.completeness is not CompletenessStatus.EMPTY
        ):
            raise ValueError("empty evidence must have empty completeness")

        if (
            self.status in (STATUS_ERROR, STATUS_UNSUPPORTED)
            and self.quality.completeness is not CompletenessStatus.UNKNOWN
        ):
            raise ValueError(
                "error or unsupported evidence must have unknown completeness"
            )

    @staticmethod
    def _validate_observation(value: ObservationValue | None) -> None:
        """Keep observations scalar and immutable; missing is represented by None."""

        if value is None or isinstance(value, (bool, int)):
            return
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("observation Decimal must be finite")
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("observation float must be finite")
            return
        if isinstance(value, str):
            if not value or value != value.strip():
                raise ValueError("observation string must be non-empty and trimmed")
            return
        raise TypeError("observation must be a scalar value or None")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the stable S2 evidence surface."""

        return tuple(field.name for field in fields(cls))
