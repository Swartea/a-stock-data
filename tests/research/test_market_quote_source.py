"""Offline unit tests for the S3 daily index quote transport boundary.

No network and no live source: every case injects a recording or failing stub
transport, so the outbound-denying sentinel must observe zero attempts.

The stubs below are the only "sources" in this file. Nothing here pretends to
know a real Hong Kong or US index identity; the non-CN market cases use an
explicitly neutral, invented example market token.
"""

from datetime import date, datetime

import pytest

from analysis.fetcher_contract import (
    ERR_PARSE,
    ERR_UNKNOWN,
    ERR_UNSUPPORTED,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    is_empty,
    is_error,
    is_ok,
    is_unsupported,
    status_of,
)
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_index_universe import (
    MarketIndexUniverse,
    a_share_core_universe,
    build_universe,
)
from analysis.research.market_quote_source import (
    MARKET_SCOPE,
    fetch_index_daily_quotes,
)

START = date(2026, 10, 1)
END = date(2026, 10, 5)

ROWS = [
    {"date": "2026-10-01", "close": 3900.12, "volume": 1000},
    {"date": "2026-10-02", "close": 3910.55, "volume": 1200},
]


_DEFAULT = object()


class RecordingTransport:
    """Injected stub that records its keyword arguments and replays a result.

    ``result`` defaults through a private sentinel so that ``None`` stays a
    replayable *value* (a malformed transport result) rather than colliding with
    "no result supplied".
    """

    def __init__(self, result=_DEFAULT, error=None):
        self.result = ROWS if result is _DEFAULT else result
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _fetch(transport, *, universe=None, index_id="csi.300", provider_id="eastmoney"):
    return fetch_index_daily_quotes(
        universe=a_share_core_universe() if universe is None else universe,
        index_id=index_id,
        provider_id=provider_id,
        start=START,
        end=END,
        transport=transport,
    )


# --- injection is mandatory ------------------------------------------------


def test_transport_is_required_and_never_defaulted() -> None:
    """No default transport exists, so a fetch cannot happen implicitly."""

    with pytest.raises(TypeError):
        fetch_index_daily_quotes(  # type: ignore[call-arg]
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=START,
            end=END,
        )


def test_universe_is_required_and_never_defaulted() -> None:
    with pytest.raises(TypeError):
        fetch_index_daily_quotes(  # type: ignore[call-arg]
            index_id="csi.300",
            provider_id="eastmoney",
            start=START,
            end=END,
            transport=RecordingTransport(),
        )


def test_boundary_module_carries_no_network_client_or_endpoint() -> None:
    """Structural check: no HTTP client and no endpoint is reachable from here."""

    from analysis.research import market_quote_source

    module_names = set(vars(market_quote_source))
    for network_name in ("requests", "urllib", "http", "socket", "httpx", "urlopen"):
        assert network_name not in module_names

    # No endpoint/URL constant exists for a provider to be pointed at.
    url_like = [
        name
        for name in module_names
        if name.isupper() and ("URL" in name or "ENDPOINT" in name or "HOST" in name)
    ]
    assert url_like == []


# --- the four statuses ------------------------------------------------------


def test_ok_status_for_valid_rows() -> None:
    transport = RecordingTransport()

    result = _fetch(transport)

    assert status_of(result) == STATUS_OK
    assert is_ok(result) and not is_error(result)
    assert result["data"]["rows"] == ROWS
    assert result["scope"] == MARKET_SCOPE == "market"
    assert result["source"] == "eastmoney"


def test_ok_status_carries_the_resolved_request_verbatim() -> None:
    result = _fetch(RecordingTransport())

    request = result["data"]["request"]
    assert request["index_id"] == "csi.300"
    assert request["provider_id"] == "eastmoney"
    assert request["provider_symbol"] == "1.000300"
    assert request["publisher"] == "csi"
    assert request["local_code"] == "000300"
    assert request["start"] == "2026-10-01"
    assert request["end"] == "2026-10-05"


