"""Behavioural tests for the Swartea Market Research workbench (V2.1).

Two layers are covered:

* **Python / structural** — the workbench shell really exposes the four live
  sections, the overview really lists all nine registered indices grouped by
  market, the watchlist really stores canonical ids only, and the comparison
  section really ships a mount point plus a JS hook contract.
* **JavaScript / Node** — the *same* script source that the page ships is
  executed under Node (``vm``) and exercised as a behaviour: watchlist
  add / remove / dedup / persist / reload, corrupt and retired storage,
  storage that throws (memory fallback disclosure), legacy-alias
  normalisation, the adjacent-close change rule, section switching and the
  "the watchlist button must not navigate" guarantee.

Everything is offline: no provider, no network, no browser.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.research import market_research_view as view
from analysis.research.global_indices import list_global_indices
from analysis.research.index_registry import INDEX_ID_ALIASES

NODE = shutil.which("node")

requires_node = pytest.mark.skipif(NODE is None, reason="node is required for the JS behaviour tests")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _page() -> str:
    return view.render_global_market_research_page()


def _core_script() -> str:
    """Extract the shipped core script from the rendered page."""

    page = _page()
    match = re.search(r'<script id="swartea-core-js">(.*?)</script>', page, re.S)
    assert match, "the workbench must ship the core script"
    return match.group(1)


# The Node harness. It runs the extracted core script in a fresh V8 context and
# reports the observed behaviour as JSON so the Python test can assert on it.
_HARNESS_JS = r"""
const fs = require('fs');
const vm = require('vm');

const coreSource = fs.readFileSync(process.argv[2], 'utf8');
const sandbox = {console: console};
vm.createContext(sandbox);
vm.runInContext(coreSource, sandbox);
const core = sandbox.SwarteaCore;

const KNOWN = ['cn.index.sh_comp', 'cn.index.sz_component', 'hk.index.hang_seng.hsi'];
const ALIASES = {
  'cn.index.sse.000001': 'cn.index.sh_comp',
  'sse.composite': 'cn.index.sh_comp',
  'csi.300': 'cn.index.csi300'
};
const KEY = 'swartea.market-research.watchlist.v1';

function makeStorage(initial) {
  const data = Object.assign({}, initial || {});
  return {
    data: data,
    getItem: function (k) {
      return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null;
    },
    setItem: function (k, v) { data[k] = String(v); },
    removeItem: function (k) { delete data[k]; }
  };
}

function throwingStorage() {
  return {
    getItem: function () { throw new Error('SecurityError: storage denied'); },
    setItem: function () { throw new Error('SecurityError: storage denied'); }
  };
}

function fakeEl() {
  const classes = new Set();
  return {
    hidden: false,
    attrs: {},
    classList: {
      toggle: function (name, on) { if (on) { classes.add(name); } else { classes.delete(name); } },
      contains: function (name) { return classes.has(name); }
    },
    setAttribute: function (k, v) { this.attrs[k] = v; },
    removeAttribute: function (k) { delete this.attrs[k]; }
  };
}

function fakeButton() {
  const listeners = {};
  return {
    listeners: listeners,
    addEventListener: function (type, fn) { listeners[type] = fn; }
  };
}

function fakeEvent() {
  return {
    stopped: false,
    prevented: false,
    stopPropagation: function () { this.stopped = true; },
    preventDefault: function () { this.prevented = true; }
  };
}

const out = {};

/* --- watchlist: add / dedup / remove / empty ------------------------- */
const storage = makeStorage();
const store = core.createWatchlist({storage: storage, knownIds: KNOWN, aliasMap: ALIASES});
out.empty_at_start = store.list();
out.add_first = store.add('cn.index.sh_comp');
out.add_duplicate = store.add('cn.index.sh_comp');
out.list_after_add = store.list();
out.stored_payload = storage.data[KEY];
out.add_unknown = store.add('jp.index.n225');
out.list_after_unknown = store.list();
out.remove = store.remove('cn.index.sh_comp');
out.list_after_remove = store.list();
out.remove_missing = store.remove('cn.index.sh_comp');

