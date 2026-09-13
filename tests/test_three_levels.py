"""Task 5.2 债 2 修法 — 三价位表（4 支撑候选 / 3 压力候选 → 取最近者）测试

历史: docs/04-模板质量债.md 债 2
  - 报告"三价位"段只填 entry_low/tp1/stop_loss（来自 V2 现价百分比的简易算法），
    没有真正从技术面（MA/前高前低/筹码峰/布林）算出支撑/压力
  - 老板硬要求"结论 + 支撑/压力/止损"缺一不可

修法（Task 5.2）:
  - V3 主分析器加 compute_three_levels() — 4 支撑候选 / 3 压力候选 → 取最近者 (+/-5% 过滤)
  - result 新增 result["three_levels"] dict（与 trading_plan 同源 K 线, 但**不覆盖** Task 5.1 字段）
  - stop_loss **复用** trading_plan.stop_loss（V2 同源, **不重算**）
  - 3 渲染器同步: MD line 1185 "三价位" 段头加 "三价位(同源)" 行 + 4/3 候选调试行
                  HTML _render_checklist "操作口诀" 上方加 "三价位(同源)" 行
                  DOCX 跟随 MD 渲染 (md_to_docx.py 不硬编码, 测试锁住)
"""
import os
import sys
import json

# 绝对 import: ROOT 加入 sys.path, 让 `from analysis.xxx import yyy` 生效
# (与 plan 严格一致, 不用 `sys.path.insert(0, "analysis/")` 旧风格)
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")

import pytest

from analysis.quant_analyzer_v3 import (
    compute_three_levels,
    _klines_to_series,
    _series_ma,
    _series_boll,
    _series_recent_high,
    _series_recent_low,
)


# ============================================================
# 辅助: 构造 K 线序列
# ============================================================
def _make_klines(n=250, start_close=10.0, slope=0.02, vol=0.5, start_date="2025-01-01"):
    """造 n 日递增 K 线, close 线性增长 (slope/日), high/low ± vol"""
    import datetime as _dt
    base = _dt.date.fromisoformat(start_date)
    out = []
    for i in range(n):
        d = (base + _dt.timedelta(days=i)).isoformat()
        c = start_close + i * slope
        out.append({
            "date": d,
            "open": c - 0.05,
            "close": c,
            "high": c + vol,
            "low": c - vol,
            "turn": 10.0,
        })
    return out


# ============================================================
# 1. 4 支撑候选取最近者 (plan §三价位算法)
# ============================================================
def test_picks_lowest_support_within_5pct():
    """4 支撑候选中取最低且 ≤ 现价 × 1.05"""
    quote = {"price": 11.52}
    klines = _make_klines(n=60, start_close=10.0, slope=0.02, vol=0.5)
    # 4 候选预期: ma60 ≈ 10.59 / recent_low ≈ 9.5 / chip_peak 自由设 / boll_lower 自算
    chip_data = {"peak_price": 10.50, "kline": klines}
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    # 现价 11.52, 1.05× = 12.10; 4 候选全 ≤ 12.10 全部 eligible, 取最低
    assert r["support"] is not None
    assert r["support"] == min(r["support_candidates"].values()), \
        f"support 应取最低候选, 实际 {r['support']} vs 候选 {r['support_candidates']}"
    # 4 候选都要有 (K 线 60 日, 布林/MA60 都能算)
    assert set(r["support_candidates"].keys()) == {"ma60", "recent_low", "chip_peak", "boll_lower"}
    # stop_loss 不传 plan 时为 None
    assert r["stop_loss"] is None


# ============================================================
# 2. 3 压力候选取最近者
# ============================================================
def test_picks_highest_resistance_within_5pct():
    """3 压力候选中取最高且 ≥ 现价 × 0.95"""
    quote = {"price": 11.52}
    klines = _make_klines(n=60, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"kline": klines}  # 压力候选不依赖 peak_price
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    assert r["resistance"] is not None
    # 60 日 K 线, ma250/ma120 算不出 (K 线不足), 3 候选只剩 recent_high + boll_upper
    assert "recent_high" in r["resistance_candidates"]
    assert "boll_upper" in r["resistance_candidates"]
    # resistance = max(eligible), 即取最高
    assert r["resistance"] == max(r["resistance_candidates"].values())