def test_empty_status_for_an_empty_sequence() -> None:
    result = _fetch(RecordingTransport(result=[]))

    assert status_of(result) == STATUS_EMPTY
    assert is_empty(result) and not is_error(result)
    assert result["data"] is None
    assert result["scope"] == MARKET_SCOPE


def test_empty_status_for_an_empty_tuple() -> None:
    assert status_of(_fetch(RecordingTransport(result=()))) == STATUS_EMPTY


def test_error_status_for_a_raising_transport() -> None:
    result = _fetch(RecordingTransport(error=RuntimeError("boom")))

    assert status_of(result) == STATUS_ERROR
    assert is_error(result)
    assert result["error"]["code"] == ERR_UNKNOWN
    assert result["error"]["retryable"] is True
    assert result["data"] is None


def test_transport_error_message_reports_only_the_exception_type() -> None:
    """An exception text is never echoed into the result.

    Provider error strings routinely embed endpoints, headers or credentials,
    so the boundary records only the exception class name.  Asserting the exact
    message keeps that guarantee content-independent: the exception text is
    excluded by construction rather than by filtering for known-bad shapes, so
    no planted value of any shape could reach the result.
    """

    exception_text = "upstream refused the request"
    result = _fetch(RecordingTransport(error=ValueError(exception_text)))

    assert result["error"]["message"] == "index quote transport raised ValueError"
    assert exception_text not in str(result)


@pytest.mark.parametrize(
    "bad_result",
    [None, "not-a-sequence", 42, {"rows": ROWS}, object()],
)
def test_error_status_for_malformed_results(bad_result) -> None:
    result = _fetch(RecordingTransport(result=bad_result))

    assert status_of(result) == STATUS_ERROR
    assert result["error"]["code"] == ERR_PARSE
    assert result["error"]["retryable"] is False


def test_error_status_for_non_mapping_rows() -> None:
    result = _fetch(RecordingTransport(result=[["2026-10-01", 3900.12]]))

    assert status_of(result) == STATUS_ERROR
    assert result["error"]["code"] == ERR_PARSE


def test_unsupported_status_for_index_outside_the_universe() -> None:
    transport = RecordingTransport()

    result = _fetch(transport, index_id="unknown.index")

    assert status_of(result) == STATUS_UNSUPPORTED
    assert is_unsupported(result)
    assert result["error"]["code"] == ERR_UNSUPPORTED
    assert transport.calls == []


def test_unsupported_status_for_a_missing_provider_alias() -> None:
    """szse.component has no repository-backed alias, so nothing is invented."""

    transport = RecordingTransport()

    result = _fetch(transport, index_id="szse.component", provider_id="eastmoney")

    assert status_of(result) == STATUS_UNSUPPORTED
    assert result["error"]["code"] == ERR_UNSUPPORTED
    assert transport.calls == []


def test_unsupported_status_for_a_provider_without_any_alias() -> None:
    transport = RecordingTransport()

    result = _fetch(transport, index_id="csi.300", provider_id="bloomberg")

    assert status_of(result) == STATUS_UNSUPPORTED
    assert transport.calls == []


def test_every_alias_in_the_universe_is_addressable() -> None:
    universe = a_share_core_universe()

    for alias in universe.aliases:
        transport = RecordingTransport()
        result = _fetch(transport, index_id=alias.index_id, provider_id=alias.provider_id)

        assert status_of(result) == STATUS_OK
        assert transport.calls[0]["provider_symbol"] == alias.provider_symbol


# --- transport invocation ---------------------------------------------------


def test_transport_receives_resolved_provider_symbol_and_exact_range() -> None:
    transport = RecordingTransport()

    _fetch(transport)

    assert transport.calls == [
        {
            "provider_id": "eastmoney",
            "provider_symbol": "1.000300",
            "start": START,
            "end": END,
        }
    ]


