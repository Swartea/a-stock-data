# analysis/sections/dragon_market/fetcher.py
"""§3.9 全市场龙虎榜 fetcher

数据源：datacenter-web.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW
（端点验证 Part A.6 标记 datacenter-web 200/66 条）

注意（端点验证 Part A.6 标记）：
- `daily_dragon_tiger` 端点 v2 暂未实现（brief §关键差异），hasattr 兜底
- 市场维度（非单票）：code 不影响，fetch() 用 datetime.now() 取当日
- 数据结构（端点验证 Part A.6 标记）：`{"stocks": [...], "total_records": N}`
  每个 stock 至少含：code / name / net_buy（净买额，单位元）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import quant_analyzer_v2 as v2


def _raw_fetch(date: str) -> dict:
    """底层拉数据 — 调用 v2 的 daily_dragon_tiger 端点

    Returns:
        dict: 原始数据，含 {"stocks": [...], "total_records": N}
        失败抛 RuntimeError
    """
    if not hasattr(v2, "daily_dragon_tiger"):
        raise RuntimeError("daily_dragon_tiger 端点未就绪")

    data = v2.daily_dragon_tiger(date)
    if not isinstance(data, dict):
        raise RuntimeError(f"daily_dragon_tiger 返回非 dict: {type(data).__name__}")

    return data


def fetch_dragon_market(date: str = "20260904", top_n: int = 20) -> dict:
    """拉当日全市场龙虎榜（Top N 净买额）

    Args:
        date: YYYYMMDD 交易日。默认 20260904（brief 示例）。
        top_n: 取 Top N 净买额个股，默认 20。

    Returns:
        dict: {"stocks": [...top_n 排序后...], "total_records": N}
        或 {"error": str} 兜底
    """
    try:
        data = _raw_fetch(date)
        # 排序 + 取 Top N（brief §关键差异）
        if isinstance(data, dict) and "stocks" in data and isinstance(data["stocks"], list):
            data["stocks"].sort(key=lambda s: s.get("net_buy", 0) or 0, reverse=True)
            data["stocks"] = data["stocks"][:top_n]
        return data
    except Exception as e:
        return {"error": str(e)}
