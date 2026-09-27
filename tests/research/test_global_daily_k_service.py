"""Offline tests for the V2 Daily-K provider-fallback orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest
import requests

from analysis import fetcher_contract
from analysis.research import global_daily_k_service as service
from analysis.research.global_daily_k import (
    TENCENT_DAILY_K_URL,
    TENCENT_PROVIDER_ID,
    TENCENT_SCOPE,
    TENCENT_SOURCE,
    fetch_global_daily_k,
)
from analysis.research.global_daily_k_service import (
    DailyKProvider,
    default_daily_k_providers,
    fetch_global_daily_k_service,
    tencent_daily_k_provider,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
INDEX_ID = "cn.index.csi.000300"
START = "2026-09-01"
END = "2026-09-25"


def _ok_record(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID, "market": "cn", "symbol": "000300",
        "name": "沪深300", "date": "2026-09-01",
        "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
        "volume": None, "currency": "CNY", "timezone": "Asia/Shanghai",
        "source": source,
    }


def _ok_envelope(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    return fetcher_contract.make_ok(
        [_ok_record(source=source)],
        source=source, as_of="2026-09-01", scope=TENCENT_SCOPE,
        units={"price": "index_points", "volume": "unavailable"},
    )


def _empty_envelope(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    return fetcher_contract.make_empty(
        source=source, as_of=None, scope=TENCENT_SCOPE,
        reason="no daily-K rows in window",
    )


def _ok_empty_envelope(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    """Build an ok envelope with empty data list — must be reclassified as empty.

    The strict envelope validator requires ``as_of`` to be a valid
    ``YYYY-MM-DD`` string for ``status=ok`` envelopes.
    """

    return {
        "status": fetcher_contract.STATUS_OK,
        "data": [],
        "source": source,
        "as_of": "2026-09-25",
        "fetched_at": "2026-09-27T00:00:00+00:00",
        "scope": TENCENT_SCOPE,
        "units": {"price": "index_points", "volume": "unavailable"},
        "error": None,
    }


def _ok_bad_records_envelope(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    """Build an ok envelope whose records violate the V1 normalized schema."""

    return fetcher_contract.make_ok(
        [{"date": "2026-09-01"}],  # missing all required fields
        source=source, as_of="2026-09-01", scope=TENCENT_SCOPE,
        units={"price": "index_points", "volume": "unavailable"},
    )


def _error_envelope(code: str, message: str, source: str = TENCENT_SOURCE) -> dict[str, Any]:
    return fetcher_contract.make_error_result(
        code, message, source=source, retryable=True, scope=TENCENT_SCOPE
    )


def _unsupported_envelope(source: str = TENCENT_SOURCE) -> dict[str, Any]:
    return fetcher_contract.make_unsupported(
        source=source, scope=TENCENT_SCOPE, reason="index not supported by provider"
    )


def _stub_provider(name: str, source: str, envelope: Any) -> DailyKProvider:
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        return envelope
    return DailyKProvider(name=name, source=source, fetch=_fetch)


def _ok_provider(name: str = "alt", source: str = "alt.daily_k") -> DailyKProvider:
    return _stub_provider(name, source, _ok_envelope(source=source))


def _tencent_with_transport(transport: Any) -> DailyKProvider:
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        return fetch_global_daily_k(INDEX_ID, START, END, transport=transport, now=NOW)
    return DailyKProvider(name=TENCENT_PROVIDER_ID, source=TENCENT_SOURCE, fetch=_fetch)


def _transport_returning(payload: Any) -> Any:
    def _t(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        return payload
    return _t


# ---------------------------------------------------------------------------
# Default provider / descriptor surface
# ---------------------------------------------------------------------------

def test_default_providers_is_tencent_only() -> None:
    providers = default_daily_k_providers()
    assert len(providers) == 1
    assert providers[0].name == TENCENT_PROVIDER_ID
    assert providers[0].source == TENCENT_SOURCE
    assert providers[0].fetch is fetch_global_daily_k


def test_provider_descriptor_validation() -> None:
    with pytest.raises(ValueError):
        DailyKProvider(name="", source="x", fetch=fetch_global_daily_k)
    with pytest.raises(ValueError):
        DailyKProvider(name="x", source="", fetch=fetch_global_daily_k)
    with pytest.raises(ValueError):
        DailyKProvider(name="x", source="x", fetch=None)  # type: ignore[arg-type]


def test_string_providers_collection_rejected() -> None:
    with pytest.raises(ValueError):
        fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, providers="abc")


def test_bytes_providers_collection_rejected() -> None:
    with pytest.raises(ValueError):
        fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, providers=b"abc")


def test_non_daily_k_provider_member_rejected() -> None:
    with pytest.raises(ValueError):
        fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW,
            providers=(DailyKProvider(name="a", source="a", fetch=lambda *a, **kw: {}), object()),  # type: ignore[arg-type]
        )


def test_empty_providers_sequence_rejected() -> None:
    with pytest.raises(ValueError):
        fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, providers=())


# ---------------------------------------------------------------------------
# F1: default transport path
# ---------------------------------------------------------------------------

def test_default_invocation_with_no_transport_uses_v1_default(monkeypatch: Any) -> None:
    """When the caller supplies no transport, V1's ``requests_json_transport``
    must run (i.e. ``requests.get`` is invoked). The service must never
    raise ``VALIDATION`` for a missing transport."""

    calls: list[str] = []

    def _fake_get(url: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(url)
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.json.return_value = {"code": 0, "msg": "", "data": {"sh000300": {"day": [
            ["2026-09-01", 100.0, 105.0, 110.0, 95.0, 0]
        ]}}}
        return response

    monkeypatch.setattr(requests, "get", _fake_get)

    result = fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW)

    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is False
    assert result["provider_status"] == "ok"
    assert result["source_used"] == TENCENT_PROVIDER_ID
    assert calls == [TENCENT_DAILY_K_URL]


def test_explicit_non_callable_transport_returns_validation() -> None:
    """An explicit non-callable transport must become caller VALIDATION
    before any provider/fallback invocation."""

    calls: list[Any] = []
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        calls.append(1)
        return _ok_envelope()
    providers = (DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_fetch),)

    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, transport=object(), providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert "transport" in result["error"]["message"].lower()
    assert calls == []
    assert result["provider_attempts"] == ()


# ---------------------------------------------------------------------------
# F3: ok + empty data triggers fallback
# ---------------------------------------------------------------------------

def test_primary_ok_with_empty_data_triggers_fallback() -> None:
    primary = _stub_provider("tencent", TENCENT_SOURCE, _ok_empty_envelope())
    providers = (primary, _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_status"] == "degraded"
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_EMPTY
    assert result["provider_attempts"][1]["status"] == fetcher_contract.STATUS_OK


def test_all_providers_fail_with_last_ok_empty_returns_empty_envelope() -> None:
    """When the last provider returns ``status=ok, data=[]``, the synthesized
    final envelope must be a proper ``empty`` envelope (not ok with no data)."""

    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k", _ok_empty_envelope(source="alt.daily_k")),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_EMPTY
    assert result["provider_status"] == "failed"
    assert result["source_used"] is None
    assert result["source"] == "alt.daily_k"
    assert result["failure_reason"] == "VALIDATION: no daily-K rows in window"


def test_all_providers_fail_with_last_ok_bad_records_returns_parse() -> None:
    """When the last provider returns ``status=ok`` but records violate the
    V1 schema, the synthesized envelope must be ``PARSE`` (not ``ok``)."""

    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k", _ok_bad_records_envelope(source="alt.daily_k")),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["source"] == "alt.daily_k"
    assert result["provider_status"] == "failed"


# ---------------------------------------------------------------------------
# F2: all-fail malformed last envelope is always contract-shaped
# ---------------------------------------------------------------------------

def test_all_fail_malformed_last_envelope_returns_contract_shape() -> None:
    """A malformed last envelope (missing ``status``/``data``/``error``) must
    be synthesized into a proper ``PARSE`` envelope carrying the LAST
    attempted provider's source and ``source_used=None``."""

    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k", {"weird": True, "no": "shape"}),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert "status" in result
    assert "data" in result
    assert "error" in result
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    # provenance: the LAST attempted provider (alt) is the source
    assert result["source"] == "alt.daily_k"
    assert result["source_used"] is None
    assert result["provider_status"] == "failed"
    assert len(result["provider_attempts"]) == 2