/* --- legacy alias: normalised to the canonical id --------------------- */
const aliasStorage = makeStorage();
const aliasStore = core.createWatchlist({
  storage: aliasStorage, knownIds: KNOWN, aliasMap: ALIASES
});
out.add_legacy_alias = aliasStore.add('sse.composite');
out.list_after_alias = aliasStore.list();
out.stored_payload_after_alias = aliasStorage.data[KEY];
out.has_alias = aliasStore.has('sse.composite');
out.has_canonical = aliasStore.has('cn.index.sh_comp');
// A second spelling of the very same index is a duplicate: never a second
// entry, and never a second copy in storage.
out.add_legacy_alias_again = aliasStore.add('sse.composite');
out.list_after_alias_again = aliasStore.list();
out.stored_payload_after_alias_again = aliasStorage.data[KEY];

/* --- persistence across a reload ------------------------------------- */
const persisted = makeStorage({[KEY]: JSON.stringify(['cn.index.sh_comp', 'hk.index.hang_seng.hsi'])});
const reloaded = core.createWatchlist({storage: persisted, knownIds: KNOWN, aliasMap: ALIASES});
out.reload_list = reloaded.list();
out.reload_persistent = reloaded.isPersistent();

/* --- corrupt storage -------------------------------------------------- */
const corrupt = makeStorage({[KEY]: 'not-json{{{'});
const corruptStore = core.createWatchlist({storage: corrupt, knownIds: KNOWN, aliasMap: ALIASES});
out.corrupt_list = corruptStore.list();
out.corrupt_notice = corruptStore.noticeText();
out.corrupt_stored = corrupt.data[KEY];

const wrongShape = makeStorage({[KEY]: JSON.stringify({ids: ['cn.index.sh_comp']})});
const wrongShapeStore = core.createWatchlist({
  storage: wrongShape, knownIds: KNOWN, aliasMap: ALIASES
});
out.wrong_shape_list = wrongShapeStore.list();
out.wrong_shape_notice = wrongShapeStore.noticeText();

/* --- retired / duplicate / alias entries in storage -------------------- */
const retired = makeStorage({
  [KEY]: JSON.stringify(['jp.index.n225', 'cn.index.sh_comp', 'cn.index.sh_comp', 'sse.composite'])
});
const retiredStore = core.createWatchlist({storage: retired, knownIds: KNOWN, aliasMap: ALIASES});
out.retired_list = retiredStore.list();
out.retired_notice = retiredStore.noticeText();
out.retired_stored = retired.data[KEY];

/* --- storage that throws ---------------------------------------------- */
const throwing = throwingStorage();
const throwingStore = core.createWatchlist({
  storage: throwing, knownIds: KNOWN, aliasMap: ALIASES
});
out.throwing_list = throwingStore.list();
out.throwing_persistent = throwingStore.isPersistent();
out.throwing_notice = throwingStore.noticeText();
out.throwing_add = throwingStore.add('cn.index.sh_comp');
out.throwing_list_after_add = throwingStore.list();

/* --- no storage at all ------------------------------------------------ */
const noStore = core.createWatchlist({storage: null, knownIds: KNOWN, aliasMap: ALIASES});
out.no_storage_persistent = noStore.isPersistent();
out.no_storage_notice = noStore.noticeText();
out.no_storage_add = noStore.add('cn.index.sh_comp');
out.no_storage_list = noStore.list();

/* --- normalisation ----------------------------------------------------- */
out.normalize_canonical = core.normalizeId('cn.index.sh_comp', KNOWN, ALIASES);
out.normalize_legacy = core.normalizeId('sse.composite', KNOWN, ALIASES);
out.normalize_legacy_upper = core.normalizeId('cn.index.sse.000001', KNOWN, ALIASES);
out.normalize_unknown = core.normalizeId('jp.index.n225', KNOWN, ALIASES);
out.normalize_non_string = core.normalizeId(42, KNOWN, ALIASES);
out.normalize_blank = core.normalizeId('   ', KNOWN, ALIASES);
out.normalize_trimmed = core.normalizeId('  cn.index.sh_comp  ', KNOWN, ALIASES);

