import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import quant_analyzer_v3 as v3


def test_fund_flow_daily_uses_push2his():
    """5 日主力资金流应走 push2his（同 SKILL.md §4.5），不应再有 'Expecting value' 错误"""
    if hasattr(v3, "_fetch_fund_flow_daily"):
        result = v3._fetch_fund_flow_daily("600693", days=5)
    else:
        # fall back to running analyze_single_v3 (slower)
        out = v3.analyze_single_v3("600693", "东百集团", write_artifact=False)
        result = out.get("fund_daily5") or {}
    # 1. 旧 push2 JSON 解析错误不应再现
    err = result.get("error", "")
    assert "Expecting value" not in err, f"应消除旧 push2 JSON 解析错误: {err}"
    # 2. 真实数据应有 rows（push2his 走通）
    if not err:
        # 成功路径必须有正向断言
        assert result.get("rows") or result.get("data"), f"成功路径应返回 rows/data，实际: {list(result.keys())}"
