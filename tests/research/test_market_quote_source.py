"""Tests for the injected index quote-source boundary (S3).

Every test here is offline and behavioural: the transport is a local stub that
records the requests it receives. There is no HTTP client, no real provider, no
clock, and no network access anywhere in this file -- so these tests assert what
the boundary *does*, not that any provider answers.
"""

import ast
import dataclasses
import pathlib

import pytest

from analysis import fetcher_contract
from analysis.fetcher_contract import (
    ERR_UNKNOWN,
    ERR_UNSUPPORTED,
    ERR_VALIDATION,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
)
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_index_universe import MarketIndexUniverse
from analysis.research.market_quote_source import (
    MarketIndexQuoteSource,
    MarketQuoteRequest,
    MarketQuoteRequestError,
)
from analysis.research.providers import ProviderSpec
from analysis.research.time_semantics import TimeMetadata

# --- offline fixtures -------------------------------------------------------

_TENCENT = ProviderSpec("tencent", "Tencent", "tencent")
_EASTMONEY = ProviderSpec("eastmoney", "EastMoney", "eastmoney")
_SINA = ProviderSpec("sina", "Sina", "sina")  # declared for sse.composite below

_COMPOSITE = IndexIdentity("sse.composite", IndexPublisher.SSE, "000001")
_CHINEXT = IndexIdentity("szse.chinext", IndexPublisher.SZSE, "399006")

_UNIVERSE = MarketIndexUniverse(
    identities=(_COMPOSITE, _CHINEXT),
    aliases=(
        IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
        IndexProviderSymbolAlias("sse.composite", "sina", "sh000001-sina"),
    ),
)

# Two independent clocks. data_as_of and fetched_at deliberately differ so a
# test can catch any code that copies one into the other.
_TIME = TimeMetadata(fetched_at="2026-10-08T01:00:00+08:00", data_as_of="2026-10-07")


