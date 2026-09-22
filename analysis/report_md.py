#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告 Markdown 渲染层 (P2-A Phase 5 Task 5.1, 2026-09-13)
========================================================

从 quant_analyzer_v3.py 抽离 (P0/P1 规范整改 v0.16 之后):
- 3 个报告辅助: _next_report_window / _sentiment_line / _src_foot
- 1 个主函数: write_markdown_report_v3 (r: dict) -> str

业务口径不变 (§1 '不修改业务口径'):
- 5 状态机 (35/45/55/65 阈值) 来自 analysis.trading_plan
- 三价位 (支撑/压力/止损) 命名来自 analysis.three_levels (P0-A 统一)
- 4 fetcher (公告/财务/研报/新闻) status 走 analysis.fetcher_contract
- 6 件套 (md/json/log/html/docx/pdf) status 暴露 (§2 数据契约)

依赖:
- analysis.utils: _clean, _fnum, _fpct, _finance_talk, _num_or_none,
                  _short_iso, _format_peg_talk, _json_default
- analysis.constants: _SRC_DESC, OPERATION_TEMPLATES, _STATE_DISPLAY, _NEW_IMPORTS
- analysis.trading_plan: _score_to_state
- quant_analyzer_v2: _interpret_pe / _interpret_pctile / _interpret_chips (兜底复用)