def test_transport_never_receives_an_index_id_to_map_itself() -> None:
    transport = RecordingTransport()

    _fetch(transport)

    assert "index_id" not in transport.calls[0]
    assert "universe" not in transport.calls[0]


def test_transport_receives_keyword_arguments_only() -> None:
    seen = []

    def transport(*args, **kwargs):
        seen.append((args, kwargs))
        return ROWS

    fetch_index_daily_quotes(
        universe=a_share_core_universe(),
        index_id="csi.300",
        provider_id="csi",
        start=START,
        end=END,
        transport=transport,
    )

    args, kwargs = seen[0]
    assert args == ()
    assert set(kwargs) == {"provider_id", "provider_symbol", "start", "end"}


# --- argument validation ---------------------------------------------------


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValueError, match="start must not be after end"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=END,
            end=START,
            transport=RecordingTransport(),
        )


@pytest.mark.parametrize("bad_date", ["2026-10-01", 20261001, None])
def test_non_date_range_is_rejected(bad_date) -> None:
    transport = RecordingTransport()

    with pytest.raises(TypeError, match="start and end must be datetime.date"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=bad_date,
            end=END,
            transport=transport,
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "bad_datetime",
    [datetime(2026, 10, 1, 15, 0), datetime(2026, 10, 5, 0, 0, 1)],
)
def test_datetime_bound_is_rejected_at_start(bad_datetime) -> None:
    """``datetime`` subclasses ``date``, so the naive type check would admit it.

    The quote range is date-only: a timestamp carries an intraday instant and a
    timezone that this daily contract cannot honour.  Rejecting it beats
    truncating it, which would silently drop information the caller supplied.
    """

    transport = RecordingTransport()

    with pytest.raises(TypeError, match="not datetime.datetime"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=bad_datetime,
            end=END,
            transport=transport,
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "bad_datetime",
    [datetime(2026, 10, 5, 15, 0), datetime(2026, 10, 1, 0, 0, 1)],
)
def test_datetime_bound_is_rejected_at_end(bad_datetime) -> None:
    transport = RecordingTransport()

    with pytest.raises(TypeError, match="not datetime.datetime"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=START,
            end=bad_datetime,
            transport=transport,
        )

    assert transport.calls == []


def test_datetime_rejection_holds_even_for_a_fully_valid_target() -> None:
    """The rejection is about the bound type, not about the target being legal.

    ``csi.300`` on ``eastmoney`` is the one combination that reaches the
    transport in the happy path, so it is used here to prove the datetime guard
    fires before any invocation rather than being masked by an earlier failure.
    """

    transport = RecordingTransport()

    with pytest.raises(TypeError, match="not datetime.datetime"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=datetime(2026, 10, 1, 9, 30),
            end=datetime(2026, 10, 5, 15, 0),
            transport=transport,
        )

    assert transport.calls == []


def test_date_bounds_are_still_accepted_after_the_datetime_guard() -> None:
    """The guard is narrow: plain ``date`` keeps working unchanged."""

    transport = RecordingTransport()

    result = fetch_index_daily_quotes(
        universe=a_share_core_universe(),
        index_id="csi.300",
        provider_id="eastmoney",
        start=date(2026, 10, 1),
        end=date(2026, 10, 5),
        transport=transport,
    )

    assert status_of(result) == STATUS_OK
    assert transport.calls[0]["start"] == date(2026, 10, 1)
    assert transport.calls[0]["end"] == date(2026, 10, 5)
    assert type(transport.calls[0]["start"]) is date
    assert type(transport.calls[0]["end"]) is date


