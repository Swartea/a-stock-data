"""Offline smoke tests for the V1 global-index daily-K fetcher.

This suite is intentionally narrow. It only verifies the public entrypoint
end-to-end with an injected transport, covering the supported universe,
basic validation, payload-shape failures, and the volume-unavailable rule.

Adversarial / property-based coverage is added by Kimi after this file is
accepted. Do not extend the smoke suite with deep corner cases here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
import requests

from analysis import fetcher_contract
from analysis.research import global_daily_k
from analysis.research.global_daily_k import (
    TENCENT_DAILY_K_TIMEOUT,
    TENCENT_DAILY_K_URL,
    TENCENT_SCOPE,
    TENCENT_SOURCE,
    fetch_global_daily_k,
)
from analysis.research.global_indices import (
    GLOBAL_INDEX_PROVIDER_SYMBOLS,
    list_global_indices,
)

_NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _fixture(
    *,
    provider_symbol: str,
    rows: list[list[Any]],
    code: int = 0,
) -> dict[str, Any]:
    """Build a minimal Tencent-shaped payload for one index."""

    return {
        "code": code,
        "msg": "",
        "data": {provider_symbol: {"day": rows}},
    }


def _capturing_transport(
    rows: list[list[Any]],
    *,
    code: int = 0,
    provider_symbol: str | None = None,
    follow_request_symbol: bool = True,
) -> tuple[Any, list[dict[str, Any]]]:
    """Return ``(transport, calls)`` so tests can introspect the request.

    When ``follow_request_symbol`` is true (the default), the transport
    builds its payload using the provider symbol from the outgoing request
    params. Set it to false to use the static ``provider_symbol`` argument,
    which lets tests construct payloads that miss the requested symbol.
    """

    calls: list[dict[str, Any]] = []
    static_payload_provider_symbol = provider_symbol
    if static_payload_provider_symbol is None:
        static_payload_provider_symbol = GLOBAL_INDEX_PROVIDER_SYMBOLS[
            "cn.index.csi.000300"
        ]
    static_payload = _fixture(
        provider_symbol=static_payload_provider_symbol, rows=rows, code=code
    )

    def _transport(
        url: str,
        *,
        params: dict[str, str],
        timeout: tuple[int, int] = TENCENT_DAILY_K_TIMEOUT,
    ) -> Any:
        calls.append({"url": url, "params": dict(params), "timeout": timeout})
        if follow_request_symbol:
            requested = params.get("param", "")
            symbol = requested.split(",", 1)[0]
            return _fixture(provider_symbol=symbol, rows=rows, code=code)
        return static_payload

    return _transport, calls


def _make_row(date: str, o: float, c: float, h: float, lo: float) -> list[Any]:
    return [date, o, c, h, lo, 0]


def test_supported_universe_is_fixed_at_nine_indices() -> None:
    spec_ids = tuple(spec.identity.index_id for spec in list_global_indices())
    assert spec_ids == (
        "cn.index.sse.000001",
        "cn.index.szse.399001",
        "cn.index.szse.399006",
        "cn.index.csi.000300",
        "hk.index.hang_seng.hsi",
        "hk.index.hang_seng.hstech",
        "us.index.sp_dji.sp500",
        "us.index.nasdaq.composite",
        "us.index.sp_dji.djia",
    )


def test_supported_index_returns_ok_records() -> None:
    rows = [
        _make_row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
        _make_row("2026-09-02", 4275.5, 4290.1, 4300.0, 4270.0),
        _make_row("2026-09-03", 4290.1, 4288.0, 4310.0, 4280.0),
    ]
    transport, calls = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_ok(result)
    assert result["source"] == TENCENT_SOURCE
    assert result["scope"] == TENCENT_SCOPE
    assert result["as_of"] == "2026-09-03"
    assert result["units"] == {"price": "index_points", "volume": "unavailable"}
    assert len(calls) == 1
    assert calls[0]["url"] == TENCENT_DAILY_K_URL
    assert calls[0]["params"]["param"] == "sh000300,day,2026-09-01,2026-09-25,640,"

    assert len(result["data"]) == 3
    first = result["data"][0]
    assert first["index_id"] == "cn.index.csi.000300"
    assert first["market"] == "cn"
    assert first["symbol"] == "000300"
    assert first["currency"] == "CNY"
    assert first["timezone"] == "Asia/Shanghai"
    assert first["source"] == TENCENT_SOURCE
    assert first["volume"] is None
    assert first["date"] == "2026-09-01"
    assert first["open"] == pytest.approx(4250.0)


def test_volume_is_null_for_every_v1_record() -> None:
    rows = [_make_row("2026-09-01", 100.0, 110.0, 115.0, 95.0)]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "us.index.sp_dji.sp500",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_ok(result)
    assert all(record["volume"] is None for record in result["data"])


def test_request_filters_to_inclusive_window_and_drops_same_local_day() -> None:
    rows = [
        _make_row("2026-08-31", 1.0, 1.0, 1.0, 1.0),
        _make_row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
        _make_row("2026-09-25", 4300.0, 4310.0, 4320.0, 4295.0),
        _make_row("2026-09-26", 4400.0, 4410.0, 4420.0, 4395.0),
        _make_row("2026-09-27", 4500.0, 4510.0, 4520.0, 4495.0),
    ]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_ok(result)
    dates = [record["date"] for record in result["data"]]
    assert dates == ["2026-09-01", "2026-09-25"]


def test_empty_filtered_window_returns_empty_status() -> None:
    transport, calls = _capturing_transport([])

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_empty(result)
    assert result["data"] is None
    assert result["as_of"] is None
    assert len(calls) == 1


def test_unknown_index_id_returns_unsupported_without_transport_call() -> None:
    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("transport must not be called for unknown index_id")

    result = fetch_global_daily_k(
        "cn.index.csi.999999",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_unsupported(result)
    assert result["data"] is None
    assert called == []


def test_bare_provider_symbol_is_not_accepted_as_index_id() -> None:
    transport, _ = _capturing_transport([])

    result = fetch_global_daily_k(
        "sh000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_unsupported(result)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("not-a-date", "2026-09-25"),
        ("2026-09-01", "2026-13-01"),
        ("2026-10-01", "2026-09-01"),
        ("2025-01-01", "2026-09-01"),
    ],
)
def test_invalid_date_window_returns_validation_error(start: str, end: str) -> None:
    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("transport must not be called for invalid input")

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        start,
        end,
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert result["error"]["retryable"] is False
    assert called == []


def test_naive_now_returns_validation_error_without_transport_call() -> None:
    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("transport must not be called for naive now")

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=datetime(2026, 9, 27, 12, 0),
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert result["error"]["retryable"] is False
    assert called == []


def test_non_callable_transport_returns_validation_error() -> None:
    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport="not-callable",  # type: ignore[arg-type]
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert result["error"]["retryable"] is False


def test_provider_nonzero_code_returns_error_not_empty() -> None:
    rows = [_make_row("2026-09-01", 1.0, 1.0, 1.0, 1.0)]
    transport, _ = _capturing_transport(rows, code=1)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["data"] is None


def test_provider_boolean_code_returns_error() -> None:
    """Python treats ``bool`` as ``int``; the fetcher must still reject ``False``."""

    payload = {
        "code": False,
        "msg": "",
        "data": {
            GLOBAL_INDEX_PROVIDER_SYMBOLS["cn.index.csi.000300"]: {
                "day": [_make_row("2026-09-01", 1.0, 1.0, 1.0, 1.0)],
            }
        },
    }

    def _transport(*args: Any, **kwargs: Any) -> Any:
        return payload

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_missing_symbol_section_returns_error() -> None:
    payload = {
        "code": 0,
        "msg": "",
        "data": {"some-other-symbol": {"day": []}},
    }

    def _transport(*args: Any, **kwargs: Any) -> Any:
        return payload

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_duplicate_session_with_identical_ohlc_coalesces() -> None:
    rows = [
        _make_row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
        _make_row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
    ]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_ok(result)
    assert len(result["data"]) == 1


def test_duplicate_session_with_conflicting_ohlc_is_error() -> None:
    rows = [
        _make_row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
        _make_row("2026-09-01", 4251.0, 4276.5, 4280.0, 4245.0),
    ]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_malformed_ohlc_returns_parse_error() -> None:
    rows = [["2026-09-01", "not-a-number", 1.0, 1.0, 1.0, 0]]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_high_low_inversion_returns_parse_error() -> None:
    rows = [_make_row("2026-09-01", 100.0, 110.0, 90.0, 120.0)]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_default_transport_is_tencent_url() -> None:
    """Sanity check that the default transport points at Tencent."""

    import inspect

    sig = inspect.signature(fetch_global_daily_k)
    transport_param = sig.parameters["transport"]
    assert (
        transport_param.default is global_daily_k.requests_json_transport
    )
    assert TENCENT_DAILY_K_URL.startswith("https://web.ifzq.gtimg.cn/")


def test_default_transport_actually_runs_without_crashing() -> None:
    """F1 regression: the default transport body must not raise on its own.

    The legacy guard inverted ``callable(timeout)`` against a tuple and always
    crashed before ``requests.get``. The default value of the entrypoint's
    transport parameter therefore has to be callable as-is. We block the real
    network by patching ``requests.get``.
    """

    import unittest.mock as mock

    captured: dict[str, Any] = {}

    def _fake_get(url: str, *, params: Any, timeout: Any) -> Any:
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": 0,
            "msg": "",
            "data": {
                GLOBAL_INDEX_PROVIDER_SYMBOLS["cn.index.csi.000300"]: {
                    "day": [],
                }
            },
        }
        return response

    with mock.patch.object(global_daily_k.requests, "get", side_effect=_fake_get):
        result = fetch_global_daily_k(
            "cn.index.csi.000300",
            "2026-09-01",
            "2026-09-25",
            now=_NOW,
        )

    assert fetcher_contract.is_empty(result)
    assert captured["url"] == TENCENT_DAILY_K_URL
    assert captured["timeout"] == TENCENT_DAILY_K_TIMEOUT


def test_uppercase_index_id_returns_validation_not_crash() -> None:
    """F2 regression: non-canonical ``index_id`` must return VALIDATION."""

    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("transport must not be called for invalid index_id")

    result = fetch_global_daily_k(
        "CN.INDEX.CSI.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert result["error"]["retryable"] is False
    assert called == []


@pytest.mark.parametrize(
    "raw_symbol",
    [
        "hkHSI",   # HK provider symbol with mixed casing
        "us.INX",  # US provider symbol with mixed casing
        "IXIC",    # bare publisher local_code, all uppercase
        "HSI",     # bare publisher local_code, all uppercase
        "^GSPC",   # Yahoo-style decorated short name
        "^IXIC",   # Yahoo-style decorated short name
        "N225",    # Nikkei short name with uppercase letter
    ],
)
def test_unqualified_raw_symbol_returns_unsupported(raw_symbol: str) -> None:
    """Mapping rework: unqualified raw symbols must return UNSUPPORTED.

    These seven inputs are *not* qualified canonical ``index_id`` shapes:
    they are mixed-case provider symbols, all-caps publisher local codes,
    and Yahoo-style decorated short names. Lowercasing them never lands
    on any of the nine canonical V1 ids, so the lookup must surface as
    ``UNSUPPORTED / retryable=False`` and must not touch the transport.

    Note the asymmetry with
    :func:`test_uppercase_index_id_returns_validation_not_crash`: an
    uppercase *qualified* id (e.g. ``CN.INDEX.CSI.000300``) still maps
    to ``VALIDATION`` because the caller was clearly addressing a known
    index but with the wrong casing. These seven, by contrast, are not
    in the V1 set at all.
    """

    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError(
            "transport must not be called for unqualified raw symbol"
        )

    result = fetch_global_daily_k(
        raw_symbol,
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_unsupported(result)
    assert result["data"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_UNSUPPORTED
    assert result["error"]["retryable"] is False
    assert called == []


@pytest.mark.parametrize(
    "compact",
    ["20260901", "2026-09-1", "2026/09/01", "2026-W39-6", ""],
)
def test_non_strict_input_date_returns_validation(compact: str) -> None:
    """F3 regression: input date must be strict YYYY-MM-DD."""

    called: list[Any] = []

    def _transport(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("transport must not be called for bad date")

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        compact,
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    assert result["error"]["retryable"] is False
    assert called == []


def test_non_strict_row_date_returns_parse_error() -> None:
    """F3 regression: provider row date must also be strict YYYY-MM-DD."""

    rows = [["20260901", 100.0, 110.0, 115.0, 95.0, 0]]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_requests_json_decode_error_is_parse_not_unknown() -> None:
    """Rework 1: a real ``requests.exceptions.JSONDecodeError`` (which inherits
    from both ``ValueError`` and ``RequestException``) must surface as
    ``PARSE / retryable=False`` rather than the catch-all ``UNKNOWN /
    retryable=True`` that the RequestException handler would otherwise produce.
    """

    def _transport(*args: Any, **kwargs: Any) -> Any:
        raise requests.exceptions.JSONDecodeError("bad response", "x", 0)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["data"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["error"]["retryable"] is False


def test_generic_transport_exception_returns_safe_unknown() -> None:
    """Rework 2: an injected transport that raises an ordinary ``Exception``
    (``RuntimeError`` here) must be caught at the boundary and converted to
    ``UNKNOWN`` with a safe, generic message — never letting the exception
    escape to the caller. ``KeyboardInterrupt``/``SystemExit`` must still pass
    through, which is verified implicitly because they derive from
    ``BaseException``, not ``Exception``.
    """

    def _transport(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider failure")

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=_transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["data"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_UNKNOWN
    assert result["error"]["retryable"] is True
    # Generic message must not echo the underlying exception text, which
    # keeps provider internals and credentials out of the envelope.
    assert "provider failure" not in result["error"]["message"]


def test_huge_number_in_ohlc_returns_parse_error() -> None:
    """Rework 3: a row whose open price overflows ``float`` (``10**1000``)
    must produce ``PARSE / data=None`` instead of letting ``OverflowError``
    crash the boundary.
    """

    rows = [["2026-09-01", 10**1000, 110.0, 115.0, 95.0, 0]]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["data"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["error"]["retryable"] is False


def test_huge_number_as_string_in_ohlc_returns_parse_error() -> None:
    """Rework 3 (string form): an unparseable / overflow-producing string
    must also map to ``PARSE / data=None`` rather than crashing.
    """

    rows = [["2026-09-01", "1e1000", 110.0, 115.0, 95.0, 0]]
    transport, _ = _capturing_transport(rows)

    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        "2026-09-01",
        "2026-09-25",
        transport=transport,
        now=_NOW,
    )

    assert fetcher_contract.is_error(result)
    assert result["data"] is None
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
