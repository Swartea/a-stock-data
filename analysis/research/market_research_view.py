"""Render the Swartee Market Research workbench (Chinese-first, dark).

This module is **additive and separate** from
:mod:`analysis.research.market_snapshot_view`: the existing A-share static
snapshot page and its record contract are untouched and stay in their own file.

V2.1 turns the V1 single-page terminal into a real workbench with four live
sections behind a real top navigation:

``市场总览`` (overview, default homepage)
    One card per registered global index, grouped by market (cn / hk / us),
    each showing its **own** latest daily close, adjacent-close change, data
    date, freshness, availability, source and trading-calendar status. One
    click on a card opens that index in ``指数研究``.

``指数研究`` (research)
    The unchanged V1 daily-K canvas: OHLC candles, zoom, pan, date range,
    history table, data details and the raw field disclosure.

``市场比较`` (compare)
    The section hook for the cross-market normalised comparison task. The
    section is reachable through the navigation and ships an explicit mount
    point plus a JS hook contract, so the dependent comparison task can bind
    its renderer without touching the rest of the workbench.

``自选关注`` (watchlist)
    A localStorage-backed watchlist of **canonical index ids only**, with
    legacy-alias normalisation through the existing identity vocabulary.

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

from analysis.research.market_comparison_view import COMPARISON_JS, COMPARISON_STYLE

DEFAULT_API_PATH = "/api/daily-k"

PRODUCT_NAME = "Swartea Market Research"
PRODUCT_SUBTITLE = "斯沃特 · 全球市场研究终端"

#: Top navigation: every entry is a real, reachable section of the workbench.
#: There is no inert "规划中" label and no dead route in the shell.
NAV_ITEMS: tuple[Mapping[str, str], ...] = (
    {"key": "overview", "label": "市场总览", "state": "ready"},
    {"key": "research", "label": "指数研究", "state": "ready"},
    {"key": "compare", "label": "市场比较", "state": "ready"},
    {"key": "watchlist", "label": "自选关注", "state": "ready"},
)

#: Section metadata: the navigation key and the DOM id of the section panel.
SECTIONS: tuple[Mapping[str, str], ...] = (
    {"key": "overview", "title": "市场总览", "target": "section-overview"},
    {"key": "research", "title": "指数研究", "target": "section-research"},
    {"key": "compare", "title": "市场比较", "target": "section-compare"},
    {"key": "watchlist", "title": "自选关注", "target": "section-watchlist"},
)

#: Display-only market labels. Identity (id / name / market token / currency)
#: always comes from the canonical registry; these are Chinese captions.
MARKET_LABELS: Mapping[str, str] = {
    "cn": "中国内地",
    "hk": "中国香港",
    "us": "美国",
}

STATUS_LABELS: Mapping[str, str] = {
    "ok": "数据正常 / available",
    "empty": "无数据 / empty",
    "unavailable": "不可用 / unavailable",
    "error": "错误 / error",
}

#: localStorage key holding the watchlist. Only canonical index ids are stored.
WATCHLIST_STORAGE_KEY = "swartea.market-research.watchlist.v1"


def _text(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return html.escape(fallback, quote=True)
    return html.escape(str(value), quote=True)


def legacy_alias_map() -> dict[str, list[str]]:
    """Return ``canonical id -> known legacy aliases`` from the identity module.

    The mapping is derived from the *existing* canonical identity vocabulary
    (:data:`analysis.research.index_registry.INDEX_ID_ALIASES`). No parallel
    registry is created here: the browser only receives the aliases that the
    identity layer already recognises, so the UI can normalise an old stored
    id into the current canonical id.

    The aliases of one index are ordered shortest first (alphabetically within
    one length), so the order is deterministic and independent of the mapping's
    insertion order: the short pre-canonical name (``sse.composite``) leads and
    the dotted contract id (``cn.index.sse.000001``) follows.
    """

    from analysis.research.index_registry import INDEX_ID_ALIASES

    grouped: dict[str, list[str]] = {}
    for alias, canonical in INDEX_ID_ALIASES.items():
        grouped.setdefault(canonical, []).append(alias)
    return {
        canonical: sorted(aliases, key=lambda alias: (len(alias), alias))
        for canonical, aliases in grouped.items()
    }


def _market_label(market: Any) -> str:
    token = str(market or "").strip().lower()
    return MARKET_LABELS.get(token, token.upper())


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
button:focus-visible,select:focus-visible,input:focus-visible,[tabindex]:focus-visible{
outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3,h4{margin:0}
.muted{color:var(--muted)}
.up{color:var(--up)}
.down{color:var(--down)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* --- top bar --------------------------------------------------------- */
.topbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;
padding:8px 14px;background:var(--panel-2);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:baseline;gap:8px}
.brand b{font-size:15px;letter-spacing:.2px}
.brand span{font-size:11px;color:var(--muted)}
.nav{display:flex;flex-wrap:wrap;gap:6px;margin-left:auto}
.nav-item{display:inline-flex;align-items:center;gap:5px;font-size:12px;
padding:4px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted);
background:var(--panel-2)}
.nav-item.is-active{color:var(--fg);border-color:var(--accent);background:#16233a}
.badge{font-size:10px;padding:1px 5px;border-radius:4px;background:#1d2534;color:#7d8798}
.scope{width:100%;font-size:11px;color:var(--muted)}
.overview{margin:10px 14px 0}
.overview-grid{display:grid;gap:14px}

/* --- workbench sections ---------------------------------------------- */
main{padding:12px 14px 18px;display:grid;gap:12px;max-width:1720px;margin:0 auto}
.section{display:grid;gap:12px}
.section[hidden]{display:none}
.grid3{display:grid;gap:12px;grid-template-columns:264px minmax(0,1fr) 300px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.panel-h{display:flex;align-items:center;justify-content:space-between;gap:8px;
margin:0 0 9px;font-size:13px;font-weight:600}
.panel-h small{font-weight:400;font-size:11px;color:var(--muted)}
.notice{margin:0 0 9px;padding:7px 10px;border-radius:7px;font-size:12px;
border:1px solid #6b5220;background:#221a0d;color:var(--warn)}
.notice[hidden]{display:none}

/* --- overview cards --------------------------------------------------- */
.market-group{min-width:0}
.market-group h3{font-size:12px;color:var(--muted);font-weight:600;margin:0 0 8px}
.cards{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(232px,1fr))}
.mcard{min-width:0;display:flex;flex-direction:column;gap:6px;padding:10px;
border:1px solid var(--line);border-radius:9px;background:var(--panel-2);cursor:pointer}
.mcard:hover{border-color:var(--accent)}
.mcard.is-unavailable{border-style:dashed}
.mcard-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.mcard-head h4{font-size:13px;font-weight:600;overflow-wrap:anywhere}
.mcard-market{font-size:10px;color:var(--muted);white-space:nowrap}
.mcard-close{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.mcard-close.is-unavailable{color:var(--warn)}
.mcard-change{font-size:12px;font-variant-numeric:tabular-nums}
.mcard-meta{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 8px;
font-size:11px;margin:2px 0 0}
.mcard-meta dt{color:var(--muted);white-space:nowrap}
.mcard-meta dd{margin:0;text-align:right;overflow-wrap:anywhere}
.mcard-meta dd.unknown{color:var(--warn)}
.mcard-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}
.mcard-actions .btn{min-height:30px;font-size:12px}
.mcard-actions .btn.watch[aria-pressed=true]{border-color:var(--accent);color:#cfe3ff}
.compare-mount{min-height:120px;border:1px dashed var(--line);border-radius:8px;
padding:10px;margin-top:8px}

/* --- layout ---------------------------------------------------------- */
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
@media (min-width:1440px){
.cards{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (min-width:1920px){
.cards{grid-template-columns:repeat(4,minmax(0,1fr))}
}
@media (max-width:1280px){
.grid3{grid-template-columns:232px minmax(0,1fr)}
.col-info{grid-column:1 / -1}
.col-info .kv{grid-template-columns:auto auto 1fr}
}
@media (max-width:768px){
main{grid-template-columns:minmax(0,1fr);padding:10px}
.overview{margin:8px 10px 0}
.cards{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
canvas{height:240px}
.controls input[type=range]{width:100%}
.col-info .kv{grid-template-columns:auto 1fr}
}
@media (max-width:390px){
.topbar{gap:6px 10px;padding:8px 10px}
.nav{margin-left:0;width:100%}
.overview-grid{grid-template-columns:minmax(0,1fr)}
.cards{grid-template-columns:minmax(0,1fr)}
.price{font-size:19px}
canvas{height:200px}
}
"""