def test_all_fail_non_mapping_last_envelope_returns_contract_shape() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k", None),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_UNKNOWN
    assert result["source"] == "alt.daily_k"
    assert result["source_used"] is None


# ---------------------------------------------------------------------------
# Provider-callable exception mapping
# ---------------------------------------------------------------------------

def test_provider_raises_timeout_continues_fallback() -> None:
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.Timeout()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_TIMEOUT
    assert result["provider_attempts"][1]["status"] == fetcher_contract.STATUS_OK


def test_provider_raises_connection_error_continues_fallback() -> None:
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.ConnectionError()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_CONN


def test_provider_raises_ssl_error_continues_fallback() -> None:
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.SSLError()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_SSL


def test_provider_raises_http_5xx_continues_fallback() -> None:
    response = mock.Mock()
    response.status_code = 503
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.HTTPError(response=response)
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_5XX


def test_provider_raises_http_429_continues_fallback() -> None:
    response = mock.Mock()
    response.status_code = 429
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.HTTPError(response=response)
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_RATELIMIT


def test_provider_raises_http_4xx_continues_fallback() -> None:
    response = mock.Mock()
    response.status_code = 404
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.HTTPError(response=response)
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_4XX


def test_provider_raises_runtime_error_continues_fallback() -> None:
    """Generic exceptions must map to ``ERR_UNKNOWN`` without leaking the
    underlying exception message to the caller."""

    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("internal-test-detail-19")
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_UNKNOWN
    # The original exception message must not appear in the envelope.
    assert "internal-test-detail-19" not in (result["provider_attempts"][0]["message"] or "")


