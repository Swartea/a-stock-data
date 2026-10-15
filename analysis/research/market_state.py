"""Immutable state of one market index observation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from analysis.fetcher_contract import STATUS_OK
from analysis.research.index_registry import IndexIdentity
from analysis.research.market_availability import MarketAvailability
from analysis.research.market_evidence import MarketEvidence
from analysis.research.pit_guard import PITStatus
from analysis.research.quality import FreshnessStatus


@dataclass(frozen=True)
class MarketIndexObservation:
    identity: IndexIdentity
    name: str
    close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    data_date: str | None = None
    provider: str | None = None
    degraded: bool = False
    availability: MarketAvailability = MarketAvailability.UNKNOWN
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    evidence: tuple[MarketEvidence, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, IndexIdentity):
            raise TypeError("identity must be IndexIdentity")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be non-empty")
        for field in ("close", "change", "change_percent"):
            value = getattr(self, field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"{field} must be finite numeric or None")
        if self.data_date is not None:
            try:
                parsed = date.fromisoformat(self.data_date)
            except (TypeError, ValueError) as exc:
                raise ValueError("data_date must be YYYY-MM-DD or None") from exc
            if parsed.isoformat() != self.data_date:
                raise ValueError("data_date must be canonical YYYY-MM-DD")
        if not isinstance(self.degraded, bool):
            raise TypeError("degraded must be bool")
        if not isinstance(self.availability, MarketAvailability):
            raise TypeError("availability must be MarketAvailability")
        if not isinstance(self.freshness, FreshnessStatus):
            raise TypeError("freshness must be FreshnessStatus")
        if not isinstance(self.evidence, tuple) or any(not isinstance(e, MarketEvidence) for e in self.evidence):
            raise TypeError("evidence must be a tuple of MarketEvidence values")
        if self.close is not None:
            matching = [
                evidence for evidence in self.evidence
                if evidence.subject == self.identity
                and evidence.metric == "daily_close"
                and evidence.observation == self.close
                and evidence.status == STATUS_OK
            ]
            if not matching or self.data_date is None or self.provider is None:
                raise ValueError("usable close requires matching ProviderSpec evidence and a data date")
            if any(item.provider.provider_id != self.provider for item in matching):
                raise ValueError("provider name must match evidence ProviderSpec")
            if any(item.quality.freshness is not self.freshness or item.quality.degraded is not self.degraded for item in matching):
                raise ValueError("observation quality must match evidence quality")
            if any(item.time.data_as_of is None or not item.time.data_as_of.startswith(self.data_date) for item in matching):
                raise ValueError("data_date must match evidence observation time")
            if self.availability in (MarketAvailability.AVAILABLE, MarketAvailability.DELAYED):
                if not any(item.pit_status is PITStatus.ALLOW for item in matching):
                    raise ValueError("usable numeric close requires PIT-allowed evidence")
            elif not any(item.pit_status is PITStatus.REJECT for item in matching):
                raise ValueError("non-usable numeric close requires explicit PIT-rejected evidence")
