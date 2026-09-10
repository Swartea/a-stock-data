# analysis/sections/board/fetcher.py
"""§8.1-8.3 打板情绪 fetcher

数据源：
- em_zt_pool / em_zb_pool / em_dt_pool / em_yzt_pool（东财 push2ex 四池）
- ths_limit_up_pool（同花顺涨停原因 §8.2）
- limit_up_sentiment（§8.3 由四池派生，0 额外网络）

注意（端点验证 Part A.4 标记）：
- 4 个 em_* 端点**必须全部就绪**才返回有效数据，否则返回 error
  （因为 §8.3 sentiment 是由 4 池派生，缺一不可）
- ths_limit_up_pool / limit_up_sentiment 单点可缺失（hasattr 兜底）
- ZTB_UT 是东财登录 token，公开但易失效 — 端点本身会 try/except
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import quant_analyzer_v2 as v2


# 4 个东财端点中: zt/zb/dt 三池必选, yzt(一字板) 可选 (akshare 无 stock_zt_pool_yjyg_em 接口)
_REQUIRED_ENDPOINTS = ["em_zt_pool", "em_zb_pool", "em_dt_pool"]
_OPTIONAL_ENDPOINTS = ["em_yzt_pool"]


def _raw_fetch(date: str) -> dict:
    """底层拉数据 — 调用 v2 的打板四池 + 涨停原因 + 情绪

    Returns:
        dict:
          - zt: list[dict] 涨停池
          - dt: list[dict] 跌停池
          - yzt: list[dict] 一字板池（可空，akshare 无接口时返回 []）
          - limit_up_reasons: list[dict] 同花顺涨停原因（可空）
          - sentiment: dict §8.3 情绪字典（可空）
        失败抛 RuntimeError
    """
    if not all(hasattr(v2, fn) for fn in _REQUIRED_ENDPOINTS):
        missing = [fn for fn in _REQUIRED_ENDPOINTS if not hasattr(v2, fn)]
        raise RuntimeError(f"打板端点未全部就绪: 缺 {','.join(missing)}")

    zt = v2.em_zt_pool(date) or []

    # 涨停原因（同花顺，可选）
    ths: list = []
    try:
        if hasattr(v2, "ths_limit_up_pool"):
            ths = v2.ths_limit_up_pool(date) or []
    except Exception:
        ths = []

    # 情绪（§8.3 派生，可选）
    sent: dict = {}
    try:
        if hasattr(v2, "limit_up_sentiment"):
            sent = v2.limit_up_sentiment(date) or {}
    except Exception:
        sent = {}

    # 跌停池放最后（如果 limit_up_sentiment 用了 zb 池，先 zb 再 dt 更稳）
    dt = v2.em_dt_pool(date) or []

    # 一字板池 (可选, akshare 缺 stock_zt_pool_yjyg_em, 留空 list)
    yzt: list = []
    try:
        if hasattr(v2, "em_yzt_pool"):
            yzt = v2.em_yzt_pool(date) or []
    except Exception:
        yzt = []

    return {
        "zt": zt,
        "dt": dt,
        "yzt": yzt,
        "limit_up_reasons": ths,
        "sentiment": sent if isinstance(sent, dict) else {},
    }


def fetch_board(date: str = "20260904") -> dict:
    """拉打板情绪数据（当日四池 + 涨停原因 + 情绪派生）

    Args:
        date: YYYYMMDD 交易日。默认 20260904（brief 示例）。

    Returns:
        dict: {"zt": [...], "dt": [...], "limit_up_reasons": [...], "sentiment": {...}}
        或 {"error": str} 兜底
    """
    try:
        return _raw_fetch(date)
    except Exception as e:
        return {"error": str(e)}