def test_provider_runtime_error_all_fail_synthesizes_unknown() -> None:
    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("boom")
    def _alt(*_a: Any, **_kw: Any) -> Any:
        raise ValueError("also boom")
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        DailyKProvider(name="alt", source="alt.daily_k", fetch=_alt),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["source"] == "alt.daily_k"
    assert result["source_used"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_UNKNOWN
    assert "boom" not in (result["failure_reason"] or "")


# ---------------------------------------------------------------------------
# Primary success / V1 contract
# ---------------------------------------------------------------------------

def test_primary_success_is_not_degraded() -> None:
    providers = (_ok_provider(name="tencent", source=TENCENT_SOURCE),)
    transport = _transport_returning({"code": 0, "msg": "", "data": {"sh000300": {"day": [
        ["2026-09-01", 100.0, 105.0, 110.0, 95.0, 0]
    ]}}})
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, transport=transport, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is False
    assert result["provider_status"] == "ok"
    assert result["source_used"] == "tencent"
    assert result["primary_source"] == "tencent"
    assert result["fallback_sources"] == ()
    assert result["failure_reason"] is None
    assert result["source"] == TENCENT_SOURCE
    for record in result["data"]:
        assert record["source"] == TENCENT_SOURCE


def test_v1_regression_unchanged_with_default_providers() -> None:
    payload = {"code": 0, "msg": "", "data": {"sh000300": {"day": [
        ["2026-09-01", 100.0, 105.0, 110.0, 95.0, 0]
    ]}}}
    transport = _transport_returning(payload)
    result = fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, transport=transport)
    direct = fetch_global_daily_k(INDEX_ID, START, END, transport=transport, now=NOW)
    assert result["status"] == direct["status"]
    assert result["data"] == direct["data"]
    assert result["as_of"] == direct["as_of"]
    assert result["scope"] == direct["scope"]
    assert result["units"] == direct["units"]
    assert result["source"] == direct["source"]
    assert result["degraded"] is False
    assert result["provider_status"] == "ok"
    assert result["source_used"] == TENCENT_PROVIDER_ID


def test_url_used_for_primary_tencent_provider() -> None:
    seen: list[str] = []
    def _transport(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        seen.append(url)
        return {"code": 0, "msg": "", "data": {"sh000300": {"day": [
            ["2026-09-01", 100.0, 105.0, 110.0, 95.0, 0]
        ]}}}
    result = fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, transport=_transport)
    assert result["status"] == fetcher_contract.STATUS_OK
    assert seen == [TENCENT_DAILY_K_URL]


# ---------------------------------------------------------------------------
# Fallback success / provenance
# ---------------------------------------------------------------------------