/* --- adjacent-close change rule --------------------------------------- */
out.two_closes = core.latestClose([
  {date: '2026-09-24', close: 3040.0},
  {date: '2026-09-25', close: 3075.5}
]);
out.one_close = core.latestClose([{date: '2026-09-25', close: 3075.5}]);
out.zero_base = core.latestClose([
  {date: '2026-09-24', close: 0},
  {date: '2026-09-25', close: 3075.5}
]);
out.missing_base = core.latestClose([
  {date: '2026-09-24', close: null},
  {date: '2026-09-25', close: 3075.5}
]);
out.string_close = core.latestClose([
  {date: '2026-09-24', close: '3040.0'},
  {date: '2026-09-25', close: '3075.5'}
]);
out.no_bars = core.latestClose([]);
out.no_dated_bars = core.latestClose([{close: 1.0}, null, {date: '', close: 2.0}]);

/* --- section switching ------------------------------------------------- */
const overviewEl = fakeEl();
const researchEl = fakeEl();
const compareEl = fakeEl();
const watchEl = fakeEl();
const overviewNav = fakeEl();
const compareNav = fakeEl();
core.activateSection('compare',
  [{key: 'overview', el: overviewEl}, {key: 'research', el: researchEl},
   {key: 'compare', el: compareEl}, {key: 'watchlist', el: watchEl}],
  [{key: 'overview', el: overviewNav}, {key: 'compare', el: compareNav}]);
out.section_hidden = {
  overview: overviewEl.hidden, research: researchEl.hidden,
  compare: compareEl.hidden, watchlist: watchEl.hidden
};
out.section_nav_active = {
  overview: overviewNav.classList.contains('is-active'),
  compare: compareNav.classList.contains('is-active')
};
out.section_aria_current = {
  overview: overviewNav.attrs['aria-current'] || null,
  compare: compareNav.attrs['aria-current'] || null
};

/* --- the watchlist button must never navigate ------------------------- */
const navStore = core.createWatchlist({storage: makeStorage(), knownIds: KNOWN, aliasMap: ALIASES});
const button = fakeButton();
let changed = null;
core.bindWatchButton(button, 'cn.index.sh_comp', navStore, function (id, added) {
  changed = {id: id, added: added};
});
const ev = fakeEvent();
button.listeners.click(ev);
out.watch_event_stopped = ev.stopped;
out.watch_event_prevented = ev.prevented;
out.watch_store_list = navStore.list();
out.watch_changed = changed;

