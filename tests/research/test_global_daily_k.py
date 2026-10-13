"""Adversarial contract tests for the V1 global-index daily-K fetcher.

This suite complements ``tests/research/test_global_daily_k_smoke.py`` (the
accepted MiniMax smoke suite) with independent, behavior-based coverage of the
controller-decided V1 contract:

* the fixed nine-index universe and every index/provider-symbol mapping,
* registry immutability and the absence of bare-code inference,
* the exact provider request shape (unadjusted ``day`` series, bounded
  timeout, exactly one request per fetch),
* record/envelope shape, cross-market identity, and the volume-unavailable
  rule (``volume=None`` even when the provider's sixth column is present),
* date/time semantics: strict ``YYYY-MM-DD`` inputs, inclusive windows of at
  most 366 calendar days, per-market local cutoffs derived from an aware
  ``now``, UTC/local date crossings, US DST offsets, conservative
  current-local-day exclusion even after close, ``fetched_at`` (retrieval
  instant) versus ``as_of`` (latest session date),
* ordering, duplicate coalescing / conflict rejection, non-trading gaps
  without synthesized bars,
* row-level OHLC validation (bool / NaN / infinity / overflow / sign /
  high-low inversions / strict dates / container shapes),
* payload-structure errors (provider code must be the integer ``0``,
  adjusted-only fields rejected, missing/wrong symbol or day list),
* transport exception mapping (timeout / SSL / connection / 4xx / 429 / 5xx /
  JSON decode / generic escape) and invalid-input handling that never reaches
  the transport,
* compatibility with the pre-existing ``fetcher_contract`` and
  ``time_metadata_from_fetcher_result`` contracts, and
* the absence of any legacy pipeline / analyzer wiring.

All tests are offline: the transport is always injected or ``requests.get``
is patched. No external API is contacted.
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
import requests

from analysis import fetcher_contract
from analysis.research import capabilities, global_daily_k
from analysis.research.global_daily_k import (
    TENCENT_DAILY_K_TIMEOUT,
    TENCENT_DAILY_K_URL,
    TENCENT_PROVIDER_ID,
    TENCENT_SCOPE,
    TENCENT_SOURCE,
    fetch_global_daily_k,
    requests_json_transport,
)
from analysis.research.global_indices import (
    GlobalIndexSpec,
    build_global_index_symbol_registry,
    get_global_index,
    list_global_indices,
)
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.time_adapter import time_metadata_from_fetcher_result

_NOW_UTC = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
_FAR_FUTURE_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
_WINDOW_START = "2026-09-01"
_WINDOW_END = "2026-09-25"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_NEW_YORK_TZ = ZoneInfo("America/New_York")

# The controller-decided V1 table: index_id, publisher value, local_code,
# market, display name, currency, timezone, Tencent provider symbol.
V1_TABLE: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    ("cn.index.sse.000001", "sse", "000001", "cn", "上证指数", "CNY", "Asia/Shanghai", "sh000001"),
    ("cn.index.szse.399001", "szse", "399001", "cn", "深证成指", "CNY", "Asia/Shanghai", "sz399001"),
    ("cn.index.szse.399006", "szse", "399006", "cn", "创业板指", "CNY", "Asia/Shanghai", "sz399006"),
    ("cn.index.csi.000300", "csi", "000300", "cn", "沪深300", "CNY", "Asia/Shanghai", "sh000300"),
    ("hk.index.hang_seng.hsi", "hang_seng", "HSI", "hk", "恒生指数", "HKD", "Asia/Hong_Kong", "hkHSI"),
    ("hk.index.hang_seng.hstech", "hang_seng", "HSTECH", "hk", "恒生科技指数", "HKD", "Asia/Hong_Kong", "hkHSTECH"),
    ("us.index.sp_dji.sp500", "sp_dji", "SP500", "us", "S&P 500", "USD", "America/New_York", "us.INX"),
    ("us.index.nasdaq.composite", "nasdaq", "IXIC", "us", "Nasdaq Composite", "USD", "America/New_York", "us.IXIC"),
    ("us.index.sp_dji.djia", "sp_dji", "DJI", "us", "Dow Jones Industrial Average", "USD", "America/New_York", "us.DJI"),
)

_RECORD_KEYS = [
    "index_id",
    "market",
    "symbol",
    "name",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "currency",
    "timezone",
    "source",
]

_ENVELOPE_KEYS = {"status", "data", "source", "as_of", "fetched_at", "scope", "units", "error"}


def _row(
    day: str,
    open_px: Any,
    close_px: Any,
    high_px: Any,
    low_px: Any,
    activity: Any = 0,
) -> list[Any]:
    """Build one Tencent-shaped row [date, open, close, high, low, activity]."""

    return [day, open_px, close_px, high_px, low_px, activity]


def _row_ohlc(day: str, base: float = 100.0) -> list[Any]:
    return _row(day, base, base + 5.0, base + 10.0, base - 5.0)


def _payload(provider_symbol: str, rows: list[Any], code: Any = 0) -> dict[str, Any]:
    return {"code": code, "msg": "", "data": {provider_symbol: {"day": rows}}}


_PAYLOAD_UNSET = object()


class RecordingTransport:
    """Deterministic transport stub that records calls and replays a payload.

    ``follow_request_symbol`` mirrors the provider echoing the requested
    symbol; set it to False to serve a static (possibly mismatched) payload.
    """

    def __init__(
        self,
        rows: list[Any] | None = None,
        *,
        code: Any = 0,
        payload: Any = _PAYLOAD_UNSET,
        follow_request_symbol: bool = True,
        static_symbol: str = "sh000300",
        error: Exception | None = None,
    ) -> None:
        self.rows = rows if rows is not None else [_row_ohlc("2026-09-01")]
        self.code = code
        self.static_payload = payload
        self.follow_request_symbol = follow_request_symbol
        self.static_symbol = static_symbol
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, str], timeout: Any) -> Any:
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        if self.error is not None:
            raise self.error
        if self.static_payload is not _PAYLOAD_UNSET:
            return self.static_payload
        symbol = self.static_symbol
        if self.follow_request_symbol:
            symbol = params.get("param", "").split(",", 1)[0]
        return _payload(symbol, self.rows, code=self.code)

    @property
    def call_count(self) -> int:
        return len(self.calls)


class _ForbiddenTransport:
    """Transport that fails the test if the fetcher ever calls it."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("transport must not be called for rejected inputs")