def test_primary_timeout_triggers_fallback() -> None:
    def _transport(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        raise requests.exceptions.Timeout()
    providers = (_tencent_with_transport(_transport), _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["primary_source"] == "tencent"
    assert result["fallback_sources"] == ("alt",)
    assert result["provider_status"] == "degraded"
    assert result["source"] == "alt.daily_k"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_TIMEOUT
    assert result["provider_attempts"][1]["status"] == fetcher_contract.STATUS_OK


def test_primary_http_error_triggers_fallback() -> None:
    response = mock.Mock()
    response.status_code = 503
    http_error = requests.exceptions.HTTPError(response=response)

    def _transport(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        raise http_error
    providers = (_tencent_with_transport(_transport), _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_5XX


def test_primary_connection_error_triggers_fallback() -> None:
    def _transport(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        raise requests.exceptions.ConnectionError()
    providers = (_tencent_with_transport(_transport), _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_CONN


def test_primary_empty_triggers_fallback() -> None:
    primary = _stub_provider("tencent", TENCENT_SOURCE, _empty_envelope())
    providers = (primary, _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_status"] == "degraded"
    assert result["status"] == fetcher_contract.STATUS_OK


def test_primary_malformed_envelope_triggers_fallback() -> None:
    primary = _stub_provider("tencent", TENCENT_SOURCE, {"unexpected": "shape"})
    providers = (primary, _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_primary_parse_error_triggers_fallback() -> None:
    primary = _stub_provider(
        "tencent", TENCENT_SOURCE,
        _error_envelope(fetcher_contract.ERR_PARSE, "Tencent payload structure invalid"),
    )
    providers = (primary, _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_primary_unsupported_triggers_fallback() -> None:
    primary = _stub_provider("tencent", TENCENT_SOURCE, _unsupported_envelope())
    providers = (primary, _ok_provider())
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_UNSUPPORTED


def test_provider_envelope_data_records_rewritten_to_used_provider() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "x")),
        _ok_provider(name="alt", source="alt.daily_k"),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["source"] == "alt.daily_k"
    assert all(r["source"] == "alt.daily_k" for r in result["data"])


def test_fallback_attempt_marked_degraded_even_when_succeeding() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "x")),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["provider_attempts"][1]["degraded"] is True
    assert result["degraded"] is True
    assert result["provider_status"] == "degraded"


# ---------------------------------------------------------------------------
# Unknown / unsupported index paths
# ---------------------------------------------------------------------------

def test_unknown_index_never_calls_any_provider() -> None:
    calls: list[Any] = []
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        calls.append(1)
        return _ok_envelope()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_fetch),
        DailyKProvider(name="alt", source="alt.daily_k", fetch=_fetch),
    )
    result = fetch_global_daily_k_service(
        "unknown.index", START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_UNSUPPORTED
    assert result["source_used"] is None
    assert result["provider_status"] == "failed"
    assert result["provider_attempts"] == ()
    assert calls == []


def test_invalid_index_id_never_calls_any_provider() -> None:
    calls: list[Any] = []
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        calls.append(1)
        return _ok_envelope()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_fetch),
    )
    result = fetch_global_daily_k_service(
        "CN.INDEX.CSI.000300", START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert calls == []


# ---------------------------------------------------------------------------
# All-providers-fail / stable failure reason / partial chain
# ---------------------------------------------------------------------------

def test_all_providers_fail_preserves_last_status_and_attempts() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k",
                       _error_envelope(fetcher_contract.ERR_NET_5XX, "alt 503")),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_NET_5XX
    assert result["provider_status"] == "failed"
    assert result["source_used"] is None
    assert result["degraded"] is False
    assert result["failure_reason"] == "NET_5XX: alt 503"
    assert result["source"] == "alt.daily_k"
    assert len(result["provider_attempts"]) == 2
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_TIMEOUT
    assert result["provider_attempts"][1]["code"] == fetcher_contract.ERR_NET_5XX


def test_all_providers_fail_with_last_empty_preserves_empty() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k", _empty_envelope(source="alt.daily_k")),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_EMPTY
    assert result["provider_status"] == "failed"
    assert result["source_used"] is None
    assert result["source"] == "alt.daily_k"
    assert result["failure_reason"] == "VALIDATION: no daily-K rows in window"


def test_stable_failure_reason_is_deterministic() -> None:
    providers = (_stub_provider(
        "tencent", TENCENT_SOURCE,
        _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout"),
    ),)
    r1 = fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, providers=providers)
    r2 = fetch_global_daily_k_service(INDEX_ID, START, END, now=NOW, providers=providers)
    assert r1["failure_reason"] == r2["failure_reason"]


def test_partial_market_failure_via_attempts() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_CONN, "tencent conn refused")),
        _stub_provider("alt", "alt.daily_k",
                       _error_envelope(fetcher_contract.ERR_PARSE, "alt parse")),
        _ok_provider(name="yahoo", source="yahoo.daily_k"),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "yahoo"
    assert result["primary_source"] == "tencent"
    assert result["fallback_sources"] == ("alt", "yahoo")
    assert [a["provider"] for a in result["provider_attempts"]] == ["tencent", "alt", "yahoo"]
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_CONN
    assert result["provider_attempts"][1]["code"] == fetcher_contract.ERR_PARSE
    assert result["provider_attempts"][2]["status"] == fetcher_contract.STATUS_OK
    assert result["provider_attempts"][2]["degraded"] is True


# ---------------------------------------------------------------------------
# Input validation precedence (matches V1)
# ---------------------------------------------------------------------------

def test_invalid_input_does_not_fallback() -> None:
    fallback_calls: list[Any] = []
    def _fallback_fetch(*_a: Any, **_kw: Any) -> Any:
        fallback_calls.append(1)
        return _ok_envelope()
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE,
                       fetch=tencent_daily_k_provider().fetch),
        DailyKProvider(name="alt", source="alt.daily_k", fetch=_fallback_fetch),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, "bad-date", END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert fallback_calls == []


