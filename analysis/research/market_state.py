"""Pure market-state and time composition for the Research Engine.

This module is the **S4** slice.  It composes the contracts that already exist --
:class:`~analysis.research.trading_calendar.TradingCalendar` evidence,
:class:`~analysis.research.time_semantics.TimeMetadata` clocks,
:class:`~analysis.research.freshness.MaxAgePolicy` /
:class:`~analysis.research.freshness.FreshnessDecision`, and
:class:`~analysis.research.quality.QualityMetadata` -- into one explainable
decision, and it adds no new facts of its own.

Two independent questions are answered side by side and are never merged:

* **What does the calendar say about the supplied ``calendar_date``?**
  Only explicit rows for *that* date may answer.  A missing calendar, an empty
  calendar, an unobserved date, and an explicit ``UNKNOWN`` row are four
  distinguishable situations that all resolve to
  :attr:`~analysis.research.trading_calendar.TradingDayStatus.UNKNOWN` with four
  different reasons.  ``OPEN`` and ``CLOSED`` rows are preserved exactly.
* **How old is the observation under the supplied policy?**
  This is delegated verbatim to
  :func:`~analysis.research.freshness.evaluate_freshness`.  The inclusive
  max-age boundary, the ``UNKNOWN`` result for a missing ``data_as_of``, and the
  invalid / future / naive-vs-aware errors all stay owned by that function; this
  module neither copies the calculation nor reinterprets its exceptions.

Deliberate non-behaviour
------------------------

* **No inference.**  The calendar answer is not derived from a weekday, a holiday
  list, session hours, the current clock, ``evaluation_time``'s own date,
  ``fetched_at``, ``data_as_of``, the latest observed row, or any previous
  trading day.  A date with no evidence stays ``UNKNOWN``; it is never coerced
  to ``CLOSED``.
* **One date, not "the market right now".**  The result states the supplied
  date's calendar evidence only.  It deliberately does **not** say whether a
  session is currently open or closed, and it does not pick a "latest" date.
* **No clock substitution.**  ``fetched_at``, ``period_start``/``period_end``,
  ``published_at``, and ``effective_from``/``effective_to`` never stand in for
  ``data_as_of``, and a date-only value is never given an invented aware
  timestamp to make it comparable.
* **No business policy.**  The returned :class:`QualityMetadata` copies
  ``completeness``, ``degraded``, and ``quality_flags`` verbatim.  Only
  ``freshness`` is recomputed, from the freshness decision itself.  A ``CLOSED``
  or ``UNKNOWN`` calendar row and a ``STALE`` observation do not by themselves
  mark anything degraded, incomplete, or flagged; point-in-time availability and
  other downstream judgments belong to later layers.
* **No defaults and no ambient inputs.**  Every input is keyword-only and
  required: there is no default calendar, policy, time, quality, or "now".
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from analysis.research.freshness import (
    FreshnessDecision,
    MaxAgePolicy,
    evaluate_freshness,
)
from analysis.research.quality import QualityMetadata
from analysis.research.time_semantics import TimeMetadata
from analysis.research.trading_calendar import (
    TradingCalendar,
    TradingDayStatus,
    _parse_iso_date,
)

# Stable machine-readable calendar reasons.  The four UNKNOWN causes stay
# distinct on purpose: "we were not told" is a different claim from "we were told
# and it is unresolved", and a caller must be able to tell them apart.
_REASON_OPEN = "calendar_row_explicitly_open"
_REASON_CLOSED = "calendar_row_explicitly_closed"
_REASON_NO_CALENDAR = "calendar_not_supplied"
_REASON_NO_OBSERVATIONS = "calendar_has_no_observations"
_REASON_DATE_NOT_OBSERVED = "calendar_date_not_observed"
_REASON_ROW_UNKNOWN = "calendar_row_explicitly_unknown"

_UNKNOWN_CALENDAR_REASONS = frozenset(
    {
        _REASON_NO_CALENDAR,
        _REASON_NO_OBSERVATIONS,
        _REASON_DATE_NOT_OBSERVED,
        _REASON_ROW_UNKNOWN,
    }
)


def _resolve_calendar(
    calendar: TradingCalendar | None,
    calendar_date: str,
) -> tuple[TradingDayStatus, str]:
    """Return the supplied date's explicit calendar status and its reason.

    Only rows carrying ``calendar_date`` itself may produce a decision.  The
    lookup never consults a weekday, a holiday list, session hours, a clock, or
    the most recent row, so an unobserved or unresolved date remains ``UNKNOWN``
    instead of being inferred closed.
    """

    if calendar is None:
        return TradingDayStatus.UNKNOWN, _REASON_NO_CALENDAR
    if not calendar.days:
        return TradingDayStatus.UNKNOWN, _REASON_NO_OBSERVATIONS

    target = _parse_iso_date(calendar_date, field_name="calendar_date")
    for day in calendar.days:
        if _parse_iso_date(day.date, field_name="calendar date") != target:
            continue
        if day.status is TradingDayStatus.UNKNOWN:
            return TradingDayStatus.UNKNOWN, _REASON_ROW_UNKNOWN
        if day.status is TradingDayStatus.CLOSED:
            return TradingDayStatus.CLOSED, _REASON_CLOSED
        return TradingDayStatus.OPEN, _REASON_OPEN

    return TradingDayStatus.UNKNOWN, _REASON_DATE_NOT_OBSERVED


@dataclass(frozen=True)
class MarketStateDecision:
    """One explainable composition of calendar evidence, freshness, and quality.

    The record keeps every input it was derived from -- ``calendar_date``, the
    original ``time`` metadata, the explicit ``evaluation_time`` and ``policy``,
    and the resulting ``freshness`` decision -- so a reader can re-derive the
    outcome instead of trusting a bare label.  ``calendar`` itself is not stored:
    it is evidence, and the evidence about the decision is the status plus its
    reason.

    ``quality.freshness`` is required to equal ``freshness.status``; the
    remaining quality fields are carried over untouched.
    """

    calendar_date: str
    trading_day_status: TradingDayStatus
    calendar_reason: str
    time: TimeMetadata
    evaluation_time: str
    policy: MaxAgePolicy
    freshness: FreshnessDecision
    quality: QualityMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_date, str):
            raise TypeError("calendar_date must be a string")
        _parse_iso_date(self.calendar_date, field_name="calendar_date")

        if not isinstance(self.trading_day_status, TradingDayStatus):
            raise TypeError("trading_day_status must be TradingDayStatus")

        if not isinstance(self.calendar_reason, str):
            raise TypeError("calendar_reason must be a string")
        if not self.calendar_reason or self.calendar_reason != self.calendar_reason.strip():
            raise ValueError("calendar_reason must be a non-empty trimmed string")

        # The reason must explain the status it is paired with, so a hand-built
        # decision cannot claim "open" while citing an unresolved-calendar reason.
        expected_reason = {
            TradingDayStatus.OPEN: _REASON_OPEN,
            TradingDayStatus.CLOSED: _REASON_CLOSED,
        }.get(self.trading_day_status)
        if expected_reason is None:
            if self.calendar_reason not in _UNKNOWN_CALENDAR_REASONS:
                raise ValueError(
                    "unknown trading_day_status requires one of the four unknown "
                    "calendar reasons"
                )
        elif self.calendar_reason != expected_reason:
            raise ValueError(
                f"{self.trading_day_status.value} requires calendar_reason "
                f"{expected_reason!r}"
            )

        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")

        if not isinstance(self.evaluation_time, str):
            raise TypeError("evaluation_time must be a string")
        if not self.evaluation_time.strip():
            raise ValueError("evaluation_time must be a non-empty string")

        if not isinstance(self.policy, MaxAgePolicy):
            raise TypeError("policy must be MaxAgePolicy")

        if not isinstance(self.freshness, FreshnessDecision):
            raise TypeError("freshness must be FreshnessDecision")

        if not isinstance(self.quality, QualityMetadata):
            raise TypeError("quality must be QualityMetadata")

        # The output quality envelope is the freshness decision, not a second
        # opinion about it.
        if self.quality.freshness is not self.freshness.status:
            raise ValueError("quality.freshness must equal freshness.status")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small decision surface."""

        return tuple(field.name for field in fields(cls))


