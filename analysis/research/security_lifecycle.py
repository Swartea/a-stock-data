"""Listing-lifecycle contract for Security Master.

This B0 layer models when a listing state is effective for a stable security
identity. It deliberately does not model daily trading suspension, prices,
provider symbols, names, or exchange-code changes.

Lifecycle validity reuses A3 TimeMetadata effective_from/effective_to semantics
and A5 PIT evaluation. Intervals are half-open: [effective_from, effective_to).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import Enum

from analysis.research.pit_guard import PITDecision, evaluate_pit
from analysis.research.time_semantics import TimeMetadata

_SECURITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


class ListingState(str, Enum):
    """Provider-neutral listing lifecycle states.

    SUSPENDED means a formal listing-status suspension, not an ordinary
    intraday/daily trading halt.
    """

    LISTED = "listed"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


@dataclass(frozen=True)
class ListingLifecycleRecord:
    """One effective listing-state interval for a stable security identity."""

    security_id: str
    state: ListingState
    time: TimeMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str):
            raise TypeError("security_id must be a string")
        if (
            not self.security_id
            or self.security_id != self.security_id.strip().lower()
            or not _SECURITY_ID_RE.fullmatch(self.security_id)
        ):
            raise ValueError("security_id must be a canonical machine-readable token")

        if not isinstance(self.state, ListingState):
            raise TypeError("state must be ListingState")

        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")
        if self.time.effective_from is None:
            raise ValueError("listing lifecycle requires effective_from")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small lifecycle contract surface."""

        return tuple(field.name for field in fields(cls))


def evaluate_listing_lifecycle(
    record: ListingLifecycleRecord,
    decision_time: str,
) -> PITDecision:
    """Evaluate whether the lifecycle record is effective at decision_time.

    This delegates interval semantics to A5. Publication time is not required
    in this B0 domain contract because some lifecycle sources may not expose it;
    callers that need publication-time strictness should apply A5 separately
    with require_published_at=True.
    """

    if not isinstance(record, ListingLifecycleRecord):
        raise TypeError("record must be ListingLifecycleRecord")

    return evaluate_pit(
        record.time,
        decision_time,
        require_effective_interval=True,
    )