def test_invalid_dates_precede_registry_lookup() -> None:
    """Bad dates with an unknown index must surface as VALIDATION (date
    shape), not UNSUPPORTED (registry lookup). Matches V1 precedence."""

    result = fetch_global_daily_k_service(
        "unknown.index", "bad-date", END, now=NOW
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION


def test_naive_now_returns_validation_before_provider() -> None:
    calls: list[Any] = []
    def _fetch(*_a: Any, **_kw: Any) -> Any:
        calls.append(1)
        return _ok_envelope()
    providers = (DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_fetch),)
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=datetime(2026, 9, 27, 12, 0), providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert calls == []


# ---------------------------------------------------------------------------
# Sanity: orchestration module imports & helpers
# ---------------------------------------------------------------------------

def test_synthesize_final_envelope_uses_last_provider_source() -> None:
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE,
                       _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout")),
        _stub_provider("alt", "alt.daily_k",
                       _error_envelope(fetcher_contract.ERR_PARSE, "alt parse")),
        _stub_provider("yahoo", "yahoo.daily_k", {"unexpected": "shape"}),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    # Source provenance is the LAST attempted provider (yahoo).
    assert result["source"] == "yahoo.daily_k"
    assert result["source_used"] is None


# ---------------------------------------------------------------------------
# Contract defect fixes — fallback-success failure_reason + malformed envelopes
# ---------------------------------------------------------------------------

def test_fallback_success_retains_primary_timeout_failure_reason() -> None:
    """Primary timeout → fallback success must surface the primary failure
    reason in ``failure_reason`` (e.g. ``NET_TIMEOUT: ...``) while the final
    envelope remains ``status=ok`` and ``degraded=True``.
    """

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout"),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["provider_status"] == "degraded"
    assert result["source_used"] == "alt"
    assert result["failure_reason"] == (
        f"{fetcher_contract.ERR_NET_TIMEOUT}: tencent timeout"
    )
    # All attempt detail must remain in order.
    assert [a["provider"] for a in result["provider_attempts"]] == ["tencent", "alt"]
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_ERROR
    assert result["provider_attempts"][1]["status"] == fetcher_contract.STATUS_OK


def test_fallback_success_retains_primary_http_5xx_failure_reason() -> None:
    """Primary 5xx → fallback success: failure_reason must identify the
    primary code/message deterministically.
    """

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _error_envelope(fetcher_contract.ERR_NET_5XX, "tencent 503"),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["failure_reason"] == (
        f"{fetcher_contract.ERR_NET_5XX}: tencent 503"
    )