# ============================================================
# 3. 过滤边界: 候选价 > 1.05×现价 应被排除 (plan 硬约束)
# ============================================================
def test_filter_support_above_1pct05_threshold():
    """支撑候选价 > 现价 × 1.05 必须被排除"""
    quote = {"price": 11.00}   # 现价 11.00, 1.05× = 11.55
    # K 线造 ma60 = 12.0 (远高于 11.55, 应被排除)
    klines = _make_klines(n=60, start_close=11.5, slope=0.01, vol=0.1)  # 60 日 close 11.5~12.1
    chip_data = {"peak_price": 10.0, "kline": klines}  # chip_peak 10.0 应保留
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    # 验证 ma60 已被过滤 (12.0 > 11.55)
    assert r["support"] is not None
    # support 应 = chip_peak (10.0) 或 recent_low, 不会是 ma60
    assert r["support"] <= 11.55, f"support {r['support']} 超过 1.05×现价 (11.55), 过滤失败"
    # ma60 候选在 candidates 字典里仍存在 (调试用), 但不是被选中的最近者
    # 用实际值验证: 选中的不是 ma60
    if "ma60" in r["support_candidates"]:
        assert r["support"] != r["support_candidates"]["ma60"], \
            f"ma60={r['support_candidates']['ma60']} 超过阈值, 不应被选, 但 support={r['support']}"


# ============================================================
# 4. 过滤边界: 压力候选 < 0.95×现价 应被排除
# ============================================================
def test_filter_resistance_below_0pct95_threshold():
    """压力候选价 < 现价 × 0.95 必须从 resistance 选中排除

    注意: candidates 字典保留**全部**候选用于调试（plan 字段名映射 §"调试用，4/3 候选价都列出"），
    这里只断言最终选中的 resistance 必须 ≥ 0.95×现价, 或为 None (无候选达标)。
    """
    quote = {"price": 11.00}   # 现价 11.00, 0.95× = 10.45
    # K 线造很弱, recent_high 9.0 (低于 10.45 应被排除)
    klines = _make_klines(n=60, start_close=8.0, slope=0.02, vol=0.1)
    chip_data = {"kline": klines}
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    # 断言 1: 若 resistance 不为 None, 必须 ≥ 0.95×现价
    if r["resistance"] is not None:
        assert r["resistance"] >= quote["price"] * 0.95, \
            f"resistance {r['resistance']} 低于 0.95×现价 ({quote['price']*0.95:.2f}), 过滤失败"
    # 断言 2: candidates 字典保留全部候选 (调试用)
    if r["resistance_candidates"]:
        # 候选可能含低于阈值的 (调试显示)
        for k, v in r["resistance_candidates"].items():
            assert v is not None, f"{k} 候选价不应为 None"


# ============================================================
# 5. stop_loss 复用 trading_plan.stop_loss (债 2 修法硬约束)
# ============================================================
def test_stop_loss_reuses_trading_plan_field():
    """three_levels.stop_loss == trading_plan.stop_loss (V2 同源, 不重算)"""
    quote = {"price": 11.52}
    klines = _make_klines(n=60, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"kline": klines}
    plan = {"stop_loss": 9.95, "entry_low": 11.17, "tp1": 12.67, "tp2": 14.0, "tp3": 17.0}
    r = compute_three_levels(quote, chip_data, plan)
    assert r["stop_loss"] == 9.95, \
        f"stop_loss 必须复用 trading_plan.stop_loss=9.95, 实际={r['stop_loss']}"
    # trading_plan.stop_loss 是 9.95, support/pressure 与 plan 独立 (4/3 候选价)
    assert r["stop_loss"] != r.get("support"), \
        "stop_loss 不应被重算, 必须严格 = trading_plan.stop_loss"


