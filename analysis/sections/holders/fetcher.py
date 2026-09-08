# analysis/sections/holders/fetcher.py
"""§4.3 股东户数 fetcher

数据源：datacenter-web.eastmoney.com RPT_HOLDERNUMLATEST
（端点验证 Part A.2 标记 datacenter-web 稳定可集成）

注意：v2 中暂未实现 fetch_holder_num_change（待 Phase 3 补齐），
本 fetcher 用 hasattr 兜底，无端点时返回空 rows。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import quant_analyzer_v2 as v2


def _raw_fetch(code: str, limit: int = 4) -> list:
    """底层拉数据 — 调用 v2 的 holder_num_change 端点

    返回 list[dict]，每个 dict 至少含：
        - date: 报告期（YYYY-MM-DD）
        - holder_num: 股东户数
        - change_ratio: 环比%
        - avg_shares_per_holder: 户均持股数
    """
    try:
        if hasattr(v2, "fetch_holder_num_change"):
            rows = v2.fetch_holder_num_change(code, limit=limit)
            return rows or []
        # 兜底：v2 暂未实现该端点
        return []
    except Exception as e:
        raise RuntimeError(f"holder_num_change 拉取失败: {e}") from e


def fetch_holders(code: str, limit: int = 4) -> dict:
    """拉股东户数（最近 4 季）

    Returns:
        dict: {"rows": [...]}
        或 {"error": str} 兜底
    """
    try:
        rows = _raw_fetch(code, limit)
        return {"rows": rows or []}
    except Exception as e:
        return {"error": str(e)}