def test_fallback_success_retains_primary_failure_reason_via_exception() -> None:
    """Primary raises Timeout → V2 maps to NET_TIMEOUT envelope → fallback
    succeeds → failure_reason must be ``NET_TIMEOUT: ...``."""

    def _primary(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.Timeout("connection took too long — internal-test-detail-73")
    providers = (
        DailyKProvider(name="tencent", source=TENCENT_SOURCE, fetch=_primary),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["failure_reason"] is not None
    assert result["failure_reason"].startswith(fetcher_contract.ERR_NET_TIMEOUT + ":")
    # Original exception message must NOT leak through failure_reason.
    assert "internal-test-detail-73" not in (result["failure_reason"] or "")
    assert "connection took too long" not in (result["failure_reason"] or "")


def test_primary_malformed_error_envelope_triggers_fallback() -> None:
    """``{"status":"error","data":None,"error":None}`` is malformed (no proper
    error mapping) → must trigger fallback when a later provider exists and
    surface ``code=PARSE`` in the attempt."""

    malformed: dict[str, Any] = {
        "status": fetcher_contract.STATUS_ERROR,
        "data": None,
        "error": None,
        "source": TENCENT_SOURCE,
        "scope": TENCENT_SCOPE,
    }
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE, malformed),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_ERROR
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE
    # The malformed provider's source must NOT leak through to the fallback's
    # envelope or any record.
    assert result["source"] == "alt.daily_k"
    assert all(r["source"] == "alt.daily_k" for r in result["data"])
    # The failed reason must still be derived from the primary (synthesized as PARSE).
    assert result["failure_reason"] is not None
    assert result["failure_reason"].startswith(fetcher_contract.ERR_PARSE + ":")


def test_primary_malformed_empty_envelope_triggers_fallback() -> None:
    """``{"status":"empty","data":[],``error" missing}`` is malformed
    (data is [], no error mapping) → must trigger fallback."""

    malformed: dict[str, Any] = {
        "status": fetcher_contract.STATUS_EMPTY,
        "data": [],
        "error": None,
        "source": TENCENT_SOURCE,
        "scope": TENCENT_SCOPE,
    }
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE, malformed),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_ERROR
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_primary_malformed_unsupported_envelope_triggers_fallback() -> None:
    """``{"status":"unsupported","data":[...],``error" missing}`` is malformed
    → must trigger fallback when a later provider exists."""

    malformed: dict[str, Any] = {
        "status": fetcher_contract.STATUS_UNSUPPORTED,
        "data": [{"bogus": "row"}],
        "error": None,
        "source": TENCENT_SOURCE,
        "scope": TENCENT_SCOPE,
    }
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE, malformed),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_ERROR
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_all_providers_fail_with_last_malformed_error_returns_parse() -> None:
    """When all providers fail and the last envelope is
    ``{"status":"error","data":None,"error":None}``, the synthesized envelope
    must carry ``status``/``data``/``error`` keys with ``code=PARSE``.
    Provider internals must not leak."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout"),
        ),
        _stub_provider(
            "alt", "alt.daily_k",
            {
                "status": fetcher_contract.STATUS_ERROR,
                "data": None,
                "error": None,
                "source": "alt.daily_k",
                "scope": TENCENT_SCOPE,
            },
        ),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    # Contract shape: status/data/error must all be present.
    assert "status" in result
    assert "data" in result
    assert "error" in result
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["data"] is None
    assert result["error"] is not None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    # Source provenance is the LAST attempted provider (alt).
    assert result["source"] == "alt.daily_k"
    assert result["source_used"] is None
    assert result["provider_status"] == "failed"
    assert result["degraded"] is False
    # failure_reason must NOT echo the original malformed envelope's "error".
    assert "None" not in (result["failure_reason"] or "")
    assert result["failure_reason"].startswith(fetcher_contract.ERR_PARSE + ":")
    # Provider internals must not leak through failure_reason.
    assert "alt.daily_k" not in (result["failure_reason"] or "")
    # All attempt detail must remain in order.
    assert [a["provider"] for a in result["provider_attempts"]] == ["tencent", "alt"]
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_NET_TIMEOUT
    assert result["provider_attempts"][1]["code"] == fetcher_contract.ERR_PARSE


def test_all_providers_fail_with_last_malformed_empty_returns_parse() -> None:
    """When all providers fail and the last envelope is
    ``{"status":"empty","data":[]}`` (no error field), the synthesized envelope
    must carry ``status``/``data``/``error`` keys with ``code=PARSE``."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout"),
        ),
        _stub_provider(
            "alt", "alt.daily_k",
            {
                "status": fetcher_contract.STATUS_EMPTY,
                "data": [],
                "error": None,
                "source": "alt.daily_k",
                "scope": TENCENT_SCOPE,
            },
        ),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert "status" in result
    assert "data" in result
    assert "error" in result
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["data"] is None
    assert result["error"] is not None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["source"] == "alt.daily_k"
    assert result["source_used"] is None
    assert result["failure_reason"].startswith(fetcher_contract.ERR_PARSE + ":")


def test_malformed_error_envelope_does_not_leak_error_none() -> None:
    """Sanity: a single malformed ``{"status":"error","error":None}`` envelope
    returned by the only configured provider must never reach the caller with
    ``error=None``."""

    malformed: dict[str, Any] = {
        "status": fetcher_contract.STATUS_ERROR,
        "data": None,
        "error": None,
        "source": TENCENT_SOURCE,
        "scope": TENCENT_SCOPE,
    }
    providers = (_stub_provider("tencent", TENCENT_SOURCE, malformed),)
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"] is not None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["data"] is None
    assert "status" in result
    assert "data" in result
    assert "error" in result