class RecordingTransport:
    """Callable transport stub that records every request it is handed."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[MarketQuoteRequest] = []

    def __call__(self, request):
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("transport was called more times than the test expected")
        response = self._responses.pop(0)
        # BaseException, not Exception: the stub must faithfully simulate a
        # transport that raises KeyboardInterrupt/SystemExit, rather than
        # handing the signal back as if it were a payload.
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def call_count(self) -> int:
        return len(self.requests)


def _source(*responses):
    transport = RecordingTransport(*responses)
    return MarketIndexQuoteSource(universe=_UNIVERSE, transport=transport), transport


def _ok(**overrides):
    response = {"status": STATUS_OK, "data": {"last": 3000.0}, "error": None}
    response.update(overrides)
    return response


# --- construction: nothing is defaulted, nothing is imported ----------------


def test_constructor_requires_explicit_universe_and_transport() -> None:
    """There is no default transport, so a partial construction is a TypeError."""

    with pytest.raises(TypeError):
        MarketIndexQuoteSource(universe=_UNIVERSE)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        MarketIndexQuoteSource(transport=RecordingTransport(_ok()))  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        MarketIndexQuoteSource()  # type: ignore[call-arg]


def test_constructor_rejects_non_universe_and_non_callable() -> None:
    with pytest.raises(TypeError, match="universe must be MarketIndexUniverse"):
        MarketIndexQuoteSource(
            universe=(_COMPOSITE,),  # type: ignore[arg-type]
            transport=RecordingTransport(_ok()),
        )

    with pytest.raises(TypeError, match="transport must be callable"):
        MarketIndexQuoteSource(universe=_UNIVERSE, transport="tencent")  # type: ignore[arg-type]


def test_constructing_the_source_performs_no_transport_call() -> None:
    transport = RecordingTransport(_ok())

    source = MarketIndexQuoteSource(universe=_UNIVERSE, transport=transport)

    assert source is not None
    assert transport.call_count == 0


def test_module_imports_no_network_client_clock_or_calendar() -> None:
    """Importing the boundary must not drag in a client, a clock, or a calendar."""

    from analysis.research import market_quote_source

    tree = ast.parse(pathlib.Path(market_quote_source.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported.isdisjoint(
        {
            "requests", "httpx", "urllib", "urllib3", "socket", "http", "aiohttp",
            "datetime", "time", "calendar", "zoneinfo", "asyncio",
        }
    )


def test_module_does_not_define_a_status_enum_or_bar_schema() -> None:
    """States are imported, never redefined; bar/evidence shapes stay out."""

    from analysis.research import market_quote_source

    tree = ast.parse(pathlib.Path(market_quote_source.__file__).read_text())
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            defined.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)

    for forbidden in (
        "STATUS_OK", "STATUS_EMPTY", "STATUS_ERROR", "STATUS_UNSUPPORTED",
        "VALID_STATUSES", "QuoteBar", "MarketEvidence", "_now_iso", "now_iso",
        "Ok", "Empty", "Error", "Unsupported",
    ):
        assert forbidden not in defined, forbidden

    # The only scope-like constant is a string, not a new state vocabulary.
    assert market_quote_source.SCOPE_MARKET == "market"


# --- happy path: exact request, exactly one call ---------------------------


def test_transport_receives_the_exact_resolved_request() -> None:
    source, transport = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_TENCENT, time=_TIME)

    assert transport.call_count == 1
    request = transport.requests[0]
    assert request.identity is _COMPOSITE
    assert request.provider is _TENCENT
    assert request.alias == IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001")
    assert request.time is _TIME
    # The request is the same frozen object that comes back as provenance.
    assert envelope.alias is request.alias
    assert envelope.identity is request.identity


def test_exact_provider_match_is_selected_over_other_declared_aliases() -> None:
    source, transport = _source(_ok())

    source.fetch("sse.composite", provider=_SINA, time=_TIME)

    assert transport.requests[0].alias.provider_symbol == "sh000001-sina"


def test_result_is_ok_with_data_and_explicit_provenance_fields() -> None:
    source, _ = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_TENCENT, time=_TIME)
    result = envelope.result

    assert result["status"] == STATUS_OK
    assert result["data"] == {"last": 3000.0}
    assert result["error"] is None
    assert result["scope"] == "market"
    assert result["source"] == "tencent"
    assert result["as_of"] == "2026-10-07"
    assert result["fetched_at"] == "2026-10-08T01:00:00+08:00"


def test_identity_provider_time_and_result_stay_separate_fields() -> None:
    """Provenance is retained alongside the payload, not merged into it."""

    source, _ = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_TENCENT, time=_TIME)

    assert dataclasses.is_dataclass(envelope)
    assert envelope.identity.index_id == "sse.composite"
    assert envelope.identity.local_code == "000001"
    assert envelope.provider.provider_id == "tencent"
    assert envelope.alias.provider_symbol == "sh000001"
    assert envelope.time is _TIME
    # The payload is not re-labelled with identity fields.
    assert set(envelope.result) == {
        "status", "data", "source", "as_of", "fetched_at", "scope", "units", "error",
    }


def test_envelope_and_request_surfaces_are_frozen_and_small() -> None:
    source, _ = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_TENCENT, time=_TIME)

    assert MarketQuoteRequest.contract_fields() == ("identity", "provider", "alias", "time")
    assert envelope.__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.alias = None


def test_result_carries_no_quote_bar_schema_or_evidence() -> None:
    """The payload is opaque: this boundary neither defines nor aggregates bars."""

    source, _ = _source(_ok(data={"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["data"] == {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}
    assert "evidence" not in result
    assert "availability" not in result
    assert "market_state" not in result


# --- numeric zero is real data, not absence --------------------------------


def test_zero_is_valid_ok_data() -> None:
    source, _ = _source(_ok(data=0))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_OK
    assert result["data"] == 0
    assert result["error"] is None


def test_falsey_but_present_data_is_preserved_verbatim() -> None:
    for payload in (0.0, "", False, [], {}):
        source, _ = _source(_ok(data=payload))

        result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

        assert result["status"] == STATUS_OK
        assert result["data"] == payload


# --- empty / error / unsupported -------------------------------------------


def test_empty_with_a_valid_error_object_is_preserved() -> None:
    source, transport = _source(
        {
            "status": STATUS_EMPTY,
            "data": None,
            "error": {"code": "PARSE", "message": "no rows", "retryable": False},
        }
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert transport.call_count == 1
    assert result["status"] == STATUS_EMPTY
    assert result["data"] is None
    assert result["error"]["code"] == "PARSE"


def test_empty_without_an_error_object_gets_the_canonical_empty_error() -> None:
    source, _ = _source({"status": STATUS_EMPTY, "data": None, "error": None})

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_EMPTY
    assert result["data"] is None
    assert result["error"]["code"] == ERR_VALIDATION
    assert result["error"]["retryable"] is False


def test_error_from_transport_is_preserved_with_its_code() -> None:
    source, _ = _source(
        {
            "status": STATUS_ERROR,
            "data": None,
            "error": {"code": "NET_TIMEOUT", "message": "read timed out", "retryable": True},
        }
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_ERROR
    assert result["data"] is None
    assert result["error"] == {
        "code": "NET_TIMEOUT", "message": "read timed out", "retryable": True,
    }
    assert result["scope"] == "market"
    assert result["source"] == "tencent"


def test_unsupported_from_transport_requires_the_unsupported_code() -> None:
    source, _ = _source(
        {
            "status": STATUS_UNSUPPORTED,
            "data": None,
            "error": {"code": ERR_UNSUPPORTED, "message": "no such endpoint", "retryable": False},
        }
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_UNSUPPORTED
    assert result["data"] is None
    assert result["error"]["code"] == ERR_UNSUPPORTED


def test_transport_exception_becomes_canonical_error_with_unknown() -> None:
    source, transport = _source(ConnectionRefusedError("no route"))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert transport.call_count == 1
    assert result["status"] == STATUS_ERROR
    assert result["data"] is None
    assert result["error"]["code"] == ERR_UNKNOWN
    assert "ConnectionRefusedError" in result["error"]["message"]
    assert "no route" in result["error"]["message"]


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("token=secret-value", "token=[redacted]"),
        ("https://example.test/quote?api_key=secret-value", "api_key=[redacted]"),
        ("refresh_token=secret-value", "refresh_token=[redacted]"),
        ("client_secret=secret-value", "client_secret=[redacted]"),
        ("Authorization: Bearer abc123", "Authorization: [redacted]"),
        ("first line\npassword: secret-value", "password: [redacted]"),
    ],
)
def test_transport_exception_detail_is_sanitized_and_single_line(
    detail: str, expected: str
) -> None:
    source, _ = _source(ConnectionRefusedError(detail))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    message = result["error"]["message"]
    assert expected in message
    assert "secret-value" not in message
    assert "abc123" not in message
    assert "\n" not in message
    assert len(message) <= 200


def test_base_exception_from_transport_is_not_swallowed() -> None:
    """Only ordinary failures become data; control-flow signals still propagate."""

    source, _ = _source(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        source.fetch("sse.composite", provider=_TENCENT, time=_TIME)


# --- malformed responses never become success ------------------------------


@pytest.mark.parametrize(
    ("label", "response"),
    [
        ("not_a_mapping", ["ok"]),
        ("none", None),
        ("string", "ok"),
        ("unknown_status", {"status": "OK", "data": {"last": 1.0}}),
        ("missing_status", {"data": {"last": 1.0}}),
        ("empty_status", {"status": "", "data": 1}),
        ("numeric_status", {"status": 200, "data": 1}),
        ("unhashable_status", {"status": [], "data": 1}),
        ("mapping_status", {"status": {"ok": True}, "data": 1}),
        ("ok_without_data", {"status": STATUS_OK, "data": None, "error": None}),
        ("ok_with_data_omitted", {"status": STATUS_OK, "error": None}),
        ("ok_with_error", {"status": STATUS_OK, "data": 1, "error": {"code": "PARSE"}}),
        ("empty_with_data", {"status": STATUS_EMPTY, "data": [1], "error": None}),
        ("error_with_data", {"status": STATUS_ERROR, "data": [1], "error": {"code": "PARSE"}}),
        ("error_without_error_object", {"status": STATUS_ERROR, "data": None, "error": None}),
        ("error_with_string_error", {"status": STATUS_ERROR, "data": None, "error": "boom"}),
        ("error_without_code", {"status": STATUS_ERROR, "data": None, "error": {"message": "x"}}),
        ("error_with_empty_code", {"status": STATUS_ERROR, "data": None, "error": {"code": ""}}),
        ("error_with_non_bool_retryable", {
            "status": STATUS_ERROR, "data": None,
            "error": {"code": "PARSE", "retryable": "yes"},
        }),
        ("error_with_non_string_message", {
            "status": STATUS_ERROR, "data": None,
            "error": {"code": "PARSE", "message": 5},
        }),
        ("unsupported_with_data", {"status": STATUS_UNSUPPORTED, "data": 1, "error": None}),
        ("unsupported_without_error", {"status": STATUS_UNSUPPORTED, "data": None, "error": None}),
        ("unsupported_with_wrong_code", {
            "status": STATUS_UNSUPPORTED, "data": None, "error": {"code": "PARSE"},
        }),
        ("units_not_a_mapping", _ok(units=["pct"])),
        ("units_with_non_string_value", _ok(units={"pct": 1})),
        ("units_with_non_string_key", _ok(units={1: "%"})),
        ("units_with_empty_value", _ok(units={"amount": ""})),
    ],
)
def test_malformed_responses_become_canonical_error_not_ok(label, response) -> None:
    source, transport = _source(response)

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_ERROR, label
    assert result["data"] is None, label
    assert result["error"]["code"] == ERR_VALIDATION, label
    assert result["error"]["retryable"] is False, label
    assert result["scope"] == "market"
    assert result["source"] == "tencent"
    assert transport.call_count == 1


def test_valid_units_are_preserved_onto_the_result() -> None:
    source, _ = _source(_ok(units={"amount": "CNY", "pct": "%"}))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_OK
    assert result["units"] == {"amount": "CNY", "pct": "%"}


def test_result_absent_units_default_to_empty_mapping() -> None:
    source, _ = _source(_ok())

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["units"] == {}


# --- transport error objects must match make_error exactly ------------------


def _error_response(status, error):
    """A minimal, state-shaped transport response carrying one error object."""

    return {"status": status, "data": None, "error": error}


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("missing_message", {"code": "NET_TIMEOUT", "retryable": True}),
        ("missing_retryable", {"code": "NET_TIMEOUT", "message": "read timed out"}),
        ("blank_message", {"code": "NET_TIMEOUT", "message": "   ", "retryable": True}),
        ("empty_message", {"code": "NET_TIMEOUT", "message": "", "retryable": True}),
        ("blank_code", {"code": "   ", "message": "read timed out", "retryable": True}),
        ("missing_code_and_message", {"retryable": True}),
        ("null_retryable", {"code": "NET_TIMEOUT", "message": "x", "retryable": None}),
        ("numeric_retryable", {"code": "NET_TIMEOUT", "message": "x", "retryable": 1}),
        ("missing_all_three", {}),
    ],
)
def test_incomplete_transport_error_object_is_rejected(label, error) -> None:
    """Absent is not a weaker form of valid: all three fields are required.

    Without this the contract helper's defaults would invent a code and a
    retryable flag that the provider never declared.
    """

    source, transport = _source(_error_response(STATUS_ERROR, error))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_ERROR, label
    assert result["data"] is None, label
    assert result["error"]["code"] == ERR_VALIDATION, label
    assert result["error"]["retryable"] is False, label
    assert transport.call_count == 1, label


def test_rejected_error_object_is_replaced_wholesale() -> None:
    """A malformed object is discarded; its own code never survives."""

    source, _ = _source(
        _error_response(
            STATUS_ERROR,
            {"code": "NET_TIMEOUT", "message": " ", "retryable": True},
        )
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["error"]["code"] == ERR_VALIDATION
    assert result["error"]["code"] != "NET_TIMEOUT"


def test_error_object_extension_keys_are_not_forwarded() -> None:
    """Provider-specific extras are dropped by the canonical rebuild."""

    source, _ = _source(
        _error_response(
            STATUS_ERROR,
            {
                "code": "NET_TIMEOUT",
                "message": "read timed out",
                "retryable": True,
                "detail": {"socket": "10.0.0.1"},
                "trace_id": "abc-123",
                "http_status": 504,
            },
        )
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["status"] == STATUS_ERROR
    assert set(result["error"]) == {"code", "message", "retryable"}
    assert result["error"] == {
        "code": "NET_TIMEOUT", "message": "read timed out", "retryable": True,
    }


@pytest.mark.parametrize(
    ("label", "status", "error"),
    [
        (
            "error",
            STATUS_ERROR,
            {"code": "NET_5XX", "message": "bad gateway", "retryable": True},
        ),
        (
            "empty",
            STATUS_EMPTY,
            {"code": "PARSE", "message": "no rows", "retryable": False},
        ),
        (
            "unsupported",
            STATUS_UNSUPPORTED,
            {"code": ERR_UNSUPPORTED, "message": "no such endpoint", "retryable": False},
        ),
    ],
)
def test_complete_error_object_survives_rebuild_in_every_state(label, status, error) -> None:
    """A well-formed object is rebuilt, not rejected, in each reporting state."""

    source, transport = _source(_error_response(status, dict(error, extra="dropped")))

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert transport.call_count == 1, label
    assert result["status"] == status, label
    assert result["data"] is None, label
    assert result["error"] == error, label


def test_transport_error_message_is_bounded_by_the_contract_helper() -> None:
    """Rebuilding goes through make_error, so the 200-char cap still applies."""

    source, _ = _source(
        _error_response(
            STATUS_ERROR,
            {"code": "PARSE", "message": "x" * 500, "retryable": False},
        )
    )

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert len(result["error"]["message"]) == 200


# --- provider/time types are checked before any state is derived ------------


@pytest.mark.parametrize(
    ("label", "index_id", "provider", "time", "match"),
    [
        ("provider_str", "sse.composite", "tencent", _TIME, "provider must be ProviderSpec"),
        ("provider_none", "sse.composite", None, _TIME, "provider must be ProviderSpec"),
        ("time_str", "sse.composite", _TENCENT, "2026-10-08", "time must be TimeMetadata"),
        ("time_none", "sse.composite", _TENCENT, None, "time must be TimeMetadata"),
        (
            "time_mapping",
            "sse.composite",
            _TENCENT,
            {"fetched_at": "2026-10-08T01:00:00+08:00"},
            "time must be TimeMetadata",
        ),
        # The same mistakes where no alias exists at all: without an early
        # type gate these would have been reported as `unsupported` instead.
        ("provider_str_no_alias", "szse.chinext", "tencent", _TIME, "provider must be ProviderSpec"),
        ("time_str_no_alias", "szse.chinext", _TENCENT, "2026-10-08", "time must be TimeMetadata"),
        (
            "provider_str_unmatched_alias",
            "sse.composite",
            "eastmoney",
            _TIME,
            "provider must be ProviderSpec",
        ),
        (
            "time_none_unmatched_alias",
            "sse.composite",
            _EASTMONEY,
            None,
            "time must be TimeMetadata",
        ),
    ],
)
def test_invalid_provider_or_time_raises_type_error_before_any_state(
    label, index_id, provider, time, match
) -> None:
    """A caller mistake is a TypeError, never an unsupported/empty result."""

    source, transport = _source(_ok())

    with pytest.raises(TypeError, match=match):
        source.fetch(index_id, provider=provider, time=time)

    assert transport.call_count == 0, label


def test_invalid_time_raises_even_when_the_alias_would_have_matched() -> None:
    """The type gate runs before the alias gate, not after it."""

    source, transport = _source(_ok())

    with pytest.raises(TypeError, match="time must be TimeMetadata"):
        source.fetch("sse.composite", provider=_TENCENT, time=None)

    assert transport.call_count == 0


def test_unknown_index_still_wins_over_the_argument_type_checks() -> None:
    """An unknown id is a KeyError even when provider/time are also mistyped."""

    source, transport = _source(_ok())

    with pytest.raises(KeyError):
        source.fetch("szse.component", provider="tencent", time=_TIME)

    assert transport.call_count == 0


# --- gates that must run before the transport ------------------------------


def test_unknown_index_raises_before_the_transport_is_invoked() -> None:
    source, transport = _source(_ok())

    with pytest.raises(KeyError):
        source.fetch("szse.component", provider=_TENCENT, time=_TIME)

    assert transport.call_count == 0


def test_unknown_index_id_is_not_normalized_into_a_known_one() -> None:
    source, transport = _source(_ok())

    for candidate in ("sse.composite ", "SSE.COMPOSITE", "sse.composi", "csi.300"):
        with pytest.raises(KeyError):
            source.fetch(candidate, provider=_TENCENT, time=_TIME)

    assert transport.call_count == 0


def test_covered_index_without_any_alias_is_unsupported_before_transport() -> None:
    source, transport = _source(_ok())

    envelope = source.fetch("szse.chinext", provider=_TENCENT, time=_TIME)

    assert transport.call_count == 0
    assert envelope.result["status"] == STATUS_UNSUPPORTED
    assert envelope.result["error"]["code"] == ERR_UNSUPPORTED
    assert envelope.alias is None
    assert envelope.identity is _CHINEXT
    assert envelope.is_unsupported is True


def test_unmatched_provider_is_unsupported_and_never_falls_back() -> None:
    """Asking eastmoney for sse.composite must not borrow tencent's symbol."""

    source, transport = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_EASTMONEY, time=_TIME)

    assert transport.call_count == 0
    assert envelope.alias is None
    assert envelope.result["status"] == STATUS_UNSUPPORTED
    assert envelope.result["error"]["code"] == ERR_UNSUPPORTED
    assert envelope.result["source"] == "eastmoney"
    assert "sh000001" not in envelope.result["error"]["message"]


