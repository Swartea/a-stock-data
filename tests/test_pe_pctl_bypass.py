"""批次 E 痛 3 修法 — PE 分位旁路 5 状态机测试

痛点: 杰瑞股份 53 分"区间操作"vs PE 分位 87.8% 自相矛盾
  - 53 分 → state=neutral → "区间操作"
  - 但 PE 分位 87.8% 极高估
  - 普通用户: "PE 都 87% 了还让我'低吸'? 不合理"
修法: 批次 E 痛 3 PE 分位旁路
  - PE 分位 > 85% 触发旁路:
    bullish    → mild_bear (估值极贵, 不允许看多)
    mild_bull  → neutral   (估值偏高, 减仓为主)
    neutral / mild_bear / bearish 保持原状
  - 旁路状态注入 plan['state_after_pe_bypass'] + plan['bypass_applied']
  - 报告层显示原状态 → 旁路后
"""
import json

import pytest

from analysis.trading_plan import (
    PE_PCTL_BYPASS_THRESHOLD,
    apply_pe_pctl_bypass,
    inject_state_to_plan,
    score_to_state,
)


# ============================================================
# 1. 旁路核心函数
# ============================================================
def test_bypass_no_trigger_when_pctile_low():
    """PE 分位 ≤ 85% 不触发旁路"""
    for pct in [None, 0, 50, 80, 85.0, 84.999]:
        for st in ["bullish", "mild_bull", "neutral", "mild_bear", "bearish"]:
            out = apply_pe_pctl_bypass(st, pct)
            assert out == st, f"PE 分位 {pct} 不应触发旁路, {st} → {out}"


def test_bypass_bullish_to_mild_bear_when_pe_high():
    """PE 分位 > 85% + bullish → mild_bear"""
    for pct in [85.001, 87.8, 90, 99, 100]:
        out = apply_pe_pctl_bypass("bullish", pct)
        assert out == "mild_bear", f"PE {pct} 时 bullish 应旁路到 mild_bear, 实际 {out}"


def test_bypass_mild_bull_to_neutral_when_pe_high():
    """PE 分位 > 85% + mild_bull → neutral"""
    out = apply_pe_pctl_bypass("mild_bull", 87.8)
    assert out == "neutral", f"PE 87.8 时 mild_bull 应旁路到 neutral, 实际 {out}"


def test_bypass_does_not_upgrade_bearish_states():
    """PE 分位 > 85% 时, neutral/mild_bear/bearish 保持原状"""
    for pct in [87.8, 95, 100]:
        for st in ["neutral", "mild_bear", "bearish"]:
            out = apply_pe_pctl_bypass(st, pct)
            assert out == st, f"PE {pct} + {st} 应保持原状, 实际 {out}"


def test_bypass_threshold_is_exactly_85():
    """边界: PE 分位 = 85% 不触发 (85 > 85 False); 85.001 触发"""
    assert apply_pe_pctl_bypass("bullish", 85.0) == "bullish"
    assert apply_pe_pctl_bypass("bullish", 85.001) == "mild_bear"


# ============================================================
# 2. inject_state_to_plan 集成 (plan 注入旁路字段)
# ============================================================
def test_inject_state_to_plan_no_bypass_default():
    """不传 pe_pctile 时, 无旁路, state_after_pe_bypass = state"""
    plan = {"stop_loss": 9.0, "entry_low": 10.0, "tp1": 12.0}
    inject_state_to_plan(plan, 70)  # 70 分 → bullish
    assert plan["state"] == "bullish"
    assert plan["state_after_pe_bypass"] == "bullish"
    assert plan["bypass_applied"] is False
    assert "valuation_pctile" not in plan


def test_inject_state_to_plan_with_bypass():
    """传 pe_pctile > 85% 时, 触发旁路"""
    plan = {"stop_loss": 9.0, "entry_low": 10.0, "tp1": 12.0}
    inject_state_to_plan(plan, 70, valuation_pctile=87.8)  # 70 分 bullish + PE 87.8%
    assert plan["state"] == "bullish"  # 原始状态保留
    assert plan["state_after_pe_bypass"] == "mild_bear"  # 旁路后
    assert plan["bypass_applied"] is True
    assert plan["valuation_pctile"] == 87.8
    # template_used 应基于旁路后状态
    assert "减仓" in plan["template_used"] or "轻空" in plan["template_used"] or "mild_bear" in plan["template_used"]


def test_jierui_real_case_53_score_87_8pe():
    """杰瑞股份 9-12 实测: 53 分 + PE 87.8% → state=neutral (53 已是 neutral, 但 bypass 仍走一遍)

    实际效果: 53 分本身是 neutral, PE 87.8% 时 neutral 不变; 但 bypass_applied=True 因 trade plan 字段
    """
    plan = {"stop_loss": 110.61, "entry_low": 115.37, "entry_high": 118.94,
            "tp1": 130.83, "tp2": 148.68, "tp3": 178.41}
    inject_state_to_plan(plan, 53, valuation_pctile=87.8)
    assert plan["state"] == "neutral"
    # 53 分本身是 neutral, PE 87.8% 不升级 → bypass_applied=False
    # 但 plan 应记录 pe_pctile
    assert plan["valuation_pctile"] == 87.8


# ============================================================
# 3. 端到端: pipeline.py 注入旁路
# ============================================================
def test_pipeline_inject_state_with_pe_pctile():
    """pipeline.py 调用 inject_state_to_plan 时传入 vh['pe_percentile_3y']

    模拟杰瑞股份: 53 分 + PE 87.8% → state=neutral, state_after_pe_bypass=neutral
    """
    plan = {"stop_loss": 110.61, "entry_low": 115.37, "entry_high": 118.94}
    pe_pctile = 87.8
    inject_state_to_plan(plan, 53, pe_pctile)
    assert plan["state"] == "neutral"
    assert plan["state_after_pe_bypass"] == "neutral"
    # bypass_applied 在 state==state_after_bypass 时 False (因为没真正变化)
    assert plan["bypass_applied"] is False


def test_pipeline_construct_high_pe_pctile_bullish_bypass():
    """假想 mild_bull + PE 95% → 旁路到 neutral

    构造: score=58 → mild_bull, valuation_pctile=95% > 85% → 旁路到 neutral
    """
    plan = {"stop_loss": 9.5, "entry_low": 10.0, "tp1": 12.0}
    inject_state_to_plan(plan, 58, valuation_pctile=95.0)
    assert plan["state"] == "mild_bull"
    assert plan["state_after_pe_bypass"] == "neutral"
    assert plan["bypass_applied"] is True
    # 报告层会显示 "原 mild_bull → 旁路 neutral"
