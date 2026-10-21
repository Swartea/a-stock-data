"""Tests for the Swartea global market research terminal and its HTTP endpoints.

Everything here is offline. The HTTP handler is exercised with an injected
research callable (``fixture isolation``) so no provider and no network is
touched, and the existing A-share static snapshot page is asserted to still
render exactly as before.

The renderer tests focus on the new product structure (identity, four live
navigation sections, three-column layout, tabbed history, canvas geometry) and
on the absence of hardcoded market quotes in the page shell.
"""

from __future__ import annotations

import html
import importlib.util
import json
import re
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
        {"date": "2026-09-25", "open": 3040.0, "high": 3090.0, "low": 3025.0, "close": 3075.5,
         "volume": 999.0},
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


def _options() -> list[dict[str, str]]:
    return view.selector_options()


def _shell() -> str:
    return view.render_global_market_research_page()


# --- product identity and navigation --------------------------------------


def test_page_is_the_swartea_chinese_first_research_terminal():
    page = _shell()
    assert "<title>Swartea Market Research</title>" in page
    assert "斯沃特" in page
    assert '<html lang="zh-CN">' in page
    # The previous English shell identity is gone.
    assert "Global Index Daily-K Research" not in page
    # Dark, terminal-style surface.
    assert "color-scheme:dark" in page and "--bg:#0b0e13" in page


def _nav_html() -> str:
    """Return the top-bar navigation markup of the rendered workbench."""

    page = _shell()
    assert '<nav class="nav"' in page, "the workbench must ship a top navigation"
    return page.split('<nav class="nav"')[1].split("</nav>")[0]


def test_top_bar_has_four_live_sections_and_no_inert_planning_item():
    nav = _nav_html()
    # Exactly one entry is active: the overview is the default homepage.
    assert nav.count('class="nav-item is-active"') == 1
    assert 'class="nav-item is-active" data-nav="overview"' in nav
    # Every entry is a real, live section of the workbench.
    for key, label in (
        ("overview", "市场总览"),
        ("research", "指数研究"),
        ("compare", "市场比较"),
        ("watchlist", "自选关注"),
    ):
        assert f'data-nav="{key}"' in nav
        assert f">{label}</button>" in nav
    # Nothing is a placeholder any more: no inert "规划中" label, no dead link.
    assert "规划中" not in nav
    assert "<a " not in nav and "href" not in nav
    assert nav.count('type="button"') == 4


def test_no_navigation_item_points_at_an_unbuilt_route():
    page = _shell()
    nav = _nav_html()
    assert "<a " not in nav and "href" not in nav
    # Every navigation entry resolves to a section panel that really exists.
    keys = re.findall(r'data-nav="([^"]+)"', nav)
    assert keys == ["overview", "research", "compare", "watchlist"]
    for key in keys:
        assert f'id="section-{key}" data-section="{key}"' in page


# --- registry-driven data, no hardcoded quotes ----------------------------


def test_page_selectors_come_from_the_registry():
    page = _shell()
    for spec in list_global_indices():
        assert spec.identity.index_id in page
        assert spec.market in page
    assert page.count("<select") >= 2, "market and index selectors are required"
    for option in _options():
        assert option["name"] in page or option["index_id"] in page


def test_page_never_embeds_a_provider_call():
    page = _shell()
    assert '"/api/daily-k"' in page or "'/api/daily-k'" in page
    for forbidden in ("qt.gtimg.cn", "web.ifzq.gtimg.cn", "push2his.eastmoney.com"):
        assert forbidden not in page


def test_page_embeds_no_hardcoded_market_quote():
    page = _shell()
    # Provider/publisher codes only ever arrive through the API payload.
    assert "sh000001" not in page
    # No numeric literal that would read as a price, index point or OHLC value
    # in the shell: bar coordinates are computed at runtime from the payload.
    body = page.split("<style>")[0] + page.split("</style>")[1].split("<script>")[0]
    # The registered display names legitimately contain digits (沪深300, S&P 500);
    # they are index names, not quotes, so they are removed before the scan
    # (both raw and HTML-escaped, because the page escapes them).
    for spec in list_global_indices():
        body = body.replace(spec.name, "").replace(html.escape(spec.name), "")
    for match in re.finditer(r"(?<![a-zA-Z_])[3-9]\d{2,}(?:\.\d+)?(?![a-zA-Z_])", body):
        raise AssertionError(f"possible hardcoded quote in page shell: {match.group(0)}")