def test_provider_id_match_is_exact_and_not_case_folded() -> None:
    """A non-canonical provider id cannot even be built, so no fold can occur."""

    source, transport = _source(_ok())

    with pytest.raises(ValueError, match="provider_id must be a lowercase stable token"):
        ProviderSpec("TENCENT", "Tencent", "tencent")

    # And an undeclared-but-canonical provider still stops at the alias gate.
    envelope = source.fetch("sse.composite", provider=_EASTMONEY, time=_TIME)

    assert transport.call_count == 0
    assert envelope.result["status"] == STATUS_UNSUPPORTED


def test_provider_alias_is_matched_verbatim_from_the_universe() -> None:
    """The symbol handed to transport is the declared one, not a rebuilt string."""

    source, transport = _source(_ok())

    source.fetch("sse.composite", provider=_TENCENT, time=_TIME)

    declared = _UNIVERSE.aliases_for("sse.composite")[0]
    assert transport.requests[0].alias is declared
    assert transport.requests[0].alias.provider_symbol == "sh000001"


def test_unsupported_gate_still_reports_both_clocks_verbatim() -> None:
    source, _ = _source(_ok())

    result = source.fetch("sse.composite", provider=_EASTMONEY, time=_TIME).result

    assert result["as_of"] == "2026-10-07"
    assert result["fetched_at"] == "2026-10-08T01:00:00+08:00"


