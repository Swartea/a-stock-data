"""V3 Markdown 当前渲染契约测试。

所有断言都基于 deterministic result fixture 实时渲染，不读取 reports/ 历史产物。
"""

import math

import pytest

from conftest import _sample_result_v3


def test_md_has_30s_decision_card(rendered_markdown_v3):
    md = rendered_markdown_v3

    assert "## 🎯 30 秒决策卡" in md
    assert "💰 现价" in md
    assert "📊 涨跌" in md
    assert "🏭 流通市值" in md
    assert "📈 PE(TTM)" in md
    assert "📉 PB" in md
    assert "📊 PE 分位" in md
    assert "🎯 PEG" in md


def test_md_has_current_three_levels_table(rendered_markdown_v3):
    """当前三价位契约是现价 + 操作支撑/压力 + 参考支撑/压力 + 止损。"""
    md = rendered_markdown_v3

    assert "### 🎯 三价位" in md
    assert "💰 **现价**" in md
    assert "🟢 **操作支撑位**" in md
    assert "🔴 **操作压力位**" in md
    assert "📌 **参考支撑位**" in md
    assert "📌 **参考压力位**" in md
    assert "🟡 **止损位**" in md
    assert "距现价" in md
    assert "0% (参考)" in md


def test_md_has_operation_proverb_5state(rendered_markdown_v3):
    md = rendered_markdown_v3

    assert "### 💰 操作口诀" in md
    assert "【结论】" in md
    assert "【操作】" in md
    assert "【风险】" in md
    assert "多目标价" in md
    assert "买入区间" in md
    assert "周期" in md
    assert "🔒" in md
    assert "V2 同源实时模型" in md


def test_md_peg_4tier_threshold(rendered_markdown_v3):
    md = rendered_markdown_v3

    decision_section = md.split("## 🚨 风险警报区")[0]
    assert "极贵" in decision_section


def test_md_has_candidates_blockquote(rendered_markdown_v3):
    md = rendered_markdown_v3

    for cand in ["ma60", "recent_low", "chip_peak", "boll_lower"]:
        assert cand in md

    for cand in ["ma250_or_ma120", "recent_high", "boll_upper"]:
        assert cand in md


# ============================================================
# P2-7: PEG 不可用必须显式解释, 且不得渲染成数值
# ============================================================


def _render_with_peg(peg, drop_key=False):
    """用确定性 fixture 渲染一份指定 PEG 的 V3 Markdown (隔离 result fixture)。"""
    from analysis.report_md import write_markdown_report_v3

    result = _sample_result_v3()
    result["quote"].update({
        "price": 10.00, "pe_ttm": 88.0, "pb": 2.40, "float_mcap": 86.4,
        "limit_up": 11.00, "limit_down": 9.00, "amplitude": 3.20,
        "turnover_rate": 4.10, "vol_ratio": 1.20,
    })
    valuation = {
        "analyst_count": 5, "digest_years": 5,
        "pe_fwd": 30.1, "eps_cur": 0.33, "eps_next": 0.40, "cagr_pct": 22.5,
    }
    if not drop_key:
        valuation["peg"] = peg
    result["valuation"] = valuation
    result["valuation_hist"] = {"pe_percentile_3y": 92.0, "pb_percentile_3y": 55.0}
    result["score"] = {
        "total": 50, "change_pct": 1.25, "trend": 6, "valuation": 7,
        "valuation_pctile": 4, "capital": 8, "momentum": 4, "sentiment": 4,
        "risk": 5, "chip": 4, "sw_stability": 3, "dragon": 5, "factors": [],
    }
    result["emoji"] = "🟡"
    result["advice"] = "中性"
    result["detail"] = "Markdown 契约测试"
    result["_md_full"] = True
    result["trading_plan"].update({
        "state": "neutral", "entry_low": 9.50, "entry_high": 9.80,
        "stop_loss": 9.20, "stop_loss_pct": -8.0, "tp1": 10.80, "tp2": 11.50,
        "tp3": 12.20, "position": "轻仓", "period": "1-2 周",
        "template_used": (
            "【结论】当前维持中性 ｜ "
            "【操作】按买入区间分批执行 ｜ "
            "【风险】跌破止损位退出"
        ),
    })
    result["three_levels"].update({
        "support": 9.50, "resistance": 10.80, "stop_loss": 9.20,
        "stop_loss_method": "trading_plan", "support_op_key": "ma60",
        "resistance_op_key": "boll_upper", "support_extreme": 8.80,
        "resistance_extreme": 11.60, "support_extreme_label": "60日最低",
        "resistance_extreme_label": "60日最高",
        "support_candidates": {"ma60": 9.50, "recent_low": 8.80,
                               "chip_peak": 9.60, "boll_lower": 9.40},
        "resistance_candidates": {"ma250_or_ma120": 10.70, "recent_high": 11.60,
                                  "boll_upper": 10.80},
    })
    result.update({
        "signals": {"good": [], "bad": []}, "blocks": [], "fund": {},
        "chip_data": {}, "lockup": {}, "dragon": {},
        "macro": {"north_label": "北向资金：市场口径"}, "sw_data": {},
        "announcements": None, "finance": None, "research": None, "news": None,
        "margin": None, "margin_hist": {}, "fund_daily5": {}, "peers": {},
        "irm": {}, "holders": {}, "dividend": {}, "board": {}, "dragon_market": {},
    })
    result["run_log"].update({
        "source_meta": {}, "fallback_chain": [],
        "guard": {"status": "ok", "kline_freshness": {"last_bar": "2026-09-18"}},
        "started_at": "2026-09-18T10:00:00+08:00",
        "finished_at": "2026-09-18T10:00:01+08:00", "total_sec": 1.0,
    })
    return write_markdown_report_v3(result)


