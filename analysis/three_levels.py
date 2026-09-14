"""analysis/ 三价位层 (P2-A Phase 3, 2026-09-13; 批次 D 债 2 修法, 2026-09-14; 批次 E 痛 1 修法, 2026-09-14)

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

批次 D 债 2 修法 (2026-09-14):
  - 止损 = max(支撑 × 0.97, trading_plan.stop_loss) [取高者, 防倒挂]
  - "倒挂" 指 V2 按现价-7% 反推的止损与"技术位支撑"口径不一致:
      - V2 > 支撑 (杰瑞 110.61 > 104.87): 接受 V2 (大止损, method="trading_plan")
      - V2 < 支撑 × 0.97: 强切到 支撑 × 0.97 (止损过紧, method="support_buffer")
  - 新增字段 stop_loss_method: "trading_plan" / "support_buffer" / "max_of_both"
  - 杰瑞类 (V2 > 支撑) 数值不变, 仅 method 标签化, 报告层可据此注明计算来源

批次 E 痛 1 修法 (2026-09-14):
  - 远/近期位分层: 拆"操作位" (近, 5-25% 范围) + "参考位" (远, 60 日极值)
  - support / resistance 字段语义升级为"操作位":
      - 操作支撑 = 4 候选中"距现价 5-25% 范围 且 < 现价 且距现价最近"者
      - 操作压力 = 3 候选中"距现价 5-25% 范围 且 > 现价 且距现价最近"者
      - 旧行为作为 fallback: 操作位无候选时, 用原 ±5% 过滤后取最近 (保持向后兼容)
  - 新增 4 字段:
      - support_recent / resistance_recent (float)  : 操作位距现价百分比
      - support_extreme / resistance_extreme (float) : 参考位 (60 日最低 / 最高)
      - support_extreme_label / resistance_extreme_label (str) : 标签
      - operational_band_pct (tuple) : 操作位允许范围 (5.0, 25.0)

向后兼容: v3 顶层 `from analysis.three_levels import compute_three_levels, ...`,
          老 `from analysis.quant_analyzer_v3 import compute_three_levels` 仍能找到 (re-export)。

§1 '不修改业务口径' — 4 支撑/3 压力候选 + ±5% 过滤 + 候选键名 照搬, 仅搬位置。
   批次 D 改 stop_loss 计算口径 (债 2), 但 4 支撑/3 压力候选逻辑零变更。
   批次 E 痛 1 改 support/resistance 字段语义 (4 候选中"操作位"语义), 但
   fallback 路径与原 ±5% 过滤行为一致, 旧调用方拿到 support/resistance 仍可用。
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

    止损 (批次 D 债 2 修法, 2026-09-14):
      - 旧版: 严格复用 trading_plan.stop_loss (V2 同源)
      - 新版: stop_loss = max(支撑 × 0.97, trading_plan.stop_loss), 取高者
      - 目的: 防 V2 止损 < 支撑 × 0.97 的"倒挂" (即止损过紧, 突破即走, 没缓冲)
      - 边界:
          - trading_plan 缺失或 stop_loss=None → stop_loss = None (不编造)
          - 支撑为 None 但 plan.stop_loss 有值 → 用 plan.stop_loss (method="trading_plan")
          - 两者都有 → max() 规则
              - plan.stop_loss >= 支撑 × 0.97 → 用 plan.stop_loss (method="trading_plan")
              - 支撑 × 0.97 > plan.stop_loss  → 用 支撑 × 0.97 (method="support_buffer")
              - 相等 → 任意, method="max_of_both"
      - 杰瑞类 (V2 > 支撑) 数值不变, 仅 method 标签化, 报告层可据此注明

    返回 dict (与 docs/references/three-levels-rules.md §五 一致, 批次 D 新增 stop_loss_method):
        {
            "support": float|None,           # 支撑下沿
            "resistance": float|None,        # 压力上沿
            "stop_loss": float|None,         # 止损 (max 规则或 None)
            "stop_loss_method": str|None,    # 批次 D 新增: 计算来源
                                            #   "trading_plan"  | 用了 V2 计划止损
                                            #   "support_buffer"| 用了 支撑*0.97 (防倒挂)
                                            #   "max_of_both"   | 两源相等 (罕见)
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

    # ---- 过滤 + 取操作位 (批次 E 痛 1 修法, 2026-09-14) ----
    # 操作位 = ma60 / chip_peak / boll 三类近期候选中"距现价 5-25% 范围"的最近者
    #   痛点: 旧版用 recent_low (60 日最低) 距现价 28% 形同"画饼"
    #   修法: 近期位只在均线/筹码/布林中挑, 远端极值移到参考位
    #   边界: 5-25% 范围无候选 → 兜底用 ±5% 旧行为 (保持向后兼容)
    OP_BAND = (5.0, 25.0)  # 操作位距现价允许范围 (%)
    op_sup_candidates = ["ma60", "chip_peak", "boll_lower"]  # 支撑: 均线/筹码/布林下
    op_res_candidates = ["ma250_or_ma120", "boll_upper", "recent_high"]  # 压力: 长期均线/布林上/60日高

    def _pick_operational(cand_dict, op_keys, price, want):
        """want="min" → 支撑 (操作位选距现价最近, 5-25% 范围)
        want="max" → 压力 (操作位选距现价最近, 5-25% 范围)
        兜底: 5-25% 无候选 → ±5% 范围内距现价最近
        兜底2: 全部无候选 → None
        边界: v == price (d_pct == 0) 允许入选 (d_pct ≤ 0 / ≥ 0 包含 0)
        """
        if price is None or not cand_dict:
            return None, None
        # 严格 5-25% 范围
        band_strict = {}
        for k in op_keys:
            v = cand_dict.get(k)
            if v is None:
                continue
            d_pct = (v - price) / price * 100
            if want == "min" and d_pct <= 0 and OP_BAND[0] <= abs(d_pct) <= OP_BAND[1]:
                band_strict[k] = (v, abs(d_pct))
            elif want == "max" and d_pct >= 0 and OP_BAND[0] <= abs(d_pct) <= OP_BAND[1]:
                band_strict[k] = (v, abs(d_pct))
        if band_strict:
            # 距现价最近 (|d_pct| 最小)
            k_pick = min(band_strict.items(), key=lambda kv: kv[1][1])[0]
            return band_strict[k_pick][0], k_pick
        # 兜底: ±5% 范围
        band_loose = {}
        for k in op_keys:
            v = cand_dict.get(k)
            if v is None:
                continue
            d_pct = (v - price) / price * 100
            if want == "min" and d_pct <= 0 and abs(d_pct) <= 5.0:
                band_loose[k] = (v, abs(d_pct))
            elif want == "max" and d_pct >= 0 and abs(d_pct) <= 5.0:
                band_loose[k] = (v, abs(d_pct))
        if band_loose:
            k_pick = min(band_loose.items(), key=lambda kv: kv[1][1])[0]
            return band_loose[k_pick][0], k_pick
        return None, None

    support, support_op_key = _pick_operational(sup_valid, op_sup_candidates, price, "min")
    resistance, resistance_op_key = _pick_operational(res_valid, op_res_candidates, price, "max")

    # ---- 参考位 (批次 E 痛 1 修法): 60 日极值 + 布林, 远端不筛选 ----
    # 60 日最低/最高永远取极端值, 不管距现价多远, 报告层明确标"参考位"vs"操作位"
    ref_support = series_recent_low(series, 60) if series else None  # recent_low 平铺
    ref_resistance = series_recent_high(series, 60) if series else None
    # 布林上下轨
    boll = series_boll(series, 20, 2) if series else None
    boll_lower_val = boll[0] if boll else None
    boll_upper_val = boll[1] if boll else None

    # ---- stop_loss: 批次 D 债 2 修法 (2026-09-14) ----
    # 旧版: 严格复用 trading_plan.stop_loss (V2 同源, 不重算)
    # 新版: stop_loss = max(支撑 * 0.97, trading_plan.stop_loss) — 取高者, 防倒挂
    # 边界: plan.stop_loss 缺失 → None (不编造); support 缺失 → 用 plan.stop_loss
    plan_stop_loss = None
    if isinstance(trading_plan, dict):
        plan_stop_loss = to_float(trading_plan.get("stop_loss"))

    stop_loss: Optional[float] = None
    stop_loss_method: Optional[str] = None
    if plan_stop_loss is not None:
        if support is None:
            # 无技术支撑, 兜底用 V2
            stop_loss = plan_stop_loss
            stop_loss_method = "trading_plan"
        else:
            support_buffer = support * 0.97  # 不提前 round, 末尾统一
            if plan_stop_loss >= support_buffer:
                # V2 止损 >= 支撑下方 3% 缓冲: V2 是合理的大止损 (杰瑞类)
                stop_loss = plan_stop_loss
                stop_loss_method = "trading_plan"
            elif support_buffer > plan_stop_loss:
                # V2 止损过紧 (< 支撑 × 0.97): 强切到 支撑 × 0.97 (防倒挂)
                stop_loss = support_buffer
                stop_loss_method = "support_buffer"
            else:
                # 罕见: 两者相等
                stop_loss = support_buffer
                stop_loss_method = "max_of_both"
    # plan_stop_loss is None → stop_loss / stop_loss_method 保持 None (不编造)

    return {
        "support": round(support, 2) if support is not None else None,
        "resistance": round(resistance, 2) if resistance is not None else None,
        "stop_loss": round(stop_loss, 2) if stop_loss is not None else None,
        "stop_loss_method": stop_loss_method,
        "support_candidates": {k: round(v, 2) for k, v in sup_valid.items()},
        "resistance_candidates": {k: round(v, 2) for k, v in res_valid.items()},
        "method": (f"支撑下沿(操作位, ma60/chip_peak/boll 三候选距现价 5-25% 范围最近者, 批次 E 痛 1 修法, 2026-09-14); "
                   f"压力上沿(操作位, ma250_or_ma120/boll_upper 二候选距现价 5-25% 范围最近者); "
                   f"参考位 = 60 日最低/最高 + 布林, 远端不筛选; "
                   f"止损 = max(支撑×0.97, V2 计划止损) [批次 D 债 2 修法, 2026-09-14]; "
                   f"N={n} 根K线"),
        # 批次 E 痛 1 新增字段 (远/近期位分层)
        "support_op_key": support_op_key,           # 操作支撑的来源候选 (e.g. "boll_lower")
        "resistance_op_key": resistance_op_key,      # 操作压力的来源候选
        "support_recent_pct": (                        # 操作支撑距现价百分比 (负数, 因为低于现价)
            round((support - price) / price * 100, 2) if (support is not None and price) else None
        ),
        "resistance_recent_pct": (                     # 操作压力距现价百分比 (正数)
            round((resistance - price) / price * 100, 2) if (resistance is not None and price) else None
        ),
        "support_extreme": round(ref_support, 2) if ref_support is not None else None,
        "resistance_extreme": round(ref_resistance, 2) if ref_resistance is not None else None,
        "support_extreme_label": "60日最低" if ref_support is not None else None,
        "resistance_extreme_label": "60日最高" if ref_resistance is not None else None,
        "boll_lower": round(boll_lower_val, 2) if boll_lower_val is not None else None,
        "boll_upper": round(boll_upper_val, 2) if boll_upper_val is not None else None,
        "operational_band_pct": OP_BAND,             # (5.0, 25.0)
    }
