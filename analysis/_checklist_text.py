# -*- coding: utf-8 -*-
"""操作检查清单文案表 (P2-8: 从 html_report_v3._render_checklist 抽出的硬编码买卖文案)

背景
----
`_render_checklist` 原本把 3 套旧状态 (bull/neutral/bear) 的 buy/sell/stop/position
文案 + 5 状态机 × 5 项 GFM 模板全部内联在一个函数里 (80+ 行), 维护时容易漏改某一套。
本模块只负责**中文文案本身**, 保持纯文本, 不含任何 HTML 结构与转义逻辑。

职责边界 (与 html_report_v3._render_checklist 的分工)
---------------------------------------------------
- 本模块: 行标签 + 文案模板 + `{}` 占位符替换, 5 状态 GFM 套装的查表与兜底。
- html_report_v3: 状态选择 (state → 哪套文案)、数据提取 (trading_plan/signals/three_levels)、
  数值格式化 (money/_num/_esc)、HTML 结构拼装与转义。

**文案契约**: 这里的字符串是对用户可见的原文, 任何改动都会改变报告输出。
测试 tests/test_checklist_text.py 锁死字面量 + 占位符顺序; 改文案必须同步改测试。
"""
from __future__ import annotations

# ============================================================
# 1. 行类型与行标签 (供 _render_checklist 映射 CSS class)
# ============================================================
KIND_BUY = "buy"
KIND_SELL = "sell"
KIND_STOP = "stop"
KIND_WATCH = "watch"

LABEL_BUY_TRIGGER = "买入触发"
LABEL_SELL_TRIGGER = "卖出触发"
LABEL_STOP_DISCIPLINE = "止损纪律"
LABEL_POSITION = "仓位建议"

# 仓位建议 3 状态通用（bull / neutral / bear 文案一致）
POSITION_TEXT = "{position} · 持仓周期 {period}"

# ============================================================
# 2. 旧 3 状态 buy / sell / stop 文案
#    key = _render_checklist 传入的 state 分支名
#    buy  : 回踩/站稳价  sell: 压力/减仓价  stop: 止损价 + 止损幅度
#    兜底文案 (如 "止损位" / "支撑区") 由调用方算好传入, 本模块不造数据。
# ============================================================
LEGACY_BUY_TEXT = {
    "bull": "回踩 {price} 分批进场（每档最多 1/2 仓），不追高、不满仓一把梭",
    "neutral": "观望为主：放量站稳 {price} 上方再小仓试探，否则不动",
    # 空头无买入价占位: 整句为固定文案
    "bear": "空头结构，不建议新开仓；等底部放量企稳再评估",
}

LEGACY_SELL_TEXT = {
    "bull": "冲高至 {price} 减 1/3~1/2 仓锁利，余仓分批看更高位",
    "neutral": "已有持仓：反弹至 {price} 附近先减仓，落袋为安",
    "bear": "已有持仓：逢反弹至 {price} 附近减仓/离场",
}

LEGACY_STOP_TEXT = {
    "bull": "收盘跌破 {price}（约 -{pct}%）无条件离场，不补仓、不摊薄",
    "neutral": "持股底线 {price}（-约 {pct}%），破位必走，不留恋",
    "bear": "跌破 {price} 清仓回避，不抄底、不接飞刀",
}

# 旧 3 状态分支名 → 文案 key（_render_checklist 传入的是 5 状态机 state_key）。
# 注意: 只认 bullish / mild_bull / neutral 三键 —— 原实现是
# `if state in ("bullish","mild_bull") / elif state == "neutral" / else`,
# 裸 "bull"/"bear" 等历史 3 状态名都会落 else(看空) 分支, 此处保持一致。
LEGACY_STATE_KEYS = {
    "bullish": "bull",
    "mild_bull": "bull",
    "neutral": "neutral",
    "mild_bear": "bear",
    "bearish": "bear",
}
# 未命中任何已知 state 时的兜底分支（原 else = 看空）
LEGACY_FALLBACK_KEY = "bear"


def legacy_branch(state):
    """把 state 映射到旧 3 状态文案 key（bull / neutral / bear），未知 -> bear。

    对应原 `if state in ("bullish", "mild_bull") / elif state == "neutral" / else`。
    """
    return LEGACY_STATE_KEYS.get(state) or LEGACY_FALLBACK_KEY


def legacy_buy_text(state, price):
    """旧 3 状态 买入触发行文案。price 仅在 bull/neutral 分支使用。"""
    return LEGACY_BUY_TEXT[legacy_branch(state)].format(price=price)


def legacy_sell_text(state, price):
    """旧 3 状态 卖出触发行文案（是否出该行由调用方按数据有无决定）。"""
    return LEGACY_SELL_TEXT[legacy_branch(state)].format(price=price)


def legacy_stop_text(state, price, pct):
    """旧 3 状态 止损纪律行文案；pct 为调用方算好的止损百分比字符串。"""
    return LEGACY_STOP_TEXT[legacy_branch(state)].format(price=price, pct=pct)