def _peg_table_row(md):
    """取 30 秒决策卡 7 列大表里 🎯 PEG 所在的那一行。"""
    for line in md.splitlines():
        if line.startswith("|") and "PE 分位(3年)" in line:
            continue
        if line.startswith("|") and "元**" in line:
            return line
    raise AssertionError("未找到决策卡核心指标行")


@pytest.mark.parametrize(
    "peg, expected",
    [
        (0.85, "0.85 (便宜)"),
        (1.20, "1.20 (合理)"),
        (2.00, "2.00 (偏贵)"),
        (4.20, "4.20 (极贵)"),
    ],
)
def test_md_peg_valid_keeps_4tier_wording(peg, expected):
    """有效 PEG: 四档措辞与两位小数格式保持不变, 且不出现 unavailable 提示。"""
    md = _render_with_peg(peg)

    assert expected in _peg_table_row(md)
    assert "PEG 不可用" not in md


def test_md_peg_missing_key_shows_unavailable_explanation():
    """缺一致预期数据 (peg 键缺失): 必须给出显式 unavailable 说明, 不静默省略。"""
    md = _render_with_peg(None, drop_key=True)

    decision = md.split("## 🚨 风险警报区")[0]
    assert "PEG 不可用" in decision
    assert "缺少机构一致预期 EPS/增速数据" in decision
    assert "PE(TTM) ÷ 机构一致预期净利增速" in decision
    # 单元格给显式标记, 而不是留白
    assert "不可用" in _peg_table_row(md)


@pytest.mark.parametrize(
    "peg, reason_fragment",
    [
        (None, "缺少机构一致预期 EPS/增速数据"),
        (float("inf"), "无界"),
        (float("-inf"), "无界"),
        (math.nan, "NaN"),
        (0, "非正"),
        ("n/a", "格式异常"),
    ],
)
def test_md_peg_unusable_never_rendered_as_number(peg, reason_fragment):
    """None/NaN/±inf/非数值 一律不可用, 且绝不被当成数值渲染。"""
    md = _render_with_peg(peg)
    decision = md.split("## 🚨 风险警报区")[0]
    row = _peg_table_row(md)

    assert "不可用" in row
    assert reason_fragment in decision
    for bad in ("None", "nan", "NaN", "inf", "∞"):
        assert bad not in row


def test_md_peg_unavailable_explained_in_both_valuation_sections():
    """估值贵不贵 + 机构一致预期表两处都不能静默省略或打印裸 None。"""
    md = _render_with_peg(None)

    # V2 保留块: 估值贵不贵 — 之前这里因 if 条件不成立而整行消失
    assert "- **PEG 不可用** —" in md
    # V2 保留块: 机构一致预期表 — 之前这里渲染成 `| PEG | None |`
    assert "| PEG | 不可用 |" in md
    assert "| PEG | None |" not in md
