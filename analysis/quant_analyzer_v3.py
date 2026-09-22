#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股多因子量化分析器 V3 — 入口薄壳 (P2-A Phase 5 Task 5.3, 2026-09-13)
====================================================================

P2-A 模块拆分收口: V3 不再持有实现代码, 全部从 analysis/ 子模块 re-export。
- 主分析流程: analysis.pipeline.analyze_single_v3
- 6 件套落盘: analysis.pipeline._emit
- 报告 Markdown 渲染: analysis.report_md.write_markdown_report_v3
- 三价位: analysis.three_levels.compute_three_levels
- 5 状态机 + plan 注入: analysis.trading_plan
- 工具/常量: analysis.utils + analysis.constants
- fetcher 4 状态契约: analysis.fetcher_contract (P0-B 规范 §4)
- 4 独立 fetcher 软导入 + 调度: analysis.fetcher_dispatcher (P2-A Phase 4)
- 3 内部 fetcher 集中: analysis.data_fetcher (P2-A Phase 4)

调用入口:
  - CLI:    python quant_analyzer_v3.py <code> [name]
  - 脚本:   bash scripts/run_in_venv.sh analysis/quant_analyzer_v3.py 603319 美湖股份
  - 模块:   from analysis.quant_analyzer_v3 import analyze_single_v3

向后兼容 (§四 不破坏向后兼容):
  老 import 路径 `from analysis.quant_analyzer_v3 import X` 仍能拿到 X,
  X 现位于 analysis 子模块, 由本文件透传 re-export。

result dict 契约 (HTML 组也按此读):
  code/name/quote/valuation/blocks/fund/valuation_hist/lockup/dragon/macro/
  chip_data/sw_data/announcements/finance/news/research/margin/peers(附加)/
  score/advice/emoji/detail/trading_plan/signals/run_log/report_date
"""

# ============================================================
# 路径: 本文件所在目录 → 兄弟模块 / v2 / fetcher_contract / sections
# ============================================================
import os
import sys

_ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

# ============================================================
# 兄弟模块 re-export (§四 向后兼容)
# 显式列名 (不用 import *), 让老 import 路径仍工作
# ============================================================
# utils (P2-A Phase 1)
# fetcher_contract (P0-B 规范 §4: 4 状态契约, v3 老 try-import 已弃用)
from fetcher_contract import (  # noqa: E402
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    is_empty,
    is_ok,
    is_unsupported,
    status_of,
)
from fetcher_contract import (  # noqa: E402  # sys.path 兄弟目录引导
    from_legacy as _from_legacy,
)
from fetcher_contract import (  # noqa: E402  # sys.path 兄弟目录引导
    is_error as _is_error_fc,
)

# constants (P2-A Phase 1)
from analysis.constants import (  # noqa: E402  # sys.path 兄弟目录引导
    _SRC_DESC,
    _STATE_DISPLAY,
    OPERATION_TEMPLATES,
)

# data_fetcher (P2-A Phase 4 Task 4.1: 3 内部 fetcher 集中)
from analysis.data_fetcher import (  # noqa: E402  # sys.path 兄弟目录引导
    _fetch_concept_peers,
    _fetch_fund_flow_daily,
    _fetch_margin_history,
)

# fetcher_dispatcher (P2-A Phase 4 Task 4.2: 4 独立 fetcher 软导入 + 调度)
from analysis.fetcher_dispatcher import (  # noqa: E402  # sys.path 兄弟目录引导
    _NEW_IMPORTS,
    call_fetcher,
)

# three_levels (P2-A Phase 3)
from analysis.three_levels import (  # noqa: E402  # sys.path 兄弟目录引导
    _klines_to_series,
    _series_boll,
    _series_ma,
    _series_recent_high,
    _series_recent_low,
    compute_three_levels,
)

# trading_plan (P2-A Phase 2)
from analysis.trading_plan import (  # noqa: E402  # sys.path 兄弟目录引导
    _score_to_state,
    _state_display,
    inject_state_to_plan,
)
from analysis.utils import (  # noqa: E402  # sys.path 兄弟目录引导
    _clean,
    _finance_talk,
    _fmt_time,
    _fnum,
    _format_peg_talk,
    _fpct,
    _interpret_qoq,
    _interpret_yoy,
    _json_default,
    _num_or_none,
    _short_iso,
    _to_float,
)

_HAS_FETCHER_CONTRACT = True
# report_md (P2-A Phase 5 Task 5.1)
# v2 同源复用 (v3 顶层 import 仅做命名暴露, 主流程已用 pipeline 内的 v2)
import quant_analyzer_v2 as v2  # noqa: E402

# Section Registry (P1 §10.1, 5 sections 渲染列表; pipeline/report_md 也独立 import)
from sections import enabled_sections  # noqa: E402

# pipeline (P2-A Phase 5 Task 5.2: 6 编排辅助 + analyze_single_v3 + _emit + _dump_run_log)
from analysis.pipeline import (  # noqa: E402  # sys.path 兄弟目录引导
    _classify_north_scope,
    _dump_run_log,
    _emit,
    _kline_freshness,
    _latest_trading_day,
    _patch_v2_timers,
    _restore_v2,
    _retry_call,
    analyze_single_v3,
)
from analysis.report_md import write_markdown_report_v3  # noqa: E402  # sys.path 兄弟目录引导

__all__ = [
    # utils
    "_json_default", "_fmt_time", "_to_float", "_num_or_none",
    "_clean", "_fnum", "_fpct", "_interpret_yoy", "_interpret_qoq", "_finance_talk",
    "_short_iso", "_format_peg_talk",
    # constants
    "_SRC_DESC", "OPERATION_TEMPLATES", "_STATE_DISPLAY",
    # trading_plan
    "_score_to_state", "inject_state_to_plan", "_state_display",
    # three_levels
    "compute_three_levels", "_klines_to_series", "_series_ma", "_series_boll",
    "_series_recent_high", "_series_recent_low",
    # data_fetcher
    "_fetch_fund_flow_daily", "_fetch_margin_history", "_fetch_concept_peers",
    # fetcher_dispatcher
    "_NEW_IMPORTS", "call_fetcher",
    # fetcher_contract
    "status_of", "_is_error_fc", "is_ok", "is_empty", "is_unsupported",
    "_from_legacy", "STATUS_OK", "STATUS_EMPTY", "STATUS_ERROR", "STATUS_UNSUPPORTED",
    "_HAS_FETCHER_CONTRACT",
    # report_md
    "write_markdown_report_v3",
    # pipeline
    "analyze_single_v3", "_emit", "_dump_run_log",
    "_classify_north_scope", "_patch_v2_timers", "_restore_v2",
    "_latest_trading_day", "_kline_freshness", "_retry_call",
    # v2 / sections
    "v2", "enabled_sections",
    # CLI
    "main",
]


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