def test_malformed_empty_envelope_with_array_data_synthesizes_parse() -> None:
    """``{"status":"empty","data":[]}`` (data must be None per the empty
    contract) — single-provider case must produce PARSE."""

    malformed: dict[str, Any] = {
        "status": fetcher_contract.STATUS_EMPTY,
        "data": [],
        "error": None,
        "source": TENCENT_SOURCE,
        "scope": TENCENT_SCOPE,
    }
    providers = (_stub_provider("tencent", TENCENT_SOURCE, malformed),)
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_valid_v1_empty_envelope_preserved_as_empty() -> None:
    """A properly-shaped V1 empty envelope (data=None, proper error mapping)
    must still pass through as ``status=empty`` and trigger fallback per the
    contract."""

    providers = (
        _stub_provider("tencent", TENCENT_SOURCE, _empty_envelope()),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["status"] == fetcher_contract.STATUS_EMPTY
    # failure_reason comes from the synthesized primary empty envelope.
    assert result["failure_reason"] == "VALIDATION: no daily-K rows in window"


def test_fallback_success_failure_reason_uses_earliest_failed_attempt() -> None:
    """With three providers where the primary fails, the second fails, and
    the third succeeds, the failure_reason must derive from the EARLIEST
    failed attempt (the primary), not the last failure."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _error_envelope(fetcher_contract.ERR_NET_TIMEOUT, "tencent timeout"),
        ),
        _stub_provider(
            "alt", "alt.daily_k",
            _error_envelope(fetcher_contract.ERR_NET_5XX, "alt 503"),
        ),
        _ok_provider(name="yahoo", source="yahoo.daily_k"),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "yahoo"
    assert result["failure_reason"] == (
        f"{fetcher_contract.ERR_NET_TIMEOUT}: tencent timeout"
    )
    # Attempts remain in order.
    assert [a["provider"] for a in result["provider_attempts"]] == ["tencent", "alt", "yahoo"]


# ---------------------------------------------------------------------------
# Rework: full envelope + normalized-row validation
# ---------------------------------------------------------------------------

import math  # noqa: E402  (kept with the new tests for clarity)


def _ok_envelope_with_overrides(**overrides: Any) -> dict[str, Any]:
    """Build a copy of a valid ok envelope with selected fields overridden.

    The validator must reject the resulting envelope whenever an override
    violates the V1 contract.
    """

    envelope = _ok_envelope()
    envelope.update(overrides)
    return envelope


def test_envelope_missing_source_field_triggers_fallback() -> None:
    """``status=ok`` with an empty/missing ``source`` field is malformed and
    must trigger fallback to the next provider."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(source=""),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_missing_scope_field_triggers_fallback() -> None:
    """``status=ok`` with an empty/missing ``scope`` field is malformed."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(scope=""),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_missing_units_field_triggers_fallback() -> None:
    """``status=ok`` with a non-mapping ``units`` field is malformed."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(units=None),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_error_not_none_triggers_fallback() -> None:
    """``status=ok`` with ``error != None`` violates the contract."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(error={"code": "X", "message": "y", "retryable": False}),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_naive_fetched_at_triggers_fallback() -> None:
    """``fetched_at`` must be aware ISO-8601; naive datetimes must reject."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(fetched_at="2026-09-27T12:00:00"),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_invalid_fetched_at_triggers_fallback() -> None:
    """``fetched_at`` must parse via ``datetime.fromisoformat``; garbage rejects."""

    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            _ok_envelope_with_overrides(fetched_at="not-iso-at-all"),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_envelope_invalid_as_of_triggers_fallback() -> None:
    """``as_of`` must be strict ``YYYY-MM-DD``; any other form rejects."""

    for bad in ("20260901", "2026-09-1", "2026/09/01", "", "2026-W39-6"):
        providers = (
            _stub_provider(
                "tencent", TENCENT_SOURCE,
                _ok_envelope_with_overrides(as_of=bad),
            ),
            _ok_provider(),
        )
        result = fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW, providers=providers
        )
        assert result["degraded"] is True
        assert result["source_used"] == "alt"
        assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_wrong_index_id_triggers_fallback() -> None:
    """Rows whose ``index_id`` does not match the requested canonical id
    must trigger fallback (and never be returned as healthy success)."""

    bad_record = _ok_record()
    bad_record["index_id"] = "us.index.sp_dji.sp500"  # wrong index
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_wrong_market_symbol_name_currency_timezone_triggers_fallback() -> None:
    """Any canonical identity field that drifts from the V1 registry
    rejects the row."""

    for field, wrong in (
        ("market", "us"),
        ("symbol", "wrong"),
        ("name", "WrongName"),
        ("currency", "USD"),
        ("timezone", "America/New_York"),
    ):
        bad_record = _ok_record()
        bad_record[field] = wrong
        providers = (
            _stub_provider(
                "tencent", TENCENT_SOURCE,
                fetcher_contract.make_ok(
                    [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                    scope=TENCENT_SCOPE,
                    units={"price": "index_points", "volume": "unavailable"},
                ),
            ),
            _ok_provider(),
        )
        result = fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW, providers=providers
        )
        assert result["degraded"] is True
        assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE, field


def test_row_malformed_date_triggers_fallback() -> None:
    """Row ``date`` must be strict ``YYYY-MM-DD``; compact/week/garbage reject."""

    for bad_date in ("20260901", "2026-09-1", "2026/09/01", "2026-W39-6", ""):
        bad_record = _ok_record()
        bad_record["date"] = bad_date
        providers = (
            _stub_provider(
                "tencent", TENCENT_SOURCE,
                fetcher_contract.make_ok(
                    [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                    scope=TENCENT_SCOPE,
                    units={"price": "index_points", "volume": "unavailable"},
                ),
            ),
            _ok_provider(),
        )
        result = fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW, providers=providers
        )
        assert result["degraded"] is True
        assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE, bad_date