def _forbidden_transport() -> _ForbiddenTransport:
    return _ForbiddenTransport()


def _fetch_ok(
    index_id: str,
    start: str = _WINDOW_START,
    end: str = _WINDOW_END,
    *,
    now: datetime | None = _NOW_UTC,
    rows: list[Any] | None = None,
    code: Any = 0,
) -> tuple[dict[str, Any], RecordingTransport]:
    transport = RecordingTransport(rows=rows, code=code)
    result = fetch_global_daily_k(index_id, start, end, transport=transport, now=now)
    return result, transport


def _assert_error_shape(result: dict[str, Any], code: str, retryable: bool) -> None:
    assert fetcher_contract.is_error(result)
    assert result["data"] is None
    assert result["error"]["code"] == code
    assert result["error"]["retryable"] is retryable
    message = result["error"]["message"]
    assert isinstance(message, str) and message.strip()
    assert len(message) <= 200


# ---------------------------------------------------------------------------
# A. Registry: fixed universe, mappings, immutability, no bare-code inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index_id", "publisher", "local_code", "market", "name", "currency", "tz", "symbol"),
    V1_TABLE,
)
def test_v1_table_mapping_is_exact(
    index_id: str,
    publisher: str,
    local_code: str,
    market: str,
    name: str,
    currency: str,
    tz: str,
    symbol: str,
) -> None:
    spec = get_global_index(index_id)
    assert isinstance(spec, GlobalIndexSpec)
    assert spec.identity == IndexIdentity(
        index_id=index_id,
        publisher=IndexPublisher(publisher),
        local_code=local_code,
    )
    assert spec.market == market
    assert spec.name == name
    assert spec.currency == currency
    assert spec.timezone == tz
    assert spec.provider_symbol == symbol


def test_registry_universe_is_fixed_tuple_of_nine_in_controller_order() -> None:
    specs = list_global_indices()
    assert isinstance(specs, tuple)
    assert len(specs) == 9
    assert tuple(spec.identity.index_id for spec in specs) == tuple(row[0] for row in V1_TABLE)
    # Registration order is stable: repeated calls return the same frozen tuple.
    assert list_global_indices() is specs


def test_global_index_spec_is_frozen_with_exact_contract_fields() -> None:
    assert GlobalIndexSpec.contract_fields() == (
        "identity",
        "market",
        "name",
        "currency",
        "timezone",
        "provider_symbol",
    )
    spec = get_global_index("cn.index.csi.000300")
    with pytest.raises(FrozenInstanceError):
        spec.market = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        spec.identity.local_code = "MUTATED"  # type: ignore[misc]


def test_global_index_spec_rejects_noncanonical_context() -> None:
    identity = IndexIdentity(
        index_id="cn.index.csi.000300",
        publisher=IndexPublisher.CSI,
        local_code="000300",
    )
    base = {
        "identity": identity,
        "market": "cn",
        "name": "沪深300",
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "provider_symbol": "sh000300",
    }
    for field, bad in [
        ("market", "CN"),
        ("market", ""),
        ("market", " cn"),
        ("name", ""),
        ("currency", "cny"),
        ("timezone", ""),
        ("timezone", "Asia/Shanghai "),
        ("provider_symbol", ""),
        ("provider_symbol", " sh000300"),
    ]:
        kwargs = dict(base)
        kwargs[field] = bad
        with pytest.raises((TypeError, ValueError)):
            GlobalIndexSpec(**kwargs)
    with pytest.raises(TypeError):
        GlobalIndexSpec(**{**base, "identity": "not-an-identity"})


def test_index_identity_contract_unchanged() -> None:
    assert IndexIdentity.contract_fields() == ("index_id", "publisher", "local_code")
    # Pre-existing publishers are untouched by the additive V1 enum values.
    for legacy in ("csi", "sse", "szse", "cni"):
        assert IndexPublisher(legacy).value == legacy
    # New enum values are exactly the controller-decided additive values.
    assert IndexPublisher.HANG_SENG.value == "hang_seng"
    assert IndexPublisher.SP_DJI.value == "sp_dji"
    assert IndexPublisher.NASDAQ.value == "nasdaq"


def test_get_global_index_unknown_and_nikkei_raise_keyerror() -> None:
    for unknown in (
        "jp.index.nikkei.n225",
        "jp.index.nikkei.nikkei225",
        "de.index.dax.dax",
        "cn.index.csi.999999",
        "us.index.nasdaq.nasdaq100",
    ):
        with pytest.raises(KeyError):
            get_global_index(unknown)