def test_page_escapes_json_and_stays_self_contained():
    page = _shell()
    assert "</script>" not in page.split("<script>")[1].split("</script>")[0].replace("<\\/script>", "")
    assert "http://" not in page and "https://" not in page


# --- index overview strip and quote framing --------------------------------


def test_overview_strip_lists_registry_indices_without_quotes():
    page = _shell()
    assert 'class="panel overview"' in page and 'id="strip"' in page
    assert "renderOverviewQuote" in page and "cachedPayload(requestFor(opt))" in page
    assert "const AVAIL" in page and "已验证" in page and "未验证" in page
    assert "OPTS.forEach" in page and "OPTS.filter(o => o.market === m)" in page
    assert "data-field=\"close\"" in page and "data-field=\"date\"" in page
    assert "function pumpRequests()" in page and "activeRequests < 3" in page
    # The overview values are fetched from the same local API and shared cache
    # as the selected chart; no literal quote is embedded in the page shell.
    assert "payloadCache.has(key)" in page and "API + '?' + key" in page


def test_numbers_are_framed_as_latest_daily_close_not_realtime():
    page = _shell()
    assert "最新日线收盘" in page
    assert "非实时行情" in page
    for forbidden in ("实时价", "实时行情价", "实时报价"):
        assert forbidden not in page


def test_percentage_change_requires_two_adjacent_closes_and_labels_its_basis():
    page = _shell()
    assert "rows.length >= 2" in page
    # The percentage only exists when two valid adjacent closes are available.
    assert "change = summary && summary.changePct !== null" in page
    assert "? {pct: summary.changePct, prevDate: summary.prevDate" in page
    # Basis and dates are always shown together with the percentage.
    assert "涨跌幅基于相邻两日收盘" in page
    assert "esc(change.prevDate)" in page and "esc(lastRow.date)" in page
    # A single bar says so instead of inventing a change.
    assert "仅有一根日线" in page


# --- three-column layout and responsive collapse ---------------------------


def test_desktop_layout_is_three_columns_and_collapses_at_target_widths():
    page = _shell()
    assert "grid-template-columns:264px minmax(0,1fr) 300px" in page
    for col in ("col-nav", "col-chart", "col-info"):
        assert col in page
    assert "@media (max-width:1280px)" in page
    assert "@media (max-width:768px)" in page
    assert "@media (max-width:390px)" in page
    # The nav/chart/info order stays source order, so collapse is a stack.
    body = page.split("<main>")[1]
    assert body.index('class="panel col-nav"') < body.index('class="panel col-chart"')
    assert body.index('class="panel col-chart"') < body.index('class="panel col-info"')


def test_status_is_chinese_and_canonical_fields_are_disclosed():
    page = _shell()
    assert "数据状态" in page and "数据日期" in page and "来源" in page
    assert "可用性" in page and "新鲜度" in page and "交易日状态" in page
    # Provider / internal fields live behind a details disclosure.
    assert "<details>" in page and "规范字段" in page
    assert "provider_symbol" in page and "local_code" in page and "evaluated_at" in page


# --- tabbed history -------------------------------------------------------


def test_history_is_a_tabbed_lower_section_with_a_scroll_region():
    page = _shell()
    assert 'class="tabs"' in page
    assert 'data-tab="daily"' in page and 'data-tab="about"' in page
    assert 'id="panel-daily"' in page and 'id="panel-about"' in page
    assert ".tabpanel[hidden]{display:none}" in page
    # The OHLC table lives in the lower tabbed section, not the initial viewport.
    head = page.split("<main>")[1].split('<section class="panel history">')[0]
    assert "<table>" not in head
    assert 'class="scroll"' in page and "max-height:260px" in page
    assert "position:sticky" in page  # scrollable table keeps its header


def test_volume_column_is_preserved_only_when_present():
    page = _shell()
    assert "const showVol = bars.some(b => b.volume != null);" in page
    assert "(showVol ? '<th>成交量</th>' : '')" in page