def test_row_nan_price_triggers_fallback() -> None:
    """NaN prices must be rejected."""

    bad_record = _ok_record()
    bad_record["open"] = float("nan")
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE
    # NaN must not leak through failure_reason.
    assert "nan" not in (result["failure_reason"] or "").lower()


def test_row_infinity_price_triggers_fallback() -> None:
    """Positive/negative infinity must be rejected."""

    for value in (float("inf"), -float("inf")):
        bad_record = _ok_record()
        bad_record["close"] = value
        providers = (
            _stub_provider(
                "tencent", TENCENT_SOURCE,
                fetcher_contract.make_ok(
                    [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                    scope=TENCENT_SCOPE,
                    units={"price": "index_points", "volume": "unavailable"},
                ),
            ),
            _ok_provider(),
        )
        result = fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW, providers=providers
        )
        assert result["degraded"] is True
        assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_string_price_triggers_fallback() -> None:
    """String prices that do not coerce to a positive finite number reject."""

    bad_record = _ok_record()
    bad_record["high"] = "not-a-number"
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_bool_price_triggers_fallback() -> None:
    """``True``/``False`` must be rejected (Python bool is an int subclass)."""

    for value in (True, False):
        bad_record = _ok_record()
        bad_record["low"] = value
        providers = (
            _stub_provider(
                "tencent", TENCENT_SOURCE,
                fetcher_contract.make_ok(
                    [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                    scope=TENCENT_SCOPE,
                    units={"price": "index_points", "volume": "unavailable"},
                ),
            ),
            _ok_provider(),
        )
        result = fetch_global_daily_k_service(
            INDEX_ID, START, END, now=NOW, providers=providers
        )
        assert result["degraded"] is True
        assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_inconsistent_high_low_triggers_fallback() -> None:
    """``low > high`` violates the OHLC invariant."""

    bad_record = _ok_record()
    bad_record["low"] = 120.0
    bad_record["high"] = 90.0
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [bad_record], source=TENCENT_SOURCE, as_of="2026-09-01",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_duplicate_dates_triggers_fallback() -> None:
    """Two rows with the same session date must trigger fallback."""

    record_a = _ok_record()
    record_b = _ok_record()
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [record_a, record_b], source=TENCENT_SOURCE, as_of="2026-09-01",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_row_out_of_order_dates_triggers_fallback() -> None:
    """Rows whose dates are not strictly ascending trigger fallback."""

    record_late = dict(_ok_record())
    record_late["date"] = "2026-09-15"
    record_early = dict(_ok_record())
    record_early["date"] = "2026-09-01"
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [record_late, record_early], source=TENCENT_SOURCE, as_of="2026-09-15",
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_as_of_mismatch_with_last_date_triggers_fallback() -> None:
    """``as_of`` must equal the last ordered session date; mismatch rejects."""

    record = _ok_record()  # date == 2026-09-01
    providers = (
        _stub_provider(
            "tencent", TENCENT_SOURCE,
            fetcher_contract.make_ok(
                [record], source=TENCENT_SOURCE, as_of="2026-09-25",  # lies
                scope=TENCENT_SCOPE,
                units={"price": "index_points", "volume": "unavailable"},
            ),
        ),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["degraded"] is True
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE


def test_fallback_success_from_malformed_primary() -> None:
    """End-to-end: malformed primary envelope → fallback succeeds.

    The final envelope must be ``status=ok`` (healthy success from alt),
    ``degraded=True``, ``source_used='alt'``, and ``failure_reason``
    identifies the synthesized primary PARSE failure. The malformed
    primary must never be returned as healthy success.
    """

    malformed: dict[str, Any] = _ok_envelope_with_overrides(scope="")
    providers = (
        _stub_provider("tencent", TENCENT_SOURCE, malformed),
        _ok_provider(),
    )
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is True
    assert result["provider_status"] == "degraded"
    assert result["source_used"] == "alt"
    assert result["source"] == "alt.daily_k"
    assert all(r["source"] == "alt.daily_k" for r in result["data"])
    assert result["provider_attempts"][0]["code"] == fetcher_contract.ERR_PARSE
    assert result["failure_reason"].startswith(fetcher_contract.ERR_PARSE + ":")


def test_valid_v1_envelope_is_not_reclassified_as_parse() -> None:
    """A V1-conformant envelope returned by the alt provider must still
    be classified as ok (not PARSE) even though the source label is
    different from the canonical tencent source."""

    providers = (_ok_provider(),)
    result = fetch_global_daily_k_service(
        INDEX_ID, START, END, now=NOW, providers=providers
    )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["degraded"] is False
    assert result["source_used"] == "alt"
    assert result["provider_attempts"][0]["code"] is None
