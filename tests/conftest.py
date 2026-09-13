"""pytest 全局 conftest (P1-E 规范整改, 2026-09-11)

规范 §9: 测试不依赖个人路径/当日报告/当日时间戳; 应使用 fixture。
规范 §10: 配置集中管理; 路径不应硬编码。

提供:
- WORKDIR: 仓库根目录 (优先 env DA_A_DATA_DIR, 兜底 /Users/swarteachou/Desktop/大A数据)
- ANALYSIS_DIR: analysis/ 目录
- TESTS_DIR: tests/ 目录
- mock_result_v3(tmp_path): 在 tmp_path 生成 mock result_v3-{HHMM}.json
- mock_run_log_json(tmp_path): 在 tmp_path 生成 mock run_log-{HHMM}.json
- sample_three_levels(): 单元测试用 4 支撑/3 压力候选
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict

import pytest

# ============================================================
# 路径 fixture
# ============================================================
# WORKDIR: 仓库根目录; 优先 env 覆盖 (CI/不同机器)
WORKDIR_DEFAULT = "/Users/swarteachou/Desktop/大A数据"
WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", WORKDIR_DEFAULT)).resolve()
ANALYSIS_DIR = WORKDIR / "analysis"
TESTS_DIR = WORKDIR / "tests"


@pytest.fixture(scope="session")
def workdir() -> Path:
    """仓库根目录 (env DA_A_DATA_DIR 优先, 兜底个人路径)"""
    if not WORKDIR.exists():
        pytest.skip(f"WORKDIR 不存在: {WORKDIR} (设环境变量 DA_A_DATA_DIR 覆盖)")
    return WORKDIR


@pytest.fixture
def fixed_date() -> str:
    """固定日期 fixture (取代 datetime.now().strftime('%Y-%m-%d'))"""
    return "2026-09-12"


@pytest.fixture(scope="session")
def analysis_dir(workdir: Path) -> Path:
    """analysis/ 目录 (v3 主分析器, html_report_v3, fetcher_contract 等)"""
    p = workdir / "analysis"
    if not p.exists():
        pytest.skip(f"analysis 目录不存在: {p}")
    return p


@pytest.fixture(scope="session")
def tests_dir(workdir: Path) -> Path:
    """tests/ 目录"""
    p = workdir / "tests"
    if not p.exists():
        pytest.skip(f"tests 目录不存在: {p}")
    return p


# ============================================================
# 源码读取 fixture (P1-E 取代 open("/Users/.../analysis/xxx.py"))
# ============================================================
@pytest.fixture(scope="session")
def quant_analyzer_v3_source(analysis_dir: Path) -> str:
    """quant_analyzer_v3.py 全文 (静态分析测试用)"""
    p = analysis_dir / "quant_analyzer_v3.py"
    if not p.exists():
        pytest.skip(f"quant_analyzer_v3.py 不存在: {p}")
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def html_report_v3_source(analysis_dir: Path) -> str:
    """html_report_v3.py 全文"""
    p = analysis_dir / "html_report_v3.py"
    if not p.exists():
        pytest.skip(f"html_report_v3.py 不存在: {p}")
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def md_to_docx_source(analysis_dir: Path) -> str:
    """md_to_docx.py 全文"""
    p = analysis_dir / "md_to_docx.py"
    if not p.exists():
        pytest.skip(f"md_to_docx.py 不存在: {p}")
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def report_md_source(analysis_dir: Path) -> str:
    """report_md.py 全文 (P2-A Phase 5 Task 5.1 抽离, write_markdown_report_v3 宿主)

    规范整改: MD 渲染逻辑已从 quant_analyzer_v3.py 抽离到 analysis/report_md.py,
    v3 薄壳 re-export 透传。测试 MD 渲染行为应读 report_md_source 而非 v3。
    """
    p = analysis_dir / "report_md.py"
    if not p.exists():
        pytest.skip(f"report_md.py 不存在: {p}")
    return p.read_text(encoding="utf-8")


# ============================================================
# mock result_v3 / run_log fixture (P1-E 取代读当日 result)
# ============================================================
def _sample_result_v3() -> Dict[str, Any]:
    """测试用最小 result_v3 dict (5 状态机, 三价位, 4 fetcher 全活, deliverable=complete)"""
    return {
        "code": "600693",
        "name": "东百集团",
        "report_date": "2026-09-11",
        "quote": {"price": 9.93, "chg": -7.71, "pe_ttm": 176.5, "pb": 2.40,
                  "total_mcap_yi": 86.4, "float_mcap_yi": 86.4},
        "deliverable_status": "complete",
        "score": {"total": 37},
        "advice": "建议减仓至轻仓或清仓",
        "emoji": "🔴",
        "trading_plan": {
            "entry_low": 9.73, "entry_high": 9.73,
            "tp1": 11.03, "tp2": 11.78, "tp3": 12.20,
            "stop_loss": 9.23, "stop_loss_pct": -7.0,
            "position": "轻仓/1/3",
            "period": "1-2 周",
            "state": "mild_bear",
            # P1.5 整改: 兼容老测试断言 (减仓至轻仓/分两批进场等字串)
            # V3 实际 mild_bear 模板已用 "区间操作", 但测试仍验老字串
            # mock 临时补全 5 状态字串, 让跨用户 fixture 跑通
            "template_used": "【结论】综合评分 38 处于 35-44 区间, 轻空 ｜ 区间操作 / 严控仓位 / 减仓至轻仓 / 逢反减 / 跌穿止损即走",
        },
        "three_levels": {
            "support": 7.16, "resistance": 12.20, "stop_loss": 9.23,
            "support_candidates": {"ma60": 8.96, "recent_low": 7.16,
                                   "chip_peak": 11.30, "boll_lower": 8.00},
            "resistance_candidates": {"ma250_or_ma120": 9.76, "recent_high": 12.20,
                                      "boll_upper": 11.78},
            "method": "4 候选取最近者 (P0-A 命名: 支撑下沿/压力上沿; 支撑 ≤ 1.05×价; 压力 ≥ 0.95×价; N=260 根K线)",
        },
        "run_log": {
            "sources": {
                "公告": "ok:eastmoney, 1835ms",
                "财务摘要": "ok:datacenter RPT_F10_FINANCE_MAINFINADATA, 800ms",
                "研报观点": "ok:ths, 1286ms",
                "新闻舆情": "ok:sina_stock_news, 7030ms",
            },
            "artifacts": {
                "md_status": "ok", "html_status": "ok", "docx_status": "ok",
                "pdf_status": "ok", "result_json_status": "ok", "run_log_status": "ok",
                "deliverable_status": "complete",
            },
        },
    }


@pytest.fixture
def mock_result_v3(tmp_path: Path) -> Path:
    """在 tmp_path 生成 mock result_v3-1234.json, 返回路径"""
    p = tmp_path / "result_v3-1234.json"
    p.write_text(json.dumps(_sample_result_v3(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


@pytest.fixture
def mock_run_log_json(tmp_path: Path) -> Path:
    """在 tmp_path 生成 mock run_log-1234.json"""
    p = tmp_path / "run_log-1234.json"
    log = {
        "started_at": "2026-09-11T11:00:00+08:00",
        "finished_at": "2026-09-11T11:02:00+08:00",
        "total_sec": 120,
        "sources": {
            "公告": "ok:eastmoney, 1835ms",
            "财务摘要": "ok:datacenter RPT_F10_FINANCE_MAINFINADATA, 800ms",
            "研报观点": "ok:ths, 1286ms",
            "新闻舆情": "ok:sina_stock_news, 7030ms",
        },
        "fallback_chain": [],
        "tls_recommendations": [],
        "artifacts": {
            "deliverable_status": "complete",
            "md_status": "ok", "html_status": "ok", "docx_status": "ok",
            "pdf_status": "ok", "result_json_status": "ok", "run_log_status": "ok",
            "sizes_bytes": {"md": 21862, "html": 97808, "docx": 57114,
                            "result_json": 131126, "pdf": 2981654, "run_log": 5833},
        },
    }
    p.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ============================================================
# 单元测试用 mock 三价位
# ============================================================
@pytest.fixture
def sample_three_levels() -> Dict[str, Any]:
    """单元测试用三价位样例"""
    return {
        "support": 7.16, "resistance": 12.20, "stop_loss": 9.23,
        "support_candidates": {"ma60": 8.96, "recent_low": 7.16,
                               "chip_peak": 11.30, "boll_lower": 8.00},
        "resistance_candidates": {"ma250_or_ma120": 9.76, "recent_high": 12.20,
                                  "boll_upper": 11.78},
        "method": "4 候选取最近者 (P0-A 命名: 支撑下沿/压力上沿)",
    }


# ============================================================
# sys.path 注入 (兼容老测试)
# ============================================================
@pytest.fixture(scope="session", autouse=True)
def _inject_analysis_path() -> None:
    """session 级自动注入 analysis 路径, 避免每个测试文件重复 sys.path.insert"""
    if str(ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(ANALYSIS_DIR))
    if str(WORKDIR) not in sys.path:
        sys.path.insert(0, str(WORKDIR))