# --- request-level validation ---------------------------------------------


def test_request_rejects_alias_from_another_index() -> None:
    with pytest.raises(MarketQuoteRequestError, match="alias index must match identity"):
        MarketQuoteRequest(
            identity=_COMPOSITE,
            provider=_TENCENT,
            alias=IndexProviderSymbolAlias("szse.chinext", "tencent", "sz399006"),
            time=_TIME,
        )


def test_request_rejects_alias_from_another_provider() -> None:
    with pytest.raises(MarketQuoteRequestError, match="alias provider must match"):
        MarketQuoteRequest(
            identity=_COMPOSITE,
            provider=_TENCENT,
            alias=IndexProviderSymbolAlias("sse.composite", "sina", "sh000001-sina"),
            time=_TIME,
        )


def test_request_rejects_non_string_time_metadata() -> None:
    with pytest.raises(TypeError, match="time must be TimeMetadata"):
        MarketQuoteRequest(
            identity=_COMPOSITE,
            provider=_TENCENT,
            alias=IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
            time="2026-10-08T01:00:00+08:00",  # type: ignore[arg-type]
        )


def test_request_rejects_non_provider_spec() -> None:
    with pytest.raises(TypeError, match="provider must be ProviderSpec"):
        MarketQuoteRequest(
            identity=_COMPOSITE,
            provider="tencent",  # type: ignore[arg-type]
            alias=IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
            time=_TIME,
        )


