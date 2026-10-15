"""Render the Swartee global market research terminal (Chinese-first, dark).

This module is **additive and separate** from
:mod:`analysis.research.market_snapshot_view`: the existing A-share static
snapshot page and its record contract are untouched and stay in their own file.

The page shell is a single-screen research terminal:

* a compact top bar carrying the product identity, the one real page (全球市场)
  and the clearly-marked planning items (A股研究 / 市场发现 / AI研究) — planning
  items are plain labels, never links, so there is no dead route to click;
* an overview strip plus navigation built from the canonical registry
  (``list_global_indices``) metadata only;
* a three-column desktop layout (市场与指数导航 / 主图 / 市场信息) that collapses
  at 1280 / 768 / 390 px;
* a tabbed lower section for history, so the full OHLC table never occupies the
  initial viewport.

Every price number is fetched at runtime through the single research service
endpoint, so the browser never calls a provider and no market data is hardcoded
here. The UI describes its numbers as 最新日线收盘 (latest daily close), never as
real-time quotes; a percentage change is shown only when it is derivable from two
adjacent returned closes, and always together with its basis and date.

Rendered states: ``loading`` / ``ok`` / ``empty`` / ``unavailable`` / ``error``.
Standard availability / freshness / trading-day values are translated into
readable Chinese, and an ``unknown`` value is never presented as a normal one.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_API_PATH = "/api/daily-k"

PRODUCT_NAME = "Swartee Market Research"
PRODUCT_SUBTITLE = "斯沃尔蒂 · 全球市场研究终端"

#: Navigation labels: the first entry is the live page, the rest are planning
#: items rendered as inert labels (never links) so there is no dead route.
NAV_ITEMS: tuple[Mapping[str, str], ...] = (
    {"key": "global", "label": "全球市场", "state": "active"},
    {"key": "cn_equity", "label": "A股研究", "state": "planning"},
    {"key": "discovery", "label": "市场发现", "state": "planning"},
    {"key": "ai", "label": "AI研究", "state": "planning"},
)

STATUS_LABELS: Mapping[str, str] = {
    "ok": "数据正常 / available",
    "empty": "无数据 / empty",
    "unavailable": "不可用 / unavailable",
    "error": "错误 / error",
}


def _text(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return html.escape(fallback, quote=True)
    return html.escape(str(value), quote=True)


_STYLE = """
:root{color-scheme:dark;--bg:#0b0e13;--panel:#131822;--panel-2:#0f141d;--fg:#e6e9f0;
--muted:#8b97a8;--line:#242c3a;--accent:#4c9ffe;--ok:#5fd08a;--warn:#f2b04c;--bad:#f2777a;
--up:#f2564d;--down:#39b87a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
button,select,input{font:inherit;color:var(--fg);background:var(--panel);
border:1px solid var(--line);border-radius:6px;min-height:32px;padding:5px 9px}
button{cursor:pointer}
button:hover{border-color:var(--accent)}
h1,h2,h3{margin:0}
.muted{color:var(--muted)}
.up{color:var(--up)}
.down{color:var(--down)}

/* --- top bar --------------------------------------------------------- */
.topbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;
padding:8px 14px;background:var(--panel-2);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:baseline;gap:8px}
.brand b{font-size:15px;letter-spacing:.2px}
.brand span{font-size:11px;color:var(--muted)}
.nav{display:flex;flex-wrap:wrap;gap:6px;margin-left:auto}
.nav-item{display:inline-flex;align-items:center;gap:5px;font-size:12px;
padding:4px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.nav-item.is-active{color:var(--fg);border-color:var(--accent);background:#16233a}
.nav-item.is-planning{color:#6d7787;border-style:dashed;cursor:not-allowed}
.badge{font-size:10px;padding:1px 5px;border-radius:4px;background:#1d2534;color:#7d8798}
.scope{width:100%;font-size:11px;color:var(--muted)}
.overview{margin:10px 14px 0}
.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.overview-market{min-width:0}
.overview-market h3{font-size:11px;color:var(--muted);font-weight:500;margin:0 0 6px}
.chips{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
.chip{display:flex;flex-direction:column;align-items:flex-start;gap:2px;min-width:0;
padding:7px 8px;border:1px solid var(--line);border-radius:7px;background:var(--panel-2);
text-align:left;overflow:hidden}
.chip strong{max-width:100%;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip .chip-quote{font-size:14px;font-variant-numeric:tabular-nums;font-weight:600}
.chip .chip-meta{font-size:10px;color:var(--muted)}
.chip.is-selected{border-color:var(--accent);background:#16233a}
.chip.is-unproven{border-style:dashed}
.chip.is-unavailable .chip-quote{color:var(--warn)}
.chip .unknown{color:var(--warn)}

/* --- layout ---------------------------------------------------------- */
main{padding:12px 14px 18px;display:grid;gap:12px;
grid-template-columns:264px minmax(0,1fr) 300px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.panel-h{display:flex;align-items:center;justify-content:space-between;gap:8px;
margin:0 0 9px;font-size:13px;font-weight:600}
.panel-h small{font-weight:400;font-size:11px;color:var(--muted)}

/* --- overview strip + navigation ------------------------------------- */
.field{display:grid;gap:4px;margin-bottom:9px}
.field label{font-size:11px;color:var(--muted)}
.field select,.field input{width:100%}

/* --- chart ----------------------------------------------------------- */
.chartwrap{overflow-x:auto;overflow-y:hidden;border:1px solid var(--line);
border-radius:8px;background:#0a0d13}
canvas{display:block;height:300px;cursor:crosshair;touch-action:pan-x}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:9px}
.controls label{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:6px}
.controls input[type=range]{padding:0;min-height:auto;width:150px}
.probe{margin-top:8px;font-size:12px;color:var(--muted);min-height:18px;
font-variant-numeric:tabular-nums}
.legend{display:flex;gap:12px;font-size:11px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}
.legend .up-bg{background:var(--up)}
.legend .down-bg{background:var(--down)}

/* --- status + info --------------------------------------------------- */
.state{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
padding:3px 9px;border-radius:999px;border:1px solid var(--line)}
.state.ok{color:var(--ok);border-color:#245c40}
.state.empty{color:var(--warn);border-color:#6b5220}
.state.unavailable,.state.error{color:var(--bad);border-color:#6d2b2c}
.state.loading{color:var(--accent);border-color:#274a72}
.state.unknown{color:var(--warn);border-color:#6b5220}
.kv dd.unknown{color:var(--warn)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:5px 10px;font-size:12px;margin-top:9px}
.kv dt{color:var(--muted);white-space:nowrap}
.kv dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;word-break:break-all}
.price{font-size:22px;font-variant-numeric:tabular-nums;font-weight:600}
.reason{margin-top:8px;font-size:12px;color:var(--muted);white-space:pre-wrap}
details{margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
summary{cursor:pointer;font-size:12px;color:var(--muted)}

/* --- tabbed history -------------------------------------------------- */
.history{padding:0}
.tabs{display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px 0}
.tab{font-size:12px;padding:4px 11px;border-radius:6px 6px 0 0}
.tab.is-active{border-color:var(--accent);color:#cfe3ff;background:#16233a}
.tabpanel{padding:10px 12px 12px}
.tabpanel[hidden]{display:none}
.scroll{max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:12px}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--panel);color:var(--muted);font-weight:600;text-align:right}
th:first-child,td:first-child{text-align:left}

/* --- responsive ------------------------------------------------------ */
@media (max-width:1280px){
main{grid-template-columns:232px minmax(0,1fr)}
.col-info{grid-column:1 / -1}
.col-info .kv{grid-template-columns:auto auto 1fr}
}
@media (max-width:768px){
main{grid-template-columns:minmax(0,1fr);padding:10px}
.overview{margin:8px 10px 0}
canvas{height:240px}
.controls input[type=range]{width:100%}
.col-info .kv{grid-template-columns:auto 1fr}
}
@media (max-width:390px){
.topbar{gap:6px 10px;padding:8px 10px}
.nav{margin-left:0;width:100%}
.overview-grid{grid-template-columns:minmax(0,1fr)}
.chips{grid-template-columns:repeat(2,minmax(0,1fr))}
.price{font-size:19px}
canvas{height:200px}
}
"""

_JS = r"""
const OPTS = window.__OPTS || [];
const API = window.__API || '/api/daily-k';
const UP = '#f2564d';      // 中国习惯：红涨
const DOWN = '#39b87a';    // 绿跌
const MARKET = {cn: '中国内地', hk: '中国香港', us: '美国', jp: '日本'};
const AVAIL = {available: '可用', delayed: '延迟行情', unavailable: '不可用', unknown: '未知'};
const FRESH = {fresh: '新鲜', stale: '已过期', unknown: '未知'};
const TRADING = {open: '开市日', closed: '休市日', unknown: '未知（无交易日历证据）'};
const PROVIDER = {ok: '正常', error: '异常', empty: '无数据', unavailable: '不可用', unknown: '未知'};
const STATUS = {
  loading: '加载中', ok: '数据正常', empty: '无数据',
  unavailable: '数据不可用', error: '请求失败'
};
const SPANS = [20, 40, 60, 120, 250, 0];

const state = {payload: null, seq: 0, hover: null, from: 0, span: 120};
const payloadCache = new Map();
const requestQueue = [];
let activeRequests = 0;
const $ = s => document.querySelector(s);
const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g,
  ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
const num = v => (typeof v === 'number' && isFinite(v)) ? v : null;
const fmt = (v, d) => {
  const n = num(v);
  if (n === null) return '—';
  return n.toLocaleString('zh-CN', {minimumFractionDigits: d == null ? 2 : d,
    maximumFractionDigits: d == null ? 2 : d});
};
const label = (map, v) => {
  const k = v == null || v === '' ? 'unknown' : String(v);
  return map[k] || ('未知（' + esc(k) + '）');
};
const tone = v => (v === 'unknown' || v == null || v === '' ? 'unknown' : '');
const marketName = m => MARKET[m] || String(m || '').toUpperCase();

function setState(kind, text) {
  const el = $('#state');
  el.className = 'state ' + kind;
  el.textContent = text;
}

/* --- navigation / overview strip ------------------------------------- */
function renderOptions() {
  const markets = [];
  OPTS.forEach(o => { if (!markets.includes(o.market)) markets.push(o.market); });
  $('#market').innerHTML = markets
    .map(m => '<option value="' + esc(m) + '">' + esc(marketName(m)) + ' · ' + esc(String(m).toUpperCase()) + '</option>')
    .join('');
  renderIndices();
  $('#strip').innerHTML = '<div class="overview-grid">' + markets.map(m => {
    const items = OPTS.filter(o => o.market === m);
    return '<section class="overview-market" data-market="' + esc(m) + '"><h3>'
      + esc(marketName(m)) + ' · ' + items.length + ' 个指数</h3>'
      + '<div class="chips">' + items.map(o =>
        '<button type="button" class="chip' + (o.proven === 'yes' ? '' : ' is-unproven') +
        '" data-index="' + esc(o.index_id) + '" title="' + esc(o.index_id) + ' · ' +
        esc(o.currency) + ' · ' + esc(o.timezone) + '"><strong>' + esc(o.name) + '</strong>'
        + '<span class="chip-meta">' + (o.proven === 'yes' ? '已验证数据源' : '未验证数据源') + '</span>'
        + '<span class="chip-quote" data-field="quote">读取中…</span>'
        + '<span class="chip-change muted" data-field="change">最新日K收盘 · 非实时</span>'
        + '<span class="chip-meta" data-field="date">等待研究服务</span></button>').join('')
      + '</div></section>';
  }).join('') + '</div>';
  $('#strip').querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const opt = OPTS.find(o => o.index_id === chip.dataset.index);
      if (!opt) return;
      $('#market').value = opt.market;
      renderIndices(opt.index_id);
      load();
    });
  });
}

function renderIndices(selected) {
  const m = $('#market').value;
  $('#index').innerHTML = OPTS.filter(o => o.market === m).map(o =>
    '<option value="' + esc(o.index_id) + '">' + esc(o.name)
    + (o.proven === 'yes' ? '' : '（未验证）') + '</option>').join('');
  if (selected) $('#index').value = selected;
  markChip();
}

function markChip() {
  const id = $('#index').value;
  $('#strip').querySelectorAll('.chip').forEach(c =>
    c.classList.toggle('is-selected', c.dataset.index === id));
}

/* --- status + information panel --------------------------------------- */
function renderInfo(p) {
  const bars = p.bars || [];
  $('#head').innerHTML = '<div class="price">' + esc(p.name || '未选择指数') + '</div>'
    + '<div class="muted" style="font-size:12px">' + esc(p.index_id) + ' · '
    + esc(marketName(p.market)) + ' · ' + esc(p.currency) + ' · ' + esc(p.timezone) + '</div>'
    + '<div class="muted" style="font-size:11px">最新日线收盘（非实时行情）</div>';
  setState(p.status || 'error', STATUS[p.status] || '未知状态');

  const rows = bars.filter(b => b && b.date);
  let change = null;
  if (rows.length >= 2) {
    const last = num(rows[rows.length - 1].close);
    const prev = num(rows[rows.length - 2].close);
    const prevDate = rows[rows.length - 2].date;
    if (last !== null && prev !== null && prev !== 0) {
      change = {pct: (last - prev) / Math.abs(prev) * 100, prevDate: prevDate, prev: prev};
    }
  }
  const closeEl = $('#close');
  const lastRow = rows.length ? rows[rows.length - 1] : null;
  if (lastRow) {
    closeEl.innerHTML = '<span class="' + (change && change.pct >= 0 ? 'up' : 'down') + '">'
      + fmt(lastRow.close) + '</span>'
      + (change
        ? ' <span class="' + (change.pct >= 0 ? 'up' : 'down') + '" style="font-size:13px">'
          + (change.pct >= 0 ? '+' : '') + change.pct.toFixed(2) + '%</span>'
          + '<div class="muted" style="font-size:11px">涨跌幅基于相邻两日收盘：'
          + esc(change.prevDate) + ' 收盘 ' + fmt(change.prev) + ' → '
          + esc(lastRow.date) + ' 收盘 ' + fmt(lastRow.close) + '</div>'
        : '<div class="muted" style="font-size:11px">仅有一根日线，暂无法计算涨跌幅</div>');
  } else {
    closeEl.innerHTML = '<span class="muted">—</span>';
  }

  $('#kv').innerHTML = [
    ['数据状态', esc(STATUS[p.status] || '未知状态'), ''],
    ['数据日期', esc(p.data_date), ''],
    ['可用性', esc(label(AVAIL, p.availability)), tone(p.availability)],
    ['新鲜度', esc(label(FRESH, p.freshness)), tone(p.freshness)],
    ['交易日状态', esc(label(TRADING, p.trading_day_status)), tone(p.trading_day_status)],
    ['数据源状态', esc(label(PROVIDER, p.provider_status)), tone(p.provider_status)],
    ['来源', esc(p.source), ''],
    ['日线条数', esc(String(p.bar_count == null ? rows.length : p.bar_count)), ''],
    ['请求窗口', esc((p.start_date || '—') + ' – ' + (p.end_date || '—')), ''],
    ['降级', p.degraded ? '是' : '否', '']
  ].map(r => '<dt>' + r[0] + '</dt><dd class="' + r[2] + '">' + r[1] + '</dd>').join('');

  $('#reason').textContent = p.unavailable_reason || p.failure_reason
    || '数据来自本地研究服务；单位为指数点位，成交量仅在数据源提供时显示。';

  $('#raw').innerHTML = [
    ['index_id', p.index_id], ['market', p.market], ['currency', p.currency],
    ['timezone', p.timezone], ['provider_symbol', p.provider_symbol],
    ['publisher', p.publisher], ['local_code', p.local_code],
    ['provider_status', p.provider_status], ['evaluated_at', p.evaluated_at],
    ['units', p.units && p.units.price], ['status', p.status],
    ['availability', p.availability], ['freshness', p.freshness],
    ['trading_day_status', p.trading_day_status]
  ].map(r => '<dt>' + r[0] + '</dt><dd>' + esc(r[1] == null ? '' : r[1]) + '</dd>').join('');
}

function requestFor(opt) {
  return new URLSearchParams({
    index_id: opt.index_id,
    market: opt.market,
    start_date: $('#start').value,
    end_date: $('#end').value
  });
}

function pumpRequests() {
  while (activeRequests < 3 && requestQueue.length) {
    const item = requestQueue.shift();
    activeRequests += 1;
    fetch(item.url).then(res => {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(payload => item.resolve(payload)).catch(error => {
      payloadCache.delete(item.key);
      item.reject(error);
    }).finally(() => {
      activeRequests -= 1;
      pumpRequests();
    });
  }
}

function cachedPayload(params) {
  const key = params.toString();
  if (payloadCache.has(key)) return payloadCache.get(key);
  const promise = new Promise((resolve, reject) => {
    requestQueue.push({key: key, url: API + '?' + key, resolve: resolve, reject: reject});
  });
  payloadCache.set(key, promise);
  pumpRequests();
  return promise;
}

function renderOverviewQuote(opt, p) {
  const card = Array.from($('#strip').querySelectorAll('.chip'))
    .find(el => el.dataset.index === opt.index_id);
  if (!card) return;
  const rows = (p.bars || []).filter(b => b && b.date);
  const last = rows.length ? rows[rows.length - 1] : null;
  const quote = card.querySelector('[data-field="quote"]');
  const changeEl = card.querySelector('[data-field="change"]');
  const date = card.querySelector('[data-field="date"]');
  const usable = p.status === 'ok' && last && num(last.close) !== null;
  card.classList.toggle('is-unavailable', !usable);
  if (!usable) {
    quote.textContent = p.status === 'unavailable' ? '暂不可用' : '暂无日K收盘';
    changeEl.textContent = label(AVAIL, p.availability) + ' · ' + label(FRESH, p.freshness);
    changeEl.className = 'chip-change ' + tone(p.availability);
    date.textContent = p.data_date ? '数据日期 ' + p.data_date : '无可用数据';
    card.title = p.unavailable_reason || p.failure_reason || opt.index_id;
    return;
  }
  quote.textContent = fmt(last.close) + ' ' + opt.currency;
  date.textContent = '最新日K收盘 · ' + (p.data_date || last.date);
  if (rows.length >= 2 && num(rows[rows.length - 2].close) !== null
      && num(rows[rows.length - 2].close) !== 0) {
    const previous = rows[rows.length - 2];
    const pct = (last.close - previous.close) / Math.abs(previous.close) * 100;
    const trend = pct >= 0 ? 'up' : 'down';
    changeEl.className = 'chip-change ' + trend;
    changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '% · 相邻日收盘';
    card.title = opt.name + ' · ' + previous.date + ' 至 ' + last.date + ' · ' + opt.index_id;
  } else {
    changeEl.className = 'chip-change muted';
    changeEl.textContent = '仅一根日线，暂无涨跌幅';
    card.title = opt.name + ' · ' + last.date + ' · ' + opt.index_id;
  }
}

function refreshOverview() {
  OPTS.forEach(opt => {
    cachedPayload(requestFor(opt)).then(p => renderOverviewQuote(opt, p)).catch(() => {
      const card = Array.from($('#strip').querySelectorAll('.chip'))
        .find(el => el.dataset.index === opt.index_id);
      if (!card) return;
      card.classList.add('is-unavailable');
      card.querySelector('[data-field="quote"]').textContent = '暂不可用';
      card.querySelector('[data-field="change"]').textContent = '研究服务请求失败';
      card.querySelector('[data-field="date"]').textContent = '无法读取日线';
    });
  });
}

/* --- history table ---------------------------------------------------- */
function renderTable(p) {
  const bars = (p.bars || []).filter(b => b && b.date);
  const showVol = bars.some(b => b.volume != null);
  const rows = bars.slice().reverse();
  $('#history').innerHTML = rows.length
    ? '<table><thead><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th>'
      + (showVol ? '<th>成交量</th>' : '') + '</tr></thead><tbody>'
      + rows.map(b => {
        const o = num(b.open), c = num(b.close);
        const cls = (o !== null && c !== null && c < o) ? 'down' : 'up';
        return '<tr><td>' + esc(b.date) + '</td><td>' + fmt(b.open) + '</td><td>' + fmt(b.high)
          + '</td><td>' + fmt(b.low) + '</td><td class="' + cls + '">' + fmt(b.close) + '</td>'
          + (showVol ? '<td>' + (b.volume == null ? '—' : fmt(b.volume, 0)) + '</td>' : '') + '</tr>';
      }).join('') + '</tbody></table>'
    : '<div class="muted" style="padding:8px">本次窗口没有可用的日线数据。</div>';
  $('#count').textContent = rows.length ? '共 ' + rows.length + ' 根日线（滚动查看）' : '';
  $('#empty').hidden = p.status !== 'empty';
  $('#notready').hidden = bars.length > 0;
}

/* --- canvas chart ----------------------------------------------------- */
function metrics() {
  const c = $('#chart'), wrap = $('#chartwrap'), bars = state.payload?.bars || [];
  const visible = Math.max(1, state.span || bars.length || 1);
  const plotW = wrap.clientWidth || 640;
  const view = Math.min(visible, bars.length);
  // Sparse data spreads over the whole plot width; dense data scrolls by slot.
  const slot = Math.max(3, Math.floor(plotW / Math.max(1, view)));
  const width = Math.max(plotW, slot * view);
  const height = c.clientHeight || 300;
  c.style.width = width + 'px';
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.round(width * dpr);
  c.height = Math.round(height * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, width, height);
  const from = Math.max(0, Math.min(bars.length - view, state.from));
  return {c, g, slot, width, height, view, from, total: bars.length};
}

function draw() {
  const m = metrics(), bars = state.payload?.bars || [];
  state.from = m.from;
  const rows = bars.slice(m.from, m.from + m.view);
  const pan = $('#pan');
  pan.max = String(Math.max(0, m.total - m.view));
  pan.value = String(m.from);
  pan.disabled = m.total <= m.view;
  $('#viewport').textContent = m.total ? ('显示 ' + (m.from + 1) + '-' + (m.from + m.view)
    + ' / ' + m.total + ' 根') : '';
  if (!rows.length) {
    m.g.fillStyle = '#8b97a8';
    m.g.font = '12px system-ui';
    m.g.textAlign = 'center';
    m.g.fillText('暂无可绘制的数据', m.width / 2, m.height / 2);
    m.g.textAlign = 'left';
    return;
  }
  const top = 12, bottom = 22, plotH = Math.max(40, m.height - top - bottom);
  const vals = rows.map(b => [num(b.high), num(b.low)]).filter(v => v[0] !== null && v[1] !== null);
  let hi = vals.length ? Math.max.apply(null, vals.map(v => v[0])) : 0;
  let lo = vals.length ? Math.min.apply(null, vals.map(v => v[1])) : 0;
  if (!isFinite(hi) || !isFinite(lo)) { hi = 0; lo = 0; }
  if (hi === lo) { hi = hi + 1; lo = lo - 1; }
  const pad = (hi - lo) * 0.08;
  const y = v => top + plotH - ((v - (lo - pad)) / ((hi - lo) + 2 * pad)) * plotH;

  const base = num(rows[0].open);
  if (base !== null) {
    m.g.strokeStyle = '#2a3342';
    m.g.beginPath();
    m.g.moveTo(0, y(base));
    m.g.lineTo(m.width, y(base));
    m.g.stroke();
  }
  const body = Math.max(1, Math.min(m.slot - 2, 22));
  rows.forEach((b, i) => {
    const cx = i * m.slot + m.slot / 2;
    const o = num(b.open), c = num(b.close);
    const hiV = num(b.high), loV = num(b.low);
    const anchor = o !== null ? o : c;
    if (anchor === null || c === null) return;
    const up = c >= anchor;
    const color = up ? UP : DOWN;
    m.g.strokeStyle = color;
    m.g.fillStyle = color;
    if (hiV !== null && loV !== null) {
      m.g.beginPath();
      m.g.moveTo(cx, y(hiV));
      m.g.lineTo(cx, y(loV));
      m.g.stroke();
    }
    const yc = y(c), yo = anchor === null ? yc : y(anchor);
    m.g.fillRect(cx - body / 2, Math.min(yo, yc), body, Math.max(1.5, Math.abs(yo - yc)));
  });

  m.g.fillStyle = '#8b97a8';
  m.g.font = '10px system-ui';
  m.g.textBaseline = 'bottom';
  const ticks = rows.length <= 4
    ? rows.map((_, i) => i)
    : [0, Math.floor((rows.length - 1) / 2), rows.length - 1];
  ticks.forEach(i => {
    const x = Math.max(2, Math.min(m.width - 74, i * m.slot + 2));
    m.g.fillText(rows[i].date, x, m.height - 3);
  });

  if (state.hover !== null) {
    const local = state.hover - m.from;
    if (local >= 0 && local < rows.length) {
      const b = rows[local];
      const cx = local * m.slot + m.slot / 2;
      m.g.strokeStyle = '#4c9ffe';
      m.g.beginPath();
      m.g.moveTo(cx, 0);
      m.g.lineTo(cx, m.height);
      m.g.stroke();
      $('#probe').textContent = '日期 ' + b.date + '　开 ' + fmt(b.open) + '　高 ' + fmt(b.high)
        + '　低 ' + fmt(b.low) + '　收 ' + fmt(b.close)
        + (b.volume != null ? '　量 ' + fmt(b.volume, 0) : '');
    } else {
      $('#probe').textContent = '把指针移到图上可查看当日 OHLC';
    }
  }
}

function pick(ev) {
  const bars = state.payload?.bars || [];
  if (!bars.length) return;
  const c = $('#chart');
  const m = metrics();
  const src = ev.touches ? ev.touches[0] : ev;
  const rect = c.getBoundingClientRect();
  const local = Math.floor((src.clientX - rect.left) / m.slot);
  state.hover = Math.max(m.from, Math.min(m.from + m.view - 1, m.from + local));
  draw();
}

/* --- data loading ----------------------------------------------------- */
function query() {
  const opt = OPTS.find(o => o.index_id === $('#index').value);
  return requestFor(opt || {index_id: $('#index').value, market: $('#market').value});
}

function clearView() {
  $('#head').innerHTML = '<div class="muted">正在请求本地研究服务…</div>';
  $('#kv').innerHTML = '';
  $('#raw').innerHTML = '';
  $('#reason').textContent = '';
  $('#close').innerHTML = '<span class="muted">—</span>';
  $('#history').innerHTML = '';
  $('#count').textContent = '';
  $('#probe').textContent = '把指针移到图上可查看当日 OHLC';
  $('#empty').hidden = true;
  $('#notready').hidden = true;
  $('#viewport').textContent = '';
  state.payload = null;
  state.hover = null;
  state.from = 0;
  draw();
}

async function load() {
  const seq = ++state.seq;
  clearView();
  setState('loading', STATUS.loading);
  markChip();
  refreshOverview();
  try {
    const payload = await cachedPayload(query());
    if (seq !== state.seq) return;
    state.payload = payload;
    state.from = 0;
    renderInfo(payload);
    renderTable(payload);
    draw();
  } catch (err) {
    if (seq !== state.seq) return;
    // Never fall back to the previously selected index's data.
    clearView();
    setState('error', STATUS.error);
    $('#reason').textContent = '研究服务不可用 / research service unavailable: ' + String(err);
  }
}

/* --- tabs / zoom / pan ------------------------------------------------ */
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('is-active', t === tab);
        const panel = $('#panel-' + t.dataset.tab);
        if (panel) panel.hidden = t !== tab;
      });
    });
  });
}

function initZoom() {
  const sel = $('#zoom');
  sel.innerHTML = SPANS.map(v => '<option value="' + v + '">'
    + (v === 0 ? '全部' : '最近 ' + v + ' 根') + '</option>').join('');
  sel.value = '120';
  sel.addEventListener('change', () => {
    state.span = Number(sel.value) || (state.payload?.bars || []).length || 1;
    state.from = 0;
    state.hover = null;
    draw();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  renderOptions();
  initTabs();
  initZoom();
  $('#market').addEventListener('change', () => {
    renderIndices();
    load();
  });
  $('#index').addEventListener('change', load);
  $('#go').addEventListener('click', load);
  $('#prev').addEventListener('click', () => {
    state.hover = null;
    const bars = state.payload?.bars || [];
    state.from = Math.max(0, state.from - Math.max(1, state.span || 1));
    state.from = Math.min(state.from, Math.max(0, bars.length));
    draw();
  });
  $('#next').addEventListener('click', () => {
    state.hover = null;
    const bars = state.payload?.bars || [];
    const view = Math.min(state.span || bars.length, bars.length);
    state.from = Math.min(Math.max(0, bars.length - view), state.from + view);
    draw();
  });
  $('#pan').addEventListener('input', ev => {
    state.from = Number(ev.target.value) || 0;
    state.hover = null;
    draw();
  });
  $('#chartwrap').addEventListener('scroll', ev => {
    const max = Math.max(0, ($('#chart').clientWidth || 0) - ($('#chartwrap').clientWidth || 0));
    if (max > 0) {
      const bars = state.payload?.bars || [];
      const view = Math.min(state.span || bars.length, bars.length);
      state.from = Math.round((ev.currentTarget.scrollLeft / max) * Math.max(0, bars.length - view));
    }
    draw();
  });
  $('#chart').addEventListener('mousemove', pick);
  $('#chart').addEventListener('touchstart', pick, {passive: true});
  $('#chart').addEventListener('touchmove', pick, {passive: true});
  $('#chart').addEventListener('mouseleave', () => {
    state.hover = null;
    draw();
  });
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 60);
  });
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => draw()).observe($('#chartwrap'));
  }
  load();
});
"""


def nav_items_html() -> str:
    """Render the top-bar navigation: one live page plus inert planning labels."""

    items = []
    for item in NAV_ITEMS:
        state = str(item.get("state") or "planning")
        cls = "nav-item is-active" if state == "active" else "nav-item is-planning"
        badge = "" if state == "active" else '<span class="badge">规划中</span>'
        # Planning entries are <span>, never <a href>: no dead route in the shell.
        items.append(
            f'<span class="{cls}" data-nav="{_text(item.get("key"))}" '
            f'aria-disabled="true" role="presentation">{_text(item.get("label"))}{badge}</span>'
        )
    return "".join(items)


def selector_options() -> list[dict[str, str]]:
    """Return selector options derived from the canonical global-index registry."""

    from analysis.research.global_market_research import list_index_choices

    return [dict(choice) for choice in list_index_choices()]


def render_global_market_research_page(
    options: Sequence[Mapping[str, Any]] | None = None,
    *,
    start_date: str = "",
    end_date: str = "",
    api_path: str = DEFAULT_API_PATH,
) -> str:
    """Render the Swartee global market research terminal shell.

    The HTML embeds only selector metadata plus a single endpoint URL; every
    price number is fetched at runtime through the research service, so the
    browser never calls a provider and no quote data is hardcoded here.
    """

    choices = [dict(item) for item in options] if options is not None else selector_options()
    payload = json.dumps(choices, ensure_ascii=False).replace("</", "<\\/")
    api_payload = json.dumps(api_path).replace("</", "<\\/")
    return (
        '<!doctype html>\n'
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="icon" href="data:,">'
        f"<title>{_text(PRODUCT_NAME)}</title>"
        f"<style>{_STYLE}</style></head><body>\n"
        '<header class="topbar"><div class="brand"><b>' + _text(PRODUCT_NAME) + "</b><span>"
        + _text(PRODUCT_SUBTITLE) + "</span></div>"
        f'<nav class="nav">{nav_items_html()}</nav>'
        '<div class="scope">数据口径：本地研究服务的<b>最新日线收盘</b>，非实时行情；'
        "涨跌幅仅在相邻两日收盘均可得时展示，并标注基准日期。</div></header>\n"
        '<section class="panel overview"><h2 class="panel-h">全球市场概览 '
        '<small>最新日K收盘 · 非实时行情</small></h2><div id="strip"></div></section>'
        "<main>"
        '<aside class="panel col-nav"><h2 class="panel-h">市场与指数 <small>来自注册表</small></h2>'
        '<div class="field"><label for="market">市场 market</label><select id="market"></select></div>'
        '<div class="field"><label for="index">指数 index</label><select id="index"></select></div>'
        '<div class="field"><label for="start">起始日期 start</label>'
        f'<input id="start" type="date" value="{_text(start_date, "")}"></div>'
        '<div class="field"><label for="end">结束日期 end</label>'
        f'<input id="end" type="date" value="{_text(end_date, "")}"></div>'
        '<button id="go" type="button" style="width:100%">查询最新日线</button></aside>'
        '<section class="panel col-chart"><h2 class="panel-h">日线走势 <small id="viewport"></small></h2>'
        '<div style="margin-bottom:8px"><span id="state" class="state loading">加载中</span></div>'
        '<div class="chartwrap" id="chartwrap"><canvas id="chart"></canvas></div>'
        '<div class="controls"><label>缩放 zoom<select id="zoom"></select></label>'
        '<button id="prev" type="button">← 前一段</button>'
        '<label>平移 pan<input id="pan" type="range" min="0" max="0" value="0"></label>'
        '<button id="next" type="button">后一段 →</button></div>'
        '<div class="probe" id="probe">把指针移到图上可查看当日 OHLC</div>'
        '<div class="legend"><span><i class="up-bg"></i>收盘 ≥ 开盘（红涨）</span>'
        '<span><i class="down-bg"></i>收盘 &lt; 开盘（绿跌）</span>'
        '<span>价格单位：指数点位</span></div>'
        '<div class="muted" id="notready" style="margin-top:10px" hidden>'
        "该指数本次窗口没有可绘制的日线。</div></section>"
        '<aside class="panel col-info"><h2 class="panel-h">市场信息</h2>'
        '<div id="head"></div><div id="close" style="margin-top:8px"></div>'
        '<dl class="kv" id="kv"></dl><div class="reason" id="reason"></div>'
        "<details><summary>规范字段（内部 / 数据源原始字段）</summary>"
        '<dl class="kv" id="raw"></dl></details>'
        '<div class="reason muted" id="empty" hidden>该窗口内没有可用的日线数据（empty）。</div>'
        "</aside>"
        '<section class="panel history"><div class="tabs">'
        '<button type="button" class="tab is-active" data-tab="daily">历史日线</button>'
        '<button type="button" class="tab" data-tab="about">数据口径</button></div>'
        '<div class="tabpanel" id="panel-daily"><div class="muted" id="count" '
        'style="margin-bottom:6px"></div><div class="scroll" id="history"></div></div>'
        '<div class="tabpanel" id="panel-about" hidden><div class="muted" style="font-size:12px">'
        "价格与成交量全部来自本地研究服务返回的日线记录，不在页面内硬编码任何行情；"
        "红涨绿跌为国内显示习惯，K 线含义始终是收盘价与开盘价的比较；"
        "可用性 / 新鲜度 / 交易日状态为 unknown 时按未知展示，不会当作正常。"
        "</div></div></section>"
        "</main>\n"
        f'<script>window.__OPTS={payload};window.__API={api_payload};</script>\n'
        f"<script>{_JS}</script>\n"
        "</body></html>"
    )


def render_research_state(payload: Mapping[str, Any]) -> str:
    """Render the status/summary block server-side for tests and CLI output."""

    status = str(payload.get("status") or "error")
    label = STATUS_LABELS.get(status, STATUS_LABELS["error"])
    return (
        f'<div class="state {_text(status, "error")}">{_text(payload.get("name"))} · '
        f'{_text(payload.get("index_id"))} · {_text(label)}</div>'
        '<div class="meta">'
        f'<span>数据日期 <b>{_text(payload.get("data_date"))}</b></span>'
        f'<span>来源 <b>{_text(payload.get("source"))}</b></span>'
        f'<span>条数 <b>{_text(payload.get("bar_count"), "0")}</b></span>'
        "</div>"
    )
