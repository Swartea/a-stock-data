#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股多因子量化分析器 V3 — 报告主分析器 (V3.7.2 era 报告层升级)
=============================================================

定位: 复用 V2 全部数据函数 (quant_analyzer_v2) + 接入 6 块新内容 (docs/05-报告升级方案.md)
  + 4 处排版改造 + 链路运行记录 (run_log)。

V2 同源复用 (只读引用, 不修改 v2):
  fetch_tencent_quote / fetch_full_valuation / fetch_eastmoney_concept_blocks
  fetch_fund_flow_minute / fetch_valuation_history / fetch_lockup_expiry
  fetch_dragon_tiger / fetch_macro_snapshot / fetch_chip_distribution
  fetch_sw_stability / fetch_margin_trading
  compute_quant_score_v2 / get_advice_v2
  _interpret_pe / _interpret_pctile / _interpret_chips
  _make_trading_plan / _make_signal_list

新数据块 fetcher (并行开发, import 容错; 缺文件 → 报告标"数据源暂缺", run_log 记 error):
  fetch_announcements  (公告)   / fetch_finance_summary (财务摘要)
  fetch_research_reports(研报)  / fetch_news_em (新闻舆情)

硬约束 (债4):
  - 三价位 (支撑/压力/止损) 必须来自 V2 同源实时 K 线模型
    (腾讯实时行情价 + baostock 前复权筹码 K 线)，严禁用 scripts/screener_pool.csv 陈旧价兜底。
  - K 线当日证据: last_bar 与最新交易日比对, 非当日(且非周末节假日)记 WARN 进 run_log。

输出: {REPORTS_ROOT}/{code}_{name}/{YYYY-MM-DD}/{code}-{name}-{HHMM}.md + run_log.json

用法: python quant_analyzer_v3.py 603319 美湖股份
运行: bash scripts/run_in_venv.sh analysis/quant_analyzer_v3.py 603319 美湖股份

result dict 契约 (HTML 组也按此读):
  code/name/quote/valuation/blocks/fund/valuation_hist/lockup/dragon/macro/
  chip_data/sw_data/announcements/finance/news/research/margin/peers(附加)/
  score/advice/emoji/detail/trading_plan/signals/run_log/report_date
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, date, time as dtime
from typing import Optional

# ---------------------------------------------------------------
# 路径: 本文件所在目录 → 可 import v2 / 4 个新 fetcher
# ---------------------------------------------------------------
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

import quant_analyzer_v2 as v2  # noqa: E402
from sections import enabled_sections  # noqa: E402  # Phase 1: Section Registry (irm §10.1)

# ---------------------------------------------------------------
# 4 个新 fetcher — 容错 import (并行开发中, 未落盘不许崩整脚本)
# ---------------------------------------------------------------
_NEW_IMPORTS = {  # label -> {"ok": bool, "err": str, "fn": callable}
    "公告":    {"ok": False, "err": "", "fn": None},
    "财务":    {"ok": False, "err": "", "fn": None},
    "研报":    {"ok": False, "err": "", "fn": None},
    "新闻":    {"ok": False, "err": "", "fn": None},
}
try:
    from fetch_announcements import fetch_announcements as _fn_ann
    _NEW_IMPORTS["公告"]["ok"], _NEW_IMPORTS["公告"]["fn"] = True, _fn_ann
except Exception as e:  # noqa: BLE001
    _NEW_IMPORTS["公告"]["err"] = f"数据源暂缺: {e}"
try:
    from fetch_finance_summary import fetch_finance_summary as _fn_fin
    _NEW_IMPORTS["财务"]["ok"], _NEW_IMPORTS["财务"]["fn"] = True, _fn_fin
except Exception as e:  # noqa: BLE001
    _NEW_IMPORTS["财务"]["err"] = f"数据源暂缺: {e}"
try:
    from fetch_research_reports import fetch_research_reports as _fn_res
    _NEW_IMPORTS["研报"]["ok"], _NEW_IMPORTS["研报"]["fn"] = True, _fn_res
except Exception as e:  # noqa: BLE001
    _NEW_IMPORTS["研报"]["err"] = f"数据源暂缺: {e}"
try:
    from fetch_news_em import fetch_news_em as _fn_news
    _NEW_IMPORTS["新闻"]["ok"], _NEW_IMPORTS["新闻"]["fn"] = True, _fn_news
except Exception as e:  # noqa: BLE001
    _NEW_IMPORTS["新闻"]["err"] = f"数据源暂缺: {e}"

REPORTS_ROOT = os.path.normpath(os.path.join(_ANALYSIS_DIR, "..", "reports"))

# ============================================================
# 数据源标签 — 全链路 11+4 类 (run_log.sources 全列)
# ============================================================
# V2 内嵌 10 类 + V3 追加: 融资融券 + 研报/公告/财务/新闻
_SRC_DESC = {
    "行情":       "腾讯实时行情 qt.gtimg.cn",
    "估值一致预期": "同花顺一致预期 basic.10jqka.com.cn",
    "概念板块":     "东财概念板块 slist",
    "当日资金流":   "东财当日分钟资金流 fflow",
    "估值历史分位": "baostock 估值历史(近3年)",
    "解禁日历":     "东财数据中心 RPT_LIFT_STAGE",
    "龙虎榜":       "东财数据中心 RPT_DAILYBILLBOARD_DETAILSNEW",
    "宏观底色":     "同花顺北向 + 东财行业 + 同花顺强势股",
    "筹码K线":      "baostock 前复权日K(筹码计算用)",
    "申万分类":     "申万行业分类表 swsresearch",
    "融资融券":     "东财数据中心 RPTA_WEB_RZRQ_GGMX",
    "研报观点":     "东财研报 reportapi / 同花顺降级",
    "公告":         "东财公告 / 巨潮 cninfo",
    "财务摘要":     "东财数据中心 RPT_F10_FINANCE_MAINFINADATA",
    "新闻舆情":     "东财个股新闻",
}
_V2_FN_TO_SRC = {
    "fetch_tencent_quote": "行情",
    "fetch_full_valuation": "估值一致预期",
    "fetch_eastmoney_concept_blocks": "概念板块",
    "fetch_fund_flow_minute": "当日资金流",
    "fetch_valuation_history": "估值历史分位",
    "fetch_lockup_expiry": "解禁日历",
    "fetch_dragon_tiger": "龙虎榜",
    "fetch_macro_snapshot": "宏观底色",
    "fetch_chip_distribution": "筹码K线",
    "fetch_sw_stability": "申万分类",
}
# v2 函数名 → 结果字段 / 校验器 (dict, 键在 result 里)
_FIELD_OF = {
    "行情": "quote", "估值一致预期": "valuation", "概念板块": "blocks",
    "当日资金流": "fund", "估值历史分位": "valuation_hist", "解禁日历": "lockup",
    "龙虎榜": "dragon", "宏观底色": "macro", "筹码K线": "chip_data",
    "申万分类": "sw_data",
}
_TOP_FIELD_OF = {fn: _FIELD_OF[lab] for fn, lab in _V2_FN_TO_SRC.items()}

_src_meta: dict = {}   # label -> {"ms":int,"at":"HH:MM:SS","status":str,"detail":str}


# ============================================================
# 多空状态机 — 债 1 修法 (Task 5.1)
# 阈值与 analysis/references/report-design-principles.md:88-94 仓位建议 5 档对齐,
# 但 state 拆分更细：≥65 多 / 55-65 轻多 / 45-55 中性 / 35-45 轻空 / <35 空。
# 5 状态对应 5 套独立"结论+操作+风险"三段模板, 杜绝 V3 原报告"看空 43 分仍写分两批进场"矛盾。
# ============================================================
def _score_to_state(score: float) -> str:
    """综合评分 → 多空状态映射（5 状态）。阈值与 plan 文档 Task 5.1 Step 2 一致。"""
    try:
        sc = float(score)
    except (TypeError, ValueError):
        sc = 0.0
    if sc >= 65:
        return "bullish"      # 看多（≥65）
    if sc >= 55:
        return "mild_bull"    # 轻多（55-65）
    if sc >= 45:
        return "neutral"      # 中性/震荡（45-55）
    if sc >= 35:
        return "mild_bear"    # 轻空（35-45）
    return "bearish"          # 看空（<35）


# 5 状态独立模板：每条都包含"结论+操作+风险"三段（用 `｜` 分段，Markdown 表格不破）。
# 占位符 {score}/{stop_loss}/{stop_loss_pct}/{entry_low}/{tp1} 由调用方 .format 注入。
OPERATION_TEMPLATES = {
    "bullish": (
        "【结论】综合评分 {score} ≥ 65，多头格局占优，看多确立 ｜ "
        "【操作】现价分两批进场、持有 3-6 个月 ｜ "
        "【风险】收盘跌破止损 {stop_loss}（-{stop_loss_pct}%）无条件离场，不补仓摊薄"
    ),
    "mild_bull": (
        "【结论】综合评分 {score} 处于 55-65 区间，结构偏多但需确认 ｜ "
        "【操作】轻仓试探 10-20%，等综合评分回升至 65+ 确认后加仓 ｜ "
        "【风险】若跌破止损 {stop_loss} 立即降仓至 10% 以下，不抢涨"
    ),
    "neutral": (
        "【结论】综合评分 {score} 处于 45-55 区间，多空平衡、震荡格局 ｜ "
        "【操作】区间操作 — 上沿 {tp1} 减仓、下沿 {entry_low} 低吸、严格止损 {stop_loss} ｜ "
        "【风险】单边突破区间则按突破方向顺势操作，不预判方向"
    ),
    "mild_bear": (
        "【结论】综合评分 {score} 处于 35-45 区间，空头压力偏大 ｜ "
        "【操作】减仓至轻仓（≤10%），反弹遇压力位 {tp1} 不再加仓 ｜ "
        "【风险】若继续跌破止损 {stop_loss} 直接清仓，不抄底"
    ),
    "bearish": (
        "【结论】综合评分 {score} < 35，空头主导、看空确立 ｜ "
        "【操作】清仓回避 — 等待综合评分回升至 45+ 再评估进场 ｜ "
        "【风险】不抢反弹、不抄底；套牢者按计划止损，不补仓摊薄"
    ),
}

# 状态 → 中文/图标 给 MD/HTML/DOCX 渲染层复用（避免各自再写一遍 if-elif-else）
_STATE_DISPLAY = {
    "bullish":   ("看多", "🟢"),
    "mild_bull": ("轻多", "🟢"),
    "neutral":   ("震荡", "🟡"),
    "mild_bear": ("轻空", "🔴"),
    "bearish":   ("看空", "🔴"),
}


# ============================================================
# 三价位表 (债 2 修法, Task 5.2) — 4 候选取最近者
# ============================================================
# 字段名映射 (plan 假设 → V3 实际):
#   - plan 假设 `chip_data.cost_concentration.peak_price` 实际是 `chip_data["peak_price"]` (v2 chip_distribution 平铺, line 572)
#   - plan 假设 `technical.{ma60,recent_low,recent_high,boll_lower,boll_upper,ma250}` 在 V3 不存在
#     → 自己从 `chip_data["kline"]` (~250 日 baostock 前复权 K 线, v2 line 618) 现算
def _klines_to_series(chip_data):
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


def _series_ma(series, n):
    """简单移动平均（最后 n 日 close 均值）；len < n 或 n <= 0 → None"""
    if not series or n <= 0 or len(series) < n:
        return None
    closes = [s["close"] for s in series[-n:]]
    return sum(closes) / len(closes)


def _series_boll(series, n=20, k=2):
    """布林带 (MA_n ± k·σ)。返回 (lower, upper) 二元组；不足 n 日 → None"""
    if not series or len(series) < n:
        return None
    closes = [s["close"] for s in series[-n:]]
    mean = sum(closes) / n
    var = sum((c - mean) ** 2 for c in closes) / n
    std = var ** 0.5
    return (round(mean - k * std, 2), round(mean + k * std, 2))


def _series_recent_high(series, n=60):
    if not series:
        return None
    window = series[-n:] if len(series) >= n else series
    return max(s["high"] for s in window)


def _series_recent_low(series, n=60):
    if not series:
        return None
    window = series[-n:] if len(series) >= n else series
    return min(s["low"] for s in window)