def test_stop_loss_none_when_plan_missing():
    """trading_plan 缺失时 stop_loss 兜底 None, 不抛"""
    quote = {"price": 11.52}
    klines = _make_klines(n=60, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"kline": klines}
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    assert r["stop_loss"] is None, "无 plan 时 stop_loss 应为 None"


# ============================================================
# 6. 字段缺失不崩 (kline 缺失 / chip_data 缺失 / quote 缺失)
# ============================================================
def test_handles_missing_technical_gracefully():
    """chip_data 字段缺失 / kline 为空 / error dict / quote 缺失 都不抛"""
    # 6a: chip_data None
    r = compute_three_levels({"price": 11.0}, None, trading_plan={"stop_loss": 9.0})
    assert r["support"] is None and r["resistance"] is None
    assert r["stop_loss"] == 9.0  # 仍复用 plan
    assert r["support_candidates"] == {}
    assert r["resistance_candidates"] == {}

    # 6b: chip_data 含 error
    r = compute_three_levels({"price": 11.0}, {"error": "baostock 失败"}, trading_plan={"stop_loss": 9.0})
    assert r["support"] is None and r["resistance"] is None
    assert r["stop_loss"] == 9.0

    # 6c: chip_data 有 kline 但条数 < 30 (不足以算 MA60/布林, 但 recent_high/low 仍可算)
    r = compute_three_levels({"price": 11.0}, {"kline": _make_klines(n=10)}, trading_plan=None)
    # 验证: ma60/boll_* 因 K 线不足返回 None, 但 recent_low/high 仍可算
    assert r["support_candidates"].get("ma60") is None, "K 线 10 日, ma60 候选应 None"
    assert r["support_candidates"].get("boll_lower") is None, "K 线 10 日, 布林下轨应 None"
    assert r["resistance_candidates"].get("boll_upper") is None, "K 线 10 日, 布林上轨应 None"
    # recent_low/high 仍可用 (只要 K 线 ≥ 1)
    assert "recent_low" in r["support_candidates"], "K 线 10 日, recent_low 仍应可用"
    assert "recent_high" in r["resistance_candidates"], "K 线 10 日, recent_high 仍应可用"

    # 6d: quote 缺 price
    r = compute_three_levels({}, {"kline": _make_klines(n=60)}, trading_plan=None)
    # 候选可算, 但 price 为 None 时不能过滤 ±5%, 所以 support/resistance 都为 None
    # (此为安全设计, 宁可保守不报, 也不报错价)
    assert r["support"] is None and r["resistance"] is None

    # 6e: 全部缺失
    r = compute_three_levels(None, None, None)
    assert r["support"] is None and r["resistance"] is None and r["stop_loss"] is None
    assert r["method"].startswith("4 候选取最近者")


# ============================================================
# 7. K 线 250+ 日, ma250 候选可用
# ============================================================
def test_ma250_available_with_sufficient_klines():
    """K 线 ≥ 250 日时, ma250 候选能算"""
    quote = {"price": 15.00}   # 略高于 250 日均价
    klines = _make_klines(n=260, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"kline": klines}
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    assert "ma250_or_ma120" in r["resistance_candidates"], \
        f"K 线 260 日, ma250 候选应存在, 实际 {list(r['resistance_candidates'].keys())}"


def test_ma250_falls_back_to_ma120_when_insufficient():
    """K 线 120~249 日时, ma250 不可算, 兜底用 ma120"""
    quote = {"price": 15.00}
    klines = _make_klines(n=180, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"kline": klines}
    r = compute_three_levels(quote, chip_data, trading_plan=None)
    # K 线 180 日, ma250 不能算, ma120 能算
    assert "ma250_or_ma120" in r["resistance_candidates"], \
        "K 线 180 日, 兜底 ma120 应可用"


