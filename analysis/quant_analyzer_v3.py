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

P0-B 规范整改 (2026-09-11, 规范 §4): 4 个 fetcher 入仓后, 通过 fetcher_contract.from_legacy()
适配老 ad-hoc 返回 ({"error": str, "rows": []}), 报告层用 status_of()/is_error() 统一检测。
完整契约见 `analysis/fetcher_contract.py` + §4 规范。
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

# P0-B 规范整改 (2026-09-11, 规范 §4): 统一 fetcher 返回契约
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

# ---------------------------------------------------------------
# 路径: 本文件所在目录 → 可 import v2 / 4 个新 fetcher
# ---------------------------------------------------------------
_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# ============================================================
# P2-A 模块拆分 (2026-09-12): 工具函数/常量从 v3 提到独立模块
# v3 内 def 函数体已删除, 通过 import 透传 (§1 '不修改业务口径')
# 向后兼容: from analysis.quant_analyzer_v3 import _json_default 仍能拿到 (在 utils)
# ============================================================
from analysis.utils import (
    _json_default, _fmt_time, _to_float, _num_or_none,
    _clean, _fnum, _fpct, _interpret_yoy, _interpret_qoq, _finance_talk,
    _short_iso, _format_peg_talk,
)
from analysis.constants import (
    _SRC_DESC, OPERATION_TEMPLATES, _STATE_DISPLAY,
)
# P2-A Phase 2 (2026-09-13): 5 状态机 + plan 注入
from analysis.trading_plan import (
    _score_to_state, inject_state_to_plan, _state_display,
)
# P2-A Phase 3 (2026-09-13): 三价位 (P0-A 命名统一 + 规则文档)
from analysis.three_levels import (
    compute_three_levels, _klines_to_series, _series_ma, _series_boll,
    _series_recent_high, _series_recent_low,
)
# P2-A Phase 4 (2026-09-13): 3 内部 fetcher 集中
from analysis.data_fetcher import (
    _fetch_fund_flow_daily, _fetch_margin_history, _fetch_concept_peers,
)
# P2-A Phase 4 Task 4.2: 4 独立 fetcher 软导入 + 调度
from analysis.fetcher_dispatcher import _NEW_IMPORTS, call_fetcher

# P2-A Phase 5 Task 5.1 (2026-09-13): write_markdown_report_v3 抽离到 report_md.py
# v3 薄壳, 老 import 路径 quant_analyzer_v3.write_markdown_report_v3 仍工作
from analysis.report_md import write_markdown_report_v3

# P2-A Phase 5 Task 5.2 (2026-09-13): analyze_single_v3 + _emit + _dump_run_log + 6 编排辅助
# 全部抽到 analysis/pipeline.py; v3 透传 re-export (§4 '迁移期可适配器兼容')
from analysis.pipeline import (
    analyze_single_v3, _emit, _dump_run_log,
    _classify_north_scope, _patch_v2_timers, _restore_v2,
    _latest_trading_day, _kline_freshness, _retry_call,
)


import quant_analyzer_v2 as v2  # noqa: E402
from sections import enabled_sections  # noqa: E402  # Phase 1: Section Registry (irm §10.1)

# 4 个独立 fetcher 软导入已抽到 analysis.fetcher_dispatcher (P2-A Phase 4 Task 4.2)
# - 公告/财务/研报/新闻 4 块
# - 失败容错, 不崩 v3 主流程
# - 统一入口: call_fetcher(label, *args) / _NEW_IMPORTS 状态字典


# ============================================================
# CLI 入口 (P2-A Phase 5: v3 薄壳, 主分析流程在 analysis.pipeline)
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