# --- canvas chart ---------------------------------------------------------


def test_chart_uses_a_canvas_and_offers_explicit_zoom_and_pan():
    page = _shell()
    assert "getContext('2d')" in page and "<canvas" in page
    assert 'id="zoom"' in page and 'id="pan"' in page
    assert 'id="prev"' in page and 'id="next"' in page
    assert "const SPANS = " in page


def test_sparse_bars_use_the_available_plot_width():
    page = _shell()
    # Slot width is derived from the wrap width and the visible bar count, so a
    # handful of bars spreads across the whole plot instead of clumping left.
    assert "const plotW = wrap.clientWidth || 640;" in page
    assert "const view = Math.min(visible, bars.length);" in page
    assert "const slot = Math.max(3, Math.floor(plotW / Math.max(1, view)));" in page
    assert "const cx = i * m.slot + m.slot / 2;" in page
    # Bars are never stretched to fill the plot.
    assert "Math.min(m.slot - 2, 22)" in page


def test_bar_order_and_date_mapping_are_exact():
    page = _shell()
    assert "const rows = bars.slice(m.from, m.from + m.view);" in page
    assert "m.g.fillText(rows[i].date" in page
    assert "Math.floor((src.clientX - rect.left) / m.slot)" in page
    assert "state.hover = Math.max(m.from, Math.min(m.from + m.view - 1" in page


def test_hover_reads_ohlc_from_the_hovered_row():
    page = _shell()
    assert "const b = rows[local];" in page
    for field in ("b.date", "b.open", "b.high", "b.low", "b.close", "b.volume"):
        assert field in page
    assert "mousemove" in page and "touchstart" in page and "mouseleave" in page


def test_resize_redraws_and_zero_or_one_bars_are_handled():
    page = _shell()
    assert "window.addEventListener('resize'" in page
    assert "ResizeObserver" in page
    assert "if (!rows.length) {" in page  # zero bars: no fabricated drawing
    assert "if (hi === lo) { hi = hi + 1; lo = lo - 1; }" in page  # one bar / flat range
    assert "Math.max(1, state.span || bars.length || 1)" in page  # never divide by zero


def test_stale_or_failed_request_never_shows_the_previous_index():
    page = _shell()
    assert "const seq = ++state.seq;" in page
    assert "if (seq !== state.seq) return;" in page
    assert "cachedPayload(query())" in page
    # The view and canvas are cleared before every request, so no stale bars linger.
    assert "function clearView()" in page
    assert "state.payload = null;" in page
    assert "state.from = 0;\n  draw();" in page


# --- states and Chinese value translation ---------------------------------


def test_page_renders_every_required_state():
    page = _shell()
    for token in ("加载中", "数据正常", "无数据", "数据不可用", "请求失败"):
        assert token in page
    assert 'class="state loading"' in page
    assert "$('#empty').hidden = p.status !== 'empty';" in page


def test_unavailable_and_failed_states_render_a_reason():
    page = _shell()
    assert "p.unavailable_reason || p.failure_reason" in page
    assert "研究服务不可用" in page
    assert "setState('error', STATUS.error);" in page


def test_standard_availability_freshness_and_trading_values_are_chinese():
    page = _shell()
    assert "const AVAIL = {available: '可用', delayed: '延迟行情', unavailable: '不可用'" in page
    assert "const FRESH = {fresh: '新鲜', stale: '已过期'" in page
    assert "open: '开市日', closed: '休市日'" in page
    assert "const label = (map, v) =>" in page


def test_unknown_is_never_rendered_as_normal():
    page = _shell()
    assert "unknown: '未知'" in page
    assert "未知（无交易日历证据）" in page
    assert "'未知（'" in page  # unmapped values stay unknown, never "正常"
    assert "const tone = v =>" in page and "'unknown'" in page
    # The unknown class is not the ok/normal styling.
    assert ".state.unknown{color:var(--warn)" in page
    assert ".state.ok{color:var(--ok)" in page
    # Info rows carrying an unknown value are flagged in the panel too, not just
    # on the status pill.
    assert ".kv dd.unknown{color:var(--warn)}" in page