# ---------------------------------------------------------------------------
# Core script: pure logic, no DOM access. Kept dependency-free on purpose so
# the very same source can be executed under Node in the automated tests.
# ---------------------------------------------------------------------------
_CORE_JS = r"""
(function (root) {
  'use strict';

  var WATCHLIST_KEY = 'swartea.market-research.watchlist.v1';

  function toNum(value) {
    if (typeof value === 'number') return isFinite(value) ? value : null;
    if (typeof value === 'string' && value.trim() !== '') {
      var n = Number(value);
      return isFinite(n) ? n : null;
    }
    return null;
  }

  function buildAliasMap(options) {
    var map = Object.create(null);
    (options || []).forEach(function (opt) {
      if (!opt || !opt.index_id) return;
      map[opt.index_id] = opt.index_id;
      (opt.aliases || []).forEach(function (alias) {
        if (alias) map[alias] = opt.index_id;
      });
    });
    return map;
  }

  /* Resolve any recognised identifier (canonical id or known legacy alias) to
     the canonical id. Unknown / retired ids resolve to null: they are never
     silently accepted, and never crash the caller. */
  function normalizeId(raw, knownIds, aliasMap) {
    if (typeof raw !== 'string') return null;
    var trimmed = raw.trim();
    if (!trimmed) return null;
    var known = knownIds || [];
    if (known.indexOf(trimmed) !== -1) return trimmed;
    var resolved = (aliasMap || {})[trimmed];
    if (resolved && known.indexOf(resolved) !== -1) return resolved;
    return null;
  }

  /* Latest valid daily close plus the adjacent-close change. The change is
     only produced from two valid closes; a single bar, a missing base or a
     zero base yields no percentage at all (never a fabricated one). */
  function latestClose(bars) {
    var rows = (bars || []).filter(function (b) { return b && b.date; });
    if (!rows.length) return null;
    var last = rows[rows.length - 1];
    var close = toNum(last.close);
    var result = {
      date: last.date, close: close, prevDate: null, prevClose: null,
      changePct: null, barCount: rows.length
    };
    if (close === null) return result;
    if (rows.length >= 2) {
      var prev = rows[rows.length - 2];
      var prevClose = toNum(prev.close);
      if (prevClose !== null && prevClose !== 0) {
        result.prevDate = prev.date;
        result.prevClose = prevClose;
        result.changePct = (close - prevClose) / Math.abs(prevClose) * 100;
      }
    }
    return result;
  }

  /* Watchlist store: canonical ids only, persisted in localStorage when it
     works, degraded to memory when it does not. Corrupt, retired or duplicate
     stored entries are dropped instead of breaking the page. */
  function createWatchlist(config) {
    var opts = config || {};
    var storage = opts.storage || null;
    var knownIds = (opts.knownIds || []).slice();
    var aliasMap = opts.aliasMap || {};
    var key = opts.key || WATCHLIST_KEY;
    var ids = [];
    var persistent = true;
    var notice = '';

    function readRaw() {
      if (!storage) {
        persistent = false;
        notice = '浏览器存储不可用，自选暂存于内存，刷新页面后不会保留。';
        return null;
      }
      try {
        var raw = storage.getItem(key);
        return typeof raw === 'string' ? raw : null;
      } catch (err) {
        persistent = false;
        notice = '浏览器存储读取失败，自选暂存于内存，刷新页面后不会保留。';
        return null;
      }
    }

    function writeRaw(text) {
      if (!storage) {
        persistent = false;
        notice = '浏览器存储不可用，自选暂存于内存，刷新页面后不会保留。';
        return false;
      }
      try {
        storage.setItem(key, text);
        return true;
      } catch (err) {
        persistent = false;
        notice = '浏览器存储写入失败，自选暂存于内存，刷新页面后不会保留。';
        return false;
      }
    }

    function persist() { writeRaw(JSON.stringify(ids)); }

    function load() {
      var raw = readRaw();
      ids = [];
      if (raw === null) return;
      var parsed;
      try { parsed = JSON.parse(raw); } catch (err) { parsed = undefined; }
      if (!Array.isArray(parsed)) {
        notice = notice || '自选存储内容损坏或格式无效，已重置为空。';
        writeRaw('[]');
        return;
      }
      var seen = [];
      var dropped = 0;
      parsed.forEach(function (item) {
        var id = normalizeId(item, knownIds, aliasMap);
        if (!id) { dropped += 1; return; }
        if (seen.indexOf(id) !== -1) { dropped += 1; return; }
        seen.push(id);
      });
      ids = seen;
      if (dropped) {
        notice = notice || '已忽略无效、重复或已退役的自选条目。';
        writeRaw(JSON.stringify(ids));
      }
    }

    function add(rawId) {
      var id = normalizeId(rawId, knownIds, aliasMap);
      if (!id) return false;
      if (ids.indexOf(id) !== -1) return false;
      ids.push(id);
      persist();
      return true;
    }

    function remove(rawId) {
      var id = normalizeId(rawId, knownIds, aliasMap);
      if (!id) return false;
      var at = ids.indexOf(id);
      if (at === -1) return false;
      ids.splice(at, 1);
      persist();
      return true;
    }

    function toggle(rawId) {
      var id = normalizeId(rawId, knownIds, aliasMap);
      if (!id) return false;
      if (ids.indexOf(id) !== -1) { remove(id); return false; }
      add(id);
      return true;
    }

    function has(rawId) {
      var id = normalizeId(rawId, knownIds, aliasMap);
      return id !== null && ids.indexOf(id) !== -1;
    }

    function list() { return ids.slice(); }
    function clear() { ids = []; persist(); }
    function isPersistent() { return persistent; }
    function noticeText() { return notice; }

    load();

    return {
      add: add, remove: remove, toggle: toggle, has: has, list: list,
      clear: clear, persist: persist, isPersistent: isPersistent,
      noticeText: noticeText, key: key
    };
  }

  /* Section switching: one active section, one active navigation item. */
  function activateSection(key, sections, navItems) {
    (sections || []).forEach(function (item) {
      if (!item || !item.el) return;
      item.el.hidden = item.key !== key;
    });
    (navItems || []).forEach(function (item) {
      if (!item || !item.el) return;
      var active = item.key === key;
      if (item.el.classList) item.el.classList.toggle('is-active', active);
      if (typeof item.el.setAttribute === 'function') {
        if (active) item.el.setAttribute('aria-current', 'page');
        else item.el.removeAttribute('aria-current');
      }
    });
    return key;
  }

  /* Watchlist button binding. The handler never lets the click reach an
     enclosing navigation target, so adding or removing an index can not
     accidentally open the research section. */
  function bindWatchButton(el, indexId, store, onChanged) {
    if (!el || typeof el.addEventListener !== 'function') return;
    el.addEventListener('click', function (ev) {
      if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation();
      if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
      var added = store.toggle(indexId);
      if (typeof onChanged === 'function') onChanged(indexId, added);
    });
  }

  var api = {
    WATCHLIST_KEY: WATCHLIST_KEY,
    toNum: toNum,
    buildAliasMap: buildAliasMap,
    normalizeId: normalizeId,
    latestClose: latestClose,
    createWatchlist: createWatchlist,
    activateSection: activateSection,
    bindWatchButton: bindWatchButton
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SwarteaCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
"""