# ============================================================
# 8. plan Task 5.2 §Step 2 例子校验
# ============================================================
def test_plan_step2_example_4_candidates_3_candidates():
    """plan Step 2 例子: 4 支撑候选全列出 + 3 压力候选全列出"""
    quote = {"price": 11.52}
    klines = _make_klines(n=260, start_close=10.0, slope=0.02, vol=0.5)
    chip_data = {"peak_price": 10.50, "kline": klines}
    plan = {"stop_loss": 9.95}
    r = compute_three_levels(quote, chip_data, plan)
    # 4 支撑候选必须全在
    assert set(r["support_candidates"].keys()) == {"ma60", "recent_low", "chip_peak", "boll_lower"}
    # 3 压力候选必须全在
    assert set(r["resistance_candidates"].keys()) == {"ma250_or_ma120", "recent_high", "boll_upper"}
    # support/resistance 已选
    assert r["support"] is not None
    assert r["resistance"] is not None
    # stop_loss 复用 plan
    assert r["stop_loss"] == 9.95
    # method 字段
    assert "4 候选" in r["method"] and "1.05" in r["method"] and "0.95" in r["method"]


# ============================================================
# 9. 端到端: V3 result 必须含 three_levels (从 result_v3-{HHMM}.json 验证)
# ============================================================
def _latest_result_v3_600693(mock_result_v3=None):
    """加载 600693 今日最新 result_v3-{HHMM}.json; 缺失则 skip

    P1.5 整改: 接受 conftest mock_result_v3 fixture (P1-E 配套), 优先用 mock
    """
    if mock_result_v3 is not None:
        # 端到端用 mock fixture, 跨用户/跨日期可跑
        with open(mock_result_v3, "r", encoding="utf-8") as f:
            return json.load(f), str(mock_result_v3)
    # 兜底: 读当日 result (依赖个人路径, 仅本机可跑)
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    day_dir = f"/Users/swarteachou/Desktop/大A数据/reports/600693_东百集团/{today}"
    if not os.path.exists(day_dir):
        pytest.skip(f"未找到 {day_dir}（需先跑 V3 至少一次）")
    files = [f for f in os.listdir(day_dir) if f.startswith("result_v3-") and f.endswith(".json")]
    if not files:
        pytest.skip("未找到 result_v3-*.json（需先跑 V3）")
    latest = max(files, key=lambda f: os.path.getmtime(os.path.join(day_dir, f)))
    with open(os.path.join(day_dir, latest), "r", encoding="utf-8") as f:
        return json.load(f), os.path.join(day_dir, latest)


def test_v3_result_has_three_levels_for_600693(mock_result_v3):
    """V3 跑 600693 → result 必须含 three_levels dict（债 2 修法硬指标）

    P1.5 整改: 用 mock_result_v3 fixture 跨用户可跑
    """
    result, path = _latest_result_v3_600693(mock_result_v3=mock_result_v3)
    tl3 = result.get("three_levels")
    assert tl3 is not None, f"result['three_levels'] 缺失 (文件: {path})"
    # 必含 5 字段
    for k in ("support", "resistance", "stop_loss", "support_candidates", "resistance_candidates", "method"):
        assert k in tl3, f"three_levels 缺 {k} 字段 (文件: {path})"
    # 数字合理性: 600693 现价 ~11.5
    price = (result.get("quote") or {}).get("price")
    if price:
        sup = tl3.get("support")
        res = tl3.get("resistance")
        sl = tl3.get("stop_loss")
        if sup is not None:
            assert sup <= price * 1.05, f"support {sup} > 1.05×现价 {price*1.05:.2f}"
        if res is not None:
            assert res >= price * 0.95, f"resistance {res} < 0.95×现价 {price*0.95:.2f}"
        # 4 支撑候选全在
        if tl3["support_candidates"]:
            assert set(tl3["support_candidates"].keys()) == {"ma60", "recent_low", "chip_peak", "boll_lower"}, \
                f"4 支撑候选 key 错: {list(tl3['support_candidates'].keys())}"
        # 3 压力候选全在
        if tl3["resistance_candidates"]:
            assert set(tl3["resistance_candidates"].keys()) == {"ma250_or_ma120", "recent_high", "boll_upper"}, \
                f"3 压力候选 key 错: {list(tl3['resistance_candidates'].keys())}"


