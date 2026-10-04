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
- analysis.orchestration.result_builder: build_trade_levels / build_signals /
                                         assemble_result / enrich_result / finalize_run
- analysis.orchestration.v2_stage: run_v2_stage (V2 全链路重试 + fatal 中止)
- analysis.reporting.artifact_writer: _emit / _dump_run_log
- quant_analyzer_v2 (根模块): analyze_single, _make_trading_plan, _make_signal_list, fetch_margin_trading

向 v3 兼容:
- v3 顶部 from analysis.pipeline import analyze_single_v3, _emit 透传
- 老调用 quant_analyzer_v3.analyze_single_v3(code, name) 仍能拿到
"""

import os
import sys
import time
from datetime import datetime

# 兄弟目录加 sys.path (与 v3 / report_md 一致, 让 v2 / html_report_v3 / md_to_docx 裸 import 可解析)
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# 兄弟模块 (§1 业务口径, 阈值/模板不动)
# V2 同源复用 (只读引用, 不修改 v2)
import quant_analyzer_v2 as v2  # noqa: E402

# Section Registry (P1 §10.1, 5 sections 渲染列表, 与 v3 line 108 一致)
from sections import enabled_sections  # noqa: E402

from analysis.analytics.scope import _classify_north_scope  # noqa: E402  # sys.path 兄弟目录引导
from analysis.analytics.scoring import (  # noqa: E402  # sys.path 兄弟目录引导
    _build_scoring_breakdown,
)
from analysis.constants import (  # noqa: E402  # sys.path 兄弟目录引导
    _SRC_DESC,
)
from analysis.data_fetcher import (  # noqa: E402  # sys.path 兄弟目录引导
    _fetch_concept_peers,
    _fetch_fund_flow_daily,
    _fetch_margin_history,
)
from analysis.fetcher_dispatcher import _NEW_IMPORTS  # noqa: E402  # sys.path 兄弟目录引导
from analysis.orchestration.fetching import (  # noqa: E402  # sys.path 兄弟目录引导
    _call_new,
    _fetch_margin,
    _fetch_sections,
    _fetch_supplements,
    _retry_call,  # noqa: E402,F401  # v3 透传契约
    fetch_v3_blocks,
)
from analysis.orchestration.helpers import (  # noqa: E402  # sys.path 兄弟目录引导
    _finalize_run_log_timing,
    _initialize_run_log,
    _kline_freshness,
    _latest_trading_day,  # noqa: F401  # v3 透传契约 (quant_analyzer_v3 从此 re-export)
    _record_kline_freshness_guard,
)
from analysis.orchestration.legacy_bridge import (  # noqa: E402  # sys.path 兄弟目录引导
    _FIELD_OF,
    _TOP_FIELD_OF,  # noqa: F401  # v3 透传契约
    _V2_FN_TO_SRC,  # noqa: F401  # v3 透传契约
    _patch_v2_timers,
    _restore_v2,
)
from analysis.orchestration.result_builder import (  # noqa: E402  # sys.path 兄弟目录引导
    assemble_result,
    build_signals,
    build_trade_levels,
    enrich_result,
    finalize_run,
)
from analysis.orchestration.source_status import (  # noqa: E402  # sys.path 兄弟目录引导
    SourceStatusRecorder,
    _record_sw_tls_failure,
    _record_v2_source_statuses,
)
from analysis.orchestration.v2_stage import (  # noqa: E402  # sys.path 兄弟目录引导
    run_v2_stage,
)
from analysis.reporting.artifact_writer import (  # noqa: E402  # sys.path 兄弟目录引导
    _dump_run_log,
    _emit,
)
from analysis.three_levels import (  # noqa: E402  # sys.path 兄弟目录引导
    compute_three_levels,
)
from analysis.trading_plan import (  # noqa: E402  # sys.path 兄弟目录引导
    inject_state_to_plan,
)
from analysis.utils import (  # noqa: E402  # sys.path 兄弟目录引导
    _fmt_time,
)

# P0-B 规范整改 (2026-09-11, 规范 §4): 统一 fetcher 返回契约
# (与 v3 line 50-64 镜像, 让 _call_new 内 status_of() 等可用)
try:
    from fetcher_contract import (
        status_of,
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
    # Phase 1J: 本段已抽到 analysis.orchestration.v2_stage.run_v2_stage
    # 3 次重试时间盒 / fatal 中止收尾 / finally 恢复 V2 计时器的顺序与文案逐字不变;
    # 所有注入口由本模块显式传入 (含 v2 模块对象本身, 以便测试在 pipeline.v2 上打桩)。
    v2_stage = run_v2_stage(
        code,
        name,
        run_log,
        started,
        _src_meta,
        v2,
        patch_timers=_patch_v2_timers,
        restore_v2=_restore_v2,
        finalize_timing=_finalize_run_log_timing,
        dump_run_log=_dump_run_log,
        sleep=time.sleep,
        time_fn=time.time,
        now_fn=datetime.now,
        analyze_single=v2.analyze_single,
        fmt_time=_fmt_time,
    )
    if v2_stage.abort is not None:
        return v2_stage.abort
    base_result = v2_stage.base_result

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

    q = base_result["quote"]
    v = base_result["valuation"]
    score = base_result["score"]
    score_total = score["total"]
    chip_data = base_result["chip_data"]
    vh = base_result.get("valuation_hist") or {}

    # ---- 2. 三价位 (V2 同源模型: 腾讯实时价 + baostock 筹码K线, 债4) ----
    # 2.1 多空状态机注入 (债 1 修法, Task 5.1 + 批次 E 痛 3 PE 旁路)
    # 2.2 三价位表 (债 2 修法, Task 5.2 + P0-A 规范整改): 支撑下沿/压力上沿
    # Phase 1H: 本段已抽到 analysis.orchestration.result_builder.build_trade_levels
    # 候选价从 chip_data['kline'] (~250 日 baostock 前复权 K 线) 自算 MA/布林/前高/前低;
    # 筹码峰直接读 chip_data['peak_price'] (v2 chip_distribution 平铺, line 572)。
    # stop_loss **复用** trading_plan.stop_loss（V2 同源，**不重算**）。
    # 规则文档: analysis/references/three-levels-rules.md
    plan, three_levels = build_trade_levels(
        q, v, chip_data, score_total, vh, v2._make_trading_plan,
        compute_levels=compute_three_levels,   # 契约测试在 pipeline 上打桩的注入口
        inject_state=inject_state_to_plan,
    )
    good_signals, bad_signals = build_signals(score, v2._make_signal_list)

    # ---- 3. 逐类状态判定 (V2 的 10 类) ----
    _record_v2_source_statuses(
        base_result,
        _src_meta,
        run_log,
        _FIELD_OF,
        _SRC_DESC,
    )

    # ---- 4. V3 追加数据块: 4 新 fetcher + 两融 (逐个记录耗时/状态/实际源) ----
    # Phase 1I: 本段已抽到 analysis.orchestration.fetching.fetch_v3_blocks
    # 顺序/文案/8 键形状与原内联实现逐字一致; 所有注入口由本模块显式传入。
    fetched_blocks = fetch_v3_blocks(
        code6,
        base_result,
        run_log,
        _src_meta,
        _NEW_IMPORTS,
        _SRC_DESC,
        status_of,
        _fmt_time,
        call_new=_call_new,
        enabled_sections=enabled_sections,
        fetch_sections=_fetch_sections,
        fetch_margin=_fetch_margin,
        fetch_supplements=_fetch_supplements,
        fund_flow_fetcher=_fetch_fund_flow_daily,
        margin_history_fetcher=_fetch_margin_history,
        peers_fetcher=_fetch_concept_peers,
        margin_fetcher=v2.fetch_margin_trading,
    )
    fetched = fetched_blocks.fetched
    margin = fetched_blocks.margin
    sections_data = fetched_blocks.sections_data

    # ---- 5. 组装 result_v3 (契约) ----
    # Phase 1H: 组装 + 北向口径 + 评分构成已抽到 analysis.orchestration.result_builder
    result = assemble_result(
        base_result,
        plan,
        three_levels,
        good_signals,
        bad_signals,
        fetched,
        margin,
        run_log,
        sections_data,
        name,
        datetime.now,
    )

    # ---- 5.5 北向资金口径分类 (债 3 修法, Task 5.3) ----
    # ---- 5.6 痛 7 修法 (报告质量债 2.0 批次 C): 5 维评分构成 ----
    enrich_result(
        result,
        score,
        classify_north_scope=_classify_north_scope,
        build_scoring_breakdown=_build_scoring_breakdown,
    )

    # ---- 6/7. guard + 时点收尾 + 产物落盘 + 控制台摘要 ----
    finalize_run(
        code6,
        result,
        plan,
        chip_data,
        run_log,
        started,
        score_total,
        _emit,
        datetime.now,
        time.time,
        kline_freshness=_kline_freshness,
        record_guard=_record_kline_freshness_guard,
        finalize_timing=_finalize_run_log_timing,
    )
    return result


# ============================================================
# CLI
