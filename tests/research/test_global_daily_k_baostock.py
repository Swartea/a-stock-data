"""Offline contracts for the BaoStock Daily-K fallback."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest
import requests

from analysis import fetcher_contract
from analysis.research import global_daily_k_baostock as bao
from analysis.research.global_daily_k_service import (
    DailyKProvider,
    default_daily_k_providers,
    fetch_global_daily_k_service,
)
from analysis.research.global_indices import list_global_indices

START = "2026-09-01"
END = "2026-09-04"
NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
INDEX_MAP = {
    "cn.index.sse.000001": "sh.000001",
    "cn.index.szse.399001": "sz.399001",
    "cn.index.szse.399006": "sz.399006",
    "cn.index.csi.000300": "sh.000300",
}


def _row(
    code: str,
    date: str = "2026-09-01",
    *,
    open_: str = "100.0",
    high: str = "110.0",
    low: str = "95.0",
    close: str = "105.0",
) -> dict[str, str]:
    return {
        "date": date,
        "code": code,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": "123456789",
        "amount": "987654321",
    }


def _protocol(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {"status": "ok", "rows": rows}


def _worker_rows(code: str, start: str, end: str) -> dict[str, Any]:
    return _protocol([_row(code)])


def _worker_hang(code: str, start: str, end: str) -> dict[str, Any]:
    time.sleep(10)
    return _protocol([_row(code)])


def _worker_ignore_term(code: str, start: str, end: str) -> dict[str, Any]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(10)
    return _protocol([_row(code)])


def _worker_exits_without_reply(code: str, start: str, end: str) -> None:
    os._exit(0)


def _assert_ok(result: dict[str, Any]) -> None:
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["source"] == bao.BAOSTOCK_SOURCE
    assert result["scope"] == "market"
    assert result["units"] == {"price": "index_points", "volume": "unavailable"}


@pytest.mark.parametrize(("index_id", "code"), INDEX_MAP.items())
def test_all_four_a_share_codes_normalize_to_v1_identity(
    index_id: str, code: str
) -> None:
    with mock.patch.object(
        bao, "_run_baostock_child", return_value=_protocol([_row(code)])
    ) as runner:
        result = bao.fetch_baostock_daily_k(index_id, START, END, now=NOW)

    _assert_ok(result)
    runner.assert_called_once()
    assert runner.call_args.args[1:] == (code, START, END)
    record = result["data"][0]
    spec = next(s for s in list_global_indices() if s.identity.index_id == index_id)
    assert record == {
        "index_id": index_id,
        "market": "cn",
        "symbol": spec.identity.local_code,
        "name": spec.name,
        "date": "2026-09-01",
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "volume": None,
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "source": bao.BAOSTOCK_SOURCE,
    }


def test_provider_descriptor_has_stable_name_source_and_callable() -> None:
    provider = bao.baostock_daily_k_provider()
    assert isinstance(provider, DailyKProvider)
    assert provider.name == "baostock"
    assert provider.source == "baostock.daily_k"
    assert provider.fetch is bao.fetch_baostock_daily_k


def test_non_a_share_symbol_is_unsupported_without_child_process() -> None:
    with mock.patch.object(bao, "_run_baostock_child") as runner:
        result = bao.fetch_baostock_daily_k(
            "hk.index.hang_seng.hsi", START, END, now=NOW
        )
    assert result["status"] == fetcher_contract.STATUS_UNSUPPORTED
    runner.assert_not_called()


def test_noncanonical_registered_symbol_is_validation_without_child_process() -> None:
    with mock.patch.object(bao, "_run_baostock_child") as runner:
        result = bao.fetch_baostock_daily_k(
            "CN.INDEX.CSI.000300", START, END, now=NOW
        )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    runner.assert_not_called()


def test_rows_are_sorted_and_identical_duplicates_coalesce() -> None:
    rows = [
        _row("sh.000300", "2026-09-02", open_="101", high="112", low="99", close="111"),
        _row("sh.000300"),
        _row("sh.000300"),
    ]
    with mock.patch.object(bao, "_run_baostock_child", return_value=_protocol(rows)):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=NOW
        )
    _assert_ok(result)
    assert [row["date"] for row in result["data"]] == [
        "2026-09-01",
        "2026-09-02",
    ]


@pytest.mark.parametrize(
    "rows",
    [
        [_row("sz.399001", "2026-09-01")],
        [_row("sh.000300", "20260901")],
        [_row("sh.000300", open_="true")],
        [_row("sh.000300", high="90")],
    ],
)
def test_wrong_symbol_or_malformed_row_is_parse_error(
    rows: list[dict[str, str]],
) -> None:
    with mock.patch.object(bao, "_run_baostock_child", return_value=_protocol(rows)):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=NOW
        )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE
    assert result["error"]["retryable"] is False


def test_conflicting_duplicate_date_is_parse_error() -> None:
    rows = [
        _row("sh.000300"),
        _row("sh.000300", close="106"),
    ]
    with mock.patch.object(bao, "_run_baostock_child", return_value=_protocol(rows)):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=NOW
        )
    assert result["error"]["code"] == fetcher_contract.ERR_PARSE


def test_empty_window_uses_existing_empty_contract() -> None:
    with mock.patch.object(bao, "_run_baostock_child", return_value=_protocol([])):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=NOW
        )
    assert result["status"] == fetcher_contract.STATUS_EMPTY
    assert result["data"] is None
    assert result["source"] == bao.BAOSTOCK_SOURCE
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION


@pytest.mark.parametrize(
    ("protocol", "code"),
    [
        ({"status": "login_error"}, fetcher_contract.ERR_NET_CONN),
        ({"status": "query_error"}, fetcher_contract.ERR_UNKNOWN),
        ({"status": "worker_error"}, fetcher_contract.ERR_UNKNOWN),
        ({"status": "ok", "rows": None}, fetcher_contract.ERR_UNKNOWN),
        ({"status": "timeout"}, fetcher_contract.ERR_NET_TIMEOUT),
    ],
)
def test_sdk_and_process_failures_map_to_stable_errors(
    protocol: dict[str, Any], code: str
) -> None:
    with mock.patch.object(bao, "_run_baostock_child", return_value=protocol):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=NOW
        )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["error"]["code"] == code
    assert "traceback" not in result["error"]["message"].lower()


def test_invalid_dates_do_not_start_child() -> None:
    with mock.patch.object(bao, "_run_baostock_child") as runner:
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", "2026-09-04", "2026-09-01", now=NOW
        )
    assert result["error"]["code"] == fetcher_contract.ERR_VALIDATION
    runner.assert_not_called()


def test_local_session_day_cutoff_uses_index_timezone() -> None:
    rows = [_row("sh.000300", "2026-09-02")]
    # 16:30 UTC is 00:30 on the next Shanghai calendar date.
    now = datetime(2026, 9, 1, 16, 30, tzinfo=timezone.utc)
    with mock.patch.object(bao, "_run_baostock_child", return_value=_protocol(rows)):
        result = bao.fetch_baostock_daily_k(
            "cn.index.csi.000300", START, END, now=now
        )
    assert result["status"] == fetcher_contract.STATUS_EMPTY


def test_spawn_runner_returns_serializable_protocol_and_reaps_child() -> None:
    result = bao._run_baostock_child(
        _worker_rows,
        "sh.000300",
        START,
        END,
        timeout_seconds=3,
    )
    assert result == _protocol([_row("sh.000300")])
    assert multiprocessing.active_children() == []


def test_spawn_runner_timeout_kills_and_reaps_child() -> None:
    result = bao._run_baostock_child(
        _worker_ignore_term,
        "sh.000300",
        START,
        END,
        timeout_seconds=0.4,
    )
    assert result == {"status": "timeout"}
    assert multiprocessing.active_children() == []


def test_spawn_runner_no_response_is_a_stable_worker_error() -> None:
    result = bao._run_baostock_child(
        _worker_exits_without_reply,
        "sh.000300",
        START,
        END,
        timeout_seconds=3,
    )
    assert result == {"status": "worker_error"}
    assert multiprocessing.active_children() == []


def _tencent_payload() -> dict[str, Any]:
    return {
        "code": 0,
        "msg": "",
        "data": {
            "sh000300": {
                "day": [
                    ["2026-09-01", 100, 105, 110, 95, 0],
                    ["2026-09-02", 105, 107, 112, 100, 0],
                ]
            }
        },
    }


def _ok_transport(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _tencent_payload()


def _provider_protocol(rows: list[dict[str, str]]) -> dict[str, Any]:
    return _protocol(rows)


def test_default_routing_is_a_share_only() -> None:
    assert [p.name for p in default_daily_k_providers()] == ["tencent"]
    for index_id in INDEX_MAP:
        assert [p.name for p in default_daily_k_providers(index_id)] == [
            "tencent",
            "baostock",
        ]
    assert [
        p.name for p in default_daily_k_providers("hk.index.hang_seng.hsi")
    ] == ["tencent"]
    assert [
        p.name for p in default_daily_k_providers("us.index.sp_dji.sp500")
    ] == ["tencent"]


def test_default_chain_tencent_success_skips_baostock() -> None:
    with mock.patch.object(bao, "_run_baostock_child") as runner:
        result = fetch_global_daily_k_service(
            "cn.index.csi.000300", START, END, now=NOW, transport=_ok_transport
        )
    assert result["status"] == fetcher_contract.STATUS_OK
    assert result["source_used"] == "tencent"
    assert result["fallback_sources"] == ("baostock",)
    assert result["degraded"] is False
    runner.assert_not_called()


def _primary_failure_transport(kind: str):
    def transport(url: str, *, params: dict[str, str], timeout: Any) -> Any:
        if kind == "timeout":
            raise requests.exceptions.Timeout()
        if kind == "http":
            response = mock.Mock(status_code=503)
            raise requests.exceptions.HTTPError(response=response)
        if kind == "empty":
            return {"code": 0, "msg": "", "data": {"sh000300": {"day": []}}}
        payload = _tencent_payload()
        payload["data"]["sh000300"]["day"][0][3] = 90
        return payload

    return transport


@pytest.mark.parametrize("kind", ["timeout", "http", "empty", "malformed"])
def test_primary_failure_uses_baostock_and_records_degraded_provenance(
    kind: str,
) -> None:
    with mock.patch.object(
        bao,
        "_run_baostock_child",
        return_value=_provider_protocol([_row("sh.000300")]),
    ) as runner:
        result = fetch_global_daily_k_service(
            "cn.index.csi.000300",
            START,
            END,
            now=NOW,
            transport=_primary_failure_transport(kind),
        )

    _assert_ok(result)
    assert result["source_used"] == "baostock"
    assert result["source"] == bao.BAOSTOCK_SOURCE
    assert result["degraded"] is True
    assert result["provider_status"] == "degraded"
    assert result["failure_reason"]
    assert [a["provider"] for a in result["provider_attempts"]] == [
        "tencent",
        "baostock",
    ]
    assert result["provider_attempts"][1]["degraded"] is True
    runner.assert_called_once()


def test_both_providers_fail_reports_baostock_as_last_attempt() -> None:
    with mock.patch.object(
        bao, "_run_baostock_child", return_value={"status": "worker_error"}
    ):
        result = fetch_global_daily_k_service(
            "cn.index.csi.000300",
            START,
            END,
            now=NOW,
            transport=_primary_failure_transport("timeout"),
        )
    assert result["status"] == fetcher_contract.STATUS_ERROR
    assert result["source"] == bao.BAOSTOCK_SOURCE
    assert result["source_used"] is None
    assert result["provider_status"] == "failed"
    assert result["failure_reason"].startswith(fetcher_contract.ERR_UNKNOWN)
    assert [a["provider"] for a in result["provider_attempts"]] == [
        "tencent",
        "baostock",
    ]


@pytest.mark.parametrize(
    "index_id", ["hk.index.hang_seng.hsi", "us.index.sp_dji.sp500"]
)
def test_hk_us_primary_failure_does_not_attempt_baostock(index_id: str) -> None:
    with mock.patch.object(bao, "_run_baostock_child") as runner:
        result = fetch_global_daily_k_service(
            index_id,
            START,
            END,
            now=NOW,
            transport=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                requests.exceptions.Timeout()
            ),
        )
    assert result["fallback_sources"] == ()
    assert len(result["provider_attempts"]) == 1
    assert result["provider_attempts"][0]["provider"] == "tencent"
    runner.assert_not_called()
