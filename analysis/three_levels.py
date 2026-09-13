"""analysis/ 三价位层 (P2-A Phase 3, 2026-09-13)

按规范 §2 模块边界 + P0-A 三价位规范整改, 把 compute_three_levels + 5 辅助函数
抽到 three_levels.py:
- compute_three_levels(quote, chip_data, trading_plan): 主函数, 4 支撑/3 压力候选 → 1 个
- _klines_to_series(chip_data): 从 chip_data['kline'] 提取 K 线序列
- _series_ma(series, n): 简单移动平均
- _series_boll(series, n, k): 布林带 (lower, upper) 二元组
- _series_recent_high/low(series, n): 60 日内 high/low 最值
- (5 个辅助函数对内 / 对外用)

P0-A 命名 (2026-09-11 整改, 与 §6 规范对齐):
  - 支撑 = "支撑下沿" (4 候选最小, 过滤>1.05×价, 允许跨现价 5%)
  - 压力 = "压力上沿" (3 候选最大, 过滤<0.95×价, 允许跨现价 5%)
  - 与 §6 标准"最近支撑/压力" (不高于现价最大/不低于现价最小) 不同,
    §6 要求"若产品选择区间极值或允许跨越现价, 必须另行命名" — 本模块即采用此命名
  - 完整规则+例子+边界: analysis/references/three-levels-rules.md

向后兼容: v3 顶层 `from analysis.three_levels import compute_three_levels, ...`,
          老 `from analysis.quant_analyzer_v3 import compute_three_levels` 仍能找到 (re-export)。

§1 '不修改业务口径' — 4 支撑/3 压力候选 + ±5% 过滤 + 候选键名 照搬, 仅搬位置。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from analysis.utils import to_float


# ============================================================
# K 线序列 + 辅助计算
# ============================================================
def klines_to_series(chip_data: Optional[Dict]) -> Optional[List[Dict]]:
    """从 chip_data['kline'] 提取 [{date, close, high, low}, ...] 序列（按时间正序）。

    chip_data 是 v2.fetch_chip_distribution() 返回值，含 kline 字段（v2 line 616-618）。
    无 kline / 含 error / 解析失败 → 返回 None（不抛）。
    """
    if not chip_data or not isinstance(chip_data, dict):
        return None
    if "error" in chip_data:
        return None
    klines = chip_data.get("kline") or []
    if not klines:
        return None
    out = []
    for k in klines:
        try:
            out.append({
                "date": str(k["date"]),
                "close": float(k["close"]),
                "high": float(k["high"]),
                "low": float(k["low"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


# 别名
def _klines_to_series(chip_data):
    return klines_to_series(chip_data)


def series_ma(series: Optional[List[Dict]], n: int) -> Optional[float]:
    """简单移动平均（最后 n 日 close 均值）；len < n 或 n <= 0 → None"""
    if not series or n <= 0 or len(series) < n:
        return None
    closes = [s["close"] for s in series[-n:]]
    return sum(closes) / len(closes)


# 别名
def _series_ma(series, n):
    return series_ma(series, n)


def series_boll(series: Optional[List[Dict]], n: int = 20, k: int = 2) -> Optional[Tuple[float, float]]:
    """布林带 (MA_n ± k·σ)。返回 (lower, upper) 二元组；不足 n 日 → None"""
    if not series or len(series) < n:
        return None
    closes = [s["close"] for s in series[-n:]]
    mean = sum(closes) / n
    var = sum((c - mean) ** 2 for c in closes) / n
    std = var ** 0.5
    return (round(mean - k * std, 2), round(mean + k * std, 2))


# 别名
def _series_boll(series, n=20, k=2):
    return series_boll(series, n, k)


def series_recent_high(series: Optional[List[Dict]], n: int = 60) -> Optional[float]:
    """最近 n 日 K 线 high 最大值；无 series → None"""
    if not series:
        return None
    window = series[-n:] if len(series) >= n else series
    return max(s["high"] for s in window)


# 别名
def _series_recent_high(series, n=60):
    return series_recent_high(series, n)


def series_recent_low(series: Optional[List[Dict]], n: int = 60) -> Optional[float]:
    """最近 n 日 K 线 low 最小值；无 series → None"""
    if not series:
        return None
    window = series[-n:] if len(series) >= n else series
    return min(s["low"] for s in window)


# 别名
def _series_recent_low(series, n=60):
    return series_recent_low(series, n)


# ============================================================
# 主函数: 三价位 (P0-A 规范整改 v1.0)
# ============================================================
def compute_three_levels(quote: Optional[Dict], chip_data: Optional[Dict],
                         trading_plan: Optional[Dict] = None) -> Dict[str, Any]:
    """三价位: 支撑下沿/压力上沿/止损 (P0-A 规范整改 v1.0, 2026-09-11)

    业务含义: 报告 §"三价位" 段展示的"支撑/压力/止损", 供"低吸/减仓/止损离场"参考。
    完整规则+例子+边界: `analysis/references/three-levels-rules.md`

    命名约定 (与 §6 规范对齐, 2026-09-11 整改):
      - 支撑 = "支撑下沿" = ±5% 区间内最低 (允许跨现价 5%)
      - 压力 = "压力上沿" = ±5% 区间内最高 (允许跨现价 5%)
      - 与 §6 标准"最近支撑/压力" (不高于现价最大 / 不低于现价最小) 不同,
        §6 要求"若产品选择区间极值或允许跨越现价, 必须另行命名" — 本函数即采用此命名

    支撑候选 (4 类, 任一缺失不影响其他):
      1. ma60        — K 线 close 60 日均线
      2. recent_low  — 60 日内 K 线 low 最小值
      3. chip_peak   — 筹码峰 (chip_data['peak_price'], v2 line 572 平铺)
      4. boll_lower  — 布林下轨 = MA20 - 2σ

    压力候选 (3 类, 任一缺失不影响其他):
      1. ma250_or_ma120 — K 线 close 250 日均线, N<250 回退 120 日
      2. recent_high    — 60 日内 K 线 high 最大值
      3. boll_upper     — 布林上轨 = MA20 + 2σ

    过滤与选择:
      - 支撑: 过滤掉 > 1.05×现价 的候选, 剩余取最小
      - 压力: 过滤掉 < 0.95×现价 的候选, 剩余取最大
      - 任一过滤后无候选 → 对应字段 = None, 不填充

    止损: 复用 trading_plan.stop_loss (V2 同源, 不重算, 防覆盖 Task 5.1 锁定字段)
           trading_plan 缺失或 stop_loss=None → 字段 = None

    返回 dict (与 docs/references/three-levels-rules.md §五 一致):
        {
            "support": float|None,           # 支撑下沿
            "resistance": float|None,        # 压力上沿
            "stop_loss": float|None,         # 止损 (复用 trading_plan)
            "support_candidates": dict,      # 全部支撑候选 (未过滤)
            "resistance_candidates": dict,   # 全部压力候选 (未过滤)
            "method": str,                   # 算法描述, 含 N=K线数
        }
    """
    price = to_float((quote or {}).get("price"))
    series = klines_to_series(chip_data)
    n = len(series) if series else 0

    # ---- 4 支撑候选 ----
    sup_raw = {
        "ma60": series_ma(series, 60),
        "recent_low": series_recent_low(series, 60),
        "chip_peak": to_float((chip_data or {}).get("peak_price")) if chip_data else None,
        "boll_lower": (series_boll(series, 20, 2) or (None, None))[0],
    }
    sup_valid = {k: v for k, v in sup_raw.items() if v is not None}

    # ---- 3 压力候选 ----
    long_ma = series_ma(series, 250) or series_ma(series, 120)
    boll_bands = series_boll(series, 20, 2)
    res_raw = {
        "ma250_or_ma120": long_ma,
        "recent_high": series_recent_high(series, 60),
        "boll_upper": boll_bands[1] if boll_bands else None,
    }
    res_valid = {k: v for k, v in res_raw.items() if v is not None}

    # ---- 过滤 ±5% + 取最近者 (支撑下沿/压力上沿, P0-A 命名统一) ----
    support = None
    if price is not None and sup_valid:
        eligible = {k: v for k, v in sup_valid.items() if v <= price * 1.05}
        if eligible:
            support = min(eligible.values())  # 支撑下沿 = 区间内最低 (允许跨价 5%)
    resistance = None
    if price is not None and res_valid:
        eligible = {k: v for k, v in res_valid.items() if v >= price * 0.95}
        if eligible:
            resistance = max(eligible.values())  # 压力上沿 = 区间内最高 (允许跨价 5%)

    # ---- stop_loss 复用 trading_plan.stop_loss (不重算, 防止覆盖 Task 5.1) ----
    stop_loss = None
    if isinstance(trading_plan, dict):
        stop_loss = to_float(trading_plan.get("stop_loss"))

    return {
        "support": round(support, 2) if support is not None else None,
        "resistance": round(resistance, 2) if resistance is not None else None,
        "stop_loss": round(stop_loss, 2) if stop_loss is not None else None,
        "support_candidates": {k: round(v, 2) for k, v in sup_valid.items()},
        "resistance_candidates": {k: round(v, 2) for k, v in res_valid.items()},
        "method": (f"4 候选取最近者 (P0-A 命名: 支撑下沿/压力上沿; "
                   f"4 候选 → 支撑下沿 (取最小, 过滤>1.05×价); "
                   f"3 候选 → 压力上沿 (取最大, 过滤<0.95×价); N={n} 根K线)"),
    }