def test_get_global_index_bad_shape_raises_explicitly() -> None:
    with pytest.raises(TypeError):
        get_global_index(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        get_global_index("CN.INDEX.CSI.000300")
    with pytest.raises(ValueError):
        get_global_index("Cn.Index.Csi.000300")


def test_symbol_registry_resolves_exact_tencent_aliases_only() -> None:
    registry = build_global_index_symbol_registry()
    for index_id, _publisher, _code, _market, _name, _cur, _tz, symbol in V1_TABLE:
        assert registry.resolve(TENCENT_PROVIDER_ID, symbol) == index_id
        aliases = registry.aliases_for(index_id)
        assert len(aliases) == 1
        assert aliases[0].provider_id == "tencent"
        assert aliases[0].provider_symbol == symbol
    # No heuristic bare-code inference: bare local codes and bare market
    # prefixes must never resolve.
    for bare in ("000001", "399001", "000300", "HSI", "HSTECH", "SP500", "IXIC", "DJI"):
        assert registry.resolve(TENCENT_PROVIDER_ID, bare) is None
        with pytest.raises(KeyError):
            registry.require(TENCENT_PROVIDER_ID, bare)
    with pytest.raises(KeyError):
        registry.require(TENCENT_PROVIDER_ID, "nk225")


def test_capability_spec_index_daily_k_is_registered() -> None:
    spec = capabilities.CapabilityRegistry(capabilities.DEFAULT_CAPABILITY_SPECS).require(
        "index.daily_k"
    )
    assert spec.display_name == "指数日K"
    assert spec.domain == "index"
    assert any(c.capability_id == "index.daily_k" for c in capabilities.DEFAULT_CAPABILITY_SPECS)


@pytest.mark.parametrize(
    "bad_id",
    [
        "000001",  # ambiguous bare local code (SSE index vs SZSE share)
        "sh000001",
        "sz399001",
        "hsi",
        "nk225",
        "jp.index.nikkei.n225",
        "cn.index.csi.999999",
        "us.index.nasdaq.nasdaq100",
        "hkHSI",
        "us.INX",
        "IXIC",
        "HSI",
        "^GSPC",
        "^IXIC",
        "N225",
    ],
)
def test_bare_or_unknown_index_ids_return_unsupported_without_transport(bad_id: str) -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        bad_id, _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    assert fetcher_contract.is_unsupported(result)
    assert result["error"]["code"] == fetcher_contract.ERR_UNSUPPORTED
    assert result["error"]["retryable"] is False
    assert result["data"] is None
    assert result["units"] == {}
    assert transport.calls == []


# ---------------------------------------------------------------------------
# B. Exact provider request shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index_id", "symbol"),
    [(row[0], row[7]) for row in V1_TABLE],
)
def test_exact_unadjusted_request_param_for_every_supported_index(
    index_id: str, symbol: str
) -> None:
    result, transport = _fetch_ok(index_id)
    assert fetcher_contract.is_ok(result)
    assert transport.call_count == 1
    call = transport.calls[0]
    assert call["url"] == TENCENT_DAILY_K_URL
    assert call["url"].startswith("https://web.ifzq.gtimg.cn/")
    assert call["params"] == {"param": f"{symbol},day,2026-09-01,2026-09-25,640,"}
    param = call["params"]["param"]
    assert ",day," in param
    assert param.endswith(",640,")
    assert "qfq" not in param.lower()
    assert call["timeout"] == (5, 15)


def test_exactly_one_request_per_fetch_even_for_empty_result() -> None:
    result, transport = _fetch_ok("cn.index.csi.000300", rows=[])
    assert fetcher_contract.is_empty(result)
    assert transport.call_count == 1


def test_default_transport_is_the_requests_json_transport() -> None:
    signature = inspect.signature(fetch_global_daily_k)
    assert signature.parameters["transport"].default is requests_json_transport
    assert TENCENT_DAILY_K_TIMEOUT == (5, 15)
    assert TENCENT_PROVIDER_ID == "tencent"
    assert TENCENT_SCOPE == "market"
    assert TENCENT_SOURCE == "tencent.daily_k"


# ---------------------------------------------------------------------------
# C. Record and envelope shape, cross-market identity, volume rule
# ---------------------------------------------------------------------------


def test_record_keys_exact_set_and_order() -> None:
    result, _ = _fetch_ok("cn.index.csi.000300", rows=[_row("2026-09-01", 1, 2, 3, 0.5)])
    assert fetcher_contract.is_ok(result)
    (record,) = result["data"]
    assert list(record.keys()) == _RECORD_KEYS


def test_envelope_carries_all_fetcher_contract_fields() -> None:
    result, _ = _fetch_ok("cn.index.csi.000300")
    assert set(result.keys()) == _ENVELOPE_KEYS
    assert result["scope"] == "market"
    assert result["source"] == "tencent.daily_k"
    assert result["units"] == {"price": "index_points", "volume": "unavailable"}
    assert result["error"] is None


@pytest.mark.parametrize(
    ("index_id", "market", "local_code", "name", "currency", "tz", "provider_symbol"),
    [
        ("cn.index.sse.000001", "cn", "000001", "上证指数", "CNY", "Asia/Shanghai", "sh000001"),
        ("hk.index.hang_seng.hsi", "hk", "HSI", "恒生指数", "HKD", "Asia/Hong_Kong", "hkHSI"),
        ("hk.index.hang_seng.hstech", "hk", "HSTECH", "恒生科技指数", "HKD", "Asia/Hong_Kong", "hkHSTECH"),
        ("us.index.sp_dji.sp500", "us", "SP500", "S&P 500", "USD", "America/New_York", "us.INX"),
        (
            "us.index.nasdaq.composite",
            "us",
            "IXIC",
            "Nasdaq Composite",
            "USD",
            "America/New_York",
            "us.IXIC",
        ),
        (
            "us.index.sp_dji.djia",
            "us",
            "DJI",
            "Dow Jones Industrial Average",
            "USD",
            "America/New_York",
            "us.DJI",
        ),
    ],
)
def test_cross_market_identity_uses_local_code_not_provider_symbol(
    index_id: str,
    market: str,
    local_code: str,
    name: str,
    currency: str,
    tz: str,
    provider_symbol: str,
) -> None:
    result, transport = _fetch_ok(index_id)
    assert fetcher_contract.is_ok(result)
    (record,) = result["data"]
    assert record["index_id"] == index_id
    assert record["market"] == market
    assert record["symbol"] == local_code
    assert record["symbol"] != provider_symbol
    assert record["name"] == name
    assert record["currency"] == currency
    assert record["timezone"] == tz
    assert record["source"] == TENCENT_SOURCE
    assert record["volume"] is None
    # The provider symbol is used only to build the request, never surfaced.
    assert provider_symbol not in record.values()
    assert transport.calls[0]["params"]["param"].startswith(f"{provider_symbol},day,")


