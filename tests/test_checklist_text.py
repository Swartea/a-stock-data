# -*- coding: utf-8 -*-
"""P2-8: analysis/_checklist_text.py 买卖文案表单元测试

覆盖:
  1. 旧 3 状态 (bull / neutral / bear) 的 buy / sell / stop / position 文案与分支映射
  2. 5 状态机 × 5 项 GFM 模板的标签、顺序与占位符替换
  3. 动态占位符 (支撑/压力/止损价、止损幅度、仓位、周期) 全部落到正确位置
  4. HTML 转义: 渲染层 `_esc` 仍在 html_report_v3, 文案层保持纯文本不转义
  5. 状态兜底: 未知 state → 旧 3 状态走 bear 分支 + GFM 走 neutral 模板

规范 §9: 不依赖个人路径 / 当日报告 / 当日时间戳; 不读 report fixture, 不联网。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", Path(__file__).resolve().parents[1])).resolve()
ANALYSIS_DIR = WORKDIR / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))

import _checklist_text as ct  # noqa: E402
import html_report_v3 as hr  # noqa: E402

FIVE_STATES = ["bullish", "mild_bull", "neutral", "mild_bear", "bearish"]
GFM_LABELS = ["状态确认", "买点触发", "卖点触发", "止损纪律", "仓位管理"]

# 确定性占位值: 全部含 HTML 敏感字符, 便于同时验证占位替换与转义边界
ENTRY = "9.80 元"
TP1 = "11.00 元"
STOP = "9.50 元"
POS = "6-7 成"
PER = "2-4 周"
SL_PCT = "5.0"


# ============================================================
# 1. 旧 3 状态: 分支映射
# ============================================================
@pytest.mark.parametrize("state,expected", [
    ("bullish", "bull"),
    ("mild_bull", "bull"),
    ("neutral", "neutral"),
    ("mild_bear", "bear"),
    ("bearish", "bear"),
    # 未命中 → 原 else 分支(看空); 裸 3 状态名也走 else, 与原实现一致
    ("weird_state", "bear"),
    ("bull", "bear"),
    ("bear", "bear"),
    (None, "bear"),
])
def test_legacy_branch_mapping(state, expected):
    assert ct.legacy_branch(state) == expected


def test_legacy_buy_sell_stop_cover_all_three_branches():
    """三套旧状态文案互不相同, 且 branch 切换时确实换句。"""
    buys = {b: ct.LEGACY_BUY_TEXT[b] for b in ("bull", "neutral", "bear")}
    sells = {b: ct.LEGACY_SELL_TEXT[b] for b in ("bull", "neutral", "bear")}
    stops = {b: ct.LEGACY_STOP_TEXT[b] for b in ("bull", "neutral", "bear")}
    assert len(set(buys.values())) == 3
    assert len(set(sells.values())) == 3
    assert len(set(stops.values())) == 3


# ============================================================
# 2. 旧 3 状态: 文案字面量 + 占位符
# ============================================================
def test_legacy_buy_text_literals():
    assert ct.legacy_buy_text("bullish", ENTRY) == \
        "回踩 9.80 元 分批进场（每档最多 1/2 仓），不追高、不满仓一把梭"
    assert ct.legacy_buy_text("mild_bull", ENTRY) == ct.legacy_buy_text("bullish", ENTRY)
    assert ct.legacy_buy_text("neutral", ENTRY) == \
        "观望为主：放量站稳 9.80 元 上方再小仓试探，否则不动"
    assert ct.legacy_buy_text("bearish", "") == \
        "空头结构，不建议新开仓；等底部放量企稳再评估"


def test_legacy_sell_text_literals():
    assert ct.legacy_sell_text("bullish", TP1) == \
        "冲高至 11.00 元 减 1/3~1/2 仓锁利，余仓分批看更高位"
    assert ct.legacy_sell_text("neutral", TP1) == \
        "已有持仓：反弹至 11.00 元 附近先减仓，落袋为安"
    assert ct.legacy_sell_text("mild_bear", TP1) == \
        "已有持仓：逢反弹至 11.00 元 附近减仓/离场"


def test_legacy_stop_text_literals():
    assert ct.legacy_stop_text("bullish", STOP, SL_PCT) == \
        "收盘跌破 9.50 元（约 -5.0%）无条件离场，不补仓、不摊薄"
    assert ct.legacy_stop_text("neutral", STOP, SL_PCT) == \
        "持股底线 9.50 元（-约 5.0%），破位必走，不留恋"
    assert ct.legacy_stop_text("bearish", STOP, "") == \
        "跌破 9.50 元 清仓回避，不抄底、不接飞刀"


def test_legacy_stop_percent_sign_is_literal():
    """止损幅度用 {} 占位, % 必须是字面量而不是 %-格式化残留。"""
    out = ct.legacy_stop_text("bullish", STOP, SL_PCT)
    assert "-5.0%" in out
    assert "%%" not in out and "{}" not in out


def test_legacy_position_text():
    assert ct.legacy_position_text(POS, PER) == "6-7 成 · 持仓周期 2-4 周"
    # 3 状态共用同一句
    for st in ("bullish", "neutral", "bearish"):
        assert ct.legacy_position_text(POS, PER) == ct.POSITION_TEXT.format(
            position=POS, period=PER)


def test_legacy_stop_fallback_marker_preserved():
    """止损幅度缺失时调用方传 '?  —数据源暂缺' / '—', 文案不得吞掉标记。"""
    assert "?  —数据源暂缺" in ct.legacy_stop_text("bullish", STOP, "?  —数据源暂缺")
    assert "—%" in ct.legacy_stop_text("neutral", STOP, "—")


# ============================================================
# 3. 5 状态机 GFM 模板
# ============================================================
@pytest.mark.parametrize("state", FIVE_STATES)
def test_gfm_always_five_items_in_order(state):
    items = ct.gfm_items(state, ENTRY, TP1, STOP, POS, PER, SL_PCT)
    assert len(items) == 5
    assert [label for label, _ in items] == GFM_LABELS


def test_gfm_templates_cover_exactly_five_states():
    assert set(ct.CHECKLIST_5T) == set(FIVE_STATES)


def test_gfm_bullish_items():
    items = dict(ct.gfm_items("bullish", ENTRY, TP1, STOP, POS, PER, SL_PCT))
    assert items["状态确认"] == "评分 ≥65 + 趋势确认 + 量能配合, 5 状态机判定为多头"
    assert items["买点触发"] == "回调至 9.80 元 区间分批建仓 (各 1/2 仓); 放量突破 11.00 元 可加仓"
    assert items["卖点触发"] == "达 11.00 元 卖 1/2 锁利 → 达更高位再减半 → 趋势走弱清剩余"
    assert items["止损纪律"] == "收盘跌破 9.50 元 (现价下 -5.0%) 即离场, 不补仓摊平"
    assert items["仓位管理"] == "6-7 成 · 周期 2-4 周"


def test_gfm_mild_bull_items():
    items = dict(ct.gfm_items("mild_bull", ENTRY, TP1, STOP, POS, PER, SL_PCT))
    assert items["状态确认"] == "评分 55-64 + 趋势偏多, 5 状态机判定为轻多 (震荡偏多)"
    assert items["买点触发"] == "回调至 9.80 元 附近小仓低吸 (1/3 仓); 突破 11.00 元 站稳再加 1/3"
    assert items["卖点触发"] == "达 11.00 元 减 1/3 锁利; 达更高位再减 1/3; 余仓看第三压力"
    assert items["止损纪律"] == "收盘跌破 9.50 元 (现价下 -5.0%) 即减半; 破支撑下沿全走"
    assert items["仓位管理"] == "6-7 成 · 周期 2-4 周 (轻多, 严控仓位)"


def test_gfm_neutral_items():
    items = dict(ct.gfm_items("neutral", ENTRY, TP1, STOP, POS, PER, SL_PCT))
    assert items["状态确认"] == "评分 45-54 + 多空信号混杂, 5 状态机判定为中性 (区间震荡)"
    assert items["买点触发"] == "仅在 9.80 元 支撑区低吸, 上轨 11.00 元 附近不过量追高"
    assert items["卖点触发"] == \
        "反弹至 11.00 元 一带减仓; 跌破 9.50 元 转空离场; 放量站稳 11.00 元 再看多"
    assert items["止损纪律"] == "9.50 元 为区间底沿, 收盘破位即走, 不猜底"
    assert items["仓位管理"] == "6-7 成 · 以低吸高抛为主, 周期 2-4 周"


def test_gfm_mild_bear_items():
    items = dict(ct.gfm_items("mild_bear", ENTRY, TP1, STOP, POS, PER, SL_PCT))
    assert items["状态确认"] == "评分 35-44 + 趋势偏空, 5 状态机判定为轻空 (震荡偏空)"
    assert items["买点触发"] == \
        "严控 — 仅在 9.80 元 附近且出现放量反转 K 线小仓 (1/4 仓) 抢短; 否则不动"
    assert items["卖点触发"] == "已有持仓反弹至 11.00 元 一带分批减仓; 跌破 9.50 元 清仓; 不抢反弹"
    assert items["止损纪律"] == "9.50 元 上方不留幻想仓, 反弹即减, 跌穿即走"
    assert items["仓位管理"] == "6-7 成 · 周期 2-4 周 (轻空, 逢反减)"


def test_gfm_bearish_items():
    items = dict(ct.gfm_items("bearish", ENTRY, TP1, STOP, POS, PER, SL_PCT))
    assert items["状态确认"] == "评分 <35 + 趋势空头, 5 状态机判定为空头 (下跌趋势)"
    assert items["买点触发"] == "❌ 不买入 / 不补仓 / 不抄底; 空仓者观望等底部放量企稳信号"
    assert items["卖点触发"] == \
        "反弹至压力位 11.00 元 一带分批减仓; 持仓者跌破 9.50 元 清仓; 不抢反弹"
    assert items["止损纪律"] == "反弹减仓/清仓纪律优先, 止损 9.50 元 上方不留幻想仓"
    # 看空模板的仓位项是固定文案, 不含占位符
    assert items["仓位管理"] == "清仓回避 / 极轻仓短线者当日进出"


@pytest.mark.parametrize("state", FIVE_STATES)
def test_gfm_no_unfilled_placeholder(state):
    for label, txt in ct.gfm_items(state, ENTRY, TP1, STOP, POS, PER, SL_PCT):
        assert "{" not in txt and "}" not in txt, f"{state}/{label} 仍有未替换占位符"
        assert "%s" not in txt and "%%" not in txt, f"{state}/{label} 残留 %-格式化标记"


def test_gfm_state_class_mapping():
    assert ct.gfm_state_class("bullish") == "task-bull"
    assert ct.gfm_state_class("mild_bull") == "task-bull"
    assert ct.gfm_state_class("neutral") == ""
    assert ct.gfm_state_class("mild_bear") == "task-stop"
    assert ct.gfm_state_class("bearish") == "task-stop"
    assert ct.gfm_state_class("unknown") == ""


def test_gfm_unknown_state_falls_back_to_neutral():
    """未知 state: GFM 回落中性模板 (与原 CHECKLIST_5T.get(state, [...]) 一致)。"""
    assert ct.gfm_items("weird", ENTRY, TP1, STOP, POS, PER, SL_PCT) == \
        ct.gfm_items(ct.GFM_FALLBACK_STATE, ENTRY, TP1, STOP, POS, PER, SL_PCT)


def test_gfm_placeholders_are_positional_per_state():
    """不同占位值必须落到各自模板位, 不串位。"""
    items = dict(ct.gfm_items("neutral", "1.11 元", "2.22 元", "3.33 元", "4 成", "5 日", "6.6"))
    assert items["买点触发"] == "仅在 1.11 元 支撑区低吸, 上轨 2.22 元 附近不过量追高"
    assert items["卖点触发"] == "反弹至 2.22 元 一带减仓; 跌破 3.33 元 转空离场; 放量站稳 2.22 元 再看多"
    assert items["止损纪律"] == "3.33 元 为区间底沿, 收盘破位即走, 不猜底"
    assert items["仓位管理"] == "4 成 · 以低吸高抛为主, 周期 5 日"


def test_gfm_fallback_markers_substituted():
    items = dict(ct.gfm_items("bullish", ENTRY, TP1, STOP, "数据源暂缺", "数据源暂缺", "—"))
    assert items["仓位管理"] == "数据源暂缺 · 周期 数据源暂缺"
    assert items["止损纪律"] == "收盘跌破 9.50 元 (现价下 -—%) 即离场, 不补仓摊平"


# ============================================================
# 4. 文案层不转义 / 渲染层仍转义
# ============================================================
def test_text_layer_does_not_escape():
    """文案层保持纯文本: 敏感字符原样透出, 转义只发生在渲染层。"""
    raw = '<b>&"x"</b>'
    assert ct.legacy_buy_text("neutral", raw) == f"观望为主：放量站稳 {raw} 上方再小仓试探，否则不动"
    assert ct.legacy_position_text(raw, raw) == f"{raw} · 持仓周期 {raw}"
    items = dict(ct.gfm_items("neutral", raw, raw, raw, raw, raw, raw))
    assert items["止损纪律"] == f"{raw} 为区间底沿, 收盘破位即走, 不猜底"


@pytest.mark.parametrize("state", FIVE_STATES)
def test_render_layer_escapes_gfm_and_legacy(state):
    """渲染层 _esc 仍作用于 label/txt: 注入的 <script> 不落进最终 HTML。

    注: 价格类字段走 money() -> float(), 只接受数值(既有行为);
    字符串类字段(position / period / template_used) 才注入 HTML 敏感字符。
    """
    result = {
        "quote": {"price": 10.0},
        "trading_plan": {
            "support_low": 9.8, "support_high": 10.2, "resistance": 11.0,
            "stop_loss": 9.5, "stop_loss_pct": 5.0,
            "position": "<em>6成</em>", "period": "<u>2周</u>",
            "template_used": "<b>口诀</b>",
        },
    }
    html = hr._render_checklist(result, state)
    # 原始标签绝不落进 HTML (注入被挡住)
    assert "<em>" not in html and "<u>" not in html and "<b>口诀</b>" not in html
    # position/period/template_used 走 _esc(pos) 预转义 + 行循环 _esc 再转义 = 双重转义 (既有行为)
    assert "&amp;lt;em&amp;gt;" in html and "&amp;lt;u&amp;gt;" in html
    assert "&amp;lt;b&amp;gt;口诀&amp;lt;/b&amp;gt;" in html
    # 5 项 GFM 全部渲染
    assert html.count('class="cb"') == 5
    for label in GFM_LABELS:
        assert f"<b>{label}：</b>" in html


def test_render_escaping_still_doubles_pos_and_period():
    """保留既有行为: position/period 预转义后又被行循环 _esc 一次(双重转义)。"""
    result = {"quote": {"price": 10.0},
              "trading_plan": {"stop_loss": 9.5, "position": "A&B", "period": "C&D"}}
    html = hr._render_checklist(result, "bullish")
    assert "A&amp;amp;B" in html
    assert "C&amp;amp;D" in html


# ============================================================
# 5. 渲染层行结构 (状态选择仍归 html_report_v3)
# ============================================================
def _rows(result, state):
    """从渲染 HTML 还原 (label, txt) 行, 仅用于结构断言。"""
    import re
    html = hr._render_checklist(result, state)
    return re.findall(r'<div class="grp" style="margin:0 0 2px">([^<]*)</div>', html)


def test_render_legacy_row_order_and_labels():
    result = {"quote": {"price": 10.0},
              "trading_plan": {"support_low": 9.8, "support_high": 10.2, "resistance": 11.0,
                               "stop_loss": 9.5, "stop_loss_pct": -5.0,
                               "position": "6-7 成", "period": "2-4 周"}}
    expected = [ct.LABEL_BUY_TRIGGER, ct.LABEL_SELL_TRIGGER,
                ct.LABEL_STOP_DISCIPLINE, ct.LABEL_POSITION]
    for state in FIVE_STATES:
        assert _rows(result, state) == expected, state


def test_render_drops_sell_row_when_no_resistance():
    """resistance 缺失 → 不出"卖出触发"行 (bull/neutral 原逻辑一致)。"""
    result = {"quote": {"price": 10.0},
              "trading_plan": {"support_low": 9.8, "support_high": 10.2,
                               "stop_loss": 9.5, "stop_loss_pct": -5.0,
                               "position": "6-7 成", "period": "2-4 周"}}
    for state in ("bullish", "neutral"):
        assert ct.LABEL_SELL_TRIGGER not in _rows(result, state), state
    # 看空分支的卖出行无条件输出
    assert ct.LABEL_SELL_TRIGGER in _rows(result, "bearish")


def test_render_legacy_copy_matches_module_for_each_state():
    """渲染出的旧 3 状态正文必须等于文案模块的填充结果。"""
    plan = {"support_low": 9.8, "support_high": 10.2, "resistance": 11.0,
            "stop_loss": 9.5, "stop_loss_pct": 5.0, "position": "6-7 成", "period": "2-4 周"}
    html = hr._render_checklist({"quote": {"price": 10.0}, "trading_plan": plan}, "mild_bull")
    assert ct.legacy_buy_text("mild_bull", "9.80 元") in html
    assert ct.legacy_sell_text("mild_bull", "11.00 元") in html
    assert ct.legacy_stop_text("mild_bull", "9.50 元", "5.0") in html
    assert ct.legacy_position_text("6-7 成", "2-4 周") in html


def test_render_survives_missing_plan_and_quote():
    """缺 trading_plan / quote 仍出 4 行 + 5 项 GFM, 走"数据源暂缺"兜底。"""
    for result in ({}, {"quote": {}}, {"quote": {"price": 10.0}, "trading_plan": None}):
        html = hr._render_checklist(result, "neutral")
        assert html.count('class="cb"') == 5
        assert "止损位" in html and "数据源暂缺" in html


def test_module_has_no_html_structure():
    """文案模块不含 HTML 标签 (结构与转义留在 html_report_v3)。"""
    src = (ANALYSIS_DIR / "_checklist_text.py").read_text(encoding="utf-8")
    for tag in ("<div", "<li", "<span", "<ul", "<b>"):
        assert tag not in src, f"文案模块不应含 HTML 结构 {tag}"