def _to_float(v):
    """健壮 float 转换；None / NaN / 不可解析 → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def compute_three_levels(quote, chip_data, trading_plan=None):
    """债 2 修法 (Task 5.2) — 三价位表，4 支撑候选 / 3 压力候选 取最近者。

    支撑候选（4 选 1，取最低且 ≤ 1.05×现价）:
        1. MA60 (K 线 series 自算)
        2. 前低（60 日最低，K 线 low 自算）
        3. 筹码峰 (chip_data['peak_price'], v2 line 572 平铺)
        4. 布林下轨 (MA20 - 2σ，K 线 series 自算)

    压力候选（3 选 1，取最高且 ≥ 0.95×现价）:
        1. 年线 MA250 (K 线 series 自算)，N<250 兜底用 MA120
        2. 前高（60 日最高，K 线 high 自算）
        3. 布林上轨 (MA20 + 2σ，K 线 series 自算)

    止损：**复用** trading_plan.stop_loss（V2 同源，**不重算**），
    杜绝覆盖 Task 5.1 已锁定的 trading_plan 字段。

    返回 dict:
        {
            "support": float|None,
            "resistance": float|None,
            "stop_loss": float|None,
            "support_candidates": {ma60, recent_low, chip_peak, boll_lower},
            "resistance_candidates": {ma250_or_ma120, recent_high, boll_upper},
            "method": "...",
        }
    """
    price = _to_float((quote or {}).get("price"))
    series = _klines_to_series(chip_data)
    n = len(series) if series else 0

    # ---- 4 支撑候选 ----
    sup_raw = {
        "ma60": _series_ma(series, 60),
        "recent_low": _series_recent_low(series, 60),
        "chip_peak": _to_float((chip_data or {}).get("peak_price")) if chip_data else None,
        "boll_lower": (_series_boll(series, 20, 2) or (None, None))[0],
    }
    sup_valid = {k: v for k, v in sup_raw.items() if v is not None}

    # ---- 3 压力候选 ----
    long_ma = _series_ma(series, 250) or _series_ma(series, 120)
    boll_bands = _series_boll(series, 20, 2)
    res_raw = {
        "ma250_or_ma120": long_ma,
        "recent_high": _series_recent_high(series, 60),
        "boll_upper": boll_bands[1] if boll_bands else None,
    }
    res_valid = {k: v for k, v in res_raw.items() if v is not None}

    # ---- 过滤 ±5% + 取最近者 ----
    support = None
    if price is not None and sup_valid:
        eligible = {k: v for k, v in sup_valid.items() if v <= price * 1.05}
        if eligible:
            support = min(eligible.values())  # 最低即最近（最贴近现价下方）
    resistance = None
    if price is not None and res_valid:
        eligible = {k: v for k, v in res_valid.items() if v >= price * 0.95}
        if eligible:
            resistance = max(eligible.values())  # 最高即最近（最贴近现价上方）

    # ---- stop_loss 复用 trading_plan.stop_loss（不重算）----
    stop_loss = None
    if isinstance(trading_plan, dict):
        stop_loss = _to_float(trading_plan.get("stop_loss"))

    return {
        "support": round(support, 2) if support is not None else None,
        "resistance": round(resistance, 2) if resistance is not None else None,
        "stop_loss": round(stop_loss, 2) if stop_loss is not None else None,
        "support_candidates": {k: round(v, 2) for k, v in sup_valid.items()},
        "resistance_candidates": {k: round(v, 2) for k, v in res_valid.items()},
        "method": f"4 候选取最近者（支撑 ≤ 1.05×现价；压力 ≥ 0.95×现价；N={n}）",
    }


# ============================================================
# 北向资金口径分类 — 债 3 修法 (Task 5.3)
# 背景: docs/04-模板质量债.md 债 3 — 美湖股份(603319) 报告 "北向净流入 370.5 亿"
#       与个股流通市值 102 亿 严重不符; 怀疑模板把"全市场北向"误当个股口径填入。
# 实测 (scripts/verify_north_scope.py, 600693 2026-09-08):
#   macro.hsgt = {"latest_hgt_yi": -9.28, "latest_sgt_yi": 379.75,
#                  "total_yi": 370.47, "data_points": 262}
#   → 同花顺 dayChart 接口确实返回"全市场"沪股通+深股通, 不是个股北向持股变化。
#   → 370.5 亿 = 沪 -9.28 + 深 379.75, **就是全市场值**, 数据本身正确;
#     错的只是模板未显式标 "scope", 看报告者容易误读为"个股北向"。
# 修法:
#   1) 加 _classify_north_scope() 推断 scope (market / stock / mixed / unknown)
#   2) result["macro"]["north_scope"] + ["north_label"] 注入 4 元组
#   3) 3 渲染器 (MD/HTML/DOCX) 读 north_label 替代 hardcode
# 字段名映射 (实测 vs plan 假设):
#   实测 (V3 实际返回):  total_yi / latest_hgt_yi / latest_sgt_yi
#   plan 假设 (错误):    total / sh / sz — **已校准为本节实际 keys**
#   个股北向特征字段 (前向兼容, 暂未在 V3 启用):
#     stock_change_pct / stock_holding_ratio / holdings_change / north_holding_pct
# ============================================================
def _classify_north_scope(north_data) -> tuple:
    """根据北向接口返回字段推断 scope, 返回 (scope, label)。

    Args:
        north_data: dict — V2 同花顺 dayChart 返回值
                    实际 keys: latest_hgt_yi / latest_sgt_yi / total_yi / data_points
                    个股北向 (前向兼容): stock_change_pct / stock_holding_ratio 等

    Returns:
        (scope, label) — scope ∈ {"market", "stock", "mixed", "unknown"}
                          label — 渲染层直接用的中文描述 (含 scope 关键词)
    """
    if not north_data or not isinstance(north_data, dict):
        return ("unknown", "北向数据缺失")

    # 全市场北向特征字段 (V3 实际: total_yi + latest_hgt_yi/latest_sgt_yi)
    has_market = any(k in north_data for k in (
        "total_yi", "total", "north_net", "sh_net", "sz_net",
        "latest_hgt_yi", "latest_sgt_yi", "hgt", "sgt"
    ))
    # 个股北向持股变化特征字段 (前向兼容, V3 当前未启用)
    has_stock = any(k in north_data for k in (
        "stock_change_pct", "stock_holding_ratio",
        "holdings_change", "north_holding_pct", "holding_ratio_chg"
    ))

    if has_market and not has_stock:
        # 全市场 (V3 现状): 沪 + 深 净买入 (亿)
        hgt = (north_data.get("latest_hgt_yi")
               or north_data.get("hgt")
               or north_data.get("sh_net") or 0)
        sgt = (north_data.get("latest_sgt_yi")
               or north_data.get("sgt")
               or north_data.get("sz_net") or 0)
        total = (north_data.get("total_yi")
                 or north_data.get("total")
                 or north_data.get("north_net")
                 or (hgt + sgt))
        # type-safe: 兜底非数字 → 0
        try:
            hgt, sgt, total = float(hgt), float(sgt), float(total)
        except (TypeError, ValueError):
            hgt, sgt, total = 0.0, 0.0, 0.0
        return ("market",
                f"北向资金(全市场口径): 沪股通 {hgt:+.1f} 亿 / "
                f"深股通 {sgt:+.1f} 亿 ｜ 合计 {total:+.1f} 亿")

    if has_stock and not has_market:
        # 个股北向持股变化 (前向兼容, 暂未启用)
        pct = (north_data.get("stock_change_pct")
               or north_data.get("holdings_change") or 0)
        ratio = (north_data.get("stock_holding_ratio")
                 or north_data.get("north_holding_pct") or 0)
        try:
            pct, ratio = float(pct), float(ratio)
        except (TypeError, ValueError):
            pct, ratio = 0.0, 0.0
        return ("stock",
                f"北向资金(个股口径): 持股变化 {pct:+.2f}% ｜ 持股比例 {ratio:.2f}%")

    if has_market and has_stock:
        # 混合: 同时返回全市场 + 个股
        total = float(north_data.get("total_yi", 0) or 0)
        pct = float(north_data.get("stock_change_pct", 0) or 0)
        return ("mixed",
                f"北向资金(混合): 全市场 {total:+.1f} 亿 + 个股持股 {pct:+.2f}%")

    return ("unknown", "北向数据口径未明")


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _patch_v2_timers():
    """包装 v2 的 10 个取数函数: 记录每次调用的耗时与时点 (不改变行为)。"""
    saved = {}
    def _make_wrapper(fn_name, orig):
        def wrapper(*a, **k):
            t0 = time.time()
            try:
                return orig(*a, **k)
            finally:
                lab = _V2_FN_TO_SRC.get(fn_name, fn_name)
                _src_meta.setdefault(lab, {})["ms"] = round((time.time() - t0) * 1000)
                _src_meta[lab]["at"] = _fmt_time(time.time())
        return wrapper
    for fn_name, lab in _V2_FN_TO_SRC.items():
        if not hasattr(v2, fn_name):
            continue
        saved[fn_name] = getattr(v2, fn_name)
        setattr(v2, fn_name, _make_wrapper(fn_name, saved[fn_name]))
        _src_meta[lab] = {"ms": None, "at": None, "status": None, "detail": None}
    return saved


def _restore_v2(saved: dict):
    for fn_name, orig in saved.items():
        setattr(v2, fn_name, orig)


# ============================================================
# 通用工具
# ============================================================
def _clean(s: str, n: int = 60) -> str:
    """去竖线/换行, 防 markdown 表格破坏; 截断。"""
    if s is None:
        return "—"
    s = str(s).replace("|", "／").replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _fnum(x, nd: int = 2) -> str:
    """数值 → 显示串; None/NaN/inf → '—'。"""
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x or x in (float("inf"), float("-inf")):
        return "—"
    return f"{x:,.{nd}f}"


def _fpct(x, nd: int = 1, sign: bool = True) -> str:
    """百分比显示; None → '—'"""
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return f"{x:+.{nd}f}%" if sign else f"{x:.{nd}f}%"


def _short_iso(iso: Optional[str]) -> str:
    """ISO8601 → 'YYYY-MM-DD HH:MM:SS'"""
    if not iso:
        return "—"
    return str(iso)[:19].replace("T", " ")


def _latest_trading_day() -> date:
    """最新交易日估计: 周末→上周五; 工作日 9:30 前→上一工作日 (节假日不在库, 仅提示)。"""
    now = datetime.now()
    d = now.date()
    if now.weekday() >= 5:                     # 周六/周日 → 上周五
        d = d - timedelta(days=now.weekday() - 4)
    elif now.time() < dtime(9, 30):            # 开盘前 → 上一工作日
        d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d = d - timedelta(days=1)
    return d


def _kline_freshness(chip_data: dict) -> dict:
    """K线最后 bar vs 最新交易日 → ok / warn / na。"""
    exp = _latest_trading_day().isoformat()
    last_bar = None
    note = ""
    if chip_data and isinstance(chip_data, dict) and "error" not in chip_data:
        klines = chip_data.get("kline") or []
        if klines:
            last_bar = str(klines[-1].get("date", ""))[:10]
        if not last_bar:
            last_bar = str(chip_data.get("window_end", ""))[:10] or None
    if not last_bar:
        err = (chip_data or {}).get("error", "无K线数据")
        return {"last_bar": None, "expected": exp, "level": "na",
                "text": f"无K线(筹码模块失败: {err}), 无法校验K线时点"}
    if last_bar >= exp:
        return {"last_bar": last_bar, "expected": exp, "level": "ok",
                "text": f"K线最后交易日 {last_bar} 已到最新交易日, 新鲜"}
    return {"last_bar": last_bar, "expected": exp, "level": "warn",
            "text": f"K线停在 {last_bar}, 最新交易日 {exp} — 若为法定节假日/周末属正常, 否则需关注数据延迟"}


def _retry_call(label: str, fn, *args, tries: int = 3, timeout: int = 60, **kw) -> tuple:
    """调用带重试(时间盒 tries 次), 返回 (值, 实际尝试次数, 状态串)。"""
    last_exc = None
    for i in range(1, tries + 1):
        t0 = time.time()
        try:
            val = fn(*args, **kw)
            _src_meta.setdefault(label, {})["ms"] = round((time.time() - t0) * 1000)
            return val, i, None
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(1.0)
    return None, tries, str(last_exc)


# ============================================================
# V3 附加端点 (同一数据源家族的接线复用, 不新建数据源)
# ============================================================
def _fetch_fund_flow_daily(code: str, days: int = 5) -> dict:
    """近 N 日主力资金 (东财 push2 fflow kline, klt=101 日线 — 与 v2 分钟线同源)。"""
    code = v2.normalize_code(code)
    secid = f"{v2.em_market_code(code)}.{code}"
    params = {"secid": secid, "klt": 101, "lmt": days,
              "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": v2.UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        d = v2.em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                      params=params, headers=headers, timeout=15).json()
    except Exception as e:
        return {"error": str(e), "rows": []}
    rows = []
    for line in (d.get("data") or {}).get("klines") or []:
        p = line.split(",")
        if len(p) >= 7:
            rows.append({"date": str(p[0])[:10],
                         "main_net_yi": round(float(p[1]) / 1e8, 3),
                         "large_super_yi": round((float(p[4]) + float(p[5])) / 1e8, 3)})
    if not rows:
        return {"error": "近5日主力资金无数据", "rows": []}
    return {"rows": rows, "total_main_yi": round(sum(r["main_net_yi"] for r in rows), 3),
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "as_of": datetime.now().strftime("%Y-%m-%d")}


def _fetch_margin_history(code: str, n: int = 8) -> dict:
    """两融余额近 n 期 (东财 datacenter — 与 v2.fetch_margin_trading 同源同接口)。"""
    from urllib.parse import quote
    params = {
        "reportName": "RPTA_WEB_RZRQ_GGMX", "columns": "ALL",
        "filter": f'(SCODE="{code}")', "pageNumber": "1", "pageSize": str(n),
        "sortColumns": "DATE", "sortTypes": "-1",
    }
    try:
        d = v2.em_get("https://datacenter-web.eastmoney.com/api/data/v1/get",
                      params=params, headers={"User-Agent": v2.UA,
                          "Referer": "https://data.eastmoney.com/"}, timeout=15).json()
        rows = (d.get("result") or {}).get("data") or []
        out = []
        for r in rows[:n]:
            out.append({
                "date": str(r.get("DATE", ""))[:10],
                "rzye_yi": round(float(r.get("RZYE", 0) or 0) / 1e8, 3),
                "rqye_yi": round(float(r.get("RQYE", 0) or 0) / 1e8, 3),
                "rzmr_yi": round(float(r.get("RZMRE", 0) or 0) / 1e8, 3),
                "rzch_yi": round(float(r.get("RZCHE", 0) or 0) / 1e8, 3),
            })
        if not out:
            return {"error": "两融历史无数据", "rows": []}
        # 方向: 融资余额较前一期增减
        for i, row in enumerate(out):
            if i + 1 < len(out):
                row["rzye_chg_yi"] = round(row["rzye_yi"] - out[i + 1]["rzye_yi"], 3)
            else:
                row["rzye_chg_yi"] = None
        return {"rows": out, "as_of": datetime.now().strftime("%Y-%m-%d")}
    except Exception as e:
        return {"error": str(e), "rows": []}


def _num_or_none(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _fetch_concept_peers(code: str, blocks: list, max_concepts: int = 6) -> dict:
    """同业对比(近似口径): 取本票所属东财概念板块的市值前100, 标出本票市值排名。
    数据源: 东财 push2 clist (与 v2 行业排名同端点家族)。"""
    code = v2.normalize_code(code)
    if not isinstance(blocks, list):
        return {"error": "无概念板块数据(概念归属缺失), 无法取成分股做同业对比"}
    concepts = [b for b in blocks if isinstance(b, dict) and b.get("code") and "error" not in b]
    if not concepts:
        return {"error": "概念板块列表为空(东财 slist 返回 0 条, 可能风控), 无法做同业对比"}
    tried = []
    for b in concepts[:max_concepts]:
        bcode = str(b.get("code", ""))
        params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                  "fid": "f20", "fs": f"b:{bcode}",
                  "fields": "f12,f14,f2,f3,f9,f23,f20,f21"}
        try:
            d = v2.em_get("https://push2.eastmoney.com/api/qt/clist/get",
                          params=params, headers={"User-Agent": v2.UA,
                              "Referer": "https://quote.eastmoney.com/"}, timeout=15).json()
            data = d.get("data") or {}
            diff = data.get("diff") or []
            total = int(data.get("total", 0) or 0)
            rows = []
            for it in diff:
                rows.append({
                    "code": str(it.get("f12", "")), "name": str(it.get("f14", "")),
                    "price": _num_or_none(it.get("f2")), "chg": _num_or_none(it.get("f3")),
                    "pe": _num_or_none(it.get("f9")), "pb": _num_or_none(it.get("f23")),
                    "total_mcap_yi": _num_or_none(it.get("f20")),
                    "float_mcap_yi": _num_or_none(it.get("f21")),
                })
            rank = next((i + 1 for i, r in enumerate(rows) if r["code"] == code), None)
            tried.append({"concept": b.get("name"), "code": bcode, "total": total,
                          "fetched": len(rows), "rank": rank})
            if rank is not None:
                return {"block_used": b.get("name"), "block_code": bcode,
                        "total": total, "rank": rank,
                        "rows": rows, "as_of": datetime.now().strftime("%Y-%m-%d")}
        except Exception as e:  # noqa: BLE001
            tried.append({"concept": b.get("name"), "code": bcode, "error": str(e)})
    # 全部未命中/失败 → 用第一概念的前列作参考 + 说明
    fallback = {"error": "本票未进入所查概念的市值前100或接口失败",
                "tried": tried, "rows": None}
    return fallback


# ============================================================
# V3 单票主流程
# ============================================================
def analyze_single_v3(code: str, name: str = "") -> dict:
    """V3 单票完整分析 → result_v3 (契约见文件头) + 生成 MD / run_log.json。

    K线当日证据与三价位硬约束: 全部取 V2 同源实时结果 (腾讯行情 + baostock 前复权K线),
    不读任何 pool CSV。"""
    started = datetime.now()
    run_log = {
        "started_at": started.astimezone().isoformat(timespec="seconds"),
        "finished_at": None, "total_sec": None,
        "sources": {}, "source_meta": {},
        "guard": {"status": "N/A 单票流程不用池CSV", "kline_freshness": None},
        "fallback_chain": [],
        "fatal": None,
    }

    # ---- 1. V2 全链路 (10 数据类, 计时包装) ----
    saved = _patch_v2_timers()
    base_result = {}
    fatal = None
    try:
        for attempt in range(1, 4):                      # 网络重试时间盒 3 次
            _src_meta.clear()
            base_result = v2.analyze_single(code, name, output_md=False)
            if "error" not in base_result:
                break
            fatal = base_result["error"]
            print(f"[v3] 第 {attempt} 次尝试失败: {fatal}, 3 秒后重试…")
            time.sleep(3)
        if "error" in base_result:
            run_log["fatal"] = f"V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底): {fatal}"
            run_log["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            run_log["total_sec"] = round(time.time() - started.timestamp(), 1)
            _dump_run_log(code, name, run_log)
            print(f"\n[✗] 分析中止: {run_log['fatal']}")
            return {"error": run_log["fatal"], "run_log": run_log}
    finally:
        _restore_v2(saved)

    # ---- 1.5 申万SSL直连失败 → verify=False 重试 (本机CA环境问题, 不改 v2; 成功则重算评分) ----
    code6 = base_result["code"]
    sw0 = base_result.get("sw_data") or {}
    if isinstance(sw0, dict) and "error" in sw0:
        import requests as _req
        _orig_get = _req.get

        def _patched_get(url, *a, **k):
            if "swsresearch.com" in str(url):
                k["verify"] = False
            return _orig_get(url, *a, **k)

        t0 = time.time()
        sw_retry = {"error": "未执行"}
        try:
            _req.get = _patched_get
            sw_retry = v2.fetch_sw_stability(code6)
        except Exception as e:  # noqa: BLE001
            sw_retry = {"error": str(e)}
        finally:
            _req.get = _orig_get
        ms = round((time.time() - t0) * 1000)
        if isinstance(sw_retry, dict) and "error" not in sw_retry:
            base_result["sw_data"] = sw_retry
            run_log["fallback_chain"].append(
                f"申万分类: SSL直连失败({str(sw0.get('error',''))[:44]}) → verify=False 重试成功 "
                f"({ms}ms, 变更{sw_retry.get('n_changes','?')}次) [环境CA问题已绕过, 如实记录]")
            meta = _src_meta.setdefault("申万分类", {"at": _fmt_time(time.time())})
            meta["ms"] = ms
            meta["status"] = f"ok:swsresearch(verify=False重试), {ms}ms"
            score2 = v2.compute_quant_score_v2(
                base_result["quote"], base_result["valuation"],
                base_result.get("blocks", []), base_result.get("fund", {}),
                base_result.get("valuation_hist", {}), base_result.get("lockup", {}),
                base_result.get("dragon", {}), base_result.get("macro", {}),
                chip_data=base_result["chip_data"], sw_data=sw_retry)
            base_result["score"] = score2
            adv2, emj2, det2 = v2.get_advice_v2(score2["total"])
            base_result["advice"], base_result["emoji"], base_result["detail"] = adv2, emj2, det2
            print(f"[v3] 申万 SSL 绕过成功({sw_retry.get('n_changes')}次行业变更); "
                  f"评分重算: {score2['total']}分 {emj2}{adv2}")
        else:
            run_log["fallback_chain"].append(
                f"申万分类: SSL直连失败且 verify=False 重试亦失败: {str(sw_retry.get('error',''))[:80]}")

    q = base_result["quote"]; v = base_result["valuation"]
    score = base_result["score"]; score_total = score["total"]
    chip_data = base_result["chip_data"]

    # ---- 2. 三价位 (V2 同源模型: 腾讯实时价 + baostock 筹码K线, 债4) ----
    plan = v2._make_trading_plan(q, v, chip_data, score_total)
    # ---- 2.1 多空状态机注入 (债 1 修法, Task 5.1) ----
    # 在 trading_plan 上加 state + template_used 两个字段,
    # 渲染层 (MD/HTML) 直接读 plan["template_used"] 即可, 不再各自写硬编码模板。
    if plan:
        state = _score_to_state(score_total)
        plan["state"] = state
        try:
            plan["template_used"] = OPERATION_TEMPLATES[state].format(
                score=score_total,
                stop_loss=plan.get("stop_loss", "—"),
                stop_loss_pct=plan.get("stop_loss_pct", "—"),
                entry_low=plan.get("entry_low", "—"),
                tp1=plan.get("tp1", "—"),
            )
        except (KeyError, IndexError):
            plan["template_used"] = OPERATION_TEMPLATES[state]
    good_signals, bad_signals = v2._make_signal_list(score, score["factors"])

    # ---- 2.2 三价位表 (债 2 修法, Task 5.2): 4 支撑/3 压力候选 → 最近者 ----
    # 候选价从 chip_data['kline'] (~250 日 baostock 前复权 K 线) 自算 MA/布林/前高/前低;
    # 筹码峰直接读 chip_data['peak_price'] (v2 chip_distribution 平铺, line 572)。
    # stop_loss **复用** trading_plan.stop_loss（V2 同源，**不重算**），
    # 严守 Task 5.1 锁定的 trading_plan 字段（entry_low/entry_high/tp1/tp2/tp3/stop_loss/stop_loss_pct）。
    three_levels = compute_three_levels(q, chip_data, plan)

    # ---- 3. 逐类状态判定 (V2 的 10 类) ----
    results2 = base_result
    for lab, field in _FIELD_OF.items():
        data = results2.get(field)
        meta = _src_meta.get(lab, {})
        if isinstance(data, dict) and "error" in data:
            status = f"error:{str(data['error'])[:60]}, {meta.get('ms','?')}ms"
        elif lab == "行情" and not data:
            status = f"error:行情为空, {meta.get('ms','?')}ms"
        elif lab == "概念板块" and isinstance(data, list) and any(
                isinstance(x, dict) and "error" in x for x in data):
            status = f"error:接口异常, {meta.get('ms','?')}ms"
        elif lab == "概念板块" and isinstance(data, list) and not data:
            status = f"fallback:接口返回0条(可能风控), {meta.get('ms','?')}ms"
        elif lab == "当日资金流" and isinstance(data, dict) and not data.get("klines"):
            status = f"fallback:当日无成交或分钟数据, {meta.get('ms','?')}ms"
        elif lab == "宏观底色" and isinstance(data, dict) and not any(
                data.get(k) for k in ("hsgt", "industries", "hot_stocks")):
            status = f"error:北向/行业/强势股子源全空, {meta.get('ms','?')}ms"
        else:
            status = f"ok, {meta.get('ms','?')}ms"
        meta = dict(meta)
        meta["status"] = status
        meta["detail"] = _SRC_DESC.get(lab, lab)
        run_log["sources"][lab] = status
        run_log["source_meta"][lab] = meta
        if not status.startswith("ok"):
            run_log["fallback_chain"].append(f"{lab}: {status}")

    # ---- 4. V3 追加数据块: 4 新 fetcher + 两融 (逐个记录耗时/状态/实际源) ----
    fetched = {"announcements": None, "finance": None, "news": None,
               "research": None, "margin": None,
               "fund_daily5": None, "margin_hist": None, "peers": None}

    def _call_new(src_label: str, mod_key: str, *args, tries: int = 3, **kw):
        """调新 fetcher: import 失败 → 数据源暂缺; 调用异常 → 重试 tries 次。
        src_label = run_log.sources 规范键; mod_key = _NEW_IMPORTS 模块键。"""
        mod = _NEW_IMPORTS.get(mod_key)
        if mod is None:
            return None
        lab = src_label
        if not mod["ok"]:
            status = f"error:{mod['err'][:60]}, 0ms"
            run_log["sources"][lab] = status
            run_log["source_meta"][lab] = {"ms": 0, "at": None, "status": status,
                                           "detail": _SRC_DESC.get(lab, "")}
            run_log["fallback_chain"].append(f"{lab}: {mod['err']}")
            return None
        fn = mod["fn"]
        val, n_try, exc = _retry_call(lab, fn, *args, tries=tries, **kw)
        meta = _src_meta.get(lab, {})
        if exc:
            status = f"error:调用异常 {exc[:80]}, {meta.get('ms','?')}ms"
            run_log["fallback_chain"].append(f"{lab}: 第{n_try}次后仍失败 — {exc}")
        elif isinstance(val, dict) and "error" in val:
            status = f"error:{str(val['error'])[:60]}, {meta.get('ms','?')}ms"
            run_log["fallback_chain"].append(f"{lab}: {str(val['error'])[:100]}")
        elif isinstance(val, dict) and val.get("source"):
            status = f"ok:{val['source']}, {meta.get('ms','?')}ms"     # 实际数据源
        else:
            status = f"ok, {meta.get('ms','?')}ms"
        meta["status"] = status
        meta["detail"] = _SRC_DESC.get(lab, "")
        run_log["sources"][lab] = status
        run_log["source_meta"][lab] = meta
        return val

    print("\n[V3+] 追加数据块: 公告 / 财务 / 研报 / 新闻 / Section Registry / 两融 / 5日资金 / 同业…")
    fetched["announcements"] = _call_new("公告", "公告", code6)
    fetched["finance"] = _call_new("财务摘要", "财务", code6)
    fetched["research"] = _call_new("研报观点", "研报", code6, 200)  # days=200: 小票近90日常无覆盖(真实)
    fetched["news"] = _call_new("新闻舆情", "新闻", code6)
    # Section Registry: 5 新节走新路径（灰度老路径仍保留 4 旧 fetcher；spec §3.3）
    sections_data = {}
    sections = enabled_sections()
    run_log["sections_count"] = 0
    for sec in sections:
        sec_started = time.time()
        try:
            sections_data[sec.label] = sec.fetch(code6, base_result)
            ms = int((time.time() - sec_started) * 1000)
            run_log["sources"][sec.label] = f"ok, {ms}ms"
            run_log["sections_count"] += 1
        except Exception as e:  # noqa: BLE001
            sections_data[sec.label] = {"error": str(e)}
            run_log["sources"][sec.label] = f"error: {e}"
            run_log.setdefault("fallback_chain", []).append(f"{sec.label}: {e}")

    t0 = time.time()
    margin = None
    for _ in range(3):
        try:
            margin = v2.fetch_margin_trading(code6)
            break
        except Exception as e:  # noqa: BLE001
            margin = {"error": str(e)}
            time.sleep(1.0)
    ms = round((time.time() - t0) * 1000)
    if margin and isinstance(margin, dict) and "error" in margin:
        status = f"error:{str(margin['error'])[:60]}, {ms}ms"
        run_log["fallback_chain"].append(f"融资融券: {margin['error']}")
    else:
        status = f"ok:eastmoney-datacenter, {ms}ms"
    run_log["sources"]["融资融券"] = status
    run_log["source_meta"]["融资融券"] = {"ms": ms, "at": _fmt_time(time.time()),
                                          "status": status, "detail": _SRC_DESC["融资融券"]}
    fetched["margin"] = margin

    # 附加: 近5日主力 + 两融方向历史 + 同业(概念口径) — 失败不致命, 记入 supplements
    # 灰度保留：spec §3.3（"先保留 4 旧 fetcher 走老路径，5 新节走新注册表；下版本统一"）
    run_log["supplements"] = {}
    for key, lab, fn, args in (
            ("fund_daily5", "资金面-5日主力", _fetch_fund_flow_daily, (code6,)),
            ("margin_hist", "两融历史", _fetch_margin_history, (code6,)),
            ("peers", "同业对比", _fetch_concept_peers, (code6, base_result.get("blocks", []))),
    ):
        t0 = time.time()
        try:
            val = fn(*args)
            if isinstance(val, dict) and "error" in val and key != "margin_hist":
                time.sleep(1.5)                      # 附加源网络重试 1 次 (时间盒内)
                val2 = fn(*args)
                if not (isinstance(val2, dict) and "error" in val2):
                    val = val2
        except Exception as e:  # noqa: BLE001
            val = {"error": str(e)}
        meta = _src_meta.setdefault(lab, {"at": _fmt_time(time.time())})
        meta["ms"] = round((time.time() - t0) * 1000)
        if isinstance(val, dict) and "error" in val:
            meta["status"] = f"error:{str(val['error'])[:80]}, {meta['ms']}ms"
        else:
            meta["status"] = f"ok, {meta['ms']}ms"
        meta["detail"] = _SRC_DESC.get(lab, lab)
        run_log["source_meta"][lab] = meta
        run_log["supplements"][lab] = meta["status"]
        fetched[key] = val

    # ---- 5. 组装 result_v3 (契约) ----
    result = {
        "code": code6, "name": base_result.get("name") or name,
        "quote": q, "valuation": v, "blocks": base_result.get("blocks", []),
        "fund": base_result.get("fund", {}), "valuation_hist": base_result.get("valuation_hist", {}),
        "lockup": base_result.get("lockup", {}), "dragon": base_result.get("dragon", {}),
        "macro": base_result.get("macro", {}), "chip_data": chip_data,
        "sw_data": base_result.get("sw_data", {}),
        "announcements": fetched["announcements"], "finance": fetched["finance"],
        "news": fetched["news"], "research": fetched["research"],
        "margin": margin, "peers": fetched["peers"],
        "fund_daily5": fetched["fund_daily5"], "margin_hist": fetched["margin_hist"],
        "score": score, "advice": base_result["advice"], "emoji": base_result["emoji"],
        "detail": base_result["detail"], "trading_plan": plan,
        "three_levels": three_levels,  # 债 2 修法 (Task 5.2): 4 候选取最近者, 与 trading_plan 同源 K 线
        "signals": {"good": good_signals, "bad": bad_signals},
        "run_log": run_log,
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        **sections_data,  # Phase 1: 注入 section.label (irm) 作为 result 顶层 key
    }

    # ---- 5.5 北向资金口径分类 (债 3 修法, Task 5.3) ----
    # 在 result 顶层加 macro.north_scope + macro.north_label,
    # 渲染层 (MD/HTML/DOCX) 直接读 north_label 替代 hardcode, 杜绝"全市场当个股"误读。
    # 严守 Task 5.1/5.2 锁定: 不覆盖 trading_plan / three_levels。
    _north_data = (result.get("macro") or {}).get("hsgt") or {}
    _scope, _label = _classify_north_scope(_north_data)
    result["macro"]["north_scope"] = _scope      # "market" / "stock" / "mixed" / "unknown"
    result["macro"]["north_label"] = _label      # 模板直接用的字符串 (含 scope 关键词)
    print(f"[v3] 北向资金 scope={_scope} label='{_label}'")

    # ---- 6. run_log 收尾: guard + 时点 ----
    fresh = _kline_freshness(chip_data)
    run_log["guard"]["kline_freshness"] = (
        f"last_bar={fresh['last_bar'] or 'N/A'} vs 最新交易日={fresh['expected']} -> "
        f"{fresh['level']} ({fresh['text']})")
    if fresh["level"] == "warn":
        run_log["fallback_chain"].append(f"K线时点: {fresh['text']} [WARN]")
    print(f"\n[guard] {run_log['guard']['kline_freshness']}")

    run_log["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    run_log["total_sec"] = round(time.time() - started.timestamp(), 1)

    # ---- 7. 输出: 五件套 (MD + result_v3.json + HTML + DOCX + run_log.json) ----
    files = _emit(code6, result["name"], result)

    # 控制台摘要
    print("\n" + "=" * 72)
    print(f"【V3】{result['name']} ({code6}) 综合 {score_total}分 "
          f"{result['emoji']}{result['advice']}  耗时 {run_log['total_sec']}s")
    # 三价位(同源) — 债 2 修法 (Task 5.2): 优先读 result['three_levels'] 4 候选取最近者;
    # 兜底用 plan['entry_low'/'tp1'/'stop_loss']（V2 同源），保证控制台/HTML/MD 输出口径一致
    tl3 = result.get("three_levels") or {}
    if plan and (tl3.get("support") or tl3.get("resistance") or tl3.get("stop_loss")):
        print(f"  三价位(同源): 支撑={(tl3.get('support') or plan['entry_low']):.2f} "
              f"压力={(tl3.get('resistance') or plan['tp1']):.2f} "
              f"止损={(tl3.get('stop_loss') or plan['stop_loss']):.2f} "
              f"(4 候选支撑={list((tl3.get('support_candidates') or {}).keys())}, "
              f"3 候选压力={list((tl3.get('resistance_candidates') or {}).keys())})")
    for key in ("md", "json", "html", "docx", "run_log"):
        p = files.get(key)
        if p:
            print(f"  {key.upper()}: {p}")
    st = files.get("status", {})
    print(f"  状态: html={st.get('html')}  docx={st.get('docx')}")
    return result


# ============================================================
# 输出
# ============================================================
def _emit(code: str, name: str, result: dict) -> dict:
    """三件套落盘 (out_dir 内, 同 HHMM 时间戳命名):
    ① {code}-{name}-{HHMM}.md  ② result_v3.json  ③ run_log.json
    ④ {code}-{name}-{HHMM}.html (html_report_v3)  ⑤ {code}-{name}-{HHMM}.docx (md_to_docx)
    返回 {md, html, docx, json, run_log, day_dir, status:{...}}"""
    safe_name = name or code
    day_dir = os.path.join(REPORTS_ROOT, f"{code}_{safe_name}",
                           datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    hhmm = datetime.now().strftime("%H%M")
    base = f"{code}-{safe_name}-{hhmm}"
    md_path = os.path.join(day_dir, f"{base}.md")
    html_path = os.path.join(day_dir, f"{base}.html")
    docx_path = os.path.join(day_dir, f"{base}.docx")
    json_path = os.path.join(day_dir, f"result_v3-{hhmm}.json")
    log_path = os.path.join(day_dir, f"run_log-{hhmm}.json")

    # ① MD
    md_text = write_markdown_report_v3(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    # ② 完整 result dict → result_v3.json (HTML 组同款契约; default=str 兜底非序列化字段)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    # ③ HTML — html_report_v3.write_html_report_v3(result, out_dir) (import 失败则补路径重试)
    html_status = "error:未执行"
    html_err = ""
    t0 = time.time()
    try:
        try:
            import html_report_v3 as _hrv3
        except Exception:  # noqa: BLE001 — import 失败: 补 sys.path 后重试一次
            sys.path.insert(0, _ANALYSIS_DIR)
            import html_report_v3 as _hrv3
        html_path = _hrv3.write_html_report_v3(result, day_dir)
        html_status = "ok"
    except Exception as e:  # noqa: BLE001
        html_err = str(e)
        html_status = f"error:{str(e)[:120]}"
    html_ms = round((time.time() - t0) * 1000)

    # ④ DOCX — md_to_docx(md_path, docx_path); 直接 import, 失败则 subprocess 兜底 (不改 md_to_docx.py)
    docx_status = "error:未执行"
    docx_err = ""
    t0 = time.time()
    try:
        sys.path.insert(0, _ANALYSIS_DIR)
        from md_to_docx import md_to_docx as _md2docx
        _md2docx(md_path, docx_path)
        docx_status = "ok"
    except Exception as e1:  # noqa: BLE001
        try:
            import subprocess
            subprocess.run([sys.executable, os.path.join(_ANALYSIS_DIR, "md_to_docx.py"),
                            md_path, docx_path], check=True, timeout=180)
            docx_status = "ok(import失败→subprocess)"
        except Exception as e2:  # noqa: BLE001
            docx_err = f"{e1} | subprocess: {e2}"
            docx_status = f"error:{docx_err[:120]}"
    docx_ms = round((time.time() - t0) * 1000)

    # run_log.json — 末尾再写一次, 并入产物状态与文件大小 (HTML/DOCX 成败均如实记录)
    rl = result.get("run_log") or {}
    sizes = {}
    for p in (md_path, html_path, docx_path, json_path, log_path):
        try:
            sizes[os.path.basename(p)] = os.path.getsize(p)
        except OSError:
            sizes[os.path.basename(p)] = None
    rl["artifacts"] = {
        "md": os.path.basename(md_path), "html": os.path.basename(html_path),
        "docx": os.path.basename(docx_path), "result_json": os.path.basename(json_path),
        "html_status": html_status, "html_ms": html_ms,
        "docx_status": docx_status, "docx_ms": docx_ms,
        "sizes_bytes": sizes,
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(rl, f, ensure_ascii=False, indent=2, default=str)

    files = {"md": md_path, "html": html_path, "docx": docx_path,
             "json": json_path, "run_log": log_path, "day_dir": day_dir,
             "status": {"html": html_status, "docx": docx_status,
                        "html_err": html_err, "docx_err": docx_err}}
    result["_files"] = files
    # ②(终) 补 dump: result["run_log"] 与 rl 同对象, 此时已含 artifacts; _files 也一并入 json
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    if html_status != "ok":
        print(f"  [WARN] HTML 生成失败: {html_status}")
    if docx_status != "ok":
        print(f"  [WARN] DOCX 生成失败: {docx_status}")
    return files


def _dump_run_log(code: str, name: str, run_log: dict):
    """失败中止时也落 run_log.json (便于排查)。"""
    safe_name = name or code
    day_dir = os.path.join(REPORTS_ROOT, f"{code}_{safe_name}",
                           datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, f"run_log-{datetime.now().strftime('%H%M')}.json"), "w", encoding="utf-8") as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# 数据块解读 (人话)
# ============================================================
def _interpret_yoy(growth, kind: str) -> str:
    """增速 → 人话。kind: '营收'/'净利'"""
    if growth is None:
        return f"{kind}同比 — (数据未披露/无上年同期基数)"
    g = float(growth)
    if g >= 30:
        return f"{kind}同比 **+{g:.1f}%** — 高速增长(🔥)"
    if g >= 10:
        return f"{kind}同比 **+{g:.1f}%** — 稳健增长"
    if g >= 0:
        return f"{kind}同比 **+{g:.1f}%** — 微增"
    return f"{kind}同比 **{g:.1f}%** — 负增长(⚠️ 需排查原因)"


def _interpret_qoq(growth, kind: str) -> str:
    if growth is None:
        return ""
    g = float(growth)
    return f"单季环比 **{g:+.1f}%**" + ("(环比提速)" if g > 0 else "(环比转弱)")


def _finance_talk(fin: dict) -> list:
    """财务体检一句人话点评 → 若干 bullet (数据从 fetcher 实取, 无则 '—')。"""
    if not fin or not isinstance(fin, dict) or "latest" not in fin:
        return ["> ⚠️ 财务摘要数据缺失, 无法体检 (不编造)"]
    lt = fin.get("latest") or {}
    out = [f"- 最新报告期 **{lt.get('report_date','—')}** 财务体检:"]
    out.append(f"- {_interpret_yoy(lt.get('yoy_revenue'), '营收')} | "
               f"{_interpret_yoy(lt.get('yoy_profit'), '净利')}")
    qr, qp = lt.get("qoq_revenue"), lt.get("qoq_profit")
    if qr is not None or qp is not None:
        parts = []
        if qr is not None:
            parts.append(f"营收单季环比 **{qr:+.1f}%**")
        if qp is not None:
            parts.append(f"净利单季环比 **{qp:+.1f}%**")
        out.append("- 环比动能: " + " / ".join(parts))
    # 盈利质量
    roe, gm, debt = lt.get("roe"), lt.get("gross_margin"), lt.get("debt_ratio")
    bits = []
    if roe is not None:
        bits.append(f"ROE(加权) {_fnum(roe)}%" +
                    ("(≥15% 回报强)" if roe >= 15 else ("(8~15% 中等)" if roe >= 8 else "(<8% 偏弱)")))
    if gm is not None:
        bits.append(f"毛利率 {_fnum(gm)}%" +
                    ("(≥40% 高毛利)" if gm >= 40 else ("(20~40% 中等)" if gm >= 20 else "(<20% 薄利)")))
    if debt is not None:
        bits.append(f"资产负债率 {_fnum(debt)}%" +
                    ("(≤50% 稳健)" if debt <= 50 else ("(50~70% 中性)" if debt <= 70 else "(>70% 高杠杆🚨)")))
    if bits:
        out.append("- " + " | ".join(bits))
    # 一句人话总结
    profit_yi = lt.get("profit_yi")
    yoy_p = lt.get("yoy_profit")
    if profit_yi is not None and profit_yi < 0:
        verdict = "最新一期仍处亏损状态, 首要看点是扭亏进度与现金流"
    elif yoy_p is not None and yoy_p < 0:
        verdict = "净利同比负增长是当前最大财务风险点, 需盯紧后续季报能否收窄"
    elif yoy_p is not None:
        verdict = "盈利同比正增长, 当前主业经营数据未见明显恶化"
    else:
        verdict = "同比基数缺失(披露窗口外), 以绝对额与环比为准"
    out.append(f"> 📝 人话点评: 最新一期**净利同比 {_fpct(yoy_p)}**、营收同比 "
               f"{_fpct(lt.get('yoy_revenue'))}, {verdict}")
    return out


def _next_report_window(latest_date: Optional[str]) -> str:
    """财报窗口推算 (法定披露规则推算, 非抓取): 最近已披露期 + 下一个未到法定截止日。"""
    ctx = ""
    if latest_date:
        try:
            ctx = f"最近已披露 {str(latest_date)[:10]}"
        except Exception:  # noqa: BLE001
            ctx = f"最近已披露 {latest_date}"
    else:
        ctx = "暂无最近财报日期"
    today = datetime.now()
    dl_name = {4: "年报/一季报", 8: "半年报", 10: "三季报"}
    dl_day = {4: 30, 8: 31, 10: 31}      # 法定披露截止日: 4-30 / 8-31 / 10-31
    candidates = []
    for y in (today.year, today.year + 1):
        for m, nm in ((4, "年报/一季报"), (8, "半年报"), (10, "三季报")):
            dt = datetime(y, m, dl_day[m])
            if dt > today:
                candidates.append((dt, nm))
    if not candidates:
        return f"{ctx}; 推算窗口失败"
    deadline, nm = min(candidates)
    days_left = (deadline - today).days
    flag = "🚨 **财报披露窗口临近**" if days_left <= 35 else ""
    return (f"{ctx}; 下一法定披露截止 {deadline:%Y-%m-%d} ({nm}) 距今 "
            f"{days_left} 天 {flag}").strip()


def _sentiment_line(news: dict) -> str:
    if not news or not isinstance(news, dict) or "error" in news:
        return ""
    rows = news.get("news") or []
    pos = sum(1 for r in rows if (r.get("sentiment") or "") == "利好")
    neg = sum(1 for r in rows if (r.get("sentiment") or "") == "利空")
    neu = len(rows) - pos - neg
    if pos > neg * 1.5 and pos >= 3:
        talk = "情绪偏暖, 利好多于利空"
    elif neg > pos * 1.5 and neg >= 3:
        talk = "情绪偏冷, 需警惕负面发酵"
    else:
        talk = "消息面多空交织, 情绪中性"
    return f"近{len(rows)}条样本: 利好{pos} / 利空{neg} / 中性{neu} → {talk}"


def _src_foot(lab: str, extra: Optional[dict] = None) -> str:
    """每块的数据来源+时点标注行 (从 run_log 实取)。"""
    m = extra or {}
    desc = m.get("desc") or _SRC_DESC.get(lab, lab)
    at = m.get("fetched_at") or m.get("at")
    s = m.get("status") or ""
    at_s = _short_iso(at) if at and len(str(at)) > 8 else (at or "")
    return f"> 📡 数据来源: {desc} | 抓取于 {at_s or '—'} | 状态: {s}"


# ============================================================
# V3 Markdown 报告 — 结论前置 + 新6块 + 检查清单 + 风险警报区 + V2 保留块
# ============================================================
def write_markdown_report_v3(r: dict) -> str:
    code, name = r["code"], r["name"]
    q, v, s = r["quote"], r["valuation"], r["score"]
    score_total = s["total"]
    rl: dict = r.get("run_log") or {}
    metas = rl.get("source_meta") or {}
    price, change_pct = q.get("price", 0), s.get("change_pct", 0)
    plan = r.get("trading_plan")
    signals = r.get("signals") or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 决策状态 — 5 状态机 (债 1 修法, Task 5.1)；优先读 plan["state"]（trading_plan 注入），
    # 兜底 _score_to_state()，再兜底 3 态旧逻辑（plan 缺失时）。
    if plan and plan.get("state"):
        state_key = plan["state"]
        state, state_icon = _STATE_DISPLAY.get(state_key, ("中性", "🟡"))
    else:
        state_key = _score_to_state(score_total)
        state, state_icon = _STATE_DISPLAY.get(state_key, ("中性", "🟡"))

    # 三价位 (债2显式三价位 + 债4 同源声明)
    support, resist, stop = None, None, None
    if plan:
        support, resist, stop = (plan["entry_low"], plan["tp1"], plan["stop_loss"])

    L: list = []

    # ================= 第一屏: 决策结论 =================
    L.append(f"# {name} ({code}) — V3 决策报告")
    L.append("")
    L.append(f"## 🎯 结论前置 · 30 秒决策")
    L.append("")
    L.append(f"> **{r['emoji']} {r['advice']}** ｜ 多空三态: **{state_icon} {state}** ｜ "
             f"综合评分 **{score_total}/100**")
    L.append("")
    L.append(f"- 现价 **{price:.2f} 元** ({change_pct:+.2f}%) ｜ PE(TTM) {q.get('pe_ttm',0):.1f} ｜ "
             f"PB {q.get('pb',0):.2f} ｜ 流通市值 {q.get('float_mcap',0):.1f} 亿")
    L.append(f"- 一句话理由: **{r.get('detail','')}**")
    L.append(f"- 报告生成: {now} (报告日期 {r.get('report_date','')})")
    L.append("")
    L.append("### 三价位 (支撑 / 压力 / 止损)")
    L.append("")
    if plan:
        # 债 2 修法 (Task 5.2): 4 支撑候选 / 3 压力候选 → 取最近者 (+/-5% 过滤)
        # 候选价从 chip_data['kline'] 自算 MA/布林/前高/前低, 筹码峰读 chip_data['peak_price']
        # stop_loss 复用 trading_plan.stop_loss (V2 同源, **不重算**)
        tl3 = r.get("three_levels") or {}
        tl_sup = tl3.get("support")
        tl_res = tl3.get("resistance")
        tl_sl = tl3.get("stop_loss") or plan.get("stop_loss")
        sup_cands = tl3.get("support_candidates") or {}
        res_cands = tl3.get("resistance_candidates") or {}
        if tl_sup is not None and tl_res is not None:
            L.append(f"> **三价位(同源)**: 支撑=**{tl_sup:.2f}** 压力=**{tl_res:.2f}** 止损=**{tl_sl:.2f}**")
            if sup_cands:
                sup_str = " / ".join(f"{k}={v:.2f}" for k, v in sup_cands.items())
                L.append(f"> - 4 支撑候选: {sup_str}（取最低且 ≤ 1.05×现价 = **{tl_sup:.2f}**）")
            if res_cands:
                res_str = " / ".join(f"{k}={v:.2f}" for k, v in res_cands.items())
                L.append(f"> - 3 压力候选: {res_str}（取最高且 ≥ 0.95×现价 = **{tl_res:.2f}**）")
            L.append("")
        L += [
            "| 价位 | 数值 | 说明 |",
            "|------|------|------|",
            f"| **支撑位** | **{plan['entry_low']:.2f} 元** | 回调买入区下沿 (现价-3%, 分批进场上限 "
            f"{plan['entry_high']:.2f}) |",
            f"| **压力位** | **{plan['tp1']:.2f} 元** | 第一目标 (+10%, 先减半仓锁利; 远档 "
            f"{plan['tp2']:.2f} / {plan['tp3']:.2f}) |",
            f"| **止损位** | **{plan['stop_loss']:.2f} 元** | 跌破必走 (现价下方 -{plan['stop_loss_pct']:.1f}%) |",
            "",
        ]
        L.append(f"> 🔒 三价位均由 V2 同源实时模型推导: 腾讯实时行情价 + baostock 前复权筹码K线, "
                 f"**未使用任何池 CSV 陈旧价** (债4)。")
    else:
        L.append("> ⚠️ 三价位无法生成 (行情/筹码数据缺失), 请勿据此操作。")
    L.append("")

    # ================= 风险警报区 (红色高亮) =================
    L.append("## 🚨 风险警报区")
    L.append("")
    alerts = []
    lockup = r.get("lockup") or {}
    if isinstance(lockup, dict) and "error" not in lockup and lockup.get("upcoming"):
        for u in lockup["upcoming"]:
            heavy = "【高风险🚨】" if u.get("ratio_pct", 0) > 5 else ""
            alerts.append(f"🔴 解禁 {u.get('date','—')} 解禁 {u.get('shares_wan',0):,.0f} 万股"
                          f" ({_fnum(u.get('ratio_pct'),2)}% 股本) {heavy}"
                          f" [{u.get('type','')}]")
    elif isinstance(lockup, dict) and "error" in lockup:
        alerts.append(f"🟡 解禁数据不可用: {lockup['error']}")
    if not alerts and not (isinstance(lockup, dict) and "error" in lockup):
        alerts.append("🟢 未来 90 天无解禁压力")
    # 财报窗口
    fin = r.get("finance")
    if fin and isinstance(fin, dict) and "error" not in fin and fin.get("latest"):
        win = _next_report_window(fin["latest"].get("report_date"))
        if "临近" in win:
            alerts.append("🔴 " + win)
        else:
            alerts.append("🟡 " + win)
    else:
        alerts.append("🟡 财报窗口推算: 财务摘要数据源暂缺, 无法推算")
    # 估值极端
    pe, vh = q.get("pe_ttm", 0), r.get("valuation_hist") or {}
    if pe and pe > 80:
        alerts.append(f"🔴 PE(TTM) {pe:.1f} 极高估, 泡沫风险 (估值分位 "
                      f"{_fnum(vh.get('pe_percentile_3y'),1)}%)")
    elif isinstance(vh, dict) and "error" not in vh and (vh.get("pe_percentile_3y") or 0) > 80:
        alerts.append(f"🔴 PE 历史分位 {(vh.get('pe_percentile_3y') or 0):.0f}% — 接近 3 年最高")
    # 龙虎榜大额净卖
    dragon = r.get("dragon") or {}
    if isinstance(dragon, dict) and "error" not in dragon and dragon.get("records"):
        nbs = [x.get("net_buy_wan", 0) for x in dragon["records"]]
        if nbs and sum(nbs) / len(nbs) < -1000:
            avg = sum(nbs) / len(nbs)
            alerts.append(f"🔴 龙虎榜近30日平均净卖出 {avg:,.0f} 万元 — 游资/机构撤退信号")
    if not alerts:
        alerts.append("✅ 未发现明显风险事件")
    for a in alerts:
        L.append(f"- {a}")
    L.append("")

    # ================= 操作检查清单 (按 5 状态) =================
    L.append("## ✅ 操作检查清单")
    L.append("")
    if plan:
        e_lo, e_hi = plan["entry_low"], plan["entry_high"]
        st, tp1, tp2, tp3 = plan["stop_loss"], plan["tp1"], plan["tp2"], plan["tp3"]
        if state_key in ("bullish", "mild_bull"):
            buy_t = (f"① 回调至 {e_lo:.2f}~{e_hi:.2f} 区间分批建仓(如分两批各1/2); "
                     f"② 放量突破 {tp1:.2f} 可加仓追势")
            sell_t = (f"① 达 {tp1:.2f} 卖 1/2 锁利; ② 达 {tp2:.2f} 再减半; "
                      f"③ 达 {tp3:.2f} 或趋势走弱清剩余; ④ 跌破 {st:.2f} 无条件全走")
            stop_t = f"收盘跌破 {st:.2f} (现价下 -{plan['stop_loss_pct']:.1f}%) 即离场, 不补仓摊平"
            pos_t = f"{plan['position']} | 周期 {plan['period']}"
        elif state_key == "neutral":
            buy_t = f"仅在 {e_lo:.2f}~{e_hi:.2f} 支撑区低吸, 上轨 {tp1:.2f} 附近不过量追高"
            sell_t = (f"① 反弹至 {tp1:.2f} 一带减仓; ② 跌破 {st:.2f} 转空离场; "
                      f"③ 放量站稳 {tp1:.2f} 上沿再按看多纪律执行")
            stop_t = f"{st:.2f} 为区间底沿, 收盘破位即走, 不猜底"
            pos_t = f"{plan['position']} | 以低吸高抛为主, 周期 {plan['period']}"
        else:  # mild_bear / bearish
            buy_t = "❌ 空头形态: 不买入、不补仓、不抄底; 空仓者观望等底部放量企稳信号"
            sell_t = f"① 反弹至压力位 {tp1:.2f} 一带分批减仓; ② 持仓者跌破 {st:.2f} 清仓; ③ 不抢反弹"
            stop_t = f"反弹减仓/清仓纪律优先, 止损 {st:.2f} 上方不留幻想仓"
            pos_t = "清仓回避 / 极轻仓短线者当日进出"
        # 操作口诀 (债 1 修法): 读 plan["template_used"], 5 状态各自独立模板, 不再 hardcode
        operation_tip = plan.get("template_used") or "（无操作口诀 — trading_plan.template_used 未注入）"
        L += [
            "| 检查项 | 触发条件与纪律 |",
            "|--------|----------------|",
            f"| 当前状态 | {state_icon} **{state}** (评分 {score_total} 分, 状态 `{state_key}`) |",
            f"| 操作口诀 | {operation_tip} |",
            f"| 买入触发 | {buy_t} |",
            f"| 卖出/减仓触发 | {sell_t} |",
            f"| 止损纪律 | {stop_t} |",
            f"| 仓位建议 | {pos_t} |",
            "",
        ]
    else:
        L.append("> ⚠️ 无三价位, 检查清单不可用, 观望为主。")
    L.append("")

    # ================= 6 块新内容 =================
    L.append("---")
    L.append("")
    L.append("## 📑 六维新增情报")
    L.append("")

    # --- 1. 研报观点汇总 ---
    L.append("### 📰 1. 研报观点汇总")
    L.append("")
    res = r.get("research")
    src_m = metas.get("研报观点") or {}
    if res is None or (isinstance(res, dict) and "error" in res):
        why = (res or {}).get("error") if isinstance(res, dict) else \
            (_NEW_IMPORTS["研报"]["err"] or "未调用")
        L.append(f"> ⚠️ 研报观点数据暂缺: {_clean(why, 90)} (已记 run_log error, 不影响其他块)")
    elif isinstance(res, dict):
        dist = res.get("rating_dist") or {}
        cnt = res.get("count", 0)
        rep5 = (res.get("reports") or [])[:5]
        if cnt == 0:
            L.append(f"- 近 200 日研报 {cnt} 篇 (实际数据源: **{res.get('source','—')}**) — "
                     "小票机构覆盖稀疏属真实情况(如东财近 90 日常无新研报), 非接口错误")
        else:
            L.append(f"- 近 200 日研报 {cnt} 篇; 实际数据源: **{res.get('source','—')}**")
        if dist:
            mx = max(dist.values()) or 1
            bar = "  ".join(
                f"{k} {n} {'█' * max(1, round(n / mx * 8))}" for k, n in dist.items())
            L.append(f"- 评级分布: {bar}")
        else:
            L.append("- 评级分布: (无)")
        L.append("")
        if rep5:
            L.append("| 日期 | 机构 | 评级 | 目标价 | 观点标题 |")
            L.append("|------|------|------|--------|----------|")
            for it in rep5:
                L.append(f"| {_clean(it.get('date'))} | {_clean(it.get('org'),24)} | "
                         f"{_clean(it.get('rating'),10)} | {_fnum(it.get('target_price'),2)} | "
                         f"{_clean(it.get('title'),46)} |")
        else:
            L.append("- (窗口内无研报记录)")
    else:
        L.append("> ⚠️ 研报观点数据源暂缺")
    L.append("")
    L.append(_src_foot("研报观点", {"fetched_at": (res or {}).get("fetched_at") if isinstance(res, dict) else None,
                                    "status": rl.get("sources", {}).get("研报观点", ""),
                                    "desc": "东财研报 reportapi(降级同花顺)"}))
    L.append("")

    # --- 2. 公告速览 ---
    L.append("### 📢 2. 公告速览 (近 30 日)")
    L.append("")
    ann = r.get("announcements")
    if ann is None or (isinstance(ann, dict) and "error" in ann):
        why = (ann or {}).get("error") if isinstance(ann, dict) else \
            (_NEW_IMPORTS["公告"]["err"] or "未调用")
        L.append(f"> ⚠️ 公告数据暂缺: {_clean(why, 90)} (已记 run_log error)")
    elif isinstance(ann, dict):
        rows = (ann.get("announcements") or [])[:18]
        cat_cnt = {}
        sent = {"利好": 0, "利空": 0, "中性": 0}
        for x in rows:
            c = x.get("category") or "未分类"
            cat_cnt[c] = cat_cnt.get(c, 0) + 1
            sent[x.get("sentiment") or "中性"] = sent.get(x.get("sentiment") or "中性", 0) + 1
        cat_s = " | ".join(f"{k}×{v}" for k, v in sorted(cat_cnt.items(), key=lambda kv: -kv[1]))
        L.append(f"- 近 30 日公告 {ann.get('count', len(rows))} 条 (展示 {len(rows)} 条), "
                 f"实际数据源: **{ann.get('source','—')}**")
        if cat_s:
            L.append(f"- 分类: {cat_s}")
        L.append(f"- 情绪: 利好 {sent.get('利好',0)} / 利空 {sent.get('利空',0)} / "
                 f"中性 {sent.get('中性',0)}")
        L.append("")
        if rows:
            L.append("| 日期 | 类别 | 情绪 | 标题 |")
            L.append("|------|------|------|------|")
            for x in rows:
                st_s = x.get("sentiment") or "中性"
                icon = {"利好": "🟢", "利空": "🔴", "中性": "⚪"}.get(st_s, "⚪")
                L.append(f"| {_clean(x.get('date'),10)} | {_clean(x.get('category'),14)} | "
                         f"{icon}{_clean(st_s,4)} | {_clean(x.get('title'),56)} |")
    else:
        L.append("> ⚠️ 公告数据源暂缺")
    L.append("")
    L.append(_src_foot("公告", {"fetched_at": (ann or {}).get("fetched_at") if isinstance(ann, dict) else None,
                                "status": rl.get("sources", {}).get("公告", ""),
                                "desc": "东财公告 / 巨潮 cninfo"}))
    L.append("")

    # --- 3. 财务体检解读 ---
    L.append("### 🩺 3. 财务体检解读")
    L.append("")
    if fin is None or (isinstance(fin, dict) and "error" in fin):
        why = (fin or {}).get("error") if isinstance(fin, dict) else \
            (_NEW_IMPORTS["财务"]["err"] or "未调用")
        L.append(f"> ⚠️ 财务数据暂缺: {_clean(why, 90)} (已记 run_log error)")
    elif isinstance(fin, dict):
        reps = (fin.get("reports") or [])[:8]
        lt = fin.get("latest") or {}
        L.extend(_finance_talk(fin))
        L.append("")
        L.append("| 报告期 | 营收(亿) | 净利(亿) | EPS | ROE% | 毛利率% | 负债率% | 同比营收 | 同比净利 |")
        L.append("|--------|---------|---------|-----|------|---------|---------|---------|---------|")
        for p in reps:
            L.append(f"| {p.get('report_date','—')} | {_fnum(p.get('revenue_yi'))} | "
                     f"{_fnum(p.get('profit_yi'))} | {_fnum(p.get('eps'),3)} | "
                     f"{_fnum(p.get('roe'))} | {_fnum(p.get('gross_margin'))} | "
                     f"{_fnum(p.get('debt_ratio'))} | {_fpct(p.get('yoy_revenue'))} | "
                     f"{_fpct(p.get('yoy_profit'))} |")
        L.append("")
        L.append("> 口径说明: 同比=累计口径 vs 上年同期; 环比=单季值 vs 上一报告期单季 (来自东财 F10 "
                 "主财务指标, 经核对一致)。")
    else:
        L.append("> ⚠️ 财务数据源暂缺")
    L.append("")
    L.append(_src_foot("财务摘要", {"fetched_at": (fin or {}).get("fetched_at") if isinstance(fin, dict) else None,
                                    "status": rl.get("sources", {}).get("财务摘要", ""),
                                    "desc": "东财数据中心 主要财务指标(F10)"}))
    L.append("")

    # --- 4. 同业对比 (概念口径) ---
    L.append("### 🆚 4. 同业对比 (东财概念板块口径)")
    L.append("")
    peers = r.get("peers")
    if peers is None:
        L.append("> ⚠️ 同业对比数据暂缺 (概念板块缺失, 无法取成分股)。可先用下方估值/申万块自行定位。")
    elif isinstance(peers, dict) and peers.get("rows"):
        rows = peers["rows"]
        self_rows = [x for x in rows if str(x.get("code", "")) == code]
        show = [x for x in rows if str(x.get("code", "")) != code][:8]
        L.append(f"- 对比池: 概念板块 **{peers.get('block_used','—')}** "
                 f"(成分 {peers.get('total','—')} 只, 取流通市值前列)")
        if peers.get("rank"):
            L.append(f"- 📍 本票 {name}: 按总市值在该概念中排 **第 {peers['rank']} / "
                     f"{peers.get('total','?')}** 名")
        elif self_rows:
            L.append(f"- 📍 本票 {name} 在取回的前 {len(rows)} 只中 (总 {peers.get('total','?')} 只)")
        else:
            L.append(f"- 📍 本票未进入该概念市值前 {len(rows)} (总 {peers.get('total','?')} 只)")
        L.append("")
        L.append("| 代码 | 名称 | 现价 | 涨跌% | PE(TTM) | PB | 总市值(亿) |")
        L.append("|------|------|------|-------|---------|-----|-----------|")
        anchor = " ← 本票"
        for x in self_rows[:1]:
            L.append(f"| {x.get('code')} | **{_clean(x.get('name'),12)}**{anchor} | "
                     f"{_fnum(x.get('price'))} | {_fpct(x.get('chg'))} | {_fnum(x.get('pe'),1)} | "
                     f"{_fnum(x.get('pb'),2)} | {_fnum(x.get('total_mcap_yi'),1)} |")
        for x in show[:8]:
            L.append(f"| {x.get('code')} | {_clean(x.get('name'),12)} | {_fnum(x.get('price'))} | "
                     f"{_fpct(x.get('chg'))} | {_fnum(x.get('pe'),1)} | {_fnum(x.get('pb'),2)} | "
                     f"{_fnum(x.get('total_mcap_yi'),1)} |")
        # 位置话: 用 PE/PB 对比高估低估
        self_pe = self_rows[0].get("pe") if self_rows else None
        if self_pe is not None and show:
            ok_pe = [x["pe"] for x in show if x.get("pe") is not None]
            if ok_pe:
                mid = sorted(ok_pe)[len(ok_pe) // 2]
                rank_v = "比列示同行多数**更贵**" if self_pe > mid else "低于列示同行中位, 估值**相对不贵**"
                L.append(f"- 估值位置: 本票 PE {self_pe:.1f} vs 列示同行中位 {mid:.1f} → {rank_v} "
                         f"(粗比, 细分行业与成长性不同会有偏差)")
        L.append("")
        L.append("> 口径说明: 概念板块成分数据由东财实时接口取回 (与 v2 概念归属同源); "
                 "申万全行业同业中位暂缺专用数据源, 不做编造。")
    else:
        why = (peers or {}).get("error", "接口失败")
        L.append(f"> ⚠️ 同业对比: {_clean(why, 90)} — 可结合估值分位章节判断自身贵贱。")
    L.append("")
    L.append(_src_foot("同业对比", metas.get("同业对比")))
    L.append("")

    # --- 5. 资金面 (近5日主力 + 两融) ---
    L.append("### 💰 5. 资金面 (近 5 日主力资金 + 融资融券方向)")
    L.append("")
    fund5 = r.get("fund_daily5")
    if fund5 and isinstance(fund5, dict) and "error" not in fund5 and fund5.get("rows"):
        L.append("| 日期 | 主力净流入(亿) | 大单+超大单(亿) |")
        L.append("|------|---------------|----------------|")
        for x in fund5["rows"]:
            L.append(f"| {x.get('date','—')} | {_fnum(x.get('main_net_yi'),3)} | "
                     f"{_fnum(x.get('large_super_yi'),3)} |")
        tot = fund5.get("total_main_yi")
        talk = "近5日主力**净流入**, 资金面偏多" if (tot or 0) > 0 else \
            ("近5日主力**净流出**, 资金面承压" if (tot or 0) < 0 else "近5日主力基本平衡")
        L.append("")
        L.append(f"- 5 日合计主力净额 **{_fnum(tot,3)} 亿** → {talk} "
                 f"(区间 {fund5.get('start')} ~ {fund5.get('end')})")
    else:
        why = (fund5 or {}).get("error", "近5日主力资金不可用") if isinstance(fund5, dict) else "近5日主力资金不可用"
        L.append(f"> ⚠️ 近5日主力资金: {_clean(why, 90)} (当日分钟资金见下方 V2 保留块)")
    L.append("")
    margin = r.get("margin")
    mh = r.get("margin_hist") or {}
    if margin and isinstance(margin, dict) and "error" not in margin:
        mdate = margin.get("date", "—")
        L.append(f"- 融资融券 (最新 {mdate}): 融资余额 **{_fnum(margin.get('rzye_yi'),2)} 亿** ｜ "
                 f"融券余额 {_fnum(margin.get('rqye_yi'),2)} 亿")
        net_buy = (margin.get("rzmre_yi") or 0) - (margin.get("rzche_yi") or 0)
        L.append(f"  - 当日融资买入 {_fnum(margin.get('rzmre_yi'),3)} 亿 / 偿还 "
                 f"{_fnum(margin.get('rzche_yi'),3)} 亿 → 融资净 **{_fnum(net_buy,3)} 亿** "
                 + ("(杠杆资金在加仓🟢)" if net_buy > 0 else ("(杠杆资金在撤🟡)" if net_buy < 0 else "(持平)")))
        rows = (mh.get("rows") or []) if isinstance(mh, dict) else []
        if len(rows) >= 3:
            chg = rows[0].get("rzye_chg_yi")
            first, last = rows[-1].get("rzye_yi"), rows[0].get("rzye_yi")
            if last is not None and first is not None and last != first:
                dr = "上行🟢" if last > first else "下行🟡"
                L.append(f"  - 融资余额方向: {rows[0].get('date')} {_fnum(last,2)}亿 vs "
                         f"{rows[-1].get('date')} {_fnum(first,2)}亿 "
                         f"→ 近{len(rows)}期{dr}, 单期变动 {_fpct(chg,2)} 亿")
    else:
        why = (margin or {}).get("error", "融资融券无数据") if isinstance(margin, dict) else "融资融券未取到"
        L.append(f"> ⚠️ 融资融券: {_clean(why, 90)}")
    L.append("")
    if margin and isinstance(margin, dict) and "error" not in margin:
        L.append(_src_foot("融资融券", metas.get("融资融券")))
    L.append(_src_foot("资金面-5日主力", metas.get("资金面-5日主力")))
    L.append("")

    # --- 6. 新闻舆情 ---
    L.append("### 🗞️ 6. 新闻舆情 (利好 / 利空)")
    L.append("")
    news = r.get("news")
    if news is None or (isinstance(news, dict) and "error" in news):
        why = (news or {}).get("error") if isinstance(news, dict) else \
            (_NEW_IMPORTS["新闻"]["err"] or "未调用")
        L.append(f"> ⚠️ 新闻舆情数据暂缺: {_clean(why, 90)} (已记 run_log error)")
    elif isinstance(news, dict):
        rows = news.get("news") or []
        pos = [x for x in rows if (x.get("sentiment") or "") == "利好"][:3]
        neg = [x for x in rows if (x.get("sentiment") or "") == "利空"][:3]
        L.append(f"- 样本: 近 {news.get('count', len(rows))} 条 ｜ 实际数据源: **{news.get('source','—')}**")
        L.append(f"- 情绪一句话: **{_sentiment_line(news)}**")
        L.append("")
        L.append("**🟢 利好 (最多 3 条)**")
        if pos:
            for x in pos:
                L.append(f"- ✅ {x.get('date','—')} {_clean(x.get('title'),64)}"
                         + (f" — {_clean(x.get('summary'),60)}" if x.get("summary") else ""))
        else:
            L.append("- (无)")
        L.append("")
        L.append("**🔴 利空 (最多 3 条)**")
        if neg:
            for x in neg:
                L.append(f"- ⚠️ {x.get('date','—')} {_clean(x.get('title'),64)}"
                         + (f" — {_clean(x.get('summary'),60)}" if x.get("summary") else ""))
        else:
            L.append("- (无)")
        neu = [x for x in rows if (x.get("sentiment") or "") not in ("利好", "利空")]
        if neu and (not pos or not neg):
            L.append("")
            L.append("**⚪ 中性样本 (供核对, 最多 5 条)**")
            for x in neu[:5]:
                L.append(f"- {x.get('date','—')} {_clean(x.get('title'),72)}"
                         + (f" — {_clean(x.get('summary'),50)}" if x.get("summary") else ""))
    else:
        L.append("> ⚠️ 新闻舆情数据源暂缺")
    L.append("")
    L.append(_src_foot("新闻舆情", {"fetched_at": (news or {}).get("fetched_at") if isinstance(news, dict) else None,
                                    "status": rl.get("sources", {}).get("新闻舆情", ""),
                                    "desc": "东财个股新闻"}))
    L.append("")
    L.append("---")
    L.append("")

    # ================= V2 保留块 =================
    # --- 好/坏信号 ---
    L.append("## 👍 看好这票的理由")
    gs = signals.get("good") or []
    if gs:
        for g in gs:
            L.append(g)
    else:
        L.append("(暂时没有发现明确的正面信号)")
    L.append("")
    L.append("## 👎 要小心的信号")
    bs = signals.get("bad") or []
    if bs:
        for b in bs:
            L.append(b)
    else:
        L.append("✅ 没有发现明显负面信号")
    L.append("")

    # --- 估值贵不贵 (V2) ---
    pe_talk = v2._interpret_pe(q.get("pe_ttm", 0))
    pb = q.get("pb", 0)
    L.append("## 💰 估值贵不贵")
    L.append(f"- **{pe_talk}**")
    if pb and pb > 0:
        pb_talk = "PB 极高" if pb > 10 else ("PB 偏高" if pb > 5 else ("PB 正常" if pb >= 2 else "PB 极低"))
        L.append(f"- **PB {pb:.2f}** — {pb_talk}")
    if v.get("peg") and v["peg"] != float("inf"):
        peg = v["peg"]
        peg_talk = "PEG < 1, 便宜区" if peg < 1 else ("PEG 1~1.5, 合理" if peg < 1.5 else "PEG > 1.5, 偏贵")
        L.append(f"- **PEG {peg}** — {peg_talk}")
    if v.get("digest_years") and v["digest_years"] > 0:
        d = v["digest_years"]
        d_talk = "2 年内消化完 (便宜)" if d < 2 else ("2~4 年 (合理)" if d < 4 else "4 年以上 (太贵)")
        L.append(f"- **PE 消化年数 {d}** — {d_talk}")
    if v.get("analyst_count"):
        cnt = v["analyst_count"]
        cov_talk = "覆盖足够" if cnt >= 5 else "覆盖较少, 预期可能不准"
        L.append(f"- **机构覆盖 {cnt} 家** — {cov_talk}")
    L.append(_src_foot("估值一致预期", metas.get("估值一致预期")))
    L.append("")

    # --- 机构怎么看的 (V2 一致预期) ---
    if v.get("pe_fwd") or v.get("eps_cur"):
        L.append("## 🔮 机构一致预期")
        L += [
            "",
            "| 指标 | 值 | 说明 |",
            "|------|-----|------|",
            f"| 覆盖机构 | {v.get('analyst_count',0)} 家 | {'≥5 家才算靠谱' if (v.get('analyst_count') or 0) >= 5 else '<5 家预期不太准'} |",
            f"| 当年 EPS 预期 | {_fnum(v.get('eps_cur'),3)} | 2026 年赚多少 |",
            f"| 次年 EPS 预期 | {_fnum(v.get('eps_next'),3)} | 2027 年赚多少 |",
            f"| 预期增速 | {v.get('cagr_pct','—')}% | {'≥30% 是高增长' if (v.get('cagr_pct') or 0) >= 30 else '<30% 是普通增长'} |",
            f"| 前向 PE | {v.get('pe_fwd','—')} | 用明年预期利润算 |",
            f"| PEG | {v.get('peg','—')} | 越低越便宜 |",
            "",
        ]
        L.append(_src_foot("估值一致预期", metas.get("估值一致预期")))
        L.append("")

    # --- 估值历史分位 (V2) ---
    vh = r.get("valuation_hist") or {}
    if isinstance(vh, dict) and "error" not in vh:
        L.append("## 📈 过去 3 年估值在啥位置")
        L += [
            "",
            "| 指标 | 当前 | 3 年分位 | 历史区间 | 解读 |",
            "|------|------|---------|---------|------|",
            f"| PE(TTM) | {_fnum(vh.get('current_pe'))} | {_fnum(vh.get('pe_percentile_3y'),1)}% | "
            f"{_fnum(vh.get('pe_min'))} ~ {_fnum(vh.get('pe_max'))} | "
            f"{v2._interpret_pctile(vh.get('pe_percentile_3y'))} |",
            f"| PB(MRQ) | {_fnum(vh.get('current_pb'))} | {_fnum(vh.get('pb_percentile_3y'),1)}% | - | - |",
            f"| 区间 | {vh.get('data_start','—')} ~ {vh.get('data_end','—')} | 样本 {vh.get('n_days','—')} 日 | - | - |",
            "",
        ]
        L.append(_src_foot("估值历史分位", metas.get("估值历史分位")))
        L.append("")

    # --- 筹码 (V2 人话 + 明细) ---
    cd = r.get("chip_data")
    chips_talks = v2._interpret_chips(cd)
    if chips_talks:
        L.append("## 🎰 主力和散户的筹码状态")
        for t in chips_talks:
            L.append(f"- {t}")
        L.append("")
    if cd and isinstance(cd, dict) and "error" not in cd:
        L.append("### 🎰 筹码分布明细")
        L += [
            "",
            "| 指标 | 值 | 解释 |",
            "|------|-----|------|",
            f"| 获利比例 | {cd['profit_ratio']*100:.2f}% | 现价之下持仓占比 |",
            f"| 平均成本 | {cd['avg_cost']:.2f} | 所有人持仓的平均价格 |",
            f"| 90% 成本区间 | {cd['cost_90'][0]:.2f} ~ {cd['cost_90'][1]:.2f} | 5%~95% 分位的持仓价 |",
            f"| 70% 成本区间 | {cd['cost_70'][0]:.2f} ~ {cd['cost_70'][1]:.2f} | 15%~85% 分位的持仓价 |",
            f"| 90% 集中度 | {cd['concentration_90']*100:.2f}% | <20% 算很集中 |",
            f"| 70% 集中度 | {cd['concentration_70']*100:.2f}% | - |",
            f"| 筹码峰 | {cd['peak_price']:.2f} 元 | 最密集的持仓价位 |",
            f"| 数据窗口 | {cd.get('window_start','—')} ~ {cd.get('window_end','—')} "
            f"({cd.get('n_days','—')} 交易日) | 累计换手 {_fnum(cd.get('total_turnover_pct'),1)}% |",
            "",
        ]
        L.append(_src_foot("筹码K线", metas.get("筹码K线")))
        L.append("")

    # --- 实时行情 (V2) ---
    L.append("## 📊 实时行情")
    L += [
        "",
        "| 字段 | 值 |",
        "|------|-----|",
        f"| 价格 | {price:.2f} 元 ({change_pct:+.2f}%) |",
        f"| 涨跌停价 | {q.get('limit_up',0):.2f} / {q.get('limit_down',0):.2f} |",
        f"| 振幅 | {q.get('amplitude',0):.2f}% |",
        f"| 换手 | {q.get('turnover_rate',0):.2f}% |",
        f"| 量比 | {q.get('vol_ratio',0):.2f} |",
        f"| 流通市值 | {q.get('float_mcap',0):.2f} 亿 |",
        "",
    ]
    L.append(_src_foot("行情", metas.get("行情")))
    L.append("")

    # --- 概念板块 + 当日资金流 ---
    blocks = r.get("blocks") or []
    okb = [b for b in blocks if isinstance(b, dict) and "error" not in b]
    L.append("## 🧲 概念板块归属")
    if okb:
        up_n = sum(1 for b in okb if (_num_or_none(b.get("change_pct")) or 0) > 0)
        L.append(f"- 共 {len(okb)} 个概念板块, 其中 {up_n} 个上涨: "
                 + "、".join(_clean(b.get("name"), 16) for b in okb[:14]))
    else:
        L.append("> ⚠️ 概念板块: 东财 slist 返回 0 条(可能风控), 情绪因子按无热门概念计, "
                 "详见文末链路记录")
    L.append(_src_foot("概念板块", metas.get("概念板块")))
    L.append("")
    fd = r.get("fund") or {}
    L.append("## 💸 当日资金流 (分钟级)")
    if isinstance(fd, dict) and "error" not in fd and fd.get("summary"):
        sm = fd["summary"]
        L.append(f"- 全天主力净额 **{_fnum(sm.get('total_main_yi'),3)} 亿** ｜ "
                 f"近30分钟 {_fnum(sm.get('recent_main_yi'),3)} 亿 ｜ 趋势: {sm.get('trend','—')} "
                 f"｜ 采样 {sm.get('n_points','—')} 点")
    else:
        why = (fd.get("error") if isinstance(fd, dict) else None) or \
            "当日无成交或分钟数据"
        L.append(f"> ⚠️ 当日资金流不可用: {_clean(why, 90)} (资金因子按中性计, 详见文末链路记录)")
    L.append(_src_foot("当日资金流", metas.get("当日资金流")))
    L.append("")

    # --- 申万行业 (V2) ---
    sw = r.get("sw_data")
    if isinstance(sw, dict) and "error" not in sw:
        n = sw.get("n_changes", 0)
        median = sw.get("median_changes", 0)
        sw_talk = "很稳定" if n <= 2 else ("稳定" if n <= median else "行业换过几次")
        L.append("## 🏭 申万行业分类")
        L += [
            "",
            f"- 当前一级行业代码: **{sw.get('current_l1','?')}** / 二级 {sw.get('current_l2','?')} "
            f"(自 {sw.get('since','?')} 起)",
            f"- 历史变更 {n} 次 (中位数 {median}) — {sw_talk}",
            f"- {'⚠️ 行业换得太多, 历史数据可能有偏差' if sw.get('is_churning') else '行业分类稳定, 历史数据可用性高'}",
            "",
        ]
        L.append(_src_foot("申万分类", metas.get("申万分类")))
        L.append("")

    # --- 龙虎榜 ---
    dr = r.get("dragon") or {}
    if isinstance(dr, dict) and "error" not in dr:
        L.append("## 🐉 龙虎榜 (近 30 日)")
        if dr.get("records"):
            L += ["", "| 日期 | 上榜原因 | 净买入(万) | 换手% |",
                  "|------|----------|-----------|-------|"]
            for x in dr["records"][:8]:
                L.append(f"| {x.get('date','—')} | {_clean(x.get('reason'),30)} | "
                         f"{_fnum(x.get('net_buy_wan'),1)} | {_fnum(x.get('turnover_pct'))} |")
        else:
            L += ["", "- 近 30 日未上龙虎榜", ""]
        L.append(_src_foot("龙虎榜", metas.get("龙虎榜")))
        L.append("")

    # --- 宏观底色 ---
    macro = r.get("macro") or {}
    if isinstance(macro, dict):
        L.append("## 🌏 宏观底色 (全市场)")
        # 债 3 修法 (Task 5.3): 读 macro.north_label 替代 hardcode,
        # 杜绝"全市场北向"被误读为"个股北向" (370 亿 vs 102 亿流通市值的真实问题)。
        # north_label 由 analyze_single_v3 注入 (_classify_north_scope 推断), 含 scope 关键词。
        _north_label = macro.get("north_label")
        if _north_label:
            L.append(f"- {_north_label}")
        inds = macro.get("industries") or []
        if inds:
            L.append("- 领涨行业: " + "、".join(
                f"{_clean(i.get('name'),10)}({i.get('change_pct','?')}%)" for i in inds[:5]))
        tags = macro.get("hot_tags") or []
        if tags:
            L.append("- 强势股题材词频: " + " | ".join(f"{t}({c})" for t, c in tags[:6]))
        if not (_north_label or inds or tags):
            L.append("- (北向/行业/强势股全部为空)")
        L.append(_src_foot("宏观底色", metas.get("宏观底色")))
        L.append("")

    # --- 因子明细 (V2) ---
    L.append("## 🔬 10 因子打分明细")
    L += [
        "",
        "| 因子 | 得分 | 满分 |",
        "|------|------|------|",
        f"| 趋势 | {s['trend']} | 12 |",
        f"| 估值 | {s['valuation']} | 15 |",
        f"| 估值分位 | {s['valuation_pctile']} | 8 |",
        f"| 资金 | {s['capital']} | 15 |",
        f"| 动量 | {s['momentum']} | 8 |",
        f"| 情绪 | {s['sentiment']} | 8 |",
        f"| 风险 | {s['risk']} | 10 |",
        f"| 筹码 | {s['chip']} | 8 |",
        f"| 申万稳定 | {s['sw_stability']} | 6 |",
        f"| 龙虎榜 | {s['dragon']} | 10 |",
        f"| **综合** | **{s['total']}** | **100** |",
        "",
    ]
    if s.get("factors"):
        L.append("因子明细备注:")
        for f_ in s["factors"]:
            L.append(f"- {f_}")
        L.append("")

    # --- 三种情景 (V2) ---
    if plan:
        L.append("## 🎲 如果接下来…")
        L += [
            "",
            f"**…涨到 {plan['tp1']:.2f} (+10%)**：卖 1/2 仓锁利, 留 1/2 看 {plan['tp2']:.2f}",
            "",
            f"**…横盘不动**：观察一周, 若横在 {plan['entry_low']:.2f}~{price:.2f} 区间不破 "
            f"{plan['stop_loss']:.2f} 就按计划持有; 跌破止损线必走",
            "",
            f"**…跌到 {plan['stop_loss']:.2f}**：必走, 不留恋。可能原因: 大盘崩、个股利空、行业被砍",
            "",
        ]

    # ================= 链路运行记录 =================
    L.append("## 🔗 数据链路与运行记录")
    L.append("")
    L.append("| # | 数据类 | 状态 |")
    L.append("|---|--------|------|")
    for i, (lab, st) in enumerate((rl.get("sources") or {}).items(), 1):
        L.append(f"| {i} | {lab} | {st} |")
    L.append("")
    gd = rl.get("guard") or {}
    L.append(f"- guard.status: {gd.get('status','—')}")
    L.append(f"- guard.kline_freshness: {gd.get('kline_freshness','—')}")
    fc = rl.get("fallback_chain") or []
    if fc:
        L.append("- fallback_chain:")
        for f_ in fc:
            L.append(f"  - {f_}")
    L.append(f"- 总耗时: {rl.get('total_sec','—')}s ｜ 起 {rl.get('started_at','—')} "
             f"→ 止 {rl.get('finished_at','—')}")
    L.append("")

    L += [
        "---",
        "",
        "⚠️ 免责声明: 本报告基于公开数据的多因子量化模型生成, 不构成投资建议。"
        f" 数据时点 {now}, 市场随时变化, 请独立判断。",
        "",
    ]
    return "\n".join(L)


# ============================================================
# CLI
# ============================================================
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法: python quant_analyzer_v3.py <code> [name]")
        return 1
    code = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) >= 3 else ""
    r = analyze_single_v3(code, name)
    if "error" in r:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