def test_envelope_rejects_a_mismatched_alias() -> None:
    """The envelope refuses provenance that contradicts its own identity."""

    from analysis.research.market_quote_source import MarketQuoteEnvelope

    with pytest.raises(MarketQuoteRequestError, match="alias index must match identity"):
        MarketQuoteEnvelope(
            identity=_COMPOSITE,
            provider=_TENCENT,
            alias=IndexProviderSymbolAlias("szse.chinext", "tencent", "sz399006"),
            time=_TIME,
            result={"status": STATUS_OK, "data": 1},
        )

    with pytest.raises(MarketQuoteRequestError, match="alias provider must match"):
        MarketQuoteEnvelope(
            identity=_COMPOSITE,
            provider=_TENCENT,
            alias=IndexProviderSymbolAlias("sse.composite", "sina", "sh000001-sina"),
            time=_TIME,
            result={"status": STATUS_OK, "data": 1},
        )


# --- time is preserved, never inferred or read from a clock ----------------


def test_data_as_of_none_stays_none() -> None:
    no_as_of = TimeMetadata(fetched_at="2026-10-08T01:00:00+08:00")
    source, _ = _source(_ok())

    result = source.fetch("sse.composite", provider=_TENCENT, time=no_as_of).result

    assert result["as_of"] is None
    assert result["fetched_at"] == "2026-10-08T01:00:00+08:00"


