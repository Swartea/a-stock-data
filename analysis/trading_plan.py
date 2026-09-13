"""analysis/ 交易计划层 (P2-A Phase 2, 2026-09-13)

按规范 §2 模块边界, 把 V3 的 5 状态机映射 + plan 注入抽到 trading_plan.py:
- score_to_state(score): 综合评分 → 5 状态机 key
- inject_state_to_plan(plan, score): 把 state + template_used 注入 plan 字典
- 五状态机: bullish / mild_bull / neutral / mild_bear / bearish
- 模板来源: analysis.constants.OPERATION_TEMPLATES (债 1 修法, Task 5.1)

向后兼容: v3 顶层 `from analysis.trading_plan import _score_to_state, inject_state_to_plan`,
          老 `from analysis.quant_analyzer_v3 import _score_to_state` 仍能拿到 (re-export)。

§1 '不修改业务口径' — 阈值 (35/45/55/65) 与 plan 字段照搬, 仅搬位置。
"""
from __future__ import annotations

from typing import Any, Dict

from analysis.constants import OPERATION_TEMPLATES, STATE_DISPLAY


# 5 状态机阈值 (债 1 修法, Task 5.1 锁定)
_THRESHOLDS = (
    (65, "bullish"),       # 看多 (≥65)
    (55, "mild_bull"),     # 轻多 (55-64)
    (45, "neutral"),       # 中性/震荡 (45-54)
    (35, "mild_bear"),     # 轻空 (35-44)
)


def score_to_state(score: Any) -> str:
    """综合评分 → 多空状态映射 (5 状态机, 债 1 修法, Task 5.1 锁定)。

    阈值与 plan 文档 Task 5.1 Step 2 一致:
        ≥65   bullish      看多
        55-64 mild_bull    轻多
        45-54 neutral      中性/震荡
        35-44 mild_bear    轻空
        <35   bearish      看空

    §1 业务口径: 阈值固定, 不允许测试覆盖/人为调整
    """
    try:
        sc = float(score)
    except (TypeError, ValueError):
        sc = 0.0
    for threshold, state in _THRESHOLDS:
        if sc >= threshold:
            return state
    return "bearish"


# 别名 (兼容老调用 _score_to_state)
def _score_to_state(score: Any) -> str:
    return score_to_state(score)


def inject_state_to_plan(plan: Dict[str, Any], score: Any) -> Dict[str, Any]:
    """5 状态机注入到 trading_plan 字典 (P1-B/P1-D 配套, 债 1 修法)。

    在 trading_plan 上加 2 字段:
        state:         5 状态机 key (bullish/mild_bull/neutral/mild_bear/bearish)
        template_used: 对应状态的"结论+操作+风险"三段模板 (from OPERATION_TEMPLATES),
                       用 {score}/{stop_loss}/... 占位符 .format() 注入

    入参:
        plan:  V2 _make_trading_plan 返回的字典
        score: 综合评分 (会原样注入到 template_used 的 {score} 占位符)

    返回: 同一 plan 字典 (in-place 改 + 返回, 链式调用友好)

    §1 业务口径: 模板内容照搬, 渲染层 (MD/HTML) 直接读 plan['template_used']
    """
    if not plan:
        return plan
    state = score_to_state(score)
    plan["state"] = state
    try:
        plan["template_used"] = OPERATION_TEMPLATES[state].format(
            score=score,
            stop_loss=plan.get("stop_loss", "—"),
            stop_loss_pct=plan.get("stop_loss_pct", "—"),
            entry_low=plan.get("entry_low", "—"),
            tp1=plan.get("tp1", "—"),
        )
    except (KeyError, IndexError):
        # 模板占位符不全时, 降级用未格式化的模板 (保留状态名信息)
        plan["template_used"] = OPERATION_TEMPLATES[state]
    return plan


# 别名 (兼容老调用)
def _inject_state_to_plan(plan: Dict[str, Any], score: Any) -> Dict[str, Any]:
    return inject_state_to_plan(plan, score)


def state_display(state: str) -> tuple[str, str]:
    """5 状态 → (中文名, emoji) 映射 (报告层复用)"""
    return STATE_DISPLAY.get(state, ("—", "—"))


# 别名
def _state_display(state: str) -> tuple[str, str]:
    return state_display(state)
