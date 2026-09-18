#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V3 编排层 (P2-A Phase 5 Task 5.2, 2026-09-13)
============================================

从 quant_analyzer_v3.py 抽离 (规范 §2 报告 + §10 配置集中):
- 6 编排辅助: _classify_north_scope / _patch_v2_timers / _restore_v2 /
               _latest_trading_day / _kline_freshness / _retry_call
- 1 主函数: analyze_single_v3 (code, name) -> dict
- 1 落盘函数: _emit (6 件套: md/json/log/html/docx/pdf)
- 1 兜底函数: _dump_run_log (失败中止时也落 run_log)

业务口径不变 (§1 '不修改业务口径'):
- 10 数据类 (V2 内嵌) + 4 追加 fetcher (公告/财务/研报/新闻) + 融资融券
- 三价位 (支撑下沿/压力上沿) 来自 analysis.three_levels (P0-A 命名)
- 5 状态机 (35/45/55/65 阈值) 来自 analysis.trading_plan
- 6 件套 (md/json/log/html/docx/pdf) status 暴露 (§2 数据契约)

依赖:
- analysis.utils: _fmt_time, _to_float, _num_or_none, _clean, _fnum, _fpct
- analysis.constants: _SRC_DESC
- analysis.trading_plan: inject_state_to_plan
- analysis.three_levels: compute_three_levels
- analysis.data_fetcher: _fetch_fund_flow_daily / _fetch_margin_history / _fetch_concept_peers
- analysis.fetcher_dispatcher: call_fetcher
- analysis.reporting.artifact_writer: _emit / _dump_run_log
- quant_analyzer_v2 (根模块): analyze_single, _make_trading_plan, _make_signal_list, fetch_margin_trading

