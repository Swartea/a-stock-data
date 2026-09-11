"""Task 6.6: V3 MD 排版美观优化测试

历史: docs/superpowers/plans/2026-09-09-html-ui-upgrade.md 6.6 段
- 30 秒决策卡: 7 列大表 (现价/涨跌/市值/PE/PB/分位/PEG), 1 屏读完全部核心数据
- 三价位 4 行大表 (现价 + 支撑/压力/止损, emoji 颜色 + 距现价%)
- 操作口诀 5 状态机 (3 段: 结论 + 操作 + 风险)
- PEG 4 档阈值 (Task 5.5): 便宜/合理/偏贵/极贵
"""
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")

import pytest
from pathlib import Path


# ============================================================
# 测试 1: 30 秒决策卡大表结构
# ============================================================
def test_md_has_30s_decision_card():
    """MD 报告应含 30 秒决策卡大表 (7 列核心指标)。"""
    md_files = list(Path("/Users/swarteachou/Desktop/大A数据/reports").glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest = max(md_files, key=lambda p: p.stat().st_mtime)
    content = latest.read_text(encoding="utf-8")

    # 30 秒决策卡大表 (7 列核心指标)
    assert "## 🎯 30 秒决策卡" in content, f"{latest.name} 缺 30 秒决策卡段"
    assert "💰 现价" in content, f"{latest.name} 缺现价列"
    assert "📊 涨跌" in content, f"{latest.name} 缺涨跌列"
    assert "🏭 流通市值" in content, f"{latest.name} 缺流通市值列"
    assert "📈 PE(TTM)" in content, f"{latest.name} 缺 PE(TTM)列"
    assert "📉 PB" in content, f"{latest.name} 缺 PB 列"
    assert "📊 PE 分位" in content, f"{latest.name} 缺 PE 分位列"
    assert "🎯 PEG" in content, f"{latest.name} 缺 PEG 列"


# ============================================================
# 测试 2: 三价位 4 行大表 (含现价参考行 + emoji)
# ============================================================
def test_md_has_three_levels_4row_table():
    """MD 报告三价位段应含 4 行大表 (现价 + 支撑/压力/止损)。"""
    md_files = list(Path("/Users/swarteachou/Desktop/大A数据/reports").glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest = max(md_files, key=lambda p: p.stat().st_mtime)
    content = latest.read_text(encoding="utf-8")

    # 三价位标题
    assert "### 🎯 三价位" in content, f"{latest.name} 缺三价位段"

    # 4 行大表: 现价 + 支撑 + 压力 + 止损
    assert "💰 **现价**" in content, f"{latest.name} 缺现价行"
    assert "🟢 **支撑位（支撑下沿）**" in content, f"{latest.name} 缺支撑行 (绿, P0-A 命名)"
    assert "🔴 **压力位（压力上沿）**" in content, f"{latest.name} 缺压力行 (红, P0-A 命名)"
    assert "🟡 **止损位**" in content, f"{latest.name} 缺止损行 (黄)"

    # 距现价% 列
    assert "距现价" in content, f"{latest.name} 缺距现价%列"
    assert "0% (参考)" in content, f"{latest.name} 现价行距现价% 应为 0% (参考)"


# ============================================================
# 测试 3: 操作口诀 5 状态机 (3 段: 结论 + 操作 + 风险)
# ============================================================
def test_md_has_operation_proverb_5state():
    """MD 报告应含操作口诀段, 5 状态机 (3 段: 结论/操作/风险)。"""
    md_files = list(Path("/Users/swarteachou/Desktop/大A数据/reports").glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest = max(md_files, key=lambda p: p.stat().st_mtime)
    content = latest.read_text(encoding="utf-8")

    # 操作口诀段
    assert "### 💰 操作口诀" in content, f"{latest.name} 缺操作口诀段"

    # 3 段 (结论/操作/风险) — 用 【】 包裹
    assert "【结论】" in content, f"{latest.name} 缺【结论】段"
    assert "【操作】" in content, f"{latest.name} 缺【操作】段"
    assert "【风险】" in content, f"{latest.name} 缺【风险】段"

    # 多目标价 / 买入区间 / 周期
    assert "多目标价" in content, f"{latest.name} 缺多目标价"
    assert "买入区间" in content, f"{latest.name} 缺买入区间"
    assert "周期" in content, f"{latest.name} 缺周期"

    # 数据可信度声明
    assert "🔒" in content, f"{latest.name} 缺数据可信度声明"
    assert "V2 同源实时模型" in content, f"{latest.name} 缺 V2 同源声明"


# ============================================================
# 测试 4: PEG 4 档阈值 (Task 5.5) — 端到端验证
# ============================================================
def test_md_peg_4tier_threshold():
    """MD 报告 PEG 列应含 4 档阈值标签 (便宜/合理/偏贵/极贵)。"""
    md_files = list(Path("/Users/swarteachou/Desktop/大A数据/reports").glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest = max(md_files, key=lambda p: p.stat().st_mtime)
    content = latest.read_text(encoding="utf-8")

    # 600693 PEG 9.43 (历史) 或更新值, 极贵档 (>3)
    # 检查 30 秒决策卡 PEG 列含 "极贵"
    decision_section = content.split("## 🚨 风险警报区")[0]
    assert "极贵" in decision_section, f"{latest.name} 决策卡 PEG 列缺极贵标签"


# ============================================================
# 测试 5: 4/3 候选明细 (次要信息 blockquote 折叠)
# ============================================================
def test_md_has_candidates_blockquote():
    """MD 报告三价位段应含 4 支撑 / 3 压力候选明细 (blockquote)。"""
    md_files = list(Path("/Users/swarteachou/Desktop/大A数据/reports").glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest = max(md_files, key=lambda p: p.stat().st_mtime)
    content = latest.read_text(encoding="utf-8")

    # 4 支撑候选: ma60 / recent_low / chip_peak / boll_lower
    for cand in ["ma60", "recent_low", "chip_peak", "boll_lower"]:
        assert cand in content, f"{latest.name} 缺支撑候选 {cand}"

    # 3 压力候选: ma250_or_ma120 / recent_high / boll_upper
    for cand in ["ma250_or_ma120", "recent_high", "boll_upper"]:
        assert cand in content, f"{latest.name} 缺压力候选 {cand}"