@pytest.mark.parametrize(
    "bad_transport",
    [None, 42, "eastmoney-transport", object(), ["callable?"]],
)
def test_non_callable_transport_is_rejected(bad_transport) -> None:
    """A non-callable injection is a programming error, not a fetch outcome.

    The injectable boundary is checked up front (same rule as
    ``trading_calendar_szse_fetch``), so a ``None`` transport can never be
    silently downgraded into an ``unsupported`` result or reach a call site.
    """

    with pytest.raises(TypeError, match="transport must be callable"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=START,
            end=END,
            transport=bad_transport,
        )


def test_non_callable_transport_is_rejected_before_target_resolution() -> None:
    """The check runs before resolution, so it wins over ``unsupported``.

    Without this ordering a bad transport plus an unknown index would return
    ``unsupported`` and hide the real mistake behind a plausible-looking result.
    """

    class Exploding:
        """A non-callable stand-in that must never be touched at all."""

        def __getattr__(self, name):  # pragma: no cover - must never be reached
            raise AssertionError(f"non-callable transport was inspected: {name}")

    with pytest.raises(TypeError, match="transport must be callable"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="unknown.index",
            provider_id="eastmoney",
            start=START,
            end=END,
            transport=Exploding(),
        )


def test_non_callable_transport_is_rejected_before_any_argument_is_used() -> None:
    """Even with otherwise-invalid bounds the transport guard fires first."""

    with pytest.raises(TypeError, match="transport must be callable"):
        fetch_index_daily_quotes(
            universe=a_share_core_universe(),
            index_id="csi.300",
            provider_id="eastmoney",
            start=END,
            end=START,
            transport=None,  # type: ignore[arg-type]
        )


def test_callable_transport_that_raises_still_maps_to_error_status() -> None:
    """Callability validation must not swallow the four statuses.

    A *callable* transport that raises stays a fetch failure reported as
    ``error``/``ERR_UNKNOWN``; only a non-callable injection is a ``TypeError``.
    """

    result = _fetch(RecordingTransport(error=RuntimeError("boom")))

    assert status_of(result) == STATUS_ERROR
    assert result["error"]["code"] == ERR_UNKNOWN
    assert result["error"]["retryable"] is True


def test_callable_object_instance_is_accepted_as_transport() -> None:
    """Any callable is accepted, not only plain functions."""

    transport = RecordingTransport()

    result = _fetch(transport)

    assert status_of(result) == STATUS_OK
    assert len(transport.calls) == 1


def test_equal_start_and_end_is_allowed() -> None:
    result = fetch_index_daily_quotes(
        universe=a_share_core_universe(),
        index_id="csi.300",
        provider_id="csi",
        start=START,
        end=START,
        transport=RecordingTransport(),
    )

    assert status_of(result) == STATUS_OK


@pytest.mark.parametrize("bad_index_id", ["", "CSI.300", "csi 300", 1, None])
def test_malformed_index_id_is_rejected(bad_index_id) -> None:
    """Canonicality comes from the existing index contracts, not a local grammar.

    The boundary adds no index-id grammar of its own: a wrong type raises
    ``TypeError`` and a non-canonical token raises ``ValueError``, both decided
    by the contracts this slice reuses verbatim.
    """

    transport = RecordingTransport()

    with pytest.raises((TypeError, ValueError)):
        _fetch(transport, index_id=bad_index_id)

    assert transport.calls == []


def test_boundary_declares_no_index_id_or_provider_id_grammar() -> None:
    """Structural check: the boundary re-declares no token grammar."""

    from analysis.research import market_quote_source

    compiled = [
        name
        for name, value in vars(market_quote_source).items()
        if name.startswith("_") and hasattr(value, "fullmatch")
    ]

    assert compiled == []


@pytest.mark.parametrize("bad_provider_id", [1, None, object()])
def test_non_string_provider_id_is_rejected(bad_provider_id) -> None:
    transport = RecordingTransport()

    with pytest.raises(TypeError):
        _fetch(transport, provider_id=bad_provider_id)

    assert transport.calls == []


