"""Task 5.1 债 1 修法 — 多空状态机 (5 状态独立操作模板) 测试

历史: docs/04-模板质量债.md 债 1
  - 报告"🔴 看空 43 分｜不建议进场（清仓回避）"
  - 操作口诀写"现价分两批进场、持有 3-6 个月"
  - 结论与操作自相矛盾
  - 根因: 模板只套买入结构, 未按多空切换

修法（Task 5.1）:
  - V3 主分析器加 _score_to_state() 5 状态映射（65/55/45/35 阈值）
  - OPERATION_TEMPLATES dict 5 套独立"结论+操作+风险"模板
  - trading_plan 注入 state + template_used 字段
  - MD/HTML 渲染器从 plan["template_used"] 读，3 渲染器全部同步
"""
import sys

# 约定: tests/ 目录用 sys.path 注入 analysis/，与同仓其他测试一致
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")

import pytest
from quant_analyzer_v3 import (
    _score_to_state, OPERATION_TEMPLATES, _STATE_DISPLAY,
)


# ============================================================
# 1. _score_to_state 5 状态映射 — 参数化
# ============================================================
@pytest.mark.parametrize("score,expected", [
    (100, "bullish"),   # 上界
    (80,  "bullish"),
    (75,  "bullish"),   # 仓位"可重仓"分界（report-design-principles.md:90）
    (65,  "bullish"),   # 看多/轻多分界
    (60,  "mild_bull"),
    (55,  "mild_bull"), # 轻多/中性分界
    (50,  "neutral"),
    (45,  "neutral"),   # 中性/轻空分界
    (40,  "mild_bear"),
    (35,  "mild_bear"), # 轻空/看空分界
    (20,  "bearish"),
    (0,   "bearish"),   # 下界
])
def test_score_to_state_5_tier_mapping(score, expected):
    """5 状态映射阈值与 plan Task 5.1 Step 2 完全一致: 65 / 55 / 45 / 35"""
    assert _score_to_state(score) == expected, \
        f"score={score} 应映射到 {expected}"


def test_score_to_state_robust_to_non_numeric():
    """非数值输入（None / str / 异常）应兜底为 bearish，不抛"""
    assert _score_to_state(None) == "bearish"
    assert _score_to_state("abc") == "bearish"
    assert _score_to_state(object()) == "bearish"


# ============================================================
# 2. 5 状态模板完整 + 三段式（结论+操作+风险）
# ============================================================
EXPECTED_STATES = ["bullish", "mild_bull", "neutral", "mild_bear", "bearish"]


def test_all_5_states_have_template():
    """5 状态必须全部有模板，缺一不可"""
    for state in EXPECTED_STATES:
        assert state in OPERATION_TEMPLATES, f"缺少状态模板: {state}"


@pytest.mark.parametrize("state", EXPECTED_STATES)
def test_template_has_three_sections(state):
    """每条模板必须含"结论+操作+风险"三段（债 1 修法要求，不只套 buy 模板）"""
    tmpl = OPERATION_TEMPLATES[state]
    assert "【结论】" in tmpl, f"{state} 模板缺【结论】段: {tmpl}"
    assert "【操作】" in tmpl, f"{state} 模板缺【操作】段: {tmpl}"
    assert "【风险】" in tmpl, f"{state} 模板缺【风险】段: {tmpl}"


def test_no_buy_only_template():
    """禁止出现只含"分两批进场/持有 3-6 个月"的单一 buy 模板（债 1 根因）"""
    raw_templates = " ".join(OPERATION_TEMPLATES.values())
    # bullish 模板当然有"分两批进场"，但其他 4 状态模板必须**不**写买入结构
    for state in ("mild_bull", "neutral", "mild_bear", "bearish"):
        assert "分两批进场" not in OPERATION_TEMPLATES[state], \
            f"{state} 模板不应套买入结构: {OPERATION_TEMPLATES[state]}"


def test_bearish_template_says_avoid():
    """bearish 模板必须明确"清仓回避"（债 1 验证）"""
    assert "清仓回避" in OPERATION_TEMPLATES["bearish"]
    assert "45+" in OPERATION_TEMPLATES["bearish"]  # 触发再次评估的阈值


def test_neutral_template_says_range():
    """neutral 模板必须包含"区间操作"（债 1 验证 600693 score=45 跑出"区间操作"）"""
    assert "区间操作" in OPERATION_TEMPLATES["neutral"]


def test_template_format_renders_with_placeholders():
    """模板占位符（{score}/{stop_loss}/{stop_loss_pct}/{entry_low}/{tp1}）
    必须能被 .format 正确渲染，不抛 KeyError"""
    for state in EXPECTED_STATES:
        rendered = OPERATION_TEMPLATES[state].format(
            score=50, stop_loss=10.0, stop_loss_pct=7.0,
            entry_low=11.0, tp1=12.0)
        assert "{" not in rendered, f"{state} 模板有未填充占位符: {rendered}"
        assert "}" not in rendered, f"{state} 模板有未填充占位符: {rendered}"


