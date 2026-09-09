"""Task 5.5 D-3 修法 — PEG talk-text 4 档阈值测试

历史: docs/04-模板质量债.md D-3 + analysis/references/report-design-principles.md:73-77
  - 报告设计原则 4 档: < 1 / 1-1.5 / > 1.5 / > 3 极贵（成长股例外）
  - V3 quant_analyzer_v3.py:1702 实装 3 档, 缺 > 3 极贵
  - 实测 600693 PEG=9.56 → 错标 "PEG > 1.5, 偏贵" (粗粒度), 应为 "PEG > 3, 极贵"

修法（Task 5.5）:
  - V3 提取 _format_peg_talk(peg) 独立函数, 4 档阈值
  - line 1702 调用 _format_peg_talk(peg)
  - 测试覆盖: 4 档边界 (0.5/1.0/1.5/3.0) + 9.56 实测值
  - 严守: PEG 公式 (pe_ttm / cagr_pct) 不动, 只改阈值
"""
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")

import pytest
from analysis.quant_analyzer_v3 import _format_peg_talk  # noqa: E402


@pytest.mark.parametrize("peg,expected_substr", [
    (0.5, "便宜区"),       # < 1
    (0.99, "便宜区"),      # 边界: < 1
    (1.0, "合理"),          # 边界: = 1 (落入 1-1.5)
    (1.4, "合理"),          # 1-1.5
    (1.5, "偏贵"),          # 边界: = 1.5 (落入 1.5-3)
    (2.5, "偏贵"),          # 1.5-3
    (3.0, "极贵"),          # 边界: = 3 (落入 > 3)
    (5.0, "极贵"),          # > 3
    (9.56, "极贵"),         # 600693 实测
    (20.0, "极贵"),         # 极端
])
def test_peg_talk_4_tiers(peg, expected_substr):
    text = _format_peg_talk(peg)
    assert expected_substr in text, (
        f"PEG={peg} 应含 '{expected_substr}', 实得: {text}"
    )


def test_peg_talk_4_tiers_full_text():
    """完整 4 档文案验证 (不仅子串)."""
    assert _format_peg_talk(0.5) == "PEG < 1, 便宜区"
    assert _format_peg_talk(1.2) == "PEG 1~1.5, 合理"
    assert _format_peg_talk(2.0) == "PEG 1.5~3, 偏贵"
    assert _format_peg_talk(9.56) == "PEG > 3, 极贵（成长股例外：壁垒深可能合理）"


def test_peg_talk_600693_specific():
    """600693 实测 PEG=9.56, 必须落在 "极贵" 档 (与实测一致)."""
    text = _format_peg_talk(9.56)
    assert "极贵" in text
    assert "成长股例外" in text  # 关键免责说明


def test_peg_talk_boundary_correctness():
    """边界值正确性: < 用 not <=. 1.0 -> 合理, 1.5 -> 偏贵, 3.0 -> 极贵."""
    assert _format_peg_talk(1.0) == "PEG 1~1.5, 合理"
    assert _format_peg_talk(1.5) == "PEG 1.5~3, 偏贵"
    assert _format_peg_talk(3.0) == "PEG > 3, 极贵（成长股例外：壁垒深可能合理）"