def test_provider_activity_column_never_becomes_volume_or_zero() -> None:
    """A plausible HK-turnover-like sixth column must not leak into records."""

    rows = [
        _row("2026-09-01", 18000.0, 18100.0, 18200.0, 17900.0, 987654321.0),
        _row("2026-09-02", 18100.0, 18050.0, 18150.0, 18000.0, 1234567),
    ]
    result, _ = _fetch_ok("hk.index.hang_seng.hsi", rows=rows)
    assert fetcher_contract.is_ok(result)
    assert result["units"] == {"price": "index_points", "volume": "unavailable"}
    for record in result["data"]:
        assert record["volume"] is None  # missing, never an invented zero
        assert 987654321.0 not in record.values()
        assert 1234567 not in record.values()
        assert "activity" not in record
        assert "turnover" not in record


def test_sixth_column_may_be_garbage_and_is_still_ignored() -> None:
    rows = [
        _row("2026-09-01", 100.0, 101.0, 102.0, 99.0, None),
        _row("2026-09-02", 101.0, 100.5, 101.5, 100.0, "garbage"),
        _row("2026-09-03", 100.5, 101.5, 102.5, 100.0, {"nested": 1}),
    ]
    result, _ = _fetch_ok("us.index.sp_dji.sp500", rows=rows)
    assert fetcher_contract.is_ok(result)
    assert [record["date"] for record in result["data"]] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
    ]
    assert all(record["volume"] is None for record in result["data"])


# ---------------------------------------------------------------------------
# D. Window filtering, ordering, gaps
# ---------------------------------------------------------------------------


def test_output_is_chronological_ascending_with_unique_dates() -> None:
    rows = [
        _row_ohlc("2026-09-03"),
        _row_ohlc("2026-09-01"),
        _row_ohlc("2026-09-05"),
        _row_ohlc("2026-09-02"),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    assert fetcher_contract.is_ok(result)
    dates = [record["date"] for record in result["data"]]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert dates == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-05"]


def test_inclusive_window_keeps_both_boundary_dates() -> None:
    rows = [
        _row_ohlc("2026-08-31"),
        _row_ohlc("2026-09-01"),
        _row_ohlc("2026-09-25"),
        _row_ohlc("2026-09-26"),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    assert [record["date"] for record in result["data"]] == ["2026-09-01", "2026-09-25"]


def test_out_of_window_rows_are_dropped_on_both_sides() -> None:
    rows = [_row_ohlc("2026-08-01"), _row_ohlc("2026-10-01")]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows, now=_FAR_FUTURE_NOW)
    assert fetcher_contract.is_empty(result)
    assert result["as_of"] is None


def test_non_trading_gaps_are_not_forward_filled() -> None:
    rows = [
        _row_ohlc("2026-09-21"),
        _row_ohlc("2026-09-22"),
        _row_ohlc("2026-09-24"),
        _row_ohlc("2026-09-28"),
    ]
    result, _ = _fetch_ok(
        "cn.index.csi.000300", "2026-09-21", "2026-09-28", rows=rows, now=_FAR_FUTURE_NOW
    )
    assert fetcher_contract.is_ok(result)
    # No synthesized sessions for 09-23 / 09-25-27; no holiday inference.
    assert [record["date"] for record in result["data"]] == [
        "2026-09-21",
        "2026-09-22",
        "2026-09-24",
        "2026-09-28",
    ]


def test_non_trading_day_only_window_returns_empty_not_error() -> None:
    """2026-09-26/27 is a weekend: bars exist only on weekdays."""

    rows = [_row_ohlc("2026-09-21"), _row_ohlc("2026-09-25")]
    result, _ = _fetch_ok(
        "cn.index.csi.000300",
        "2026-09-26",
        "2026-09-27",
        rows=rows,
        now=datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc),
    )
    assert fetcher_contract.is_empty(result)
    assert result["data"] is None
    assert result["as_of"] is None


def test_explicit_empty_day_list_is_a_valid_empty_result() -> None:
    result, transport = _fetch_ok("cn.index.csi.000300", rows=[])
    assert fetcher_contract.is_empty(result)
    assert result["data"] is None
    assert result["as_of"] is None
    assert transport.call_count == 1


def test_single_day_window_is_valid() -> None:
    rows = [_row_ohlc("2026-09-10")]
    result, _ = _fetch_ok("cn.index.csi.000300", "2026-09-10", "2026-09-10", rows=rows)
    assert fetcher_contract.is_ok(result)
    assert [record["date"] for record in result["data"]] == ["2026-09-10"]
    assert result["as_of"] == "2026-09-10"


def test_as_of_is_latest_returned_session_date() -> None:
    rows = [_row_ohlc("2026-09-02"), _row_ohlc("2026-09-20"), _row_ohlc("2026-09-05")]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    assert result["as_of"] == "2026-09-20"


# ---------------------------------------------------------------------------
# E. Duplicate handling
# ---------------------------------------------------------------------------


def test_identical_duplicate_bars_coalesce_across_value_types() -> None:
    rows = [
        _row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0, 111),
        _row("2026-09-01", "4250.0", "4275.5", "4280.0", "4245.0", 999),
        _row("2026-09-02", 100, 105, 110, 95, 0),
        _row("2026-09-02", 100.0, 105.0, 110.0, 95.0, 0),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    assert fetcher_contract.is_ok(result)
    assert [record["date"] for record in result["data"]] == ["2026-09-01", "2026-09-02"]
    assert result["data"][0]["open"] == 4250.0
    assert result["data"][0]["close"] == 4275.5
    assert all(record["volume"] is None for record in result["data"])