def test_data_as_of_is_never_backfilled_from_fetched_at() -> None:
    source, _ = _source(_ok())

    result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result

    assert result["as_of"] == "2026-10-07"
    assert result["as_of"] != result["fetched_at"]


def test_extra_time_metadata_fields_survive_on_the_envelope() -> None:
    rich_time = TimeMetadata(
        fetched_at="2026-10-08T01:00:00+08:00",
        data_as_of="2026-10-07",
        period_start="2026-10-01",
        period_end="2026-10-07",
    )
    source, transport = _source(_ok())

    envelope = source.fetch("sse.composite", provider=_TENCENT, time=rich_time)

    assert transport.requests[0].time is rich_time
    assert envelope.time.period_start == "2026-10-01"
    assert envelope.time.period_end == "2026-10-07"
    # The fetcher result still exposes only the two contract time fields.
    assert envelope.result["as_of"] == "2026-10-07"


def test_no_freshness_or_market_state_is_computed() -> None:
    stale_time = TimeMetadata(fetched_at="2000-01-01T00:00:00+08:00", data_as_of="1999-12-31")
    source, _ = _source(_ok())

    result = source.fetch("sse.composite", provider=_TENCENT, time=stale_time).result

    # An ancient payload is still reported exactly as the caller declared it.
    assert result["fetched_at"] == "2000-01-01T00:00:00+08:00"
    for inferred in ("fresh", "stale", "is_stale", "max_age", "age_seconds", "market_state"):
        assert inferred not in result


