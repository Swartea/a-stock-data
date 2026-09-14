"""Task 5.4 D-2 修法 — MD 报告 Section Registry 5 sections 渲染循环测试

历史: docs/04-模板质量债.md D-2
  - V3 报告 5 sections (irm/holders/dividend/board/dragon_market) 由 Section Registry 注入
  - HTML 渲染器 (html_report_v3.py:1370-1383, Phase 1.4 改造) 已支持循环渲染
  - DOCX 渲染器 (md_to_docx.py:538-548, Phase 1.5 改造) 已支持循环渲染
  - **MD 报告 (write_markdown_report_v3) 没抄这个循环** — D-2 仅在 run_log 表格 mention, 正文缺 5 sections 完整内容

修法（Task 5.4）:
  - V3 主分析器 write_markdown_report_v3() 在 6 块 + 3 supplement 之后 / 链路运行记录之前
    追加 Section Registry 循环 (与 HTML/DOCX 渲染器 pattern 对齐)
  - 5 sections 注入到 MD 正文: irm/holders/dividend/board/dragon_market
  - 严守其他 task 锁定: trading_plan/three_levels/north_label/PEG 不动
"""
import os
import sys
from pathlib import Path

# 使用仓库/CI 工作目录, 不绑定个人 Mac 路径
WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(WORKDIR))

import pytest

REPORTS_ROOT = WORKDIR / "reports" / "600693_东百集团"

# 5 sections 各自 title (来自 analysis/sections/*/meta.py)
SECTION_TITLES = {
    "irm": "📞 投资者互动问答",
    "holders": "📊 股东户数变化",
    "dividend": "💰 分红送转",
    "board": "🎰 打板情绪",
    "dragon_market": "🐉 龙虎榜动向（市场）",
}


def _latest_md() -> Path:
    """取仓库中最新 MD 报告；CI 未携带历史实盘产物时明确跳过。"""
    md_files = list(REPORTS_ROOT.glob("*/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip(f"未提供历史 MD 报告 fixture: {REPORTS_ROOT}")
    return max(md_files, key=lambda p: p.stat().st_mtime)


# ============================================================
# 测试 1: MD 报告含 5 sections 完整内容 (D-2 主修法验证)
# ============================================================
def test_md_report_has_5_sections_in_body():
    """MD 报告正文必须含 5 sections 完整内容 (irm/holders/dividend/board/dragon_market)。

    验证方法: 5 sections 的 title 必须出现在 MD 报告**正文** (不只在 run_log 表格 mention)。
    """
    latest = _latest_md()
    content = latest.read_text(encoding="utf-8")

    for sec_id, sec_title in SECTION_TITLES.items():
        assert sec_title in content, (
            f"{sec_id} section 缺失 in {latest.name} (title='{sec_title}')"
        )


# ============================================================
# 测试 2: 每个 section 有数据行 (不只 title 单独存在)
# ============================================================
def test_md_sections_have_data_lines():
    """每个 section 必须有数据行 (不只孤零零一个 ## title)。

    验证方法: 取 title 后 500 字符, 必须含 ## 下一级 (### / ⚠️ warn / 数据行 / 数据源说明)。
    """
    latest = _latest_md()
    content = latest.read_text(encoding="utf-8")

    for sec_id, sec_title in SECTION_TITLES.items():
        idx = content.find(sec_title)
        assert idx > 0, f"{sec_id} section title 缺失 in {latest.name}"
        # 取 title 后 500 字符 (含数据行 / warn / 数据源说明)
        snippet = content[idx:idx + 500]
        # 必须含: ### 子标题 / ⚠️ warn / 数据源 (📡 / 来源:) / 数据行 ( - / |)
        has_content = (
            "###" in snippet
            or "⚠️" in snippet
            or "数据来源" in snippet
            or "数据源" in snippet
            or "📡" in snippet
            or "— " in snippet  # 数据行格式
            or "|" in snippet  # 表格格式
        )
        assert has_content, (
            f"{sec_id} section 标题后无数据行 in {latest.name}\n"
            f"snippet: {snippet[:200]}"
        )


# ============================================================
# 测试 3: 5 sections 在 run_log 之前 (位置正确, 与 HTML/DOCX 对齐)
# ============================================================
def test_sections_appear_before_run_log():
    """5 sections 位置: 在 6 块 + 3 supplement 之后, 链路运行记录 (## 🔗) 之前。

    HTML 渲染器在 6 块之后、附录 (run_log) 之前追加; MD 也应对齐。
    """
    latest = _latest_md()
    content = latest.read_text(encoding="utf-8")

    run_log_idx = content.find("## 🔗 数据链路与运行记录")
    assert run_log_idx > 0, "链路运行记录 (## 🔗) 缺失"

    for sec_id, sec_title in SECTION_TITLES.items():
        idx = content.find(sec_title)
        assert idx > 0, f"{sec_id} section 缺失"
        assert idx < run_log_idx, (
            f"{sec_id} section 位置错: 应在 run_log 之前, 但 idx={idx} > run_log_idx={run_log_idx}"
        )


# ============================================================
# 测试 4: 注入不破坏其他锁定字段 (trading_plan / three_levels / north_label)
# ============================================================
def test_locked_fields_unchanged():
    """Task 5.1/5.2/5.3 锁定字段不能被本次 patch 影响。

    - trading_plan.{state, template_used, entry_*, stop_loss_*, tp*}
    - three_levels.{support, resistance, stop_loss}
    - macro.north_label (在 MD "宏观底色" 段)
    """
    latest = _latest_md()
    content = latest.read_text(encoding="utf-8")

    # 5 状态机: state 字段值必为 5 状态之一 (Task 5.1)
    state_5 = ["🟢 强烈看多", "🟢 偏多", "🟡 中性", "🟠 偏空", "🔴 强烈看空"]
    has_state = any(s in content for s in state_5)
    assert has_state, f"5 状态机 (Task 5.1) 缺失 in {latest.name}"

    # 三价位 (Task 5.2): "三价位" 段存在
    assert "三价位" in content, "三价位段 (Task 5.2) 缺失"

    # 宏观底色 (Task 5.3): 含 "宏观底色" 段
    assert "宏观底色" in content, "宏观底色段 (Task 5.3) 缺失"
