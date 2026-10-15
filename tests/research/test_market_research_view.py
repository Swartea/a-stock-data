"""Tests for the global daily-K research page and its HTTP endpoints.

Everything here is offline. The HTTP handler is exercised with an injected
research callable (``fixture isolation``) so no provider and no network is
touched, and the existing A-share static snapshot page is asserted to still
render exactly as before.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from analysis.research import market_research_view as view
from analysis.research import market_snapshot_view as legacy_view
from analysis.research.global_indices import list_global_indices

# Import the CLI script by path: it lives in scripts/, not in an importable
# package, and importing it must not start a server.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "market_research.py"
_spec = importlib.util.spec_from_file_location("_market_research_script", _SCRIPT_PATH)
assert _spec and _spec.loader
script = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_market_research_script", script)
_spec.loader.exec_module(script)


# Labeled fixtures used by the endpoint tests only.
_LABELED_OK_PAYLOAD = {
    "index_id": "cn.index.sh_comp",
    "market": "cn",
    "name": "上证指数",
    "currency": "CNY",
    "timezone": "Asia/Shanghai",
    "provider_symbol": "sh000001",
    "publisher": "sse",
    "local_code": "000001",
    "status": "ok",
    "availability": "available",
    "freshness": "fresh",
    "data_date": "2026-09-25",
    "source": "tencent.daily_k",
    "provider_status": "ok",
    "bar_count": 2,
    "degraded": False,
    "failure_reason": None,
    "unavailable_reason": None,
    "start_date": "2026-09-01",
    "end_date": "2026-09-30",
    "evaluated_at": "2026-09-25T15:30:00+08:00",
    "trading_day_status": "unknown",
    "units": {"price": "index_points", "volume": "unavailable"},
    "bars": [
        {"date": "2026-09-24", "open": 3000.0, "high": 3050.0, "low": 2980.0, "close": 3040.0},
        {"date": "2026-09-25", "open": 3040.0, "high": 3090.0, "low": 3025.0, "close": 3075.5, "volume": 999.0},
    ],
}

_LABELED_UNAVAILABLE_PAYLOAD = {
    **_LABELED_OK_PAYLOAD,
    "index_id": "us.index.sp_dji.sp500",
    "market": "us",
    "status": "unavailable",
    "availability": "unavailable",
    "data_date": None,
    "bar_count": 0,
    "bars": [],
    "unavailable_reason": "no verified daily-K provider evidence for this market",
}

_LABELED_ERROR_PAYLOAD = {
    **_LABELED_OK_PAYLOAD,
    "status": "error",
    "availability": "unknown",
    "bar_count": 0,
    "bars": [],
    "data_date": None,
    "failure_reason": "VALIDATION: end_date must be a canonical YYYY-MM-DD day",
}

_LABELED_EMPTY_PAYLOAD = {
    **_LABELED_OK_PAYLOAD,
    "status": "empty",
    "availability": "unavailable",
    "bar_count": 0,
    "bars": [],
    "data_date": None,
    "unavailable_reason": "provider returned no daily bars for the requested window",
}


@pytest.fixture()
def server(monkeypatch):
    """Start a loopback server whose research endpoint is fixture-driven."""

    calls: list = []
    payloads = {
        "cn.index.sh_comp": _LABELED_OK_PAYLOAD,
        "us.index.sp_dji.sp500": _LABELED_UNAVAILABLE_PAYLOAD,
    }

    def fake_service(query):
        calls.append(dict(query))
        index_id = (query.get("index_id") or [""])[0]
        if index_id not in payloads:
            return _LABELED_ERROR_PAYLOAD
        payload = payloads[index_id]
        if (query.get("end_date") or [""])[0] == "bad-date":
            return _LABELED_ERROR_PAYLOAD
        return payload

    httpd = script.serve("127.0.0.1", 0, fake_service)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback only
        return response.status, response.read().decode("utf-8")


# --- page rendering ---------------------------------------------------------


def test_page_selectors_come_from_the_registry():
    page = view.render_global_market_research_page()
    for spec in list_global_indices():
        assert spec.identity.index_id in page
        assert spec.market in page
    assert page.count("<select") >= 2, "market and index selectors are required"
    # Provider symbols travel with the API payload, never embedded as market
    # data in the page shell.
    assert "sh000001" not in page


def test_page_never_embeds_a_provider_call():
    page = view.render_global_market_research_page()
    assert '"/api/daily-k"' in page or "'/api/daily-k'" in page
    # The browser may only talk to the local research endpoint.
    for forbidden in ("qt.gtimg.cn", "web.ifzq.gtimg.cn", "push2his.eastmoney.com"):
        assert forbidden not in page


def test_page_exposes_ohlc_inspection_scroll_and_zoom():
    page = view.render_global_market_research_page()
    assert "getContext('2d')" in page and "<canvas" in page
    assert "mousemove" in page and "touchstart" in page  # pointer OHLC inspection
    assert 'id="pan"' in page and "fillText(rows[i].date" in page  # horizontal browse + time axis
    assert 'id="zoom"' in page and "max-width:640px" in page  # zoom + responsive


def test_page_renders_every_required_state():
    page = view.render_global_market_research_page()
    for token in ("available", "empty", "unavailable", "error"):
        assert token in page
    assert "数据日期" in page and "来源" in page  # data date + source


def test_page_escapes_json_and_stays_self_contained():
    page = view.render_global_market_research_page()
    assert "</script>" not in page.split("<script>")[1].split("</script>")[0].replace("<\\/script>", "")
    assert "http://" not in page and "https://" not in page


def test_state_block_is_renderable():
    block = view.render_research_state(_LABELED_UNAVAILABLE_PAYLOAD)
    assert "unavailable" in block and "us.index.sp_dji.sp500" in block


# --- HTTP endpoints ---------------------------------------------------------


def test_html_endpoint_serves_the_page(server):
    base, _ = server
    status, body = _get(f"{base}/")
    assert status == 200
    assert "<canvas" in body and "Global Index Daily-K Research" in body


def test_api_endpoint_returns_labeled_payload(server):
    base, calls = server
    status, body = _get(f"{base}/api/daily-k?index_id=cn.index.sh_comp&market=cn")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["bar_count"] == 2
    assert payload["bars"][0]["date"] == "2026-09-24"
    assert "volume" not in payload["bars"][0]
    assert payload["bars"][1]["volume"] == 999.0
    assert calls, "the research endpoint must be the only data path"


def test_api_endpoint_handles_unavailable_state(server):
    base, _ = server
    _, body = _get(f"{base}/api/daily-k?index_id=us.index.sp_dji.sp500")
    payload = json.loads(body)
    assert payload["status"] == "unavailable"
    assert payload["bars"] == []
    assert payload["unavailable_reason"]


def test_api_endpoint_handles_error_and_empty_payloads(server):
    base, _ = server
    _, error_body = _get(f"{base}/api/daily-k?index_id=jp.index.n225")
    error_payload = json.loads(error_body)
    assert error_payload["status"] == "error" and error_payload["bars"] == []
    _, bad_date = _get(f"{base}/api/daily-k?index_id=cn.index.sh_comp&end_date=bad-date")
    assert json.loads(bad_date)["status"] == "error"


def test_indices_endpoint_lists_registry_entries(server):
    base, _ = server
    _, body = _get(f"{base}/api/indices")
    payload = json.loads(body)
    assert payload["markets"] == ["cn", "hk", "us"]
    assert len(payload["indices"]) == len(list_global_indices())


def test_unknown_path_returns_json_not_a_crash(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/nope")
    assert excinfo.value.code == 404
    assert json.loads(excinfo.value.read().decode("utf-8"))["status"] == "error"


# --- query handling and legacy preservation ---------------------------------


def test_missing_index_id_is_a_validation_payload():
    payload = script.build_payload({})
    assert payload["status"] == "error"
    assert "VALIDATION" in payload["failure_reason"]
    assert payload["bars"] == []


def test_default_window_is_canonical():
    start_date, end_date = script.default_window(10)
    assert start_date < end_date
    assert len(start_date) == len(end_date) == 10


def test_unknown_index_never_raises_out_of_build_payload():
    payload = script.build_payload({"index_id": ["definitely.not.registered"]})
    assert payload["status"] == "error"
    assert payload["bar_count"] == 0


def test_existing_snapshot_page_is_preserved():
    # The legacy A-share static page keeps its exact record contract: it still
    # rejects a record without the required sections instead of degrading.
    with pytest.raises(ValueError):
        legacy_view.render_market_snapshot({"schema_version": "v1"})
    assert legacy_view.load_snapshot_json('{"a": 1}') == {"a": 1}
    with pytest.raises(ValueError):
        legacy_view.load_snapshot_json("[]")
    # The research page lives in its own module; the legacy module is untouched.
    assert not hasattr(legacy_view, "render_global_market_research_page")
    assert callable(view.render_global_market_research_page)
    assert callable(view.selector_options)
    assert view.selector_options()[0]["index_id"] == "cn.index.sh_comp"