def test_conflicting_duplicate_bars_are_error_not_silent_keeps() -> None:
    rows = [
        _row("2026-09-01", 4250.0, 4275.5, 4280.0, 4245.0),
        _row("2026-09-01", 4250.0, 4276.5, 4280.0, 4245.0),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_conflicting_duplicate_outside_window_is_still_error() -> None:
    rows = [
        _row("2026-08-01", 100.0, 105.0, 110.0, 95.0),
        _row("2026-08-01", 100.0, 106.0, 110.0, 95.0),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


# ---------------------------------------------------------------------------
# F. Row-level validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_open",
    [
        True,
        False,
        "not-a-number",
        "",
        "   ",
        None,
        {},
        [],
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "inf",
        "-inf",
        0,
        0.0,
        -5.0,
        10**1000,  # int too large for float -> OverflowError
        "1e1000",  # parses to infinity
        "0x1A",
    ],
)
def test_bad_open_values_are_parse_errors(bad_open: Any) -> None:
    rows = [["2026-09-01", bad_open, 110.0, 115.0, 95.0, 0]]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


@pytest.mark.parametrize(
    "row",
    [
        _row("2026-09-01", 100.0, 110.0, 105.0, 120.0),  # low > high
        _row("2026-09-01", 100.0, 110.0, 115.0, 110.5),  # low > close
        _row("2026-09-01", 100.0, 110.0, 115.0, 100.5),  # low > open
        _row("2026-09-01", 100.0, 110.0, 105.0, 95.0),  # high < close
        _row("2026-09-01", 100.0, 98.0, 99.0, 95.0),  # high < open
        _row("2026-09-01", 100.0, 98.0, 99.5, 99.0),  # high < open and close
    ],
)
def test_high_low_inversions_are_parse_errors(row: list[Any]) -> None:
    result, _ = _fetch_ok("cn.index.csi.000300", rows=[row])
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


@pytest.mark.parametrize(
    "bad_row",
    [
        ["2026-09-01", 100.0, 110.0, 115.0],  # fewer than six fields
        ["2026-09-01", 100.0, 110.0, 115.0, 95.0],  # missing activity column
        ("2026-09-01", 100.0, 110.0, 115.0, 95.0, 0),  # tuple, not list
        "2026-09-01,100,110,115,95,0",
        {"date": "2026-09-01", "open": 100.0},
        123,
        None,
        [],
    ],
)
def test_malformed_row_containers_are_parse_errors(bad_row: Any) -> None:
    result, _ = _fetch_ok("cn.index.csi.000300", rows=[bad_row])
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


@pytest.mark.parametrize(
    "bad_day",
    [
        "2026/09/01",
        "2026-9-1",
        "20260901",
        "2026-W39-6",
        "2026-02-30",
        "2026-13-01",
        "2026-00-10",
        "2026-09-01T00:00:00",
        "09-01-2026",
        "",
        20260901,
        None,
    ],
)
def test_non_strict_or_invalid_row_dates_are_parse_errors(bad_day: Any) -> None:
    rows = [[bad_day, 100.0, 110.0, 115.0, 95.0, 0]]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_int_and_decimal_string_ohlc_are_accepted() -> None:
    rows = [
        _row("2026-09-01", 4250, "4275.5", 4280, "4245.0"),
        _row("2026-09-02", "4300.25", 4310, "4320.5", "4295.75"),
    ]
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
    assert fetcher_contract.is_ok(result)
    first, second = result["data"]
    assert first["open"] == 4250.0
    assert first["close"] == 4275.5
    assert first["high"] == 4280.0
    assert first["low"] == 4245.0
    assert second["open"] == 4300.25
    assert second["low"] == 4295.75


# ---------------------------------------------------------------------------
# G. Payload structure errors
# ---------------------------------------------------------------------------


_GOOD_SECTION = {"day": [_row_ohlc("2026-09-01")]}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "not-a-mapping",
        0,
        {},
        {"msg": "", "data": {"sh000300": _GOOD_SECTION}},  # code missing
        {"code": "0", "data": {"sh000300": _GOOD_SECTION}},  # string code
        {"code": True, "data": {"sh000300": _GOOD_SECTION}},  # bool code
        {"code": False, "data": {"sh000300": _GOOD_SECTION}},  # bool code
        {"code": 0},  # data missing entirely
        {"code": 0, "data": None},
        {"code": 0, "data": []},
        {"code": 0, "data": "sh000300"},
        {"code": 0, "data": {}},  # requested symbol missing
        {"code": 0, "data": {"sz399001": _GOOD_SECTION}},  # wrong symbol
        {"code": 0, "data": {"sh000300": []}},  # symbol section not mapping
        {"code": 0, "data": {"sh000300": "day"}},
        {"code": 0, "data": {"sh000300": {}}},  # day missing
        {"code": 0, "data": {"sh000300": {"day": None}}},
        {"code": 0, "data": {"sh000300": {"day": {}}}},
        {"code": 0, "data": {"sh000300": {"day": "2026-09-01"}}},
    ],
)
def test_malformed_payload_structures_are_parse_errors(payload: Any) -> None:
    transport = RecordingTransport(payload=payload)
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)
    assert transport.call_count == 1


@pytest.mark.parametrize("code", [1, -1, 100, 500])
def test_nonzero_provider_code_is_error_not_empty(code: int) -> None:
    transport = RecordingTransport(code=code)
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_adjusted_only_payload_is_rejected() -> None:
    """A symbol section that only carries adjusted series is an error."""

    payload = {
        "code": 0,
        "msg": "",
        "data": {"sh000300": {"qfqday": [_row_ohlc("2026-09-01")]}},
    }
    transport = RecordingTransport(payload=payload)
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_unadjusted_day_preferred_and_extra_symbols_ignored() -> None:
    payload = {
        "code": 0,
        "msg": "",
        "data": {
            "sh000300": {
                "day": [_row("2026-09-01", 100.0, 101.0, 102.0, 99.0, 0)],
                "qfqday": [_row("2026-09-01", 999.0, 999.0, 999.0, 999.0, 0)],
            },
            "sh000001": {"day": [_row_ohlc("2026-09-01")]},
        },
    }
    transport = RecordingTransport(payload=payload)
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    assert fetcher_contract.is_ok(result)
    (record,) = result["data"]
    assert record["open"] == 100.0  # unadjusted day series, never qfqday


# ---------------------------------------------------------------------------
# H. Transport exception mapping
# ---------------------------------------------------------------------------


def _http_error(status: int | None) -> requests.exceptions.HTTPError:
    if status is None:
        return requests.exceptions.HTTPError("boom")
    return requests.exceptions.HTTPError("boom", response=mock.Mock(status_code=status))