向 v3 兼容:
- v3 顶部 from analysis.pipeline import analyze_single_v3, _emit 透传
- 老调用 quant_analyzer_v3.analyze_single_v3(code, name) 仍能拿到
"""

import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Optional

# 兄弟目录加 sys.path (与 v3 / report_md 一致, 让 v2 / html_report_v3 / md_to_docx 裸 import 可解析)
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# 兄弟模块 (§1 业务口径, 阈值/模板不动)
from analysis.utils import (
    _fmt_time, _to_float, _num_or_none,
    _clean, _fnum, _fpct, _interpret_yoy, _interpret_qoq, _finance_talk,
    _short_iso, _format_peg_talk,
)
from analysis.constants import (
    _SRC_DESC, OPERATION_TEMPLATES, _STATE_DISPLAY,
)
from analysis.trading_plan import (
    _score_to_state, inject_state_to_plan, _state_display,
)
from analysis.three_levels import (
    compute_three_levels, _klines_to_series, _series_ma, _series_boll,
    _series_recent_high, _series_recent_low,
)
from analysis.data_fetcher import (
    _fetch_fund_flow_daily, _fetch_margin_history, _fetch_concept_peers,
)
from analysis.fetcher_dispatcher import _NEW_IMPORTS, call_fetcher
from analysis.orchestration.helpers import _latest_trading_day, _kline_freshness
from analysis.orchestration.helpers import _record_kline_freshness_guard
from analysis.orchestration.helpers import _initialize_run_log, _finalize_run_log_timing
from analysis.orchestration.source_status import (
    SourceStatusRecorder,
    _record_v2_source_statuses,
    _record_sw_tls_failure,
)
from analysis.orchestration.fetching import (
    _call_new,
    _fetch_margin,
    _fetch_supplements,
    _fetch_sections,
)
from analysis.orchestration.fetching import _retry_call as _retry_call  # noqa: F401
from analysis.orchestration.legacy_bridge import (
    _V2_FN_TO_SRC,
    _FIELD_OF,
    _TOP_FIELD_OF,
    _patch_v2_timers,
    _restore_v2,
)
from analysis.analytics.scope import _classify_north_scope
from analysis.analytics.scoring import _build_scoring_breakdown
from analysis.reporting.artifact_writer import _emit, _dump_run_log

# V2 同源复用 (只读引用, 不修改 v2)
import quant_analyzer_v2 as v2  # noqa: E402

# Section Registry (P1 §10.1, 5 sections 渲染列表, 与 v3 line 108 一致)
from sections import enabled_sections  # noqa: E402

# P0-B 规范整改 (2026-09-11, 规范 §4): 统一 fetcher 返回契约
# (与 v3 line 50-64 镜像, 让 _call_new 内 status_of() 等可用)
try:
    from fetcher_contract import (
        status_of, is_error as _is_error_fc, is_ok, is_empty, is_unsupported,
        from_legacy as _from_legacy,
        STATUS_OK, STATUS_EMPTY, STATUS_ERROR, STATUS_UNSUPPORTED,
    )
    _HAS_FETCHER_CONTRACT = True
except Exception:  # noqa: BLE001
    _HAS_FETCHER_CONTRACT = False
    # 兜底: 保持老 ad-hoc 检测逻辑
    def status_of(blob):
        if isinstance(blob, dict) and "error" in blob and isinstance(blob["error"], str):
            return "error"
        return "ok"

# ============================================================
# 模块级常量 (V3 数据源标签契约)
# ============================================================

# 来源 label → meta dict (analyze_single_v3 内累计, 写盘前清空)
_src_meta = SourceStatusRecorder()


# ============================================================
# V3 附加端点 (同一数据源家族的接线复用, 不新建数据源)
# ============================================================
# ============================================================
# 3 内部 fetcher (P2-A Phase 4 整改): 已抽到 analysis.data_fetcher
# - _fetch_fund_flow_daily (push2his fflow daykline)
# - _fetch_margin_history (datacenter RPTA_WEB_RZRQ_GGMX)
# - _fetch_concept_peers (push2 clist f37+f105)
# 4 独立 fetcher (公告/财务/研报/新闻) 在 analysis.fetcher_dispatcher 集中入口
# ============================================================


# ============================================================
# V3 单票主流程

def analyze_single_v3(code: str, name: str = "") -> dict:
    """V3 单票完整分析 → result_v3 (契约见文件头) + 生成 MD / run_log.json。

    K线当日证据与三价位硬约束: 全部取 V2 同源实时结果 (腾讯行情 + baostock 前复权K线),
    不读任何 pool CSV。"""
    started = datetime.now()
    run_log = _initialize_run_log(started)

    # ---- 1. V2 全链路 (10 数据类, 计时包装) ----
    saved = _patch_v2_timers(v2, _src_meta, _fmt_time)
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
            _finalize_run_log_timing(run_log, started, datetime.now, time.time)
            _dump_run_log(code, name, run_log)
            print(f"\n[✗] 分析中止: {run_log['fatal']}")
            return {"error": run_log["fatal"], "run_log": run_log}
    finally:
        _restore_v2(v2, saved)

    # ---- 1.5 申万 SSL 失败处理 (P0-C 规范整改, 2026-09-11, §5 'TLS 证书校验') ----
    # 历史: 本机 CA 证书链过旧 → swsresearch.com HTTPS 握手失败 (SSL EOF);
    #       原 P0-C 前用 verify=False 全局 patch 绕过, 9-10 plan 已标同 swsresearch 类问题.
    # 整改: 移除 verify=False 兜底 (§5 '保持 TLS 证书校验开启; 不得 verify=False 作为生产默认'),
    #       失败如实记录, run_log 推荐 'pip install -U certifi' 修复; 评分沿用 v2 已算值.
    code6 = base_result["code"]
    _record_sw_tls_failure(
        base_result,
        _src_meta,
        run_log,
        _SRC_DESC,
        _fmt_time,
        time.time,
    )

    q = base_result["quote"]; v = base_result["valuation"]
    score = base_result["score"]; score_total = score["total"]
    chip_data = base_result["chip_data"]
    vh = base_result.get("valuation_hist") or {}

    # ---- 2. 三价位 (V2 同源模型: 腾讯实时价 + baostock 筹码K线, 债4) ----
    plan = v2._make_trading_plan(q, v, chip_data, score_total)
    # ---- 2.1 多空状态机注入 (债 1 修法, Task 5.1 + 批次 E 痛 3 PE 旁路) ----
    # 在 trading_plan 上加 state + template_used + state_after_pe_bypass + bypass_applied 字段,
    # 渲染层 (MD/HTML) 直接读 plan["template_used"] 即可, 不再各自写硬编码模板。
    # 批次 E 痛 3: PE 分位 > 85% 时, 把 bullish/mild_bull 强切到 mild_bear/neutral
    #            (防"PE 高估时给中性偏多"自相矛盾, 典型例子: 杰瑞 53 分 + PE 87.8%)
    pe_pctile = vh.get("pe_percentile_3y")
    inject_state_to_plan(plan, score_total, pe_pctile) if plan else None
    good_signals, bad_signals = v2._make_signal_list(score, score["factors"])

    # ---- 2.2 三价位表 (债 2 修法, Task 5.2 + P0-A 规范整改, 2026-09-11): 支撑下沿/压力上沿 ----
    # 候选价从 chip_data['kline'] (~250 日 baostock 前复权 K 线) 自算 MA/布林/前高/前低;
    # 筹码峰直接读 chip_data['peak_price'] (v2 chip_distribution 平铺, line 572)。
    # stop_loss **复用** trading_plan.stop_loss（V2 同源，**不重算**），
    # 严守 Task 5.1 锁定的 trading_plan 字段（entry_low/entry_high/tp1/tp2/tp3/stop_loss/stop_loss_pct）。
    # 命名: 支撑 = "支撑下沿" (4 候选最小, 过滤>1.05×价), 压力 = "压力上沿" (3 候选最大, 过滤<0.95×价)。
    # 规则文档: analysis/references/three-levels-rules.md (§6 规范"区间极值/跨价"另命名要求)
    three_levels = compute_three_levels(q, chip_data, plan)

    # ---- 3. 逐类状态判定 (V2 的 10 类) ----
    _record_v2_source_statuses(
        base_result,
        _src_meta,
        run_log,
        _FIELD_OF,
        _SRC_DESC,
    )

    # ---- 4. V3 追加数据块: 4 新 fetcher + 两融 (逐个记录耗时/状态/实际源) ----
    fetched = {"announcements": None, "finance": None, "news": None,
               "research": None, "margin": None,
               "fund_daily5": None, "margin_hist": None, "peers": None}

    print("\n[V3+] 追加数据块: 公告 / 财务 / 研报 / 新闻 / Section Registry / 两融 / 5日资金 / 同业…")
    fetched["announcements"] = _call_new(
        _src_meta, run_log, _NEW_IMPORTS, _SRC_DESC, status_of,
        "公告", "公告", code6,
    )
    fetched["finance"] = _call_new(
        _src_meta, run_log, _NEW_IMPORTS, _SRC_DESC, status_of,
        "财务摘要", "财务", code6,
    )
    fetched["research"] = _call_new(
        _src_meta, run_log, _NEW_IMPORTS, _SRC_DESC, status_of,
        "研报观点", "研报", code6, 200,
    )  # days=200: 小票近90日常无覆盖(真实)
    fetched["news"] = _call_new(
        _src_meta, run_log, _NEW_IMPORTS, _SRC_DESC, status_of,
        "新闻舆情", "新闻", code6,
    )
    # Section Registry: 5 新节走新路径（灰度老路径仍保留 4 旧 fetcher；spec §3.3）
    sections = enabled_sections()
    sections_data = _fetch_sections(run_log, sections, code6, base_result)

    margin = _fetch_margin(
        run_log,
        _SRC_DESC,
        _fmt_time,
        v2.fetch_margin_trading,
        code6,
    )
    fetched["margin"] = margin

    # 附加: 近5日主力 + 两融方向历史 + 同业(概念口径) — 失败不致命, 记入 supplements
    # 灰度保留：spec §3.3（"先保留 4 旧 fetcher 走老路径，5 新节走新注册表；下版本统一"）
    _fetch_supplements(
        _src_meta,
        run_log,
        fetched,
        _SRC_DESC,
        _fmt_time,
        code6,
        base_result.get("blocks", []),
        _fetch_fund_flow_daily,
        _fetch_margin_history,
        _fetch_concept_peers,
    )

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

    # ---- 5.6 痛 7 修法 (报告质量债 2.0 批次 C, 2026-09-14): 5 维评分构成 ----
    # 把 V2 10 维评分聚合成 5 维 (技术/资金/估值/情绪/风险), 让综合评分不再是黑盒。
    # 报告层 (MD/HTML) 直接读 result["scoring_breakdown"], 缺字段时按"评分构成数据缺失"降级占位。
    result["scoring_breakdown"] = _build_scoring_breakdown(score)
    _bd = result["scoring_breakdown"]
    print(f"[v3] 评分构成: 总分 {_bd['total']['score']}/{_bd['total']['max']} | "
          f"技术 {_bd['tech']['score']}/{_bd['tech']['max']} | "
          f"资金 {_bd['capital']['score']}/{_bd['capital']['max']} | "
          f"估值 {_bd['valuation']['score']}/{_bd['valuation']['max']} | "
          f"情绪 {_bd['sentiment']['score']}/{_bd['sentiment']['max']} | "
          f"风险 {_bd['risk']['score']}/{_bd['risk']['max']}")

    # ---- 6. run_log 收尾: guard + 时点 ----
    fresh = _kline_freshness(chip_data)
    _record_kline_freshness_guard(run_log, fresh)
    print(f"\n[guard] {run_log['guard']['kline_freshness']}")

    _finalize_run_log_timing(run_log, started, datetime.now, time.time)

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
# CLI