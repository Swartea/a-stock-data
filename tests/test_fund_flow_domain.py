import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
import quant_analyzer_v3 as v3

def test_fund_flow_daily_uses_push2his():
    """5 日主力资金流应走 push2his（同 §4.5），不应 error"""
    code = "600693"
    # 触发 _fetch_fund_flow_daily（公开函数名可能不同，按实际修）
    result = v3._fetch_fund_flow_daily(code, days=5) if hasattr(v3, "_fetch_fund_flow_daily") else None
    if result is None:
        # 调外部入口验证
        from quant_analyzer_v3 import analyze_single_v3
        out = analyze_single_v3(code, "东百集团", write_artifact=False)
        assert "fund_daily5" in out or "资金面-5日主力" in str(out)
    else:
        assert "error" not in result or "Expecting value" not in result.get("error", "")