@pytest.mark.parametrize(
    ("make_exc", "code", "retryable"),
    [
        (lambda: requests.exceptions.Timeout("t"), fetcher_contract.ERR_NET_TIMEOUT, True),
        (
            lambda: requests.exceptions.ConnectTimeout("t"),
            fetcher_contract.ERR_NET_TIMEOUT,
            True,
        ),
        (
            lambda: requests.exceptions.ReadTimeout("t"),
            fetcher_contract.ERR_NET_TIMEOUT,
            True,
        ),
        (lambda: requests.exceptions.SSLError("s"), fetcher_contract.ERR_NET_SSL, True),
        (
            lambda: requests.exceptions.ConnectionError("c"),
            fetcher_contract.ERR_NET_CONN,
            True,
        ),
        (lambda: _http_error(400), fetcher_contract.ERR_NET_4XX, False),
        (lambda: _http_error(403), fetcher_contract.ERR_NET_4XX, False),
        (lambda: _http_error(404), fetcher_contract.ERR_NET_4XX, False),
        (lambda: _http_error(418), fetcher_contract.ERR_NET_4XX, False),
        (lambda: _http_error(429), fetcher_contract.ERR_NET_RATELIMIT, True),
        (lambda: _http_error(500), fetcher_contract.ERR_NET_5XX, True),
        (lambda: _http_error(502), fetcher_contract.ERR_NET_5XX, True),
        (lambda: _http_error(503), fetcher_contract.ERR_NET_5XX, True),
        (lambda: _http_error(None), fetcher_contract.ERR_NET_5XX, True),
        (
            lambda: requests.exceptions.TooManyRedirects("r"),
            fetcher_contract.ERR_UNKNOWN,
            True,
        ),
        (
            lambda: requests.exceptions.ChunkedEncodingError("e"),
            fetcher_contract.ERR_UNKNOWN,
            True,
        ),
    ],
)
def test_transport_exception_mapping(make_exc: Any, code: str, retryable: bool) -> None:
    transport = RecordingTransport(error=make_exc())
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, code, retryable)
    assert transport.call_count == 1


def test_json_decode_error_is_parse_not_unknown() -> None:
    """JSONDecodeError inherits ValueError AND RequestException; it must map
    to PARSE / retryable=False, never the catch-all UNKNOWN retry path."""

    transport = RecordingTransport(error=requests.exceptions.JSONDecodeError("bad json", "doc", 0))
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_plain_value_error_from_transport_is_parse() -> None:
    transport = RecordingTransport(error=ValueError("garbled"))
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


def test_runtime_error_from_transport_is_safe_unknown_and_does_not_escape() -> None:
    transport = RecordingTransport(error=RuntimeError("provider exploded: internal diagnostic detail"))
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_UNKNOWN, retryable=True)
    assert "provider exploded" not in result["error"]["message"]
    assert "diagnostic detail" not in result["error"]["message"]


def test_ohlc_overflow_values_are_parse_errors_not_crashes() -> None:
    for bad in (10**1000, "1e1000", "-1e1000"):
        rows = [["2026-09-01", bad, 110.0, 115.0, 95.0, 0]]
        result, _ = _fetch_ok("cn.index.csi.000300", rows=rows)
        _assert_error_shape(result, fetcher_contract.ERR_PARSE, retryable=False)


# ---------------------------------------------------------------------------
# I. Invalid inputs never reach the transport
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_start",
    [
        "2026-13-01",
        "2026-02-30",
        "2026/09/01",
        "2026-9-1",
        "20260901",
        "2026-W39-6",
        "",
        None,
        20260901,
    ],
)
def test_bad_start_dates_return_validation_without_transport(bad_start: Any) -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        "cn.index.csi.000300", bad_start, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


@pytest.mark.parametrize(
    "bad_end",
    ["2026-13-01", "2026-02-30", "2026/09/25", "20260925", "", None, 20260925],
)
def test_bad_end_dates_return_validation_without_transport(bad_end: Any) -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, bad_end, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


def test_start_after_end_returns_validation() -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        "cn.index.csi.000300", "2026-09-25", "2026-09-01", transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


def _inclusive_span(start: str, end: str) -> int:
    return (Date.fromisoformat(end) - Date.fromisoformat(start)).days + 1


def test_window_of_exactly_366_inclusive_days_is_accepted() -> None:
    start, end = "2025-09-26", "2026-09-26"
    assert _inclusive_span(start, end) == 366
    rows = [_row_ohlc("2026-09-01")]
    result, transport = _fetch_ok("cn.index.csi.000300", start, end, rows=rows)
    assert fetcher_contract.is_ok(result)
    assert transport.call_count == 1


def test_window_of_367_inclusive_days_is_rejected() -> None:
    start, end = "2025-09-25", "2026-09-26"
    assert _inclusive_span(start, end) == 367
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        "cn.index.csi.000300", start, end, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


@pytest.mark.parametrize(
    "bad_now",
    [
        datetime(2026, 9, 27, 12, 0),  # naive datetime
        Date(2026, 9, 27),
        "2026-09-27T12:00:00+00:00",
        0,
        True,
    ],
)
def test_naive_or_non_datetime_now_returns_validation(bad_now: Any) -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, transport=transport, now=bad_now
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


@pytest.mark.parametrize("bad_transport", [None, 123, "transport", object(), {}])
def test_non_callable_transport_returns_validation(bad_transport: Any) -> None:
    result = fetch_global_daily_k(
        "cn.index.csi.000300",
        _WINDOW_START,
        _WINDOW_END,
        transport=bad_transport,
        now=_NOW_UTC,
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)


@pytest.mark.parametrize(
    "bad_id",
    [
        None,
        123,
        "",
        "CN.INDEX.CSI.000300",
        "Cn.Index.Csi.000300",
    ],
)
def test_noncanonical_index_id_returns_validation_not_unsupported(bad_id: Any) -> None:
    transport = _forbidden_transport()
    result = fetch_global_daily_k(
        bad_id, _WINDOW_START, _WINDOW_END, transport=transport, now=_NOW_UTC
    )
    _assert_error_shape(result, fetcher_contract.ERR_VALIDATION, retryable=False)
    assert transport.calls == []