def legacy_position_text(position, period):
    """旧 3 状态 仓位建议行文案（bull/neutral/bear 同一句）。"""
    return POSITION_TEXT.format(position=position, period=period)


# ============================================================
# 3. 5 状态机 GFM 5 项模板 (债 5 修法, Task 7.2)
#    5 项: 状态确认 / 买点触发 / 卖点触发 / 止损纪律 / 仓位管理
#    占位符: entry(支撑/回踩) tp1(第一压力) stop(止损) pos position per period sl_pct
# ============================================================
CHECKLIST_5T = {
    "bullish": [
        ("状态确认", "评分 ≥65 + 趋势确认 + 量能配合, 5 状态机判定为多头"),
        ("买点触发", "回调至 {entry} 区间分批建仓 (各 1/2 仓); 放量突破 {tp1} 可加仓"),
        ("卖点触发", "达 {tp1} 卖 1/2 锁利 → 达更高位再减半 → 趋势走弱清剩余"),
        ("止损纪律", "收盘跌破 {stop} (现价下 -{sl_pct}%) 即离场, 不补仓摊平"),
        ("仓位管理", "{pos} · 周期 {per}"),
    ],
    "mild_bull": [
        ("状态确认", "评分 55-64 + 趋势偏多, 5 状态机判定为轻多 (震荡偏多)"),
        ("买点触发", "回调至 {entry} 附近小仓低吸 (1/3 仓); 突破 {tp1} 站稳再加 1/3"),
        ("卖点触发", "达 {tp1} 减 1/3 锁利; 达更高位再减 1/3; 余仓看第三压力"),
        ("止损纪律", "收盘跌破 {stop} (现价下 -{sl_pct}%) 即减半; 破支撑下沿全走"),
        ("仓位管理", "{pos} · 周期 {per} (轻多, 严控仓位)"),
    ],
    "neutral": [
        ("状态确认", "评分 45-54 + 多空信号混杂, 5 状态机判定为中性 (区间震荡)"),
        ("买点触发", "仅在 {entry} 支撑区低吸, 上轨 {tp1} 附近不过量追高"),
        ("卖点触发", "反弹至 {tp1} 一带减仓; 跌破 {stop} 转空离场; 放量站稳 {tp1} 再看多"),
        ("止损纪律", "{stop} 为区间底沿, 收盘破位即走, 不猜底"),
        ("仓位管理", "{pos} · 以低吸高抛为主, 周期 {per}"),
    ],
    "mild_bear": [
        ("状态确认", "评分 35-44 + 趋势偏空, 5 状态机判定为轻空 (震荡偏空)"),
        ("买点触发", "严控 — 仅在 {entry} 附近且出现放量反转 K 线小仓 (1/4 仓) 抢短; 否则不动"),
        ("卖点触发", "已有持仓反弹至 {tp1} 一带分批减仓; 跌破 {stop} 清仓; 不抢反弹"),
        ("止损纪律", "{stop} 上方不留幻想仓, 反弹即减, 跌穿即走"),
        ("仓位管理", "{pos} · 周期 {per} (轻空, 逢反减)"),
    ],
    "bearish": [
        ("状态确认", "评分 <35 + 趋势空头, 5 状态机判定为空头 (下跌趋势)"),
        ("买点触发", "❌ 不买入 / 不补仓 / 不抄底; 空仓者观望等底部放量企稳信号"),
        ("卖点触发", "反弹至压力位 {tp1} 一带分批减仓; 持仓者跌破 {stop} 清仓; 不抢反弹"),
        ("止损纪律", "反弹减仓/清仓纪律优先, 止损 {stop} 上方不留幻想仓"),
        ("仓位管理", "清仓回避 / 极轻仓短线者当日进出"),
    ],
}
# 状态未命中时回落到中性模板（原 CHECKLIST_5T.get(state, CHECKLIST_5T["neutral"])）
GFM_FALLBACK_STATE = "neutral"

# 状态 → GFM 列表边框色 class（bullish/mild_bull=up, neutral=accent, mild_bear/bearish=risk）
GFM_STATE_CLASS = {
    "bullish": "task-bull",
    "mild_bull": "task-bull",
    "neutral": "",
    "mild_bear": "task-stop",
    "bearish": "task-stop",
}


def gfm_state_class(state):
    """5 状态 → task-list-item 边框色 class；未命中 -> ""（原 dict.get(state, "")）。"""
    return GFM_STATE_CLASS.get(state, "")


def gfm_items(state, entry, tp1, stop, pos, per, sl_pct):
    """返回 5 状态机的 5 项 (label, 已填充文案) 列表。

    state 未命中任何已知键时回落 GFM_FALLBACK_STATE（中性模板）。
    """
    tpl = CHECKLIST_5T.get(state) or CHECKLIST_5T[GFM_FALLBACK_STATE]
    return [
        (label, txt.format(entry=entry, tp1=tp1, stop=stop, pos=pos, per=per, sl_pct=sl_pct))
        for label, txt in tpl
    ]