console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def core_behaviour(tmp_path_factory) -> dict:
    """Run the shipped core script under Node and return the observed behaviour."""

    if NODE is None:  # pragma: no cover - guarded by the skip marker
        pytest.skip("node is required for the JS behaviour tests")
    workdir = tmp_path_factory.mktemp("workbench-js")
    core_path = workdir / "core.js"
    harness_path = workdir / "harness.js"
    core_path.write_text(_core_script(), encoding="utf-8")
    harness_path.write_text(_HARNESS_JS, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness_path), str(core_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node harness failed: {proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# JavaScript behaviour (Node)
# ---------------------------------------------------------------------------


@requires_node
def test_watchlist_adds_dedups_and_lists_canonical_ids(core_behaviour):
    assert core_behaviour["empty_at_start"] == []
    assert core_behaviour["add_first"] is True
    assert core_behaviour["add_duplicate"] is False, "the same index must not be added twice"
    assert core_behaviour["list_after_add"] == ["cn.index.sh_comp"]
    # Only canonical ids are persisted — no alias is written to storage.
    assert json.loads(core_behaviour["stored_payload"]) == ["cn.index.sh_comp"]


@requires_node
def test_watchlist_persists_across_a_reload(core_behaviour):
    assert core_behaviour["reload_list"] == ["cn.index.sh_comp", "hk.index.hang_seng.hsi"]
    assert core_behaviour["reload_persistent"] is True


@requires_node
def test_watchlist_removal_and_empty_state(core_behaviour):
    assert core_behaviour["remove"] is True
    assert core_behaviour["list_after_remove"] == []
    assert core_behaviour["remove_missing"] is False


@requires_node
def test_watchlist_rejects_unknown_and_retired_ids_safely(core_behaviour):
    assert core_behaviour["add_unknown"] is False
    assert core_behaviour["remove_missing"] is False
    assert "jp.index.n225" not in core_behaviour["list_after_add"]
    # An unknown id never reaches the list and never changes the storage.
    assert core_behaviour["list_after_unknown"] == ["cn.index.sh_comp"]


@requires_node
def test_legacy_alias_is_normalised_to_the_canonical_id(core_behaviour):
    # A legacy alias is accepted and stored as the canonical id only.
    assert core_behaviour["add_legacy_alias"] is True
    assert core_behaviour["list_after_alias"] == ["cn.index.sh_comp"]
    assert json.loads(core_behaviour["stored_payload_after_alias"]) == ["cn.index.sh_comp"]
    assert core_behaviour["has_alias"] is True
    assert core_behaviour["has_canonical"] is True
    # Adding the same index again through another spelling never duplicates it.
    assert core_behaviour["add_legacy_alias_again"] is False
    assert core_behaviour["list_after_alias_again"] == ["cn.index.sh_comp"]
    assert json.loads(core_behaviour["stored_payload_after_alias_again"]) == ["cn.index.sh_comp"]
    assert core_behaviour["normalize_legacy"] == "cn.index.sh_comp"
    assert core_behaviour["normalize_legacy_upper"] == "cn.index.sh_comp"
    assert core_behaviour["normalize_canonical"] == "cn.index.sh_comp"
    assert core_behaviour["normalize_trimmed"] == "cn.index.sh_comp"
    assert core_behaviour["normalize_unknown"] is None
    assert core_behaviour["normalize_non_string"] is None
    assert core_behaviour["normalize_blank"] is None


@requires_node
def test_corrupt_storage_is_reset_without_crashing(core_behaviour):
    assert core_behaviour["corrupt_list"] == []
    assert "损坏" in core_behaviour["corrupt_notice"]
    # The corrupt payload is replaced by an empty, valid one.
    assert json.loads(core_behaviour["corrupt_stored"]) == []
    # A well-formed JSON value of the wrong shape is handled the same way.
    assert core_behaviour["wrong_shape_list"] == []
    assert core_behaviour["wrong_shape_notice"]


@requires_node
def test_retired_and_duplicate_stored_entries_are_dropped(core_behaviour):
    assert core_behaviour["retired_list"] == ["cn.index.sh_comp"]
    assert "已退役" in core_behaviour["retired_notice"]
    assert json.loads(core_behaviour["retired_stored"]) == ["cn.index.sh_comp"]


@requires_node
def test_storage_that_throws_falls_back_to_memory_and_discloses_it(core_behaviour):
    assert core_behaviour["throwing_list"] == []
    assert core_behaviour["throwing_persistent"] is False
    assert core_behaviour["throwing_notice"], "the memory fallback must be disclosed"
    assert "内存" in core_behaviour["throwing_notice"]
    # The watchlist still works in memory.
    assert core_behaviour["throwing_add"] is True
    assert core_behaviour["throwing_list_after_add"] == ["cn.index.sh_comp"]


@requires_node
def test_missing_storage_falls_back_to_memory_and_discloses_it(core_behaviour):
    assert core_behaviour["no_storage_persistent"] is False
    assert "内存" in core_behaviour["no_storage_notice"]
    assert core_behaviour["no_storage_add"] is True
    assert core_behaviour["no_storage_list"] == ["cn.index.sh_comp"]


@requires_node
def test_change_requires_two_valid_closes(core_behaviour):
    two = core_behaviour["two_closes"]
    assert two["date"] == "2026-09-25"
    assert two["close"] == 3075.5
    assert two["prevDate"] == "2026-09-24"
    assert two["prevClose"] == 3040.0
    assert round(two["changePct"], 6) == round((3075.5 - 3040.0) / 3040.0 * 100, 6)

    # A single bar never produces a percentage.
    assert core_behaviour["one_close"]["changePct"] is None
    # A zero base price is not a valid base.
    assert core_behaviour["zero_base"]["changePct"] is None
    # A missing base close is not a valid base either.
    assert core_behaviour["missing_base"]["changePct"] is None
    # Numeric strings are read as numbers, not as text.
    assert core_behaviour["string_close"]["changePct"] is not None
    # No bars at all is a safe null, not a crash.
    assert core_behaviour["no_bars"] is None
    assert core_behaviour["no_dated_bars"] is None


@requires_node
def test_section_switching_hides_the_other_sections(core_behaviour):
    hidden = core_behaviour["section_hidden"]
    assert hidden["compare"] is False, "the requested section must be visible"
    assert hidden["overview"] is True
    assert hidden["research"] is True
    assert hidden["watchlist"] is True
    assert core_behaviour["section_nav_active"]["compare"] is True
    assert core_behaviour["section_nav_active"]["overview"] is False
    assert core_behaviour["section_aria_current"]["compare"] == "page"
    assert core_behaviour["section_aria_current"]["overview"] is None


@requires_node
def test_watchlist_button_never_navigates(core_behaviour):
    assert core_behaviour["watch_event_stopped"] is True, "the click must not bubble up"
    assert core_behaviour["watch_event_prevented"] is True
    assert core_behaviour["watch_store_list"] == ["cn.index.sh_comp"]
    assert core_behaviour["watch_changed"] == {"id": "cn.index.sh_comp", "added": True}


# ---------------------------------------------------------------------------
# Python: the workbench shell really exposes the product structure
# ---------------------------------------------------------------------------


def test_navigation_has_four_live_sections_and_no_dead_route():
    page = _page()
    nav = page.split('<nav class="nav"')[1].split("</nav>")[0]
    assert nav.count('class="nav-item') == 4
    for key, label in (
        ("overview", "市场总览"),
        ("research", "指数研究"),
        ("compare", "市场比较"),
        ("watchlist", "自选关注"),
    ):
        assert f'data-nav="{key}"' in nav
        assert f">{label}</button>" in nav
    # Real buttons, never links: there is no dead route in the shell.
    assert "<a " not in nav and "href" not in nav
    assert "规划中" not in nav
    # Every navigation entry has a matching section panel.
    for target in ("section-overview", "section-research", "section-compare", "section-watchlist"):
        assert f'id="{target}"' in page


def test_overview_is_the_default_homepage():
    page = _page()
    assert 'id="section-overview" data-section="overview">' in page
    # The other sections start hidden.
    for target in ("section-research", "section-compare", "section-watchlist"):
        assert f'id="{target}"' in page
        block = page.split(f'id="{target}"')[1].split(">")[0]
        assert "hidden" in block
    assert 'class="nav-item is-active" data-nav="overview" aria-current="page"' in page


def test_overview_lists_all_nine_registry_indices_grouped_by_market():
    page = _page()
    cards = re.findall(r'<article class="mcard" data-index="([^"]+)" data-market="([^"]+)"', page)
    registry = [(spec.identity.index_id, spec.market) for spec in list_global_indices()]
    assert sorted(cards) == sorted(registry)
    assert len(cards) == 9
    counts: dict[str, int] = {}
    for _, market in cards:
        counts[market] = counts.get(market, 0) + 1
    assert counts == {"cn": 4, "hk": 2, "us": 3}
    # The groups are rendered in registry order with their own heading.
    for market, label in (("cn", "中国内地"), ("hk", "中国香港"), ("us", "美国")):
        assert f'<section class="market-group" data-market="{market}">' in page
        assert f"{label} · " in page


def test_overview_card_shows_every_required_data_field():
    page = _page()
    card = page.split('<article class="mcard"')[1].split("</article>")[0]
    for field in ("close", "change", "date", "freshness", "availability", "source", "calendar"):
        assert f'data-field="{field}"' in card
    # The calendar stays unknown without trading-calendar evidence.
    assert "未知（无交易日历证据）" in card
    # One click opens the research, and the watchlist control is a real button.
    assert 'data-action="open"' in card
    assert 'data-action="watch"' in card
    assert 'aria-pressed="false"' in card
    assert "最新日K收盘" in card


def test_watchlist_section_and_storage_contract():
    page = _page()
    assert 'id="watch-list"' in page
    assert 'id="watch-empty"' in page
    assert 'id="watch-count"' in page
    assert 'id="watch-notice"' in page
    assert 'role="status"' in page and 'aria-live="polite"' in page
    assert view.WATCHLIST_STORAGE_KEY == "swartea.market-research.watchlist.v1"
    # Only canonical ids are persisted: the key and the shape are explicit.
    assert "swartea.market-research.watchlist.v1" in page
    assert "JSON.stringify(ids)" in page


def test_watchlist_uses_the_existing_identity_vocabulary_and_no_parallel_registry():
    aliases = view.legacy_alias_map()
    assert aliases["cn.index.sh_comp"] == ["sse.composite", "cn.index.sse.000001"]
    # Every alias the identity module knows is exposed for its canonical id.
    # (INDEX_ID_ALIASES maps alias -> canonical id.)
    for alias, canonical in INDEX_ID_ALIASES.items():
        assert alias in aliases[canonical]
    options = view.selector_options()
    assert [option["index_id"] for option in options] == [
        spec.identity.index_id for spec in list_global_indices()
    ]
    by_id = {option["index_id"]: option for option in options}
    assert "sse.composite" in by_id["cn.index.sh_comp"]["aliases"]
    # The alias map reaches the browser through the selector options.
    page = _page()
    assert "sse.composite" in page


def test_watchlist_quote_reuses_the_shared_cached_payload():
    page = _page()
    # The watchlist never issues a request of its own: it reuses the daily-K
    # response that the overview already cached for the same index.
    assert "function syncWatchQuote(indexId, p)" in page
    assert "syncWatchQuote(opt.index_id, p);" in page
    assert "payloadResults.get(requestFor(opt || {index_id:id, market:''}).toString())" in page
    assert "if (payload) syncWatchQuote(id, payload);" in page


def test_compare_section_exposes_a_clear_mount_point_and_hook():
    page = _page()
    assert 'id="compare-root"' in page
    assert 'data-compare-mount="1"' in page
    assert "function compare()" in page
    assert "fetch('/api/compare'" in page
    assert "work.requestDailyK" in page
    assert "统一基准" in page
    # The comparison task can reuse the shared bounded queue / cache.
    assert "function cachedPayload(params)" in page
    assert "activeRequests < 3" in page
    assert "payloadCache.has(key)" in page


def test_workbench_never_calls_a_provider_from_the_ui():
    page = _page()
    for forbidden in ("qt.gtimg.cn", "web.ifzq.gtimg.cn", "push2his.eastmoney.com", "baostock"):
        assert forbidden not in page
    assert '"/api/daily-k"' in page or "'/api/daily-k'" in page


def test_overview_and_detail_share_the_same_cache_and_queue():
    page = _page()
    assert "cachedPayload(requestFor(opt))" in page
    assert "cachedPayload(query())" in page
    assert "function pumpRequests()" in page
    # A stale overview response can never overwrite a newer one.
    assert "overviewTokens.get(opt.index_id) !== token" in page
    # A stale selected response can never overwrite a newer selection.
    assert "const seq = ++state.seq;" in page
    assert "if (seq !== state.seq) return;" in page


def test_workbench_keeps_the_v1_research_capabilities():
    page = _page()
    for hook in ('id="chart"', 'id="zoom"', 'id="pan"', 'id="prev"', 'id="next"',
                 'id="history"', 'id="start"', 'id="end"', 'id="go"',
                 'id="state"', 'id="probe"', 'id="kv"', 'id="raw"'):
        assert hook in page
    assert "getContext('2d')" in page
    assert "历史日线" in page and "数据口径" in page
    assert "涨跌幅基于相邻两日收盘" in page


def test_workbench_is_responsive_at_the_target_widths():
    page = _page()
    for query in ("@media (max-width:1280px)", "@media (max-width:768px)",
                  "@media (max-width:390px)", "@media (min-width:1440px)",
                  "@media (min-width:1920px)"):
        assert query in page
    # No fixed width can force a horizontal overflow.
    assert "overflow-x:auto" in page
    assert "minmax(0,1fr)" in page
    assert "max-width:1720px" in page


def test_workbench_controls_are_accessible():
    page = _page()
    nav = page.split('<nav class="nav"')[1].split("</nav>")[0]
    assert nav.count('type="button"') == 4
    assert 'aria-label="主导航"' in page
    assert 'aria-current="page"' in page
    assert 'tabindex="0"' in page
    assert 'aria-pressed="false"' in page
    assert 'aria-label="进入 ' in page
    assert ":focus-visible" in page