def test_aware_now_with_fixed_offset_is_accepted() -> None:
    rows = [_row_ohlc("2026-09-01")]
    fixed_offset_now = datetime(2026, 9, 27, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    result, _ = _fetch_ok("cn.index.csi.000300", rows=rows, now=fixed_offset_now)
    assert fetcher_contract.is_ok(result)


# ---------------------------------------------------------------------------
# J. Date/time semantics: cutoffs, crossings, DST, fetched_at vs as_of
# ---------------------------------------------------------------------------


def test_cutoff_is_localized_per_market_for_the_same_utc_now() -> None:
    """00:30 UTC on 2026-09-27 is already Sep 27 in Shanghai/Hong Kong but
    still Sep 26 in New York (EDT). The same UTC ``now`` must therefore cut
    different session dates per market."""

    now = datetime(2026, 9, 27, 0, 30, tzinfo=timezone.utc)
    rows = [_row_ohlc("2026-09-25"), _row_ohlc("2026-09-26")]

    cn_result, _ = _fetch_ok(
        "cn.index.csi.000300", "2026-09-24", "2026-09-27", rows=list(rows), now=now
    )
    assert [r["date"] for r in cn_result["data"]] == ["2026-09-25", "2026-09-26"]

    hk_result, _ = _fetch_ok(
        "hk.index.hang_seng.hsi", "2026-09-24", "2026-09-27", rows=list(rows), now=now
    )
    assert [r["date"] for r in hk_result["data"]] == ["2026-09-25", "2026-09-26"]

    us_result, _ = _fetch_ok(
        "us.index.sp_dji.sp500", "2026-09-24", "2026-09-27", rows=list(rows), now=now
    )
    assert [r["date"] for r in us_result["data"]] == ["2026-09-25"]


def test_session_dates_are_not_converted_to_utc() -> None:
    """A US session dated 2026-09-25 stays 2026-09-25 even when the fetch
    happens on the next UTC day."""

    now = datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc)  # 05:00 in New York
    rows = [_row_ohlc("2026-09-25")]
    result, _ = _fetch_ok("us.index.sp_dji.sp500", rows=rows, now=now)
    assert fetcher_contract.is_ok(result)
    assert result["data"][0]["date"] == "2026-09-25"
    assert result["as_of"] == "2026-09-25"


def test_us_dst_offsets_are_respected_for_the_cutoff() -> None:
    """The same 04:30 UTC instant maps to different New York dates across the
    EST/EDT boundary (UTC-5 in January vs UTC-4 in July)."""

    winter_now = datetime(2026, 1, 5, 4, 30, tzinfo=timezone.utc)
    summer_now = datetime(2026, 7, 5, 4, 30, tzinfo=timezone.utc)
    assert winter_now.astimezone(_NEW_YORK_TZ).utcoffset() == timedelta(hours=-5)
    assert summer_now.astimezone(_NEW_YORK_TZ).utcoffset() == timedelta(hours=-4)
    assert winter_now.astimezone(_NEW_YORK_TZ).date() == Date(2026, 1, 4)
    assert summer_now.astimezone(_NEW_YORK_TZ).date() == Date(2026, 7, 5)

    winter_rows = [_row_ohlc("2026-01-03"), _row_ohlc("2026-01-04"), _row_ohlc("2026-01-05")]
    winter, _ = _fetch_ok(
        "us.index.sp_dji.sp500", "2026-01-01", "2026-01-06", rows=winter_rows, now=winter_now
    )
    assert [r["date"] for r in winter["data"]] == ["2026-01-03"]

    summer_rows = [_row_ohlc("2026-07-03"), _row_ohlc("2026-07-04"), _row_ohlc("2026-07-05")]
    summer, _ = _fetch_ok(
        "us.index.sp_dji.sp500", "2026-07-01", "2026-07-07", rows=summer_rows, now=summer_now
    )
    assert [r["date"] for r in summer["data"]] == ["2026-07-03", "2026-07-04"]


def test_current_local_day_bar_excluded_even_after_close() -> None:
    # Shanghai 20:00 — long after the 15:00 close.
    cn_now = datetime(2026, 9, 27, 20, 0, tzinfo=_SHANGHAI_TZ)
    cn_rows = [_row_ohlc("2026-09-26"), _row_ohlc("2026-09-27")]
    cn_result, _ = _fetch_ok(
        "cn.index.csi.000300", "2026-09-25", "2026-09-27", rows=cn_rows, now=cn_now
    )
    assert [r["date"] for r in cn_result["data"]] == ["2026-09-26"]

    # New York 23:30 — long after the 16:00 close.
    ny_now = datetime(2026, 9, 27, 23, 30, tzinfo=ZoneInfo("America/New_York"))
    us_rows = [_row_ohlc("2026-09-26"), _row_ohlc("2026-09-27")]
    us_result, _ = _fetch_ok(
        "us.index.sp_dji.sp500", "2026-09-25", "2026-09-27", rows=us_rows, now=ny_now
    )
    assert [r["date"] for r in us_result["data"]] == ["2026-09-26"]


def test_fetched_at_is_the_real_retrieval_instant_not_injected_now() -> None:
    injected_now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    before = datetime.now(timezone.utc)
    result, _ = _fetch_ok("cn.index.csi.000300", rows=[_row_ohlc("2026-09-25")], now=injected_now)
    after = datetime.now(timezone.utc)

    assert fetcher_contract.is_ok(result)
    fetched_at = datetime.fromisoformat(result["fetched_at"])
    assert fetched_at.tzinfo is not None
    # fetched_at is serialized with seconds precision, so allow a 1s skew.
    assert before - timedelta(seconds=1) <= fetched_at <= after
    # as_of is the latest session date, a plain date string — not a timestamp.
    assert result["as_of"] == "2026-09-25"
    assert result["as_of"] != result["fetched_at"]
    assert "T" not in result["as_of"]