# ---------------------------------------------------------------------------
# Application script: DOM wiring on top of the core logic.
# ---------------------------------------------------------------------------
_JS = r"""
const OPTS = window.__OPTS || [];
const API = window.__API || '/api/daily-k';
const CORE = (typeof globalThis !== 'undefined' && globalThis.SwarteaCore) || null;
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

const state = {payload: null, seq: 0, hover: null, from: 0, span: 120, section: 'overview'};
const payloadCache = new Map();
const payloadResults = new Map();
const payloadCachedAt = new Map();
const overviewRange = {start: document.querySelector("#start").value, end: document.querySelector("#end").value};
const overviewTokens = new Map();
const requestQueue = [];
let activeRequests = 0;
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
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

/* --- watchlist store -------------------------------------------------- */
function safeLocalStorage() {
  try {
    const store = window.localStorage;
    if (!store) return null;
    return store;
  } catch (err) {
    return null;
  }
}

const KNOWN_IDS = OPTS.map(o => o.index_id);
const ALIAS_MAP = CORE ? CORE.buildAliasMap(OPTS) : {};
const WATCHLIST = CORE ? CORE.createWatchlist({
  storage: safeLocalStorage(),
  knownIds: KNOWN_IDS,
  aliasMap: ALIAS_MAP
}) : {list: () => [], has: () => false, toggle: () => false, noticeText: () => '',
      isPersistent: () => false, add: () => false, remove: () => false};

/* --- navigation ------------------------------------------------------- */
function sectionItems() {
  return $$('[data-section]').filter(el => el.classList.contains('section'))
    .map(el => ({key: el.dataset.section, el: el}));
}

function navItems() {
  return $$('.nav-item').map(el => ({key: el.dataset.nav, el: el}));
}

function navigate(key) {
  if (CORE) {
    CORE.activateSection(key, sectionItems(), navItems());
  } else {
    sectionItems().forEach(item => { item.el.hidden = item.key !== key; });
  }
  state.section = key;
  try {
    document.dispatchEvent(new CustomEvent('swartea:workbench-section', {
      detail: {section: key}
    }));
  } catch (err) {
    /* CustomEvent unavailable: the section is still switched. */
  }
  return key;
}

function setState(kind, text) {
  const el = $('#state');
  if (!el) return;
  el.className = 'state ' + kind;
  el.textContent = text;
}

/* --- overview cards --------------------------------------------------- */
function cardFor(indexId) {
  return $$('#strip .mcard').find(el => el.dataset.index === indexId) || null;
}

function setField(card, field, text, cls) {
  if (!card) return;
  const el = card.querySelector('[data-field="' + field + '"]');
  if (!el) return;
  el.textContent = text;
  if (cls !== undefined) el.className = cls;
}

function renderOverviewQuote(opt, p) {
  const card = cardFor(opt.index_id);
  if (!card) return;
  const rows = (p.bars || []).filter(b => b && b.date);
  const last = rows.length ? rows[rows.length - 1] : null;
  const summary = CORE ? CORE.latestClose(p.bars) : null;
  const usable = p.status === 'ok' && summary && summary.close !== null;
  syncWatchQuote(opt.index_id, p);
  card.classList.toggle('is-unavailable', !usable);
  if (!usable) {
    setField(card, 'close', p.status === 'unavailable' ? '暂不可用' : '暂无日K收盘',
      'mcard-close is-unavailable');
    setField(card, 'change', label(AVAIL, p.availability) + ' · ' + label(FRESH, p.freshness),
      'mcard-change muted');
    setField(card, 'date', p.data_date ? '数据日期 ' + p.data_date : '无可用数据', 'mcard-meta');
    setField(card, 'freshness', label(FRESH, p.freshness), tone(p.freshness));
    setField(card, 'availability', label(AVAIL, p.availability), tone(p.availability));
    setField(card, 'source', p.source || '—', '');
    setField(card, 'calendar', label(TRADING, p.trading_day_status),
      tone(p.trading_day_status));
    card.title = p.unavailable_reason || p.failure_reason || opt.index_id;
    return;
  }
  setField(card, 'close', fmt(summary.close) + ' 点', 'mcard-close');
  if (summary.changePct !== null) {
    const trend = summary.changePct >= 0 ? 'up' : 'down';
    setField(card, 'change',
      (summary.changePct >= 0 ? '+' : '') + fmt(summary.close - summary.prevClose) + ' / ' + (summary.changePct >= 0 ? '+' : '') + summary.changePct.toFixed(2) + '% · 相邻日收盘',
      'mcard-change ' + trend);
    card.title = opt.name + ' · ' + summary.prevDate + ' 至 ' + summary.date
      + ' · ' + opt.index_id;
  } else {
    setField(card, 'change', '仅一根日线，暂无涨跌幅', 'mcard-change muted');
    card.title = opt.name + ' · ' + summary.date + ' · ' + opt.index_id;
  }
  setField(card, 'date', p.data_date || summary.date, '');
  setField(card, 'freshness', label(FRESH, p.freshness), tone(p.freshness));
  setField(card, 'availability', label(AVAIL, p.availability), tone(p.availability));
  setField(card, 'source', p.source || '—', '');
  setField(card, 'calendar', label(TRADING, p.trading_day_status), tone(p.trading_day_status));
}

function renderOverviewFailure(opt) {
  const card = cardFor(opt.index_id);
  if (!card) return;
  card.classList.add('is-unavailable');
  setField(card, 'close', '暂不可用', 'mcard-close is-unavailable');
  setField(card, 'change', '研究服务请求失败', 'mcard-change muted');
  setField(card, 'date', '无法读取日线', '');
}

/* Keep the watchlist quote in sync with the daily-K payload it shares with the
   overview: the watchlist never issues a second request, it reuses the cached
   response of the very same index. */
function syncWatchQuote(indexId, p) {
  const card = $$('#watch-list .watch-card').find(el => el.dataset.index === indexId);
  if (!card) return;
  const opt = OPTS.find(o => o.index_id === indexId);
  const summary = CORE ? CORE.latestClose(p.bars) : null;
  const closeEl = card.querySelector('[data-field="close"]');
  if (!closeEl) return;
  const usable = p.status === 'ok' && summary && summary.close !== null;
  closeEl.textContent = usable ? fmt(summary.close) + ' 点' : '—';
}

/* --- shared bounded fetch queue / cache -------------------------------- */
function requestFor(opt) {
  return paramsFor(opt.index_id, opt.market, overviewRange.start, overviewRange.end);
}

function paramsFor(indexId, market, start, end) {
  const startEl = $('#start');
  const endEl = $('#end');
  return new URLSearchParams({
    index_id: indexId,
    market: market || '',
    start_date: start == null ? (startEl ? startEl.value : '') : start,
    end_date: end == null ? (endEl ? endEl.value : '') : end
  });
}

function pumpRequests() {
  while (activeRequests < 3 && requestQueue.length) {
    const item = requestQueue.shift();
    activeRequests += 1;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    fetch(item.url, {signal: controller.signal}).then(res => {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(payload => {
      payloadResults.set(item.key, payload);
      if (payload.status !== 'ok') payloadCache.delete(item.key);
      item.resolve(payload);
    }).catch(error => {
      payloadCache.delete(item.key);
      payloadResults.delete(item.key);
      item.reject(error);
    }).finally(() => {
      clearTimeout(timeout);
      activeRequests -= 1;
      pumpRequests();
    });
  }
}

function cachedPayload(params) {
  const key = params.toString();
  if (payloadCache.has(key) && Date.now() - payloadCachedAt.get(key) < 300000) return payloadCache.get(key);
  const promise = new Promise((resolve, reject) => {
    requestQueue.push({key: key, url: API + '?' + key, resolve: resolve, reject: reject});
  });
  payloadCache.set(key, promise);
  payloadCachedAt.set(key, Date.now());
  pumpRequests();
  return promise;
}

function nextOverviewToken(indexId) {
  const token = (overviewTokens.get(indexId) || 0) + 1;
  overviewTokens.set(indexId, token);
  return token;
}

function refreshOverview() {
  OPTS.forEach(opt => {
    const token = nextOverviewToken(opt.index_id);
    cachedPayload(requestFor(opt)).then(p => {
      if (overviewTokens.get(opt.index_id) !== token) return;
      renderOverviewQuote(opt, p);
    }).catch(() => {
      if (overviewTokens.get(opt.index_id) !== token) return;
      renderOverviewFailure(opt);
    });
  });
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
  const summary = CORE ? CORE.latestClose(p.bars) : null;
  const change = summary && summary.changePct !== null
    ? {pct: summary.changePct, prevDate: summary.prevDate, prev: summary.prevClose}
    : null;
  const closeEl = $('#close');
  const lastRow = summary && summary.close !== null ? summary : null;
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
  return paramsFor((opt || {}).index_id || $('#index').value, (opt || {}).market || $('#market').value);
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

/* --- index selectors -------------------------------------------------- */
function renderOptions() {
  const markets = [];
  OPTS.forEach(o => { if (!markets.includes(o.market)) markets.push(o.market); });
  $('#market').innerHTML = markets
    .map(m => '<option value="' + esc(m) + '">' + esc(marketName(m)) + ' · ' + esc(String(m).toUpperCase()) + '</option>')
    .join('');
  renderIndices();
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
  $$('#strip .mcard').forEach(c =>
    c.classList.toggle('is-selected', c.dataset.index === id));
}

/* --- watchlist rendering ---------------------------------------------- */
function watchButtonLabel(indexId) {
  return WATCHLIST.has(indexId) ? '移出自选' : '加入自选';
}

function syncWatchButtons() {
  $$('[data-action="watch"]').forEach(btn => {
    const id = btn.dataset.index;
    const on = WATCHLIST.has(id);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = watchButtonLabel(id);
  });
}

function renderWatchlist() {
  const items = WATCHLIST.list();
  const list = $('#watch-list');
  const empty = $('#watch-empty');
  const count = $('#watch-count');
  const notice = $('#watch-notice');
  if (count) count.textContent = items.length + ' 个指数';
  const noticeText = WATCHLIST.noticeText();
  if (notice) {
    notice.textContent = noticeText;
    notice.hidden = !noticeText;
  }
  if (empty) empty.hidden = items.length > 0;
  if (!list) return;
  list.innerHTML = items.map(id => {
    const opt = OPTS.find(o => o.index_id === id);
    const name = opt ? opt.name : id;
    const market = opt ? marketName(opt.market) : '';
    return '<article class="mcard watch-card" data-index="' + esc(id) + '" tabindex="0">'
      + '<div class="mcard-head"><h4>' + esc(name) + '</h4>'
      + '<span class="mcard-market">' + esc(market) + '</span></div>'
      + '<div class="mcard-close" data-field="close">—</div>'
      + '<div class="mcard-change" data-field="change">' + esc(id) + '</div>'
      + '<div class="mcard-actions">'
      + '<button type="button" class="btn" data-action="open">进入研究</button>'
      + '<button type="button" class="btn watch" data-action="watch" data-index="' + esc(id)
      + '" aria-pressed="true">移出自选</button>'
      + '</div></article>';
  }).join('');
  // The watchlist reuses the daily-K response that the overview already cached:
  // no watchlist entry ever triggers a second request.
  items.forEach(id => {
    const opt = OPTS.find(o => o.index_id === id);
    const payload = payloadResults.get(requestFor(opt || {index_id:id, market:''}).toString());
    if (payload) syncWatchQuote(id, payload);
  });
  list.querySelectorAll('.watch-card').forEach(card => {
    const id = card.dataset.index;
    card.addEventListener('click', ev => {
      const watchBtn = ev.target.closest ? ev.target.closest('[data-action="watch"]') : null;
      if (watchBtn) return;
      openResearch(id);
    });
    card.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        openResearch(id);
      }
    });
    const watchBtn = card.querySelector('[data-action="watch"]');
    if (watchBtn && CORE) {
      CORE.bindWatchButton(watchBtn, id, WATCHLIST, () => {
        renderWatchlist();
        syncWatchButtons();
      });
    }
  });
}

/* --- open an index in the research section ---------------------------- */
function openResearch(indexId) {
  const opt = OPTS.find(o => o.index_id === indexId);
  if (!opt) return;
  navigate('research');
  $('#market').value = opt.market;
  renderIndices(opt.index_id);
  load();
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

/* --- public hook surface for the dependent comparison task -------------- */
function installWorkbenchHooks() {
  const compareRoot = $('#compare-root');
  const compareCallbacks = [];
  let compareBound = false;
  window.__WORKBENCH__ = {
    version: 'v2.1',
    sections: ['overview', 'research', 'compare', 'watchlist'],
    navigate: navigate,
    compareMount: compareRoot,
    onCompareReady: function (callback) {
      if (typeof callback !== 'function') return;
      compareCallbacks.push(callback);
      if (compareRoot && !compareBound) {
        compareBound = true;
        try { callback(compareRoot); } catch (err) { /* keep the page alive */ }
      }
    },
    requestDailyK: function (indexId, start, end) {
      const opt = OPTS.find(o => o.index_id === indexId);
      return cachedPayload(paramsFor(indexId, opt ? opt.market : '', start, end));
    },
    watchlist: {
      list: () => WATCHLIST.list(),
      has: id => WATCHLIST.has(id),
      add: id => WATCHLIST.add(id),
      remove: id => WATCHLIST.remove(id),
      isPersistent: () => WATCHLIST.isPersistent(),
      notice: () => WATCHLIST.noticeText()
    },
    options: OPTS
  };
}

document.addEventListener('DOMContentLoaded', () => {
  renderOptions();
  initTabs();
  initZoom();
  installWorkbenchHooks();

  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.nav));
  });

  $$('#strip .mcard').forEach(card => {
    const id = card.dataset.index;
    card.addEventListener('click', ev => {
      const watchBtn = ev.target.closest ? ev.target.closest('[data-action="watch"]') : null;
      if (watchBtn) return;
      openResearch(id);
    });
    card.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        openResearch(id);
      }
    });
    const watchBtn = card.querySelector('[data-action="watch"]');
    if (watchBtn && CORE) {
      CORE.bindWatchButton(watchBtn, id, WATCHLIST, () => {
        renderWatchlist();
        syncWatchButtons();
      });
    }
  });

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

  navigate('overview');
  renderWatchlist();
  syncWatchButtons();
  load();
});
"""


