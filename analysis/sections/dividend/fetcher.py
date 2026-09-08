# analysis/sections/dividend/fetcher.py
"""§4.4 分红送转 fetcher

数据源：datacenter-web.eastmoney.com RPT_SHAREBONUS_DET
（端点验证 Part A.3 标记 datacenter-web 稳定可集成）

注意：v2 中暂未实现 fetch_dividend_history（待 Phase 3 补齐），
本 fetcher 用 hasattr 兜底，无端点时返回空 rows。

None-safe 处理（端点验证 Part A.3 标记）：
- BONUS_RATIO 字段可能为 null（无送转）→ 0
- 用 `r.get("BONUS_RATIO") or 0`，不用 `r.get("BONUS_RATIO", 0)`，
  因为 null 是真实值（无送转），不能误以为是字段缺失
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import quant_analyzer_v2 as v2


def _raw_fetch(code: str, limit: int = 10) -> list:
    """底层拉数据 — 调用 v2 的 dividend_history 端点

    返回 list[dict]，每个 dict 至少含：
        - report_date: 报告期（YYYY-MM-DD）
        - plan: 方案（如 "10派4元"、"10送2转3"）
        - bonus_rmb: 每股派息（元）
        - bonus_ratio: 每股送股（None-safe → 0）
        - transfer_ratio: 每股转增（None-safe → 0）
    """
    try:
        if hasattr(v2, "fetch_dividend_history"):
            rows = v2.fetch_dividend_history(code, limit=limit)
            return rows or []
        # 兜底：v2 暂未实现该端点
        return []
    except Exception as e:
        raise RuntimeError(f"dividend_history 拉取失败: {e}") from e


def fetch_dividend(code: str, limit: int = 10) -> dict:
    """拉分红送转记录（最近 10 条 = 5 年）

    None-safe 转换：
    - BONUS_RATIO null → bonus_ratio=0（无送转）
    - 用 `.get(...) or 0` 而非 `.get(..., 0)`，因为 null 是真实值

    Returns:
        dict: {"rows": [...]}
        或 {"error": str} 兜底
    """
    try:
        rows = _raw_fetch(code, limit)
        # None-safe 转换：BONUS_RATIO null 视为 0（无送转）
        for r in rows:
            r["bonus_rmb"] = r.get("BONUS_RATIO") or 0
            r["bonus_ratio"] = r.get("BONUS_RATIO") or 0
            r["transfer_ratio"] = r.get("IT_RATIO") or 0
        return {"rows": rows or []}
    except Exception as e:
        return {"error": str(e)}