向 v3 兼容:
- v3 顶部 from analysis.report_md import write_markdown_report_v3 透传
- 老调用 quant_analyzer_v3.write_markdown_report_v3(r) 仍能拿到 (v3 顶部 re-export)
"""

import os
import re as _re
import sys
from datetime import date, datetime
from typing import Optional

# 兄弟目录加 sys.path (与 v3 line 69-71 同步, 让 quant_analyzer_v2 裸 import 可解析)
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# 兄弟模块 (§1 业务口径, 阈值/模板不动)
# V2 同源复用 (只读引用, 不修改 v2)
import quant_analyzer_v2 as v2  # noqa: E402

# Section Registry (P1 §10.1, 5 sections 渲染循环, 与 v3 line 108 一致)
from sections import enabled_sections  # noqa: E402

from analysis.constants import (  # noqa: E402  # sys.path 兄弟目录引导
    _SRC_DESC,
    _STATE_DISPLAY,
)
from analysis.fetcher_dispatcher import _NEW_IMPORTS  # noqa: E402  # sys.path 兄弟目录引导
from analysis.trading_plan import _score_to_state  # noqa: E402  # sys.path 兄弟目录引导
from analysis.utils import (  # noqa: E402  # sys.path 兄弟目录引导
    _clean,
    _finance_talk,
    _fnum,
    _format_peg_talk,
    _fpct,
    _num_or_none,
    _short_iso,
)


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
# 痛 7 修法 (报告质量债 2.0 批次 C, 2026-09-14): 5 维评分构成渲染
# ============================================================
# 简版 + 完整版 共用的 5 维聚合数据来源: r["scoring_breakdown"]
# (由 analysis.pipeline._build_scoring_breakdown 注入, 10 维 → 5 维聚合)
# 5 维: 技术/资金/估值/情绪/风险, 总分 100, 让综合评分不再是黑盒
# 兜底: 缺字段 (旧 result JSON) → "评分构成数据缺失" 降级占位
# ============================================================
_BREAKDOWN_KEYS = ("tech", "capital", "valuation", "sentiment", "risk")  # 渲染顺序固定

# 5 维渲染顺序 → 中文 label (复用 breakdown 里的 label, 这里也备一份兜底)
_BREAKDOWN_LABELS = {
    "tech": "技术", "capital": "资金", "valuation": "估值",
    "sentiment": "情绪", "risk": "风险",
}

# 子维 (10 维) → 中文 label (用于"包含的 10 维子项"列)
_BREAKDOWN_DIM_LABELS = {
    "trend": "趋势", "valuation": "估值", "valuation_pctile": "估值分位",
    "capital": "资金", "momentum": "动量", "sentiment": "情绪",
    "risk": "风险", "chip": "筹码", "sw_stability": "申万稳定", "dragon": "龙虎榜",
}


def _scoring_breakdown_summary(breakdown: dict) -> dict:
    """从 breakdown 读 5 维聚合, 返回渲染所需的 list + 兜底缺失提示。

    Returns:
        {
            "ok": True,  # 是否成功读出 breakdown
            "rows": [{"key": "tech", "label": "技术", "score": 6, "max": 28, "pct": 21.4, "dims": {...}}, ...],
            "total": {"score": 34, "max": 100, "pct": 34.0},
        }
        或 {"ok": False} — 兜底占位用
    """
    if not isinstance(breakdown, dict) or "total" not in breakdown:
        return {"ok": False}
    rows = []
    for k in _BREAKDOWN_KEYS:
        d = breakdown.get(k) or {}
        if not isinstance(d, dict) or "score" not in d or "max" not in d:
            return {"ok": False}
        rows.append({
            "key": k,
            "label": d.get("label") or _BREAKDOWN_LABELS[k],
            "score": d["score"],
            "max": d["max"],
            "pct": d.get("pct", 0),
            "dims": d.get("dims") or {},
        })
    return {"ok": True, "rows": rows, "total": breakdown["total"]}


def _scoring_breakdown_md_compact(breakdown: dict) -> list:
    """简版"📊 评分构成"区: 一行汇总 + 5 维一行展开 (口袋版, 不进 markdown 完整块)。

    位置: 30 秒决策卡下方, 三价位之前 (在 L.append("## 🎯 30 秒决策卡") 之后插入)
    输出格式:
        ## 📊 评分构成 (简版)
        > **技术 6/28 + 资金 10/25 + 估值 10/29 + 情绪 3/8 + 风险 4/10 = 综合 34/100**
        > 颜色提示: 🟢 ≥70%  黄 40-70%  🔴 <40% (技术 21%🔴 资金 40%黄 ...)
    """
    L: list = []
    info = _scoring_breakdown_summary(breakdown)
    if not info["ok"]:
        # 兜底: 旧 result JSON 没 scoring_breakdown 字段
        L.append("## 📊 评分构成")
        L.append("")
        L.append("> ⚠️ **评分构成数据缺失** (老 result JSON, 批次 C 之前生成; "
                 "请重跑 V3 重新生成)。综合评分仍可见, 但 5 维拆解暂不可用。")
        L.append("")
        return L
    L.append("## 📊 评分构成")
    L.append("")
    # 5 维一行汇总
    parts = [f"**{r['label']} {r['score']}/{r['max']}**" for r in info["rows"]]
    t = info["total"]
    L.append("> " + " + ".join(parts) + f" = **综合 {t['score']}/{t['max']}**")
    L.append("")
    # 颜色提示: 按 pct 给每维打 emoji
    def _pct_emoji(p):
        if p >= 70:
            return "🟢"
        if p >= 40:
            return "🟡"
        return "🔴"
    color_parts = [f"{_pct_emoji(r['pct'])} {r['label']} {r['pct']:.0f}%"
                  for r in info["rows"]]
    L.append("> 占比提示: " + " ｜ ".join(color_parts))
    L.append("")
    return L


def _scoring_breakdown_md_full(breakdown: dict) -> list:
    """完整版"📊 评分构成"区: 详细表 (5 行 + 子维展开)。

    位置: 完整版 6 块之后, "10 因子打分明细" 之前 (与 HTML "5 维进度条卡片" 对齐)
    输出格式:
        ## 📊 评分构成 (5 维拆解, 满分 100)
        | 维度 | 得分 | 满分 | 占比 | 包含的 10 维子项 |
        |------|------|------|------|----------------|
        | 🟡 技术 | 6 | 28 | 21.4% | 趋势 1 + 动量 1 + 筹码 4 |
        ...
    """
    L: list = []
    info = _scoring_breakdown_summary(breakdown)
    if not info["ok"]:
        L.append("## 📊 评分构成 (5 维拆解)")
        L.append("")
        L.append("> ⚠️ **评分构成数据缺失** (老 result JSON, 批次 C 之前生成; "
                 "请重跑 V3 重新生成)。")
        L.append("")
        return L
    L.append("## 📊 评分构成 (5 维拆解, 满分 100)")
    L.append("")

    def _pct_emoji(p):
        if p >= 70:
            return "🟢"
        if p >= 40:
            return "🟡"
        return "🔴"

    L += [
        "| 维度 | 得分 | 满分 | 占比 | 包含的 10 维子项 |",
        "|------|------|------|------|------------------|",
    ]
    for r in info["rows"]:
        # 子维展开: "趋势 1 + 动量 1 + 筹码 4" 形式; 缺失子维标 "—"
        dim_parts = []
        for d_key, d_val in r["dims"].items():
            d_lab = _BREAKDOWN_DIM_LABELS.get(d_key, d_key)
            if d_val is None:
                dim_parts.append(f"{d_lab} —(缺失按 50% 中性)")
            else:
                dim_parts.append(f"{d_lab} {d_val}")
        dims_str = " + ".join(dim_parts)
        L.append(f"| {_pct_emoji(r['pct'])} **{r['label']}** "
                 f"| **{r['score']}** | {r['max']} | {r['pct']:.1f}% | {dims_str} |")
    t = info["total"]
    L.append(f"| **综合** | **{t['score']}** | **{t['max']}** | "
             f"**{t.get('pct', 0):.1f}%** | 5 维之和 |")
    L.append("")
    L.append("> 📐 **维度定义** (5 维聚合规则, 与 v2 10 维口径一致):")
    L.append("> • **技术** = 趋势 + 动量 + 筹码 (max 28)")
    L.append("> • **资金** = 资金流 + 龙虎榜 (max 25)")
    L.append("> • **估值** = 估值 + 估值分位 + 申万稳定 (max 29)")
    L.append("> • **情绪** = 概念/北向情绪 (max 8)")
    L.append("> • **风险** = 市值/PE/解禁 (max 10)")
    L.append("")
    return L


# ============================================================
# 痛 6 修法 (报告质量债 2.0 批次 A): ISO 时间戳 → 股民易读格式
# ============================================================
# 输入: ISO 时间字符串如 "2026-09-13T21:50:09+08:00"
# 输出: "2026-09-13（周日）21:50" (中文括号 + 24h 时间)
# 失败时降级回原 ISO 字符串 (不崩, 保证 docx/html 链路过)
_WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_FMT_GEN_TIME_RE = _re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2})?$"
)


def fmt_gen_time(iso_str: str) -> str:
    """ISO 时间戳 → 2026-09-13（周日）21:50 格式 (痛 6 修法, 批次 A)。"""
    if not iso_str:
        return iso_str or ""
    s = str(iso_str).strip()
    m = _FMT_GEN_TIME_RE.match(s)
    if not m:
        return s  # 降级: 解析失败回原值
    y, mo, d, hh, mi = m.groups()
    try:
        wd = date(int(y), int(mo), int(d)).weekday()  # 0=周一 6=周日
        return f"{y}-{mo}-{d}（{_WEEK_CN[wd]}）{hh}:{mi}"
    except Exception:  # noqa: BLE001
        return s  # 降级: 日期无效回原值


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

    # 决策状态 — 5 状态机 (债 1 修法, Task 5.1)；优先读 plan["state_after_pe_bypass"]（批次 E 痛 3 旁路后），
    # 兜底 plan["state"]（原始）, 兜底 _score_to_state()。
    # 批次 E 痛 3: PE 分位 > 85% 时, plan["state"] 会被压低到 plan["state_after_pe_bypass"]
    if plan and plan.get("state_after_pe_bypass"):
        state_key = plan["state_after_pe_bypass"]
        state, state_icon = _STATE_DISPLAY.get(state_key, ("中性", "🟡"))
    elif plan and plan.get("state"):
        state_key = plan["state"]
        state, state_icon = _STATE_DISPLAY.get(state_key, ("中性", "🟡"))
    else:
        state_key = _score_to_state(score_total)
        state, state_icon = _STATE_DISPLAY.get(state_key, ("中性", "🟡"))

    # 三价位 (债2显式三价位 + 债4 同源声明) — 现由 tl3 段直接取 plan 字段

    L: list = []

    # ================= 第一屏: 决策结论 =================
    L.append(f"# {name} ({code}) — V3 决策报告")
    L.append("")

    # ================= §7 报告首页: 分析时点 + 关键缺失 (§7 P1-B 整改, 2026-09-11) =================
    # 规范 §7: "报告首页必须展示分析时点、关键缺失数据及其对结论的影响"
    # 来源: run_log.sources (本轮 run 的源状态) + run_log.tls_recommendations (TLS 修复建议)
    rl = r.get("run_log") or {}
    src_status = rl.get("sources") or {}
    # 关键源 (缺失会影响核心结论) vs 增量源
    KEY_SRCS = ["行情", "估值一致预期", "概念板块", "K线筹码", "估值历史分位", "解禁日历", "申万分类"]
    INCR_SRCS = ["龙虎榜", "宏观底色", "当日资金流", "资金面-5日主力", "融资融券", "公告", "财务摘要", "研报观点", "新闻舆情"]
    failed_key = [(k, src_status.get(k, "—")) for k in KEY_SRCS if "error" in str(src_status.get(k, "ok"))]
    failed_incr = [(k, src_status.get(k, "—")) for k in INCR_SRCS if "error" in str(src_status.get(k, "ok"))]
    gen_time = rl.get("finished_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    gen_time = fmt_gen_time(gen_time)  # 痛 6: ISO → "2026-09-13（周日）21:50"
    guard = rl.get("guard") or {}
    kf = guard.get("kline_freshness")
    # kf 可能是 dict (旧) 或 str (新); 提取 last_bar
    if isinstance(kf, dict):
        last_bar = kf.get("last_bar")
    elif isinstance(kf, str):
        import re as _re
        m = _re.search(r"last_bar=(\d{4}-\d{2}-\d{2})", kf)
        last_bar = m.group(1) if m else None
    else:
        last_bar = None
    L += [
        f"> 📅 **分析时点**: 报告生成 {gen_time}",
        f"> 🕯 **K线最后交易日**: {last_bar or '—'} (现价取腾讯实时, 已是最新)",
        f"> 📡 **数据源健康度**: 关键源 {len(KEY_SRCS) - len(failed_key)}/{len(KEY_SRCS)} 活, "
        f"增量源 {len(INCR_SRCS) - len(failed_incr)}/{len(INCR_SRCS)} 活",
    ]
    # 关键缺失 + 对结论影响
    if failed_key:
        L.append(">")
        L.append("> ⚠️ **关键缺失** (影响核心结论):")
        for k, st in failed_key[:5]:
            impact = {
                "行情": "现价/PE/PB/市值缺失, 报告无法继续",
                "估值一致预期": "PE/PEG 估值因子按中性计, 估值分位缺",
                "概念板块": "情绪/板块轮动因子按中性计",
                "K线筹码": "三价位/均线/布林/支撑/压力全部缺, 改用 trading_plan 默认值",
                "估值历史分位": "PE/PB 3年分位缺失, 估值高低判断缺历史锚",
                "解禁日历": "风险表'解禁压力'段标'数据源暂缺'",
                "申万分类": "申万行业因子按 v2 默认中性计, 行业稳定性不评估",
            }.get(k, "对结论影响请见各章节备注")
            L.append(f">   • **{k}**: {st[:60]}  →  {impact}")
    if failed_incr:
        L.append(">")
        L.append("> ℹ️ **增量缺失** (次要章节降级, 核心结论不受影响):")
        for k, st in failed_incr[:5]:
            L.append(f">   • **{k}**: {st[:60]}")
    # TLS 修复建议
    tls_recs = rl.get("tls_recommendations") or []
    if tls_recs:
        L.append(">")
        L.append("> 🔒 **TLS 修复建议** (§5):")
        for r0 in tls_recs:
            L.append(f">   • `{r0.get('host','—')}`: {r0.get('fix','—')}  (影响: {', '.join(r0.get('applies_to', []))})")
    L.append("")

    L.append("## 🎯 30 秒决策卡")
    L.append("")
    # 综合判定行 (block + 强语气)
    L.append(f"> **{r['emoji']} {r['advice']}** ｜ 多空三态: **{state_icon} {state}** ｜ "
             f"综合评分 **{score_total}/100** ｜ 一句话: **{r.get('detail','')}**")
    # 批次 E 痛 3: PE 旁路提示 (PE 分位 > 85% 时, 显示原状态 → 旁路后)
    pe_pctile_val = (plan or {}).get("valuation_pctile") if plan else None
    if pe_pctile_val is not None and pe_pctile_val > 85:
        original_state_key = (plan or {}).get("state", "—")
        original_state_label = _STATE_DISPLAY.get(original_state_key, ("—", ""))[0]
        bypassed_label = state  # state 已经是旁路后
        changed = (original_state_key != state_key)
        if changed:
            L.append(
                f"> ⚠️ **PE 估值旁路 (批次 E 痛 3)**: PE 分位 {pe_pctile_val:.1f}% > 85%, "
                f"原状态 `{original_state_key}` ({original_state_label}) → 强切到 `{state_key}` ({bypassed_label})"
            )
        else:
            L.append(
                f"> ⚠️ **PE 估值偏高 (批次 E 痛 3 提示)**: PE 分位 {pe_pctile_val:.1f}% > 85%, "
                f"原状态已是 `{state_key}` ({bypassed_label}) (旁路无变化), 但操作仍按 PE 高估处理 — 严格止损, 不建议加仓"
            )
    L.append("")
    # 核心指标 7 列大表 (1 屏读完所有核心数据)
    vh = r.get("valuation_hist") or {}
    pe_pct = vh.get("pe_percentile_3y")
    val = r.get("valuation") or {}
    peg_val = val.get("peg")
    change_sign = "+" if change_pct >= 0 else ""
    # PEG 4 档阈值 (Task 5.5): <1 便宜 / 1-1.5 合理 / 1.5-3 偏贵 / >=3 极贵
    if peg_val is not None and peg_val != float("inf"):
        if peg_val < 1:
            peg_label = "便宜"
        elif peg_val < 1.5:
            peg_label = "合理"
        elif peg_val < 3:
            peg_label = "偏贵"
        else:
            peg_label = "极贵"
        peg_str = f"{peg_val:.2f} ({peg_label})"
    else:
        peg_str = "—"
    L += [
        "| 💰 现价 | 📊 涨跌 | 🏭 流通市值 | 📈 PE(TTM) | 📉 PB | 📊 PE 分位(3年) | 🎯 PEG |",
        "|----------|---------|-------------|-------------|------|------------------|------|",
        f"| **{price:.2f} 元** | {change_sign}{change_pct:.2f}% | {q.get('float_mcap',0):.1f} 亿 "
        f"| {q.get('pe_ttm',0):.1f} | {q.get('pb',0):.2f} "
        f"| {(pe_pct if pe_pct is not None else 0):.1f}% | {peg_str} |",
        "",
    ]
    # ================= 痛 7 (报告质量债 2.0 批次 C, 2026-09-14): 评分构成 简版 =================
    # 位置: 30 秒决策卡 7 列大表后, 三价位前 (简版唯一暴露位置, 一行汇总 + 占比)
    L += _scoring_breakdown_md_compact(r.get("scoring_breakdown"))

    # 三价位 4 行大表 (支撑/压力/止损/现价, emoji 颜色)
    # 批次 E 痛 1 修法 (2026-09-14): 操作位 (3 候选距现价 5-25% 最近) + 参考位 (60 日极值) 分行显示
    L.append("### 🎯 三价位（V2 同源实时模型 · 远/近期位分层）")
    L.append("")
    L.append("> 📐 **命名约定** (P0-A 规范整改 v1.0 + 批次 E 痛 1, 2026-09-14): "
             "操作位 = 3 候选(ma60/chip_peak/boll) 距现价 5-25% 范围最近; "
             "参考位 = 60 日最低/最高 (远端极值, 不筛选, 仅供参考, 不是操作位)。"
             "完整规则: `analysis/references/three-levels-rules.md`")
    L.append("")
    if plan:
        tl3 = r.get("three_levels") or {}
        tl_sup = tl3.get("support")
        tl_res = tl3.get("resistance")
        tl_sl = tl3.get("stop_loss") or plan.get("stop_loss")
        sup_cands = tl3.get("support_candidates") or {}
        res_cands = tl3.get("resistance_candidates") or {}
        # 批次 E 痛 1: 操作位/参考位字段
        sup_op_key = tl3.get("support_op_key", "—")
        res_op_key = tl3.get("resistance_op_key", "—")
        sup_extreme = tl3.get("support_extreme")
        res_extreme = tl3.get("resistance_extreme")
        sup_extreme_label = tl3.get("support_extreme_label", "60日最低")
        res_extreme_label = tl3.get("resistance_extreme_label", "60日最高")
        if tl_sup is not None and tl_res is not None:
            # 6 行大表: 现价 + 操作位(支撑/压力) + 参考位(支撑/压力) + 止损
            L += [
                "| 价位 | 数值 | 距现价 | 来源 / 触发动作 |",
                "|------|------|--------|---------------|",
                f"| 💰 **现价** | **{price:.2f}** | 0% (参考) | 腾讯实时行情 (报告日 {r.get('report_date','')}) |",
                f"| 🟢 **操作支撑位** | **{tl_sup:.2f}** | {(tl_sup-price)/price*100:+.1f}% | "
                f"3 候选(ma60/chip_peak/boll) 距现价 5-25% 范围最近 · 当前来源: `{sup_op_key}` |",
                f"| 🔴 **操作压力位** | **{tl_res:.2f}** | {(tl_res-price)/price*100:+.1f}% | "
                f"3 候选(ma250/boll_upper/recent_high) 距现价 5-25% 范围最近 · 当前来源: `{res_op_key}` |",
                f"| 📌 **参考支撑位** ({sup_extreme_label}) | **{sup_extreme:.2f}** | {(sup_extreme-price)/price*100:+.1f}% | "
                f"远端极值, 不作为操作依据 (仅作'如果跌穿 X 形态破位'的参考线) |" if sup_extreme else "| 📌 参考支撑位 | — | — | 60日数据不足 |",
                f"| 📌 **参考压力位** ({res_extreme_label}) | **{res_extreme:.2f}** | {(res_extreme-price)/price*100:+.1f}% | "
                f"远端极值, 不作为操作依据 (仅作'如果涨穿 X 形态突破'的参考线) |" if res_extreme else "| 📌 参考压力位 | — | — | 60日数据不足 |",
                f"| 🟡 **止损位** | **{tl_sl:.2f}** | {(tl_sl-price)/price*100:+.1f}% | "
                f"{'复用 trading_plan.stop_loss' if tl3.get('stop_loss_method') == 'trading_plan' else '强切到 支撑×0.97 (防 V2 止损过紧倒挂)'} · 5 状态机锁定 · 跌破必走 |",
                "",
            ]
            # 候选明细 (次要信息, blockquote 折叠)
            if sup_cands:
                sup_str = " / ".join(f"{k}={v:.2f}" for k, v in sup_cands.items())
                L.append(f"> 📋 **4 支撑候选**: {sup_str}")
            if res_cands:
                res_str = " / ".join(f"{k}={v:.2f}" for k, v in res_cands.items())
                L.append(f"> 📋 **3 压力候选**: {res_str}")
            L.append("")
            L.append("### 💰 操作口诀（5 状态机）")
            L.append("")
            # 三段式: 结论 + 操作 + 风险
            template = plan.get("template_used", "")
            if template:
                # 拆 template_used 三段
                for seg in template.split("｜"):
                    seg = seg.strip()
                    if seg:
                        L.append(f"> {seg}")
                L.append("")
            # 多目标价
            L += [
                f"> 📊 **多目标价**: 短 {plan['tp1']:.2f} / 中 {plan['tp2']:.2f} / 远 {plan['tp3']:.2f} 元",
                f"> 🎯 **买入区间**: {plan['entry_low']:.2f}~{plan['entry_high']:.2f} 元 (分批上限 {plan['entry_high']:.2f})",
                "> ⏱ **周期**: 短线 1-2 周",
                "",
            ]
            L.append("> 🔒 **数据可信度**: 三价位由 V2 同源实时模型推导 (腾讯实时行情 + baostock 前复权筹码K线)，"
                     "**未使用任何池 CSV 陈旧价** (债4)。")
        else:
            L.append("> ⚠️ 三价位无法生成 (行情/筹码数据缺失), 请勿据此操作。")
        L.append("")
    else:
        L.append("> ⚠️ 三价位无法生成 (行情/筹码数据缺失), 请勿据此操作。")
        L.append("")

    # ================= 风险警报区 (5-7 行大表, 债 5 修法, Task 7.2) =================
    # 5 列: 类别 | 描述 | 严重度 | 触发条件 | 应对
    L.append("## 🚨 风险警报区")
    L.append("")
    risk_rows = []  # list[dict]: category, desc, severity, trigger, action
    # 1) 解禁
    lockup = r.get("lockup") or {}
    if isinstance(lockup, dict) and "error" not in lockup and lockup.get("upcoming"):
        for u in lockup["upcoming"][:3]:  # 最多 3 条
            ratio = u.get("ratio_pct", 0) or 0
            shares = u.get("shares_wan", 0) or 0
            severity = "🔴高" if ratio >= 5 else ("🟠中" if ratio >= 2 else "🟡低")
            risk_rows.append({
                "category": "解禁压力",
                "desc": f"{u.get('date','—')} 解禁 {shares:,.0f} 万股",
                "severity": severity,
                "trigger": f"占股本 {ratio:.2f}%" + (f" [{u.get('type','')}]" if u.get("type") else ""),
                "action": "解禁前 5 日减仓 / 解禁当日观望",
            })
    elif isinstance(lockup, dict) and "error" in lockup:
        risk_rows.append({
            "category": "解禁数据", "desc": "数据源暂缺", "severity": "🟡低",
            "trigger": lockup["error"][:30], "action": "补 fetcher 后重跑",
        })
    else:
        risk_rows.append({
            "category": "解禁压力", "desc": "未来 90 天无解禁", "severity": "🟢无",
            "trigger": "近 90 日无 upcoming 记录", "action": "无需应对",
        })
    # 2) 财报窗口
    fin = r.get("finance")
    if fin and isinstance(fin, dict) and "error" not in fin and fin.get("latest"):
        win = _next_report_window(fin["latest"].get("report_date"))
        if "临近" in win:
            risk_rows.append({
                "category": "财报窗口", "desc": win, "severity": "🔴高",
                "trigger": "距披露日 < 30 日", "action": "业绩雷风险大, 减仓/对冲",
            })
        else:
            risk_rows.append({
                "category": "财报窗口", "desc": win, "severity": "🟡低",
                "trigger": "距披露日 > 30 日", "action": "无需立即应对",
            })
    else:
        risk_rows.append({
            "category": "财报窗口", "desc": "财务摘要数据源暂缺", "severity": "🟡低",
            "trigger": "无 latest 报告期", "action": "补 fetcher 后重跑",
        })
    # 3) 估值极端
    pe, vh = q.get("pe_ttm", 0), r.get("valuation_hist") or {}
    if pe and pe > 80:
        risk_rows.append({
            "category": "估值", "desc": f"PE(TTM) {pe:.1f} 极高估, 泡沫风险",
            "severity": "🔴高",
            "trigger": f"PE(TTM) > 80; 估值分位 {_fnum(vh.get('pe_percentile_3y'),1)}%",
            "action": "减仓兑现, 不追高",
        })
    elif isinstance(vh, dict) and "error" not in vh and (vh.get("pe_percentile_3y") or 0) > 80:
        risk_rows.append({
            "category": "估值", "desc": f"PE 历史分位 {(vh.get('pe_percentile_3y') or 0):.0f}% — 接近 3 年最高",
            "severity": "🔴高",
            "trigger": "PE 分位 > 80%",
            "action": "分批减仓, 等待估值修复",
        })
    # 4) 龙虎榜大额净卖
    dragon = r.get("dragon") or {}
    if isinstance(dragon, dict) and "error" not in dragon and dragon.get("records"):
        nbs = [x.get("net_buy_wan", 0) for x in dragon["records"]]
        if nbs and sum(nbs) / len(nbs) < -1000:
            avg = sum(nbs) / len(nbs)
            risk_rows.append({
                "category": "龙虎榜", "desc": f"近 30 日平均净卖出 {avg:,.0f} 万元",
                "severity": "🟠中", "trigger": "近 30 日均净卖 > 1000 万",
                "action": "游资撤退, 谨慎追涨",
            })
    # 5) 减持公告
    anns = r.get("announcements") or {}
    for a in (anns.get("announcements") or [])[:10]:
        if not isinstance(a, dict):
            continue
        cat = str(a.get("category") or "")
        title = str(a.get("title") or "")
        if "减持" in cat or "减持" in title:
            risk_rows.append({
                "category": "减持公告", "desc": title[:40],
                "severity": "🔴高", "trigger": f"{a.get('date','—')} 公告",
                "action": "关注减持进度, 短期回避",
            })
            break
    if not risk_rows:
        risk_rows.append({
            "category": "综合", "desc": "未发现明显风险事件", "severity": "🟢无",
            "trigger": "—", "action": "正常持仓",
        })
    # 截断到 7 行
    risk_rows = risk_rows[:7]
    L += [
        "| 类别 | 描述 | 严重度 | 触发条件 | 应对 |",
        "|------|------|--------|----------|------|",
    ]
    for row in risk_rows:
        L.append(f"| {row['category']} | {row['desc']} | {row['severity']} | "
                 f"{row['trigger']} | {row['action']} |")
    L.append("")

    # ================= 操作检查清单 (5 项 checkbox, 5 状态各配 1 套, 债 5 修法, Task 7.2) =================
    L.append("## ✅ 操作检查清单")
    L.append("")
    L.append(f"> 📋 **当前状态**: {state_icon} **{state}** (评分 {score_total} 分, 状态 `{state_key}`)")
    L.append("")

    if plan:
        e_lo, e_hi = plan["entry_low"], plan["entry_high"]
        st, tp1, tp2, tp3 = plan["stop_loss"], plan["tp1"], plan["tp2"], plan["tp3"]
        # 5 状态 × 5 项 = 25 条模板; 运行时按 state_key 选 1 套
        # 5 项: 状态确认 / 买点触发 / 卖点触发 / 止损纪律 / 仓位管理
        CHECKLIST_TPL = {
            "bullish": [
                "确认多空: 评分 ≥65 + 趋势确认 + 量能配合, 5 状态机判定为多头",
                f"买点: 回调至 {e_lo:.2f}~{e_hi:.2f} 区间分批建仓 (各 1/2 仓); 放量突破 {tp1:.2f} 可加仓",
                f"卖点: 达 {tp1:.2f} 卖 1/2 锁利 → {tp2:.2f} 再减半 → {tp3:.2f} 或趋势走弱清剩余",
                f"止损: 收盘跌破 {st:.2f} (现价下 -{plan['stop_loss_pct']:.1f}%) 即离场, 不补仓摊平",
                f"仓位: {plan['position']} | 周期 {plan['period']}",
            ],
            "mild_bull": [
                "确认多空: 评分 55-64 + 趋势偏多, 5 状态机判定为轻多 (震荡偏多)",
                f"买点: 回调至 {e_lo:.2f} 附近小仓低吸 (1/3 仓); 突破 {tp1:.2f} 站稳再加 1/3",
                f"卖点: 达 {tp1:.2f} 减 1/3 锁利; 达 {tp2:.2f} 再减 1/3; 余仓看 {tp3:.2f}",
                f"止损: 收盘跌破 {st:.2f} (现价下 -{plan['stop_loss_pct']:.1f}%) 即减半; 破 {e_lo:.2f} 全走",
                f"仓位: {plan['position']} | 周期 {plan['period']} (轻多, 严控仓位)",
            ],
            "neutral": [
                "确认多空: 评分 45-54 + 多空信号混杂, 5 状态机判定为中性 (区间震荡)",
                f"买点: 仅在 {e_lo:.2f}~{e_hi:.2f} 支撑区低吸, 上轨 {tp1:.2f} 附近不过量追高",
                f"卖点: 反弹至 {tp1:.2f} 一带减仓; 跌破 {st:.2f} 转空离场; 放量站稳 {tp1:.2f} 再看多",
                f"止损: {st:.2f} 为区间底沿, 收盘破位即走, 不猜底",
                f"仓位: {plan['position']} | 以低吸高抛为主, 周期 {plan['period']}",
            ],
            "mild_bear": [
                "确认多空: 评分 35-44 + 趋势偏空, 5 状态机判定为轻空 (震荡偏空)",
                f"买点: 严控 — 仅在 {e_lo:.2f} 附近且出现放量反转 K 线小仓 (1/4 仓) 抢短; 否则不动",
                f"卖点: 已有持仓反弹至 {tp1:.2f} 一带分批减仓; 跌破 {st:.2f} 清仓; 不抢反弹",
                f"止损: {st:.2f} 上方不留幻想仓, 反弹即减, 跌穿即走",
                f"仓位: {plan['position']} | 周期 {plan['period']} (轻空, 逢反减)",
            ],
            "bearish": [
                "确认多空: 评分 <35 + 趋势空头, 5 状态机判定为空头 (下跌趋势)",
                "买点: ❌ 不买入 / 不补仓 / 不抄底; 空仓者观望等底部放量企稳信号",
                f"卖点: 反弹至压力位 {tp1:.2f} 一带分批减仓; 持仓者跌破 {st:.2f} 清仓; 不抢反弹",
                f"止损: 反弹减仓/清仓纪律优先, 止损 {st:.2f} 上方不留幻想仓",
                "仓位: 清仓回避 / 极轻仓短线者当日进出",
            ],
        }
        items = CHECKLIST_TPL.get(state_key, CHECKLIST_TPL["neutral"])
        for it in items:
            L.append(f"- [ ] {it}")
    else:
        L.append("- [ ] ⚠️ 无三价位, 检查清单不可用, 观望为主")
    L.append("")

    # ================= 痛 8 (报告质量债 2.0 批次 A): 简版(口袋版) vs 完整版 =================
    # 默认: 简版 — 30秒决策卡 + 三价位 + 操作口诀 + 风险警报 = "口袋版" (看完即决策)
    # 开关: r.get("_md_full", False) 触发完整版 (含 6 块 + V2 保留块 + Section Registry + 链路记录)
    # 职责分工: 完整内容进 HTML (html_report_v3.py 不动); markdown 走"看完即决策"路径
    # 注: 现有 pipeline.py:638 默认调用无 _md_full, 自动得到简版 markdown,
    #     docx 走同一份 markdown → 简版 docx 也满足"口袋版"诉求
    if not r.get("_md_full", False):
        L += [
            "---",
            "",
            "📎 **完整报告**: 研报 / 公告 / 财务 / 同业 / 资金面 / 新闻 / 筹码 / 估值历史 / 龙虎榜 / "
            "因子明细 / 数据链路 → 看 `*-v3-*.html` 报告",
            "",
            "⚠️ 免责声明: 本报告基于公开数据的多因子量化模型生成, 不构成投资建议。"
            f" 数据时点 {now}, 市场随时变化, 请独立判断。",
            "",
        ]
        return "\n".join(L)

    # ================= 6 块新内容 =================
    L.append("---")
    L.append("")
    L.append("## 📑 六维新增情报")
    L.append("")

    # --- 1. 研报观点汇总 ---
    L.append("### 📰 1. 研报观点汇总")
    L.append("")
    res = r.get("research")
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
        # 债 6 修法 (Task 7.3): 同业表 7 维 — 代码/简称/PE/PB/市值/ROE/近 5 日涨跌
        # 营收增速 (8 维) 东财 clist 行情接口无标准字段, 留 "—"
        L.append("| 代码 | 名称 | PE(TTM) | PB | 总市值(亿) | ROE(%) | 5日涨跌(%) |")
        L.append("|------|------|---------|-----|-----------|--------|-----------|")
        anchor = " ← 本票"
        for x in self_rows[:1]:
            L.append(f"| {x.get('code')} | **{_clean(x.get('name'),12)}**{anchor} | "
                     f"{_fnum(x.get('pe'),1)} | {_fnum(x.get('pb'),2)} | "
                     f"{_fnum(x.get('total_mcap_yi'),1)} | {_fnum(x.get('roe_pct'),2)} | "
                     f"{_fpct(x.get('chg_5d_pct'))} |")
        for x in show[:8]:
            L.append(f"| {x.get('code')} | {_clean(x.get('name'),12)} | "
                     f"{_fnum(x.get('pe'),1)} | {_fnum(x.get('pb'),2)} | "
                     f"{_fnum(x.get('total_mcap_yi'),1)} | {_fnum(x.get('roe_pct'),2)} | "
                     f"{_fpct(x.get('chg_5d_pct'))} |")
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

    # --- 5. 资金面 (近 5 日主力资金 + 融资余额变化 + 股价) ---
    # 债 6 修法 (Task 7.3): 5 行大表 6 列
    #   日期 | 主力净流入(亿) | 大单+超大单(亿) | 融资余额变化(亿) | 收盘价 | 当日涨跌幅
    L.append("### 💰 5. 资金面 (近 5 日主力资金 + 融资余额变化 + 股价)")
    L.append("")
    fund5 = r.get("fund_daily5")
    mh = r.get("margin_hist") or {}
    # 按日期合并融资余额变化
    mh_by_date = {}
    if isinstance(mh, dict) and mh.get("rows"):
        for mrow in mh["rows"]:
            mh_by_date[mrow.get("date", "")] = mrow.get("rzye_chg_yi")
    if fund5 and isinstance(fund5, dict) and "error" not in fund5 and fund5.get("rows"):
        L.append("| 日期 | 主力净流入(亿) | 大单+超大单(亿) | 融资余额变化(亿) | 收盘价(元) | 当日涨跌(%) |")
        L.append("|------|---------------|----------------|------------------|------------|-------------|")
        for x in fund5["rows"]:
            d = x.get("date", "—")
            rzye_chg = mh_by_date.get(d)
            rzye_chg_str = _fnum(rzye_chg, 3) if rzye_chg is not None else "—"
            close = x.get("close")
            close_str = f"{close:.2f}" if close is not None else "—"
            chg = x.get("chg_pct")
            chg_str = _fpct(chg) if chg is not None else "—"
            L.append(f"| {d} | {_fnum(x.get('main_net_yi'),3)} | "
                     f"{_fnum(x.get('large_super_yi'),3)} | "
                     f"{rzye_chg_str} | {close_str} | {chg_str} |")
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
        # D-3 修法 (Task 5.5): 4 档阈值, 对齐 report-design-principles.md:73-77
        L.append(f"- **PEG {peg}** — {_format_peg_talk(peg)}")
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
    # ================= 痛 7 (报告质量债 2.0 批次 C, 2026-09-14): 评分构成 完整版 =================
    # 位置: 10 因子打分明细之前, 给读者先看 5 维聚合, 再看 10 维明细
    L += _scoring_breakdown_md_full(r.get("scoring_breakdown"))

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

    # ---- Task 5.4 (D-2 修法): Section Registry 5 sections 渲染循环 ----
    # 对齐 HTML 渲染器 (html_report_v3.py:1370-1383) 和 DOCX 渲染器 (md_to_docx.py:538-548) pattern
    # 位置: 6 块 + 3 supplement 之后, 链路运行记录之前 (与 HTML "6 块之后, 附录之前" 对齐)
    # sec.render_md(sec_data) 返回完整 MD 片段 (含 ## 标题), 不是 dict — 与 plan 假设 .collect() 不同
    for sec in enabled_sections():
        try:
            sec_data = r.get(sec.label, {}) or {}
            sec_md = sec.render_md(sec_data)
            if sec_md:
                L.append(sec_md)
                L.append("")
        except Exception:  # noqa: BLE001
            # 单节失败不阻断其他渲染 (per-section isolation, 与 HTML/DOCX 渲染器一致)
            pass

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