def nav_items_html() -> str:
    """Render the top-bar navigation: four real, reachable workbench sections."""

    items = []
    for item in NAV_ITEMS:
        key = _text(item.get("key"))
        label = _text(item.get("label"))
        active = ' is-active' if item.get("key") == "overview" else ""
        current = ' aria-current="page"' if item.get("key") == "overview" else ""
        items.append(
            f'<button type="button" class="nav-item{active}" data-nav="{key}"'
            f"{current}>{label}</button>"
        )
    return "".join(items)


def selector_options() -> list[dict[str, Any]]:
    """Return selector options derived from the canonical global-index registry.

    Each option also carries the legacy aliases the *existing* identity
    vocabulary recognises for that index, so the browser can normalise an old
    stored watchlist id without a second registry.
    """

    from analysis.research.global_market_research import list_index_choices

    aliases = legacy_alias_map()
    options: list[dict[str, Any]] = []
    for choice in list_index_choices():
        option = dict(choice)
        option["aliases"] = list(aliases.get(str(option.get("index_id")), []))
        options.append(option)
    return options


def _overview_cards_html(options: Sequence[Mapping[str, Any]]) -> str:
    """Render one card per registered index, grouped by market."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for option in options:
        market = str(option.get("market") or "")
        if market not in grouped:
            grouped[market] = []
            order.append(market)
        grouped[market].append(option)

    blocks = []
    for market in order:
        items = grouped[market]
        cards = []
        for option in items:
            index_id = str(option.get("index_id") or "")
            name = str(option.get("name") or index_id)
            currency = str(option.get("currency") or "")
            cards.append(
                f'<article class="mcard" data-index="{_text(index_id)}" '
                f'data-market="{_text(market)}" tabindex="0">'
                f'<div class="mcard-head"><h4>{_text(name)}</h4>'
                f'<span class="mcard-market">{_text(_market_label(market))} · {_text(currency)}</span>'
                "</div>"
                '<div class="mcard-close" data-field="close">读取中…</div>'
                '<div class="mcard-change" data-field="change">最新日K收盘 · 非实时行情</div>'
                '<dl class="mcard-meta">'
                "<dt>数据日期</dt><dd data-field=\"date\">—</dd>"
                "<dt>新鲜度</dt><dd data-field=\"freshness\">—</dd>"
                "<dt>可用性</dt><dd data-field=\"availability\">—</dd>"
                "<dt>来源</dt><dd data-field=\"source\">—</dd>"
                "<dt>交易日历</dt><dd data-field=\"calendar\">未知（无交易日历证据）</dd>"
                "</dl>"
                '<div class="mcard-actions">'
                f'<button type="button" class="btn" data-action="open" '
                f'aria-label="进入 {_text(name)} 研究">进入研究</button>'
                f'<button type="button" class="btn watch" data-action="watch" '
                f'data-index="{_text(index_id)}" aria-pressed="false">加入自选</button>'
                "</div></article>"
            )
        blocks.append(
            f'<section class="market-group" data-market="{_text(market)}">'
            f"<h3>{_text(_market_label(market))} · {len(items)} 个指数 · "
            f"{'已验证数据源' if all(o.get('proven') == 'yes' for o in items) else '含未验证数据源'}"
            "</h3>"
            f'<div class="cards">{"".join(cards)}</div></section>'
        )
    return "".join(blocks)


def render_global_market_research_page(
    options: Sequence[Mapping[str, Any]] | None = None,
    *,
    start_date: str = "",
    end_date: str = "",
    api_path: str = DEFAULT_API_PATH,
) -> str:
    """Render the Swartee Market Research workbench shell.

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
        f"<style>{_STYLE}{COMPARISON_STYLE}</style></head><body>\n"
        '<header class="topbar"><div class="brand"><b>' + _text(PRODUCT_NAME) + "</b><span>"
        + _text(PRODUCT_SUBTITLE) + "</span></div>"
        f'<nav class="nav" aria-label="主导航">{nav_items_html()}</nav>'
        '<div class="scope">数据口径：本地研究服务的<b>最新日线收盘</b>，非实时行情；'
        "涨跌幅仅在相邻两日收盘均可得时展示，并标注基准日期。</div></header>\n"
        '<main>'
        '<section class="section" id="section-overview" data-section="overview">'
        '<div class="panel overview"><h2 class="panel-h">全球市场概览 '
        '<small>最新日K收盘 · 非实时行情</small></h2>'
        '<div class="muted" style="font-size:12px;margin-bottom:8px">'
        "共 " + str(len(choices)) + " 个注册指数；每个指数展示自己的数据日期、来源、"
        "新鲜度与可用性。点击卡片即可进入该指数的日线研究。</div>"
        f'<div id="strip" class="overview-grid">{_overview_cards_html(choices)}</div>'
        "</div></section>"
        '<section class="section" id="section-research" data-section="research" hidden>'
        '<div class="grid3">'
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
        "</div>"
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
        "</section>"
        '<section class="section" id="section-compare" data-section="compare" hidden>'
        '<div class="panel"><h2 class="panel-h">市场比较 <small>统一基准 = 100</small></h2>'
        '<div class="muted" style="font-size:12px">'
        "跨市场比较使用统一基准归一化（基准日收盘归一化为 100），不同市场的指数点位"
        "不直接比较；各指数的数据日期与来源分别标注，缺失日期保留缺失含义。</div>"
        '<div id="compare-root" class="compare-mount" data-compare-mount="1"></div>'
        '<div class="muted" id="compare-status" style="font-size:12px">'
        "选择指数后比较历史收盘的累计表现。</div>"
        "</div></section>"
        '<section class="section" id="section-watchlist" data-section="watchlist" hidden>'
        '<div class="panel"><h2 class="panel-h">自选关注 <small id="watch-count">0 个指数</small></h2>'
        '<p class="notice" id="watch-notice" role="status" aria-live="polite" hidden></p>'
        '<div class="cards" id="watch-list"></div>'
        '<div class="muted" id="watch-empty">还没有自选指数。在「市场总览」点击卡片上的'
        "「加入自选」即可添加，自选会保存在浏览器本地。</div>"
        "</div></section>"
        "</main>\n"
        f'<script>window.__OPTS={payload};window.__API={api_payload};</script>\n'
        f'<script id="swartea-core-js">{_CORE_JS}</script>\n'
        f"<script>{_JS}</script>\n"
        f"<script>{COMPARISON_JS}</script>\n"
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