def evaluate_market_state(
    *,
    calendar_date: str,
    calendar: TradingCalendar | None,
    time: TimeMetadata,
    evaluation_time: str,
    policy: MaxAgePolicy,
    quality: QualityMetadata,
) -> MarketStateDecision:
    """Compose calendar evidence and freshness into one market-state decision.

    Rules:

    * ``calendar_date`` must be a canonical ``YYYY-MM-DD`` string; the function
      never derives a date from a clock or a payload;
    * ``calendar`` may be ``None``, empty, partial, or explicit, and the four
      ``UNKNOWN`` situations stay distinguishable by ``calendar_reason``;
    * explicit ``OPEN``/``CLOSED`` rows are preserved exactly, and nothing about
      "right now" is claimed;
    * freshness is delegated to
      :func:`~analysis.research.freshness.evaluate_freshness`, whose errors --
      unparsable timestamps, naive-vs-aware mixes, and future ``data_as_of`` --
      propagate untranslated;
    * ``quality`` keeps its ``completeness``, ``degraded``, and
      ``quality_flags``; only ``freshness`` is replaced by the decision's status.

    Every argument is keyword-only and required, so no caller can inherit a
    default calendar, policy, clock, or quality envelope.
    """

    if not isinstance(calendar_date, str):
        raise TypeError("calendar_date must be a string")
    _parse_iso_date(calendar_date, field_name="calendar_date")

    if calendar is not None and not isinstance(calendar, TradingCalendar):
        raise TypeError("calendar must be TradingCalendar or None")

    if not isinstance(time, TimeMetadata):
        raise TypeError("time must be TimeMetadata")

    if not isinstance(evaluation_time, str):
        raise TypeError("evaluation_time must be a string")
    if not evaluation_time.strip():
        raise ValueError("evaluation_time must be a non-empty string")

    if not isinstance(policy, MaxAgePolicy):
        raise TypeError("policy must be MaxAgePolicy")

    if not isinstance(quality, QualityMetadata):
        raise TypeError("quality must be QualityMetadata")

    trading_day_status, calendar_reason = _resolve_calendar(calendar, calendar_date)

    # Delegated, not reimplemented: the inclusive max-age boundary, the
    # data_as_of=None UNKNOWN case, and every invalid/future/naive-vs-aware
    # ValueError stay owned by evaluate_freshness.
    freshness = evaluate_freshness(time, evaluation_time, policy=policy)

    return MarketStateDecision(
        calendar_date=calendar_date,
        trading_day_status=trading_day_status,
        calendar_reason=calendar_reason,
        time=time,
        evaluation_time=evaluation_time,
        policy=policy,
        freshness=freshness,
        quality=QualityMetadata(
            freshness=freshness.status,
            completeness=quality.completeness,
            degraded=quality.degraded,
            quality_flags=quality.quality_flags,
        ),
    )