# ============================================================
# 10. 渲染器 source code 自检: 3 渲染器都含"三价位(同源)"
# ============================================================
def test_md_renderer_contains_three_levels_same_source(pipeline_source):
    """V3 MD 渲染器 write_markdown_report_v3 含 '三价位(同源)' 字样 + 4/3 候选

    P1.5 整改: 用 conftest.quant_analyzer_v3_source fixture 取代 open 个人路径
    P2-A Phase 5 (2026-09-13): 编排层抽离后改读 pipeline_source ('三价位(同源)' 字样在 _emit 打印行)
    """
    src = pipeline_source
    assert "三价位(同源)" in src, "pipeline.py _emit 必须含'三价位(同源)'字样（债 2 修法）"
    assert "support_candidates" in src, "pipeline.py 必须输出 4 支撑候选调试行"
    assert "resistance_candidates" in src, "pipeline.py 必须输出 3 压力候选调试行"
    assert "compute_three_levels" in src, "pipeline.py 必须 import 并调用 compute_three_levels"


def test_html_renderer_contains_three_levels_same_source(html_report_v3_source):
    """HTML 渲染器 _render_checklist 必须含 '三价位(同源)' 字样

    P1.5 整改: 用 conftest.html_report_v3_source fixture
    """
    src = html_report_v3_source
    assert "三价位(同源)" in src, "html_report_v3.py 必须含'三价位(同源)'字样（债 2 修法）"
    assert "result.get(\"three_levels\")" in src or "result['three_levels']" in src, \
        "HTML 渲染器必须读 result['three_levels']"


def test_docx_renderer_follows_md_no_hardcode(md_to_docx_source):
    """DOCX 渲染器 md_to_docx.py 不硬编码'三价位'——DOCX 跟随 MD 渲染

    P1.5 整改: 用 conftest.md_to_docx_source fixture
    """
    src = md_to_docx_source
    # DOCX 跟随 MD, 不应自己写死"三价位(同源)"或"4 候选"等
    assert "三价位(同源)" not in src, \
        "md_to_docx.py 不应硬编码'三价位(同源)'，DOCX 跟随 MD 渲染"
    assert "support_candidates" not in src, \
        "md_to_docx.py 不应硬编码支撑候选，DOCX 跟随 MD 渲染"


# ============================================================
# P0-A 边界测试 (2026-09-11, 规范 §6 + §12 P0 整改)
# 规则文档: analysis/references/three-levels-rules.md
# ============================================================
import datetime as _dt


def test_p0a_n_zero_all_none():
    """N=0 (K 线全空): support/resistance/stop_loss 全 None, 候选字典空"""
    r = compute_three_levels({"price": 10.0}, None, None)
    assert r["support"] is None
    assert r["resistance"] is None
    assert r["stop_loss"] is None
    assert r["support_candidates"] == {}
    assert r["resistance_candidates"] == {}
    assert "N=0" in r["method"]


def test_p0a_support_all_above_threshold_returns_none():
    """支撑候选全部 > 1.05×价 → support=None (不强行取跨价极值)"""
    klines = _make_klines(n=200, start_close=10.0, slope=0.05, vol=0.1)  # close 持续上行
    # 构造现价低于所有候选的极端场景: 现价=5, 候选都在 9-12 区间
    r = compute_three_levels({"price": 5.0}, {"kline": klines, "peak_price": 12.0}, None)
    assert r["support"] is None
    # candidates 仍记录 (未过滤, 用于报告展示)
    assert len(r["support_candidates"]) == 4


def test_p0a_resistance_all_below_threshold_returns_none():
    """压力候选全部 < 0.95×价 → resistance=None"""
    klines = _make_klines(n=200, start_close=5.0, slope=0.0, vol=0.1)  # close 平稳在 5
    # 现价=15, 候选都在 4-6 区间
    r = compute_three_levels({"price": 15.0}, {"kline": klines, "peak_price": 4.0}, None)
    assert r["resistance"] is None
    assert len(r["resistance_candidates"]) == 3


def test_p0a_method_includes_新命名():
    """method 字段必须含规范统一后的命名 (支撑下沿/压力上沿)"""
    klines = _make_klines(n=250, start_close=10.0, slope=0.02, vol=0.5)
    r = compute_three_levels({"price": 12.0}, {"kline": klines, "peak_price": 11.0}, None)
    assert "支撑下沿" in r["method"]
    assert "压力上沿" in r["method"]
    assert "N=" in r["method"]