def test_provider_status_is_translated_and_kept_canonical_in_the_disclosure():
    page = _shell()
    # The readable Chinese state is shown in the information panel...
    assert "const PROVIDER = {ok: '正常', error: '异常', empty: '无数据'" in page
    assert "['数据源状态', esc(label(PROVIDER, p.provider_status)), tone(p.provider_status)]" in page
    # ...while the raw canonical value stays inside the details disclosure.
    raw_block = page.split("$('#raw').innerHTML = [")[1].split("].map")[0]
    assert "['provider_status', p.provider_status]" in raw_block
    assert "数据源状态" not in raw_block


def test_red_up_green_down_matches_close_versus_open():
    page = _shell()
    assert "const UP = '#f2564d';" in page  # 红涨
    assert "const DOWN = '#39b87a';" in page  # 绿跌
    assert "const up = c >= anchor;" in page  # candle meaning: close vs open
    assert "收盘 ≥ 开盘（红涨）" in page and "收盘 &lt; 开盘（绿跌）" in page


def test_state_block_is_renderable():
    block = view.render_research_state(_LABELED_UNAVAILABLE_PAYLOAD)
    assert "unavailable" in block and "us.index.sp_dji.sp500" in block


def test_navigation_metadata_is_part_of_the_module_contract():
    assert [item["key"] for item in view.NAV_ITEMS] == [
        "overview", "research", "compare", "watchlist"
    ]
    # All four entries are live sections: nothing is a planning placeholder.
    assert all(item["state"] == "ready" for item in view.NAV_ITEMS)
    assert [section["target"] for section in view.SECTIONS] == [
        "section-overview", "section-research", "section-compare", "section-watchlist"
    ]
    assert view.PRODUCT_NAME == "Swartea Market Research"
    assert view.DEFAULT_API_PATH == "/api/daily-k"
    assert set(view.STATUS_LABELS) == {"ok", "empty", "unavailable", "error"}


def test_page_renders_with_explicit_options_and_custom_window():
    page = view.render_global_market_research_page(
        [{"index_id": "cn.index.sh_comp", "market": "cn", "name": "上证指数",
          "currency": "CNY", "timezone": "Asia/Shanghai", "proven": "yes"}],
        start_date="2026-09-01",
        end_date="2026-09-30",
        api_path="/api/custom",
    )
    assert 'value="2026-09-01"' in page and 'value="2026-09-30"' in page
    assert '"/api/custom"' in page
    assert "us.index.sp_dji.djia" not in page


# --- HTTP endpoints --------------------------------------------------------


def test_html_endpoint_serves_the_page(server):
    base, _ = server
    status, body = _get(f"{base}/")
    assert status == 200
    assert "<canvas" in body and "Swartea Market Research" in body
    # The four workbench entries are served as live sections, not placeholders.
    for key in ("overview", "research", "compare", "watchlist"):
        assert f'data-nav="{key}"' in body
    assert "规划中" not in body


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
    # The research terminal lives in its own module; the legacy module is untouched.
    assert not hasattr(legacy_view, "render_global_market_research_page")
    assert callable(view.render_global_market_research_page)
    assert callable(view.selector_options)
    assert view.selector_options()[0]["index_id"] == "cn.index.sh_comp"


def test_comparison_endpoint_reuses_payloads_without_provider_calls(server):
    base, calls = server
    payloads = [dict(_LABELED_OK_PAYLOAD),
                {**_LABELED_OK_PAYLOAD, "index_id": "hk.index.hang_seng.hstech"}]
    before = len(calls)
    request = urllib.request.Request(
        base + "/api/compare", data=json.dumps({"payloads": payloads}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request) as response:
        result = json.load(response)
    assert result["status"] == "ok"
    assert result["base_date"] == "2026-09-24"
    assert len(result["series"]) == 2
    assert all(s["normalized100"][0] == 100 for s in result["series"])
    assert len(calls) == before


@pytest.mark.parametrize("body", [b"broken", b"[]", b"", b'{"payloads":NaN}'])
def test_comparison_endpoint_handles_invalid_requests(server, body):
    base, _ = server
    request = urllib.request.Request(base + "/api/compare", data=body, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        assert error.code == 400
        result = json.load(error)
    assert result["status"] == "error"
