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
- analysis.utils: _json_default, _fmt_time, _to_float, _num_or_none, _clean, _fnum, _fpct
- analysis.constants: _SRC_DESC
- analysis.trading_plan: inject_state_to_plan
- analysis.three_levels: compute_three_levels
- analysis.data_fetcher: _fetch_fund_flow_daily / _fetch_margin_history / _fetch_concept_peers
- analysis.fetcher_dispatcher: call_fetcher
- analysis.report_md: write_markdown_report_v3
- quant_analyzer_v2 (根模块): analyze_single, _make_trading_plan, _make_signal_list, fetch_margin_trading
- html_report_v3 / md_to_docx (落盘用, _emit 内 try-import 兜底)

向 v3 兼容:
- v3 顶部 from analysis.pipeline import analyze_single_v3, _emit 透传
- 老调用 quant_analyzer_v3.analyze_single_v3(code, name) 仍能拿到
"""

import os
import sys
import json
import time
from datetime import datetime, date, timedelta
from typing import Optional

# 兄弟目录加 sys.path (与 v3 / report_md 一致, 让 v2 / html_report_v3 / md_to_docx 裸 import 可解析)
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# 兄弟模块 (§1 业务口径, 阈值/模板不动)
from analysis.utils import (
    _json_default, _fmt_time, _to_float, _num_or_none,
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
from analysis.report_md import write_markdown_report_v3

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
REPORTS_ROOT = os.path.normpath(os.path.join(_ANALYSIS_DIR, "..", "reports"))

# V2 内嵌 10 类 + V3 追加: 融资融券 + 研报/公告/财务/新闻
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
# 来源 label → base_result field
_FIELD_OF = {
    "行情": "quote", "估值一致预期": "valuation", "概念板块": "blocks",
    "当日资金流": "fund", "估值历史分位": "valuation_hist", "解禁日历": "lockup",
    "龙虎榜": "dragon", "宏观底色": "macro", "筹码K线": "chip_data",
    "申万分类": "sw_data",
}
_TOP_FIELD_OF = {fn: _FIELD_OF[lab] for fn, lab in _V2_FN_TO_SRC.items()}

# 来源 label → meta dict (analyze_single_v3 内累计, 写盘前清空)
_src_meta: dict = {}   # label -> {"ms":int,"at":"HH:MM:SS","status":str,"detail":str}


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
# _short_iso 已抽到 analysis.utils (P2-A Phase 5)
# - v3 顶部 from analysis.utils import _short_iso 透传
# ============================================================
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

    # ---- 1.5 申万 SSL 失败处理 (P0-C 规范整改, 2026-09-11, §5 'TLS 证书校验') ----
    # 历史: 本机 CA 证书链过旧 → swsresearch.com HTTPS 握手失败 (SSL EOF);
    #       原 P0-C 前用 verify=False 全局 patch 绕过, 9-10 plan 已标同 swsresearch 类问题.
    # 整改: 移除 verify=False 兜底 (§5 '保持 TLS 证书校验开启; 不得 verify=False 作为生产默认'),
    #       失败如实记录, run_log 推荐 'pip install -U certifi' 修复; 评分沿用 v2 已算值.
    code6 = base_result["code"]
    sw0 = base_result.get("sw_data") or {}
    if isinstance(sw0, dict) and "error" in sw0:
        sw_err = str(sw0.get("error", ""))[:80]
        run_log["fallback_chain"].append(
            f"申万分类: SSL 直连失败 ({sw_err[:44]}) — 不再 verify=False 兜底 (§5); "
            f"修复: pip install -U certifi  (申万行业因子按 v2 默认中性计)")
        # §5: 不重试不回退, 失败如实记录; 评分不变, 由 v2.analyze_single 已按 sw 缺失算
        meta = _src_meta.setdefault("申万分类", {"at": _fmt_time(time.time())})
        meta["ms"] = 0
        meta["status"] = f"error:{sw_err[:40]} (需 pip install -U certifi), 0ms"
        meta["detail"] = _SRC_DESC.get("申万分类", "申万行业稳定性")
        meta["tls_recommendation"] = "pip install -U certifi"
        run_log.setdefault("tls_recommendations", []).append({
            "host": "swsresearch.com",
            "fix": "pip install -U certifi",
            "applies_to": ["申万分类"],
        })

    q = base_result["quote"]; v = base_result["valuation"]
    score = base_result["score"]; score_total = score["total"]
    chip_data = base_result["chip_data"]

    # ---- 2. 三价位 (V2 同源模型: 腾讯实时价 + baostock 筹码K线, 债4) ----
    plan = v2._make_trading_plan(q, v, chip_data, score_total)
    # ---- 2.1 多空状态机注入 (债 1 修法, Task 5.1) ----
    # 在 trading_plan 上加 state + template_used 两个字段,
    # 渲染层 (MD/HTML) 直接读 plan["template_used"] 即可, 不再各自写硬编码模板。
    # P2-A Phase 2 整改: 5 状态机映射 + template_used 注入统一在 trading_plan 模块
    inject_state_to_plan(plan, score_total) if plan else None
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
        # P0-B (2026-09-11, §4): 用 status_of() 统一检测, 兼容新契约 + 老 ad-hoc
        st = status_of(val) if val is not None else "error"
        if exc:
            status = f"error:调用异常 {exc[:80]}, {meta.get('ms','?')}ms"
            run_log["fallback_chain"].append(f"{lab}: 第{n_try}次后仍失败 — {exc}")
        elif st == "error":
            # 新契约从 error.message 取, 老 ad-hoc 从 error 字段取
            err_msg = ""
            if isinstance(val, dict):
                e = val.get("error")
                if isinstance(e, dict) and "message" in e:
                    err_msg = str(e["message"])
                elif isinstance(e, str):
                    err_msg = e
            status = f"error:{err_msg[:60]}, {meta.get('ms','?')}ms"
            run_log["fallback_chain"].append(f"{lab}: {err_msg[:100]}")
        elif st == "empty":
            status = f"empty:无记录, {meta.get('ms','?')}ms"
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

def _emit(code: str, name: str, result: dict) -> dict:
    """6 件套落盘 (out_dir 内, 同 HHMM 时间戳命名):
    ① {code}-{name}-{HHMM}.md            (必需, §7 必需产物)
    ② result_v3.json                     (必需, 完整 result dict)
    ③ run_log.json                       (必需, 链路记录)
    ④ {code}-{name}-{HHMM}.html          (允许降级, 写 run_log.html_status)
    ⑤ {code}-{name}-{HHMM}.docx          (允许降级, 写 run_log.docx_status)
    ⑥ {code}-{name}-{HHMM}.pdf           (允许降级, html_report_v3 写 result.pdf_status)

    P1-A (2026-09-11, §7): 输出 deliverable_status = complete / partial / failed
      - complete: 3 必需 + 3 允许降级全活
      - partial: 必需全活, 至少 1 个允许降级失败
      - failed:  至少 1 个必需失败
    """
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

    # ① MD (必需)
    md_status = "ok"
    md_err = ""
    try:
        md_text = write_markdown_report_v3(result)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
    except Exception as e:  # noqa: BLE001
        md_status = f"error:{str(e)[:120]}"
        md_err = str(e)

    # ② result_v3.json (必需, P1-C 显式 JSONEncoder)
    json_status = "ok"
    json_err = ""
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        json_status = f"error:{str(e)[:120]}"
        json_err = str(e)

    # ③ HTML (允许降级)
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
        # P1-A: html_report_v3 内部已写 result.pdf_status
        html_status = "ok" if (html_path and os.path.exists(html_path)) else f"error: HTML 文件未生成"
    except Exception as e:  # noqa: BLE001
        html_err = str(e)
        html_status = f"error:{str(e)[:120]}"
    html_ms = round((time.time() - t0) * 1000)

    # ④ DOCX (允许降级)
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

    # ⑤ PDF (允许降级, html_report_v3 已写 result.pdf_status; 兜底 None)
    pdf_status = result.get("pdf_status", "skipped:html_report_v3 未执行")
    pdf_path = result.get("pdf_path")

    # ================= P1-A deliverable_status 计算 (§7) =================
    optional_status = {"html": html_status, "docx": docx_status, "pdf": pdf_status}

    def _is_ok(s):
        return s == "ok" or (isinstance(s, str) and s.startswith("ok("))

    def _calc_deliverable(rl_status):
        req = {"md": md_status, "result_json": json_status, "run_log": rl_status}
        req_failed = [k for k, v in req.items() if not _is_ok(v)]
        opt_failed = [k for k, v in optional_status.items() if not _is_ok(v)]
        if req_failed:
            return "failed", req_failed, [k for k, v in req.items() if _is_ok(v)], opt_failed
        if opt_failed:
            return "partial", [], [k for k, v in req.items() if _is_ok(v)], opt_failed
        return "complete", [], [k for k, v in req.items() if _is_ok(v)], []

    # run_log 第一次写 (含产物状态 + sizes)
    rl = result.get("run_log") or {}
    sizes = {}
    for label, p in [("md", md_path), ("html", html_path), ("docx", docx_path),
                     ("result_json", json_path), ("pdf", pdf_path)]:
        try:
            sizes[label] = os.path.getsize(p) if p else None
        except OSError:
            sizes[label] = None
    rl["artifacts"] = {
        "md": os.path.basename(md_path), "html": os.path.basename(html_path),
        "docx": os.path.basename(docx_path),
        "pdf": os.path.basename(pdf_path) if pdf_path else None,
        "result_json": os.path.basename(json_path),
        "md_status": md_status, "html_status": html_status, "docx_status": docx_status,
        "pdf_status": pdf_status, "result_json_status": json_status,
        "html_ms": html_ms, "docx_ms": docx_ms,
        "sizes_bytes": sizes,
    }
    log_status = "ok"
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(rl, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        log_status = f"error:{str(e)[:120]}"
    rl["artifacts"]["run_log_status"] = log_status
    sizes["run_log"] = os.path.getsize(log_path) if os.path.exists(log_path) else None
    rl["artifacts"]["sizes_bytes"] = sizes

    # 算最终 deliverable (含 run_log)
    deliverable_status, req_failed, req_ok, opt_failed = _calc_deliverable(log_status)
    rl["artifacts"]["deliverable_status"] = deliverable_status
    rl["artifacts"]["required_failed"] = req_failed
    rl["artifacts"]["optional_failed"] = opt_failed
    rl["artifacts"]["required_ok"] = req_ok
    rl["artifacts"]["optional_ok"] = [k for k, v in optional_status.items() if _is_ok(v)]
    rl["artifacts"]["sizes_bytes"] = sizes

    # 第二次写 run_log (含 deliverable + sizes)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(rl, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        pass

    files = {"md": md_path, "html": html_path, "docx": docx_path, "pdf": pdf_path,
             "json": json_path, "run_log": log_path, "day_dir": day_dir,
             "status": {"md": md_status, "html": html_status, "docx": docx_status,
                        "pdf": pdf_status, "json": json_status, "log": log_status,
                        "deliverable": deliverable_status,
                        "required_failed": req_failed, "optional_failed": opt_failed,
                        "html_err": html_err, "docx_err": docx_err, "json_err": json_err,
                        "md_err": md_err}}
    result["_files"] = files
    result["deliverable_status"] = deliverable_status  # 顶层, 方便测试/外部读

    # ②(终) 补 dump: result["run_log"] 与 rl 同对象, 此时已含 artifacts; _files 也一并入 json
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] result_v3.json 终 dump 失败: {e}")

    if html_status != "ok":
        print(f"  [WARN] HTML 生成失败: {html_status}")
    if docx_status != "ok":
        print(f"  [WARN] DOCX 生成失败: {docx_status}")
    if pdf_status != "ok":
        print(f"  [WARN] PDF 生成失败: {pdf_status}")
    return files



def _dump_run_log(code: str, name: str, run_log: dict):
    """失败中止时也落 run_log.json (便于排查)。"""
    safe_name = name or code
    day_dir = os.path.join(REPORTS_ROOT, f"{code}_{safe_name}",
                           datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, f"run_log-{datetime.now().strftime('%H%M')}.json"), "w", encoding="utf-8") as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2, default=_json_default)


# ============================================================
# CLI