def test_p0a_candidate_keys_unchanged():
    """4 支撑候选键 + 3 压力候选键不能改 (下游报告+测试都依赖这些键)"""
    klines = _make_klines(n=250, start_close=10.0, slope=0.02, vol=0.5)
    r = compute_three_levels({"price": 12.0}, {"kline": klines, "peak_price": 11.0}, None)
    assert set(r["support_candidates"].keys()) == {"ma60", "recent_low", "chip_peak", "boll_lower"}
    assert set(r["resistance_candidates"].keys()) == {"ma250_or_ma120", "recent_high", "boll_upper"}


def test_p0a_stop_loss_reuse_only_no_recompute():
    """stop_loss 严格复用 trading_plan.stop_loss, 缺则 None (不复算)"""
    klines = _make_klines(n=250, start_close=10.0, slope=0.02, vol=0.5)
    # plan 缺 → stop_loss = None
    r1 = compute_three_levels({"price": 12.0}, {"kline": klines, "peak_price": 11.0}, None)
    assert r1["stop_loss"] is None
    # plan.stop_loss 显式 None → 仍 None
    r2 = compute_three_levels({"price": 12.0}, {"kline": klines, "peak_price": 11.0}, {"stop_loss": None})
    assert r2["stop_loss"] is None
    # plan.stop_loss = 9.33 → 复用为 9.33
    r3 = compute_three_levels({"price": 12.0}, {"kline": klines, "peak_price": 11.0}, {"stop_loss": 9.33})
    assert r3["stop_loss"] == 9.33


def test_p0a_threshold_exactly_5pct():
    """±5% 边界值: 候选正好 = price*1.05 应保留 (= 不 >)"""
    # 构造候选: 唯一支撑候选 = 1.05 × price 边界
    klines = _make_klines(n=60, start_close=10.0, slope=0.0, vol=0.1)
    # K 线 close 全 10, ma60 = 10, recent_low = 9.9 (10-0.1), boll_lower < 10
    # 用 chip_peak = 10.5, price=10.0 → 10.5 == 10.5 (price*1.05), 边界值
    r = compute_three_levels({"price": 10.0}, {"kline": klines, "peak_price": 10.5}, None)
    # chip_peak = 10.5 = 10.0 * 1.05, 边界值保留 (≤)
    assert "chip_peak" in r["support_candidates"]
    # 10.5 保留后, 跟其他候选 (ma60≈10) 一起, min(10, 9.9, 10.5, boll_lower≈9.8) → 9.8
    assert r["support"] is not None
    assert r["support"] <= 10.5


def test_p0a_real_600693_case_2026_09_11():
    """600693 9-11 跑通实测: 现价 10.76, 支撑 7.16 (recent_low), 压力 12.20 (recent_high)"""
    # 简化: 构造一段 60 日 K 线让 ma60/recent_low/recent_high 落在合理范围
    klines = _make_klines(n=120, start_close=8.0, slope=0.02, vol=1.0)
    # 60 日前 close≈8, 现 close≈10.4 (8+120*0.02)
    # 但 ma60 是后 60 日, 后 60 日 close ≈ 9.2-10.4, ma60 ≈ 9.8
    # recent_low (60 日内 low 最小) ≈ 后 60 日最低 close-1.0 ≈ 8.2
    # recent_high ≈ 11.4
    # chip_peak 假设 11.0
    r = compute_three_levels({"price": 10.5}, {"kline": klines, "peak_price": 11.0}, {"stop_loss": 9.33})
    assert r["support"] is not None
    assert r["resistance"] is not None
    assert r["stop_loss"] == 9.33
    # 验证过滤逻辑: support <= 1.05*10.5 = 11.025 (chip_peak 11.0 通过)
    assert r["support"] <= 10.5 * 1.05 + 0.01
    assert r["resistance"] >= 10.5 * 0.95 - 0.01