def test_boundary_never_needs_a_system_clock(monkeypatch) -> None:
    """Patch the contract's wall-clock helper to fail: nothing may call it."""

    def _fail() -> str:
        raise AssertionError("quote source must never need a system clock")

    monkeypatch.setattr(fetcher_contract, "_now_iso", _fail)

    source, transport = _source(_ok(), {"status": STATUS_EMPTY, "data": None, "error": None})
    unsupported_source, _ = _source(_ok())

    ok_result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result
    empty_result = source.fetch("sse.composite", provider=_TENCENT, time=_TIME).result
    unsupported_result = unsupported_source.fetch(
        "sse.composite", provider=_EASTMONEY, time=_TIME
    ).result

    assert transport.call_count == 2
    assert ok_result["fetched_at"] == "2026-10-08T01:00:00+08:00"
    assert empty_result["fetched_at"] == "2026-10-08T01:00:00+08:00"
    assert unsupported_result["fetched_at"] == "2026-10-08T01:00:00+08:00"


# --- contract-surface and isolation checks --------------------------------


def test_source_does_not_reuse_a_second_status_vocabulary() -> None:
    from analysis.research import market_quote_source

    exported = {
        name
        for name in dir(market_quote_source)
        if name.startswith(("STATUS_", "ERR_", "VALID_STATUSES"))
    }

    # Any state this module exposes must be the contract's, by identity.
    for name in exported:
        assert getattr(market_quote_source, name) is getattr(fetcher_contract, name)


def test_source_exposes_only_the_injected_collaborators() -> None:
    source, _ = _source(_ok())

    stored = vars(source)

    assert set(stored) == {"_universe", "_transport"}
    for forbidden in ("_clock", "_calendar", "_registry", "_endpoint", "_client", "_session"):
        assert not hasattr(source, forbidden)