@pytest.mark.parametrize("unknown_provider_id", ["", "EastMoney", "east money"])
def test_provider_id_that_matches_no_alias_is_unsupported(unknown_provider_id) -> None:
    """An unrecognized provider id is an unsupported target, not a crash.

    The provider id is only a lookup key here; when it matches no alias the
    boundary reports ``unsupported`` without calling the transport.
    """

    transport = RecordingTransport()

    result = _fetch(transport, provider_id=unknown_provider_id)

    assert status_of(result) == STATUS_UNSUPPORTED
    assert transport.calls == []


def test_non_universe_argument_is_rejected() -> None:
    transport = RecordingTransport()

    with pytest.raises(TypeError, match="universe must be a MarketIndexUniverse"):
        fetch_index_daily_quotes(
            universe=object(),  # type: ignore[arg-type]
            index_id="csi.300",
            provider_id="eastmoney",
            start=START,
            end=END,
            transport=transport,
        )

    assert transport.calls == []


# --- market scope is not hard-coded to China --------------------------------


def test_non_cn_market_scope_works_through_the_same_boundary() -> None:
    """The boundary has no China-only branch.

    The identity below is an explicitly invented placeholder, not a claim about
    any real HK/US index; ``IndexPublisher`` cannot yet name such a publisher
    (see ``test_index_publisher_enum_cannot_name_a_hk_or_us_publisher``).
    """

    placeholder = IndexIdentity("example.core.one", IndexPublisher.CSI, "EX00001")
    universe = build_universe(
        market="example-market",
        indexes=(placeholder,),
        aliases=(IndexProviderSymbolAlias("example.core.one", "examplefeed", "EX1"),),
    )
    transport = RecordingTransport()

    result = _fetch(
        transport,
        universe=universe,
        index_id="example.core.one",
        provider_id="examplefeed",
    )

    assert status_of(result) == STATUS_OK
    assert transport.calls == [
        {
            "provider_id": "examplefeed",
            "provider_symbol": "EX1",
            "start": START,
            "end": END,
        }
    ]
    assert result["data"]["request"]["market"] == "example-market"


def test_non_cn_market_scope_reports_its_own_market_in_unsupported_reason() -> None:
    placeholder = IndexIdentity("example.core.one", IndexPublisher.CSI, "EX00001")
    universe = build_universe(
        market="example-market",
        indexes=(placeholder,),
        aliases=(),
    )

    result = _fetch(
        RecordingTransport(),
        universe=universe,
        index_id="example.core.one",
        provider_id="examplefeed",
    )

    assert status_of(result) == STATUS_UNSUPPORTED
    assert "example-market" in result["error"]["message"]


# --- boundary hygiene -------------------------------------------------------


def test_boundary_makes_no_guessed_time() -> None:
    result = _fetch(RecordingTransport())

    assert result["as_of"] is None
    assert isinstance(result["fetched_at"], str) and result["fetched_at"]


def test_result_shape_matches_the_fetcher_contract() -> None:
    result = _fetch(RecordingTransport())

    assert set(result) == {
        "status",
        "data",
        "source",
        "as_of",
        "fetched_at",
        "scope",
        "units",
        "error",
    }


def test_universe_is_not_mutated_by_a_fetch() -> None:
    universe = a_share_core_universe()
    before = universe.index_ids, universe.aliases

    _fetch(RecordingTransport(), universe=universe)

    assert (universe.index_ids, universe.aliases) == before


def test_boundary_does_not_depend_on_the_a_share_helper() -> None:
    """No default universe: a fetch on a different market uses only its own data."""

    custom = MarketIndexUniverse(
        market="example-market",
        indexes=(IndexIdentity("example.core.two", IndexPublisher.SSE, "EX00002"),),
        aliases=(),
    )
    transport = RecordingTransport()

    result = _fetch(transport, universe=custom, index_id="csi.300", provider_id="csi")

    assert status_of(result) == STATUS_UNSUPPORTED
    assert transport.calls == []