def test_time_metadata_adapter_accepts_fetcher_results() -> None:
    ok_result, _ = _fetch_ok("cn.index.csi.000300", rows=[_row_ohlc("2026-09-25")])
    meta = time_metadata_from_fetcher_result(ok_result)
    assert meta.fetched_at == ok_result["fetched_at"]
    assert meta.data_as_of == "2026-09-25"
    assert meta.published_at is None
    assert meta.period_start is None
    assert meta.effective_from is None

    empty_result, _ = _fetch_ok("cn.index.csi.000300", rows=[])
    empty_meta = time_metadata_from_fetcher_result(empty_result)
    assert empty_meta.data_as_of is None
    assert empty_meta.fetched_at  # retrieval instant is still present


def test_empty_and_error_results_have_no_units_and_no_as_of() -> None:
    empty_result, _ = _fetch_ok("cn.index.csi.000300", rows=[])
    assert empty_result["units"] == {}
    assert empty_result["as_of"] is None
    assert empty_result["error"]["retryable"] is False

    error_transport = RecordingTransport(error=requests.exceptions.Timeout("t"))
    error_result = fetch_global_daily_k(
        "cn.index.csi.000300",
        _WINDOW_START,
        _WINDOW_END,
        transport=error_transport,
        now=_NOW_UTC,
    )
    assert error_result["units"] == {}
    assert error_result["as_of"] is None


# ---------------------------------------------------------------------------
# K. Default transport unit behavior (requests.get fully patched)
# ---------------------------------------------------------------------------


def test_requests_json_transport_uses_bounded_timeout_and_verifies_tls() -> None:
    payload = _payload("sh000300", [])
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload

    with mock.patch.object(global_daily_k.requests, "get", return_value=response) as get:
        result_payload = requests_json_transport(
            TENCENT_DAILY_K_URL, params={"param": "p"}, timeout=TENCENT_DAILY_K_TIMEOUT
        )

    assert result_payload is payload
    assert get.call_count == 1
    args, kwargs = get.call_args
    assert args[0] == TENCENT_DAILY_K_URL
    assert kwargs["params"] == {"param": "p"}
    assert kwargs["timeout"] == (5, 15)
    # TLS verification must remain enabled: no verify=False override.
    assert "verify" not in kwargs
    response.raise_for_status.assert_called_once_with()


def test_requests_json_transport_rejects_bad_arguments() -> None:
    with pytest.raises(TypeError):
        requests_json_transport("", params={})
    with pytest.raises(TypeError):
        requests_json_transport(
            TENCENT_DAILY_K_URL,
            params={},
            timeout=(5,),  # type: ignore[arg-type]
        )


def test_requests_json_transport_surfaces_http_errors() -> None:
    response = mock.Mock()
    response.raise_for_status.side_effect = _http_error(500)
    with (
        mock.patch.object(global_daily_k.requests, "get", return_value=response),
        pytest.raises(requests.exceptions.HTTPError),
    ):
        requests_json_transport(TENCENT_DAILY_K_URL, params={}, timeout=TENCENT_DAILY_K_TIMEOUT)


def test_default_transport_end_to_end_with_patched_requests_get() -> None:
    payload = _payload("sh000300", [_row_ohlc("2026-09-01")])
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload

    with mock.patch.object(global_daily_k.requests, "get", return_value=response) as get:
        result = fetch_global_daily_k(
            "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, now=_NOW_UTC
        )

    assert fetcher_contract.is_ok(result)
    args, kwargs = get.call_args
    assert args[0] == TENCENT_DAILY_K_URL
    assert kwargs["params"]["param"] == "sh000300,day,2026-09-01,2026-09-25,640,"
    assert kwargs["timeout"] == (5, 15)


def test_default_transport_http_failure_maps_end_to_end() -> None:
    response = mock.Mock()
    response.raise_for_status.side_effect = _http_error(404)
    with mock.patch.object(global_daily_k.requests, "get", return_value=response):
        result = fetch_global_daily_k(
            "cn.index.csi.000300", _WINDOW_START, _WINDOW_END, now=_NOW_UTC
        )
    _assert_error_shape(result, fetcher_contract.ERR_NET_4XX, retryable=False)


# ---------------------------------------------------------------------------
# L. Pre-existing contract compatibility and no pipeline wiring
# ---------------------------------------------------------------------------


def test_fetcher_contract_status_helpers_classify_every_outcome() -> None:
    ok_result, _ = _fetch_ok("cn.index.csi.000300")
    empty_result, _ = _fetch_ok("cn.index.csi.000300", rows=[])
    unsupported, _ = _fetch_ok("jp.index.nikkei.n225")
    error_transport = RecordingTransport(error=RuntimeError("x"))
    error_result = fetch_global_daily_k(
        "cn.index.csi.000300",
        _WINDOW_START,
        _WINDOW_END,
        transport=error_transport,
        now=_NOW_UTC,
    )

    assert fetcher_contract.status_of(ok_result) == "ok"
    assert fetcher_contract.is_ok(ok_result)
    assert fetcher_contract.status_of(empty_result) == "empty"
    assert fetcher_contract.is_empty(empty_result)
    assert fetcher_contract.status_of(unsupported) == "unsupported"
    assert fetcher_contract.is_unsupported(unsupported)
    assert fetcher_contract.status_of(error_result) == "error"
    assert fetcher_contract.is_error(error_result)
    assert fetcher_contract.is_error(None)


def test_no_legacy_pipeline_or_analyzer_wiring() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    analysis_dir = repo_root / "analysis"
    for relative in (
        "pipeline.py",
        "quant_analyzer.py",
        "quant_analyzer_v2.py",
        "quant_analyzer_v3.py",
        "fetcher_dispatcher.py",
        "research/__init__.py",
    ):
        source = (analysis_dir / relative).read_text(encoding="utf-8")
        assert "global_daily_k" not in source, f"wiring leak in {relative}"
        assert "global_indices" not in source, f"wiring leak in {relative}"

    # And the new fetcher must not import the legacy analyzer.
    fetcher_source = (analysis_dir / "research" / "global_daily_k.py").read_text(encoding="utf-8")
    assert "quant_analyzer" not in fetcher_source
    assert "from analysis import pipeline" not in fetcher_source
