"""Injectable daily-index-quote transport boundary for the Research Engine.

This module is slice **S3 (part 2)** of
``docs/14-智能市场研究-阶段1-MarketSnapshot-plan.md``: the seam where a daily
index quote request meets a transport, and nothing else.

Rules this module follows on purpose
------------------------------------
* **The universe is an explicit argument to every fetch.**  There is no module
  level default universe, no implicit registry lookup and no "current market"
  state.  An operation cannot be constructed without naming the indexes it is
  allowed to touch.
* **The transport is an explicit injected callable.**  There is no default
  transport, no endpoint constant, no provider client and no import of
  ``requests``.  This module performs **no network access of its own**: it
  validates, delegates, and maps the outcome onto the existing
  :mod:`analysis.fetcher_contract` status vocabulary.  A non-callable injection
  is a ``TypeError`` raised before any target is resolved, following the same
  injectable-boundary check as
  :mod:`analysis.research.trading_calendar_szse_fetch`.
* **The range is date-only.**  ``start`` / ``end`` are inclusive
  :class:`datetime.date` bounds.  :class:`datetime.datetime` is rejected even
  though it subclasses ``date``: a timestamp's intraday instant and timezone are
  not part of this daily contract and are never truncated away silently.
* **No token grammar is declared here.**  Canonical ``index_id`` / ``provider_id``
  form belongs to :mod:`analysis.research.index_registry` and
  :mod:`analysis.research.index_symbols`.  This boundary re-declares neither,
  and adds no index-id grammar of its own: it checks argument *types* itself and
  defers canonicality to the universe, which defers to the existing registry
  contract.  A malformed id therefore raises the existing ``TypeError`` /
  ``ValueError``, while a well-formed id outside the supplied universe is an
  ``unsupported`` target.
* **No provider-specific branch lives here.**  The boundary resolves an exact
  provider symbol from the universe and hands it to the transport.  It never
  knows an endpoint, a URL or a payload shape per provider.
* **The status vocabulary is reused verbatim.**  ``ok`` / ``empty`` / ``error`` /
  ``unsupported`` and their fields come from
  :func:`~analysis.fetcher_contract.make_ok`, :func:`~analysis.fetcher_contract.make_empty`,
  :func:`~analysis.fetcher_contract.make_error_result` and
  :func:`~analysis.fetcher_contract.make_unsupported`.  No new status, code or
  sentinel is invented.
* **No guessed time.**  This module does not compute ``as_of``, does not consult
  a clock and does not judge freshness.  Calendar, state and quality are later
  slices; ``as_of`` stays ``None`` here rather than being filled from a system
  clock.

Transport contract
------------------
The injected callable is invoked with keyword arguments only::

    transport(provider_id=..., provider_symbol=..., start=..., end=...)

and must return a ``list``/``tuple`` of row mappings for the requested range.
The mapping then is:

* non-empty sequence of mappings -> ``ok``
* empty sequence -> ``empty``
* any other object (including ``None``) -> ``error`` (``PARSE``)
* raised exception -> ``error`` (``UNKNOWN``, retryable)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime as DateTime

from analysis.fetcher_contract import (
    ERR_PARSE,
    ERR_UNKNOWN,
    make_empty,
    make_error_result,
    make_ok,
    make_unsupported,
)
from analysis.research.market_index_universe import MarketIndexUniverse

#: ``scope`` value used in every returned blob, per ``fetcher_contract`` §4.
MARKET_SCOPE = "market"


@dataclass(frozen=True)
class IndexQuoteRequest:
    """One resolved daily-quote request handed to the injected transport.

    The transport receives the *resolved provider symbol*, never an index id it
    would have to map itself.  This keeps provider knowledge in the universe and
    out of the boundary.
    """

    market: str
    index_id: str
    publisher: str
    local_code: str
    provider_id: str
    provider_symbol: str
    start: Date
    end: Date


IndexQuoteTransport = Callable[..., object]


def fetch_index_daily_quotes(
    *,
    universe: MarketIndexUniverse,
    index_id: str,
    provider_id: str,
    start: Date,
    end: Date,
    transport: IndexQuoteTransport,
) -> dict:
    """Fetch daily quotes for one index through an injected transport.

    Parameters
    ----------
    universe:
        The only set of indexes this call may touch.  Mandatory, with no default.
    index_id:
        Target index inside ``universe``.
    provider_id:
        Provider whose exact alias must exist in ``universe``.
    start, end:
        Inclusive date range.  ``datetime.date`` values only; a
        ``datetime.datetime`` is rejected instead of being truncated.
    transport:
        Injected callable.  Never defaulted, never constructed here, and
        callability is checked before any target resolution or invocation.

    Returns
    -------
    dict
        An ``analysis.fetcher_contract`` result blob whose ``status`` is one of
        ``ok`` / ``empty`` / ``error`` / ``unsupported``.

    Notes
    -----
    An index outside the universe, or one with no alias for ``provider_id``,
    returns ``unsupported`` **without calling the transport at all**: an
    unsupported request must not turn into a network attempt.

    A rejected argument — a non-callable ``transport``, a wrong-typed
    ``index_id`` / ``provider_id`` / ``universe``, a non-date bound or an
    inverted range — raises ``TypeError`` / ``ValueError`` instead, also without
    calling the transport.
    """

    # The transport is validated first: a bad injection is a programming error
    # and must fail before any target is resolved, so it can never be reported
    # as an ``unsupported`` request that quietly swallowed the mistake.
    transport = _validate_transport(transport)
    _validate_universe(universe)
    _require_str(index_id, "index_id")
    _require_str(provider_id, "provider_id")
    start, end = _validate_range(start, end)

    # The universe owns canonical index-id grammar (via the existing registry
    # contract): a malformed id raises here, while a well-formed id that this
    # universe does not cover is an ``unsupported`` target, not a crash.
    try:
        identity = universe.require_index(index_id)
    except KeyError:
        return make_unsupported(
            source=provider_id,
            scope=MARKET_SCOPE,
            reason=(
                f"index {index_id!r} is not part of the supplied "
                f"{universe.market!r} index universe"
            ),
        )

    alias = universe.alias_for(identity.index_id, provider_id)
    if alias is None:
        return make_unsupported(
            source=provider_id,
            scope=MARKET_SCOPE,
            reason=(
                f"no {provider_id!r} provider symbol is known for index "
                f"{index_id!r} in the supplied {universe.market!r} index universe"
            ),
        )

    request = IndexQuoteRequest(
        market=universe.market,
        index_id=identity.index_id,
        publisher=identity.publisher.value,
        local_code=identity.local_code,
        provider_id=alias.provider_id,
        provider_symbol=alias.provider_symbol,
        start=start,
        end=end,
    )

    try:
        raw = transport(
            provider_id=alias.provider_id,
            provider_symbol=alias.provider_symbol,
            start=start,
            end=end,
        )
    except Exception as exc:
        # Any transport failure becomes data, never a crash.  The message names
        # only the exception type: a transport error string may carry
        # credentials, URLs or tokens and must not be echoed into a result.
        return make_error_result(
            ERR_UNKNOWN,
            f"index quote transport raised {type(exc).__name__}",
            source=alias.provider_id,
            retryable=True,
            scope=MARKET_SCOPE,
        )

    if raw is None:
        return make_error_result(
            ERR_PARSE,
            "index quote transport returned None instead of a sequence of rows",
            source=alias.provider_id,
            retryable=False,
            scope=MARKET_SCOPE,
        )

    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        return make_error_result(
            ERR_PARSE,
            (
                "index quote transport returned "
                f"{type(raw).__name__}, expected a list or tuple of rows"
            ),
            source=alias.provider_id,
            retryable=False,
            scope=MARKET_SCOPE,
        )

    rows = list(raw)
    if not _rows_are_mappings(rows):
        return make_error_result(
            ERR_PARSE,
            "index quote rows must all be mappings",
            source=alias.provider_id,
            retryable=False,
            scope=MARKET_SCOPE,
        )

    if not rows:
        return make_empty(
            source=alias.provider_id,
            scope=MARKET_SCOPE,
            reason=(
                f"no daily quote rows for {alias.provider_id} symbol "
                f"{alias.provider_symbol!r} in the requested range"
            ),
        )

    return make_ok(
        {
            "rows": rows,
            "request": {
                "market": request.market,
                "index_id": request.index_id,
                "publisher": request.publisher,
                "local_code": request.local_code,
                "provider_id": request.provider_id,
                "provider_symbol": request.provider_symbol,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
        },
        source=alias.provider_id,
        scope=MARKET_SCOPE,
    )


def _rows_are_mappings(rows: Sequence[object]) -> bool:
    return all(isinstance(row, Mapping) for row in rows)


def _validate_universe(universe: object) -> None:
    if not isinstance(universe, MarketIndexUniverse):
        raise TypeError("universe must be a MarketIndexUniverse")


def _validate_transport(transport: object) -> IndexQuoteTransport:
    """Reject a non-callable injection before anything is resolved or called.

    The injectable boundary is checked the same way as in
    ``trading_calendar_szse_fetch.py``: a programming mistake (passing ``None``,
    a client object or a string) fails loudly with ``TypeError`` instead of
    surfacing later as a confusing ``TypeError`` from the call site — or, worse,
    as a successful ``unsupported`` result that hides the bad injection.

    This stays deliberately one-directional: a *callable* transport that raises
    is a fetch failure and keeps mapping onto ``error`` (``ERR_UNKNOWN``) further
    down, exactly as before.
    """

    if not callable(transport):
        raise TypeError("transport must be callable")
    return transport


def _require_str(value: object, name: str) -> str:
    """Reject a wrong-typed lookup key without restating its grammar.

    Canonical token form is owned by the existing ``index_registry`` /
    ``index_symbols`` contracts and is enforced through the universe, so this
    boundary never re-declares an index-id or provider-id grammar.
    """

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _validate_range(start: object, end: object) -> tuple[Date, Date]:
    """Accept date-only bounds for an inclusive daily range.

    ``datetime.datetime`` **inherits** ``datetime.date``, so a bare
    ``isinstance(..., date)`` check would quietly admit it.  That is a semantic
    leak, not a convenience: a timestamp carries an intraday instant and a
    timezone, while this contract is an inclusive *daily* range whose bounds are
    serialized with ``.isoformat()`` and compared as whole days.  Truncating a
    timestamp here would silently discard information the caller believes was
    honoured, so the value is rejected outright and the caller re-declares the
    intended day.
    """

    if isinstance(start, DateTime) or isinstance(end, DateTime):
        raise TypeError(
            "start and end must be datetime.date values, not datetime.datetime"
        )
    if not isinstance(start, Date) or not isinstance(end, Date):
        raise TypeError("start and end must be datetime.date values")
    if start > end:
        raise ValueError("start must not be after end")
    return start, end


__all__ = [
    "MARKET_SCOPE",
    "IndexQuoteRequest",
    "IndexQuoteTransport",
    "fetch_index_daily_quotes",
]