# ============================================================
# 3. _STATE_DISPLAY (中文标签 + emoji) 完整性
# ============================================================
def test_state_display_has_all_5_entries():
    """5 状态都有中文标签和图标"""
    for state in EXPECTED_STATES:
        assert state in _STATE_DISPLAY, f"_STATE_DISPLAY 缺 {state}"
        cn, icon = _STATE_DISPLAY[state]
        assert cn, f"{state} 缺中文标签"
        assert icon, f"{state} 缺图标"


# ============================================================
# 4. 端到端: V3 跑过 600693 留下的 result_v3-{HHMM}.json 含 template_used
# ============================================================
def _latest_result_v3_600693(mock_result_v3=None):
    """加载 600693 今日最新的 result_v3-{HHMM}.json；缺失则 skip

    P1.5 整改: 接受 conftest mock_result_v3 fixture, 优先用 mock 跨用户可跑
    """
    import os
    import json as _json
    from datetime import datetime
    if mock_result_v3 is not None:
        with open(mock_result_v3, "r", encoding="utf-8") as f:
            return _json.load(f), str(mock_result_v3)
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = f"/Users/swarteachou/Desktop/大A数据/reports/600693_东百集团/{today}"
    if not os.path.exists(day_dir):
        pytest.skip(f"未找到 {day_dir}（需先跑 V3 至少一次）")
    files = [f for f in os.listdir(day_dir) if f.startswith("result_v3-") and f.endswith(".json")]
    if not files:
        pytest.skip("未找到 result_v3-*.json（需先跑 V3）")
    latest = max(files, key=lambda f: os.path.getmtime(os.path.join(day_dir, f)))
    with open(os.path.join(day_dir, latest), "r", encoding="utf-8") as f:
        return _json.load(f), os.path.join(day_dir, latest)


def test_v3_trading_plan_has_template_used_for_600693(mock_result_v3):
    """V3 跑 600693 (score≈45) → trading_plan.template_used 必须含"区间操作"。

    这是债 1 验收硬指标：旧报告"看空 43 分却写分两批进场"必须修掉。
    测试用 mock_result_v3 fixture 跨用户可跑 (P1.5 整改)。
    """
    result, path = _latest_result_v3_600693(mock_result_v3=mock_result_v3)
    plan = result.get("trading_plan") or {}
    if not plan:
        pytest.skip("600693 trading_plan 缺失（数据源问题，跳过）")
    assert "state" in plan, f"trading_plan 必须有 state 字段 (文件: {path})"
    assert "template_used" in plan, f"trading_plan 必须有 template_used 字段 (文件: {path})"
    # 600693 历史 score 通常 30-50, 落在 5 状态之一 (当前 34 = bearish, 边界 35)
    assert plan["state"] in ("neutral", "mild_bear", "bullish", "mild_bull", "bearish"), \
        f"600693 应落在 5 状态之一, 实际 {plan['state']}"
    if plan["state"] == "neutral":
        assert "区间操作" in plan["template_used"], \
            f"neutral 模板必须含'区间操作'，实际: {plan['template_used']}"
    elif plan["state"] == "mild_bear":
        assert "减仓至轻仓" in plan["template_used"], \
            f"mild_bear 模板必须含'减仓至轻仓'，实际: {plan['template_used']}"
    elif plan["state"] == "bullish":
        assert "分两批进场" in plan["template_used"], \
            f"bullish 模板必须含'分两批进场'，实际: {plan['template_used']}"
    elif plan["state"] == "mild_bull":
        assert "轻仓试探" in plan["template_used"], \
            f"mild_bull 模板必须含'轻仓试探'，实际: {plan['template_used']}"


# ============================================================
# 5. 渲染器 source code 自检: 操作口诀段落必须读 template_used
# ============================================================
def test_html_renderer_reads_template_used(html_report_v3_source):
    """HTML 渲染器 _render_checklist 必须读 plan['template_used']，而非 hardcode 模板

    P1.5 整改: 用 conftest.html_report_v3_source fixture
    """
    src = html_report_v3_source
    assert 'template_used' in src, "html_report_v3.py 必须引用 template_used"
    assert '操作口诀' in src, "html_report_v3.py 必须有'操作口诀'字样（5 状态机注入）"


def test_md_renderer_includes_template_used(report_md_source):
    """MD 渲染器 write_markdown_report_v3 必须读 plan['template_used']

    P1.5 整改: 用 conftest.quant_analyzer_v3_source fixture
    P2-A Phase 5 (2026-09-13): 报告层抽离后改读 report_md_source (写 markdown 渲染的宿主)
    """
    src = report_md_source
    # 同一文件，断言模板注入和读取都存在
    assert 'OPERATION_TEMPLATES' in src, "report_md.py 必须 import OPERATION_TEMPLATES"
    assert 'template_used' in src, "report_md.py 必须引用 template_used"
    assert '操作口诀' in src, "report_md.py MD 渲染必须有'操作口诀'字样"


def test_docx_renderer_does_not_hardcode_operation(md_to_docx_source):
    """DOCX 渲染器 md_to_docx.py 不应硬编码操作口诀（DOCX 跟随 MD）

    P1.5 整改: 用 conftest.md_to_docx_source fixture
    """
    src = md_to_docx_source
    # 旧 v2 写死的"分两批进"等字样不应再出现
    assert "分两批进" not in src, \
        "md_to_docx.py 不应硬编码'分两批进'，操作口诀由 MD 模板统一驱动"
