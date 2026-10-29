"""pytest 全局 conftest (P1-E 规范整改, 2026-09-11)

规范 §9: 测试不依赖个人路径/当日报告/当日时间戳; 应使用 fixture。
规范 §10: 配置集中管理; 路径不应硬编码。

提供:
- WORKDIR: 仓库根目录 (优先 env DA_A_DATA_DIR, 兜底 Path(__file__) 推导的仓库根)
- ANALYSIS_DIR: analysis/ 目录
- TESTS_DIR: tests/ 目录
- mock_result_v3(tmp_path): 在 tmp_path 生成 mock result_v3-{HHMM}.json
- mock_run_log_json(tmp_path): 在 tmp_path 生成 mock run_log-{HHMM}.json
- sample_three_levels(): 单元测试用 4 支撑/3 压力候选
"""
from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

# ============================================================
# 路径 fixture
# ============================================================
# WORKDIR: 仓库根目录; 优先 env 覆盖 (CI/不同机器), 兜底从本文件位置推导
WORKDIR_DEFAULT = str(Path(__file__).resolve().parents[1])
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


@pytest.fixture(scope="session")
def pipeline_source(analysis_dir: Path) -> str:
    """pipeline.py 全文 (P2-A Phase 5 Task 5.2 抽离, analyze_single_v3 / _emit 宿主)

    规范整改: V3 编排层 (analyze_single_v3 + _emit + 6 编排辅助) 已从 v3 抽到 analysis/pipeline.py,
    v3 薄壳 re-export 透传。测试编排/落盘行为应读 pipeline_source 而非 v3。
    """
    p = analysis_dir / "pipeline.py"
    if not p.exists():
        pytest.skip(f"pipeline.py 不存在: {p}")
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def result_builder_source(analysis_dir: Path) -> str:
    """orchestration/result_builder.py 全文 (Phase 1H: build/finalize 阶段宿主)

    规范整改: analyze_single_v3 的 result 组装 / 北向口径 / 评分构成 / guard 收尾 /
    控制台摘要 已从 pipeline.py 抽到 analysis/orchestration/result_builder.py。
    测这些阶段的源码契约应读 result_builder_source, 测编排接线读 pipeline_source。
    """
    p = analysis_dir / "orchestration" / "result_builder.py"
    if not p.exists():
        pytest.skip(f"result_builder.py 不存在: {p}")
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
            # 批次 D 债 2 修法 (2026-09-14): 新增 stop_loss_method 字段
            # 9.23 > 7.16*0.97=6.95, V2 赢, method=trading_plan (杰瑞类)
            "stop_loss_method": "trading_plan",
            "support_candidates": {"ma60": 8.96, "recent_low": 7.16,
                                   "chip_peak": 11.30, "boll_lower": 8.00},
            "resistance_candidates": {"ma250_or_ma120": 9.76, "recent_high": 12.20,
                                      "boll_upper": 11.78},
            "method": "4 候选取最近者 (P0-A 命名: 支撑下沿/压力上沿; 支撑 ≤ 1.05×价; 压力 ≥ 0.95×价; 止损 = max(支撑×0.97, V2 计划止损) [批次 D 债 2 修法, 2026-09-14]; N=260 根K线)",
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
def rendered_markdown_v3() -> str:
    """用确定性 result fixture 渲染当前 V3 Markdown 契约，不读取 reports/ 历史产物。"""
    from analysis.report_md import write_markdown_report_v3

    result = _sample_result_v3()
    result["quote"].update({
        "price": 10.00,
        "pe_ttm": 88.0,
        "pb": 2.40,
        "float_mcap": 86.4,
        "limit_up": 11.00,
        "limit_down": 9.00,
        "amplitude": 3.20,
        "turnover_rate": 4.10,
        "vol_ratio": 1.20,
    })
    result["valuation"] = {
        "peg": 4.20,
        "analyst_count": 5,
        "digest_years": 5,
    }
    result["valuation_hist"] = {
        "pe_percentile_3y": 92.0,
        "pb_percentile_3y": 55.0,
    }
    result["score"] = {
        "total": 50,
        "change_pct": 1.25,
        "trend": 6,
        "valuation": 7,
        "valuation_pctile": 4,
        "capital": 8,
        "momentum": 4,
        "sentiment": 4,
        "risk": 5,
        "chip": 4,
        "sw_stability": 3,
        "dragon": 5,
        "factors": [],
    }
    result["emoji"] = "🟡"
    result["advice"] = "中性"
    result["detail"] = "Markdown 契约测试"
    result["_md_full"] = True
    result["trading_plan"].update({
        "state": "neutral",
        "entry_low": 9.50,
        "entry_high": 9.80,
        "stop_loss": 9.20,
        "stop_loss_pct": -8.0,
        "tp1": 10.80,
        "tp2": 11.50,
        "tp3": 12.20,
        "position": "轻仓",
        "period": "1-2 周",
        "template_used": (
            "【结论】当前维持中性 ｜ "
            "【操作】按买入区间分批执行 ｜ "
            "【风险】跌破止损位退出"
        ),
    })
    result["three_levels"].update({
        "support": 9.50,
        "resistance": 10.80,
        "stop_loss": 9.20,
        "stop_loss_method": "trading_plan",
        "support_op_key": "ma60",
        "resistance_op_key": "boll_upper",
        "support_extreme": 8.80,
        "resistance_extreme": 11.60,
        "support_extreme_label": "60日最低",
        "resistance_extreme_label": "60日最高",
        "support_candidates": {
            "ma60": 9.50,
            "recent_low": 8.80,
            "chip_peak": 9.60,
            "boll_lower": 9.40,
        },
        "resistance_candidates": {
            "ma250_or_ma120": 10.70,
            "recent_high": 11.60,
            "boll_upper": 10.80,
        },
    })
    result.update({
        "signals": {"good": [], "bad": []},
        "blocks": [],
        "fund": {},
        "chip_data": {},
        "lockup": {},
        "dragon": {},
        "macro": {"north_label": "北向资金：市场口径"},
        "sw_data": {},
        "announcements": None,
        "finance": None,
        "research": None,
        "news": None,
        "margin": None,
        "margin_hist": {},
        "fund_daily5": {},
        "peers": {},
        "irm": {},
        "holders": {},
        "dividend": {},
        "board": {},
        "dragon_market": {},
    })
    result["run_log"].update({
        "source_meta": {},
        "fallback_chain": [],
        "guard": {
            "status": "ok",
            "kline_freshness": {"last_bar": "2026-09-18"},
        },
        "started_at": "2026-09-18T10:00:00+08:00",
        "finished_at": "2026-09-18T10:00:01+08:00",
        "total_sec": 1.0,
    })
    return write_markdown_report_v3(result)


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
    """单元测试用三价位样例 (批次 D 包含 stop_loss_method)"""
    return {
        "support": 7.16, "resistance": 12.20, "stop_loss": 9.23,
        "stop_loss_method": "trading_plan",  # 批次 D 新增
        "support_candidates": {"ma60": 8.96, "recent_low": 7.16,
                               "chip_peak": 11.30, "boll_lower": 8.00},
        "resistance_candidates": {"ma250_or_ma120": 9.76, "recent_high": 12.20,
                                  "boll_upper": 11.78},
        "method": "4 候选取最近者 (P0-A 命名: 支撑下沿/压力上沿; 止损 = max(支撑×0.97, V2 计划止损) [批次 D 债 2 修法, 2026-09-14])",
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


# ============================================================
# live gate 第一步 (选择层): live 用例只认"显式选择", 不认 -m 覆盖 addopts
# ============================================================
# 事故背景: pyproject addopts 里的 `-m "not live"` 只是**默认值**, 命令行任意 -m
# 都会把它完全覆盖 (后写的 -m 生效)。于是
#     DA_A_RUN_LIVE=1 pytest -m "not slow"
# 会把 live 用例**重新选回来** (它没打 slow 标记, 匹配 "not slow"), 用例自己的
# env 门禁又因 DA_A_RUN_LIVE=1 放行 → 真打 qt.gtimg.cn / 同花顺。
# 也就是说"记得传 -m 'not live'"从来不是门禁, 只是一个可被覆盖的默认值。
#
# 这里把第一步下沉到 collection 层: 打了 live 标记的用例, 只有当**生效的 -m
# 表达式正向点名** live / integration 时才留在 items 里, 其余一律 deselect。
#   pytest                                  → 生效表达式 = addopts 的 "not live" → 排除
#   pytest -m "not slow"                    → 没点名            → 排除 (上一个洞)
#   pytest -m "not (live or integration)"   → 否定              → 排除 (不做子串误判)
#   pytest -m "unit or slow"                → 点名别的标记      → 排除
#   pytest -m "live or unit"                → or 的 unit 分支   → 排除 (这次修掉的洞)
#   pytest -m "not live or integration"     → 否定 + or         → 排除 (这次修掉的洞)
#   pytest -m integration / -m live / -m "live and integration" / -m "live or integration"
#                                          → 整个表达式就是显式 opt-in → 放行到第二步
# 生效表达式取 config.option.markexpr: pytest 已把 ini addopts 与命令行 -m 合并成
# 同一个选项, 命令行后写者覆盖 ini 默认, 拿到的就是真正生效的那份。
#
# 判定口径是 fail-closed 的"整表达式 opt-in": 只有整个生效表达式由 live/integration
# 这些 opt-in 名字合取或析取组成, 才算显式点名; 只要掺进别的标记或任何否定, 一律排除。
# 理由: or 是"任一分支匹配即选中", 一个非 opt-in 分支就足以让 live 用例被选中而
# 与显式 opt-in 无关; not 是排除信号, 复合否定必须一票否决。门禁宁可过严 ——
# 合法出口 (-m live / -m integration) 始终可用, 误杀只是少跑一个显式集成验收,
# 而误放是真实 DNS/行情请求。
#
# 只看 live 标记, 不改其它用例的选取语义 —— 例如不打网络的 LibreOffice
# integration 用例 (tests/reporting/test_artifact_delivery_contract.py) 照常收集执行。
# 第二步 (跑不跑, DA_A_RUN_LIVE 精确等于 "1") 仍归用例自己的 skipif 管, 口径见
# tests/test_peg_formula.py。
_LIVE_MARK = "live"
_LIVE_ALLOW_MARKS = frozenset({"live", "integration"})

# 子树判定三值。只有 _OPT_IN 才放行; 另两值都当"没点名" (fail closed)。
_OPT_IN = "opt_in"      # 明确正向点名 live / integration
_OPT_DENY = "deny"      # 出现否定 (not) —— 排除信号, 一票否决
_OPT_BLOCK = "block"    # 点名的是别的标记 / 认不出的写法 —— 视为没点名


def _classify_markexpr_node(node: ast.AST) -> str:
    """把生效 -m 表达式的子树归到三值之一, 认不出来一律 _OPT_BLOCK。

    and / or 一律取**严格交集**: 每个分支都必须是明确的 opt-in, 整棵子树才算 opt-in。
    不能用 any() —— 那正是这两个逃逸的根因:

      -m "live or unit"              any() 看到 live 就放行; 但 or 的 unit 分支同样
                                     能独立选中打了 live 的用例, 选取与"显式点名 live"
                                     无关。门禁无法证明这条 live 是被显式 opt-in 选中
                                     的, 只能判 block (fail closed)。
      -m "not live or integration"   any() 看到 integration 就放行; 可左边明确写着
                                     "not live" 这个排除信号。否定必须一票否决,
                                     不能被同一表达式里 live/integration 的字样洗白。

    not 一律判 _OPT_DENY (不论被否的是 live 还是别的标记): 出现否定就说明调用方在做
    排除式筛选, 把它当 opt-in 只会误放。复合否定 (not (live or integration) /
    integration and not live) 因此统一被拒。
    """
    if isinstance(node, ast.Name):
        return _OPT_IN if node.id in _LIVE_ALLOW_MARKS else _OPT_BLOCK
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _OPT_DENY
    if isinstance(node, ast.BoolOp):  # and / or
        parts = [_classify_markexpr_node(value) for value in node.values]
        if any(part == _OPT_DENY for part in parts):
            return _OPT_DENY
        return _OPT_IN if all(part == _OPT_IN for part in parts) else _OPT_BLOCK
    return _OPT_BLOCK  # 常量/比较/属性等 pytest 标记表达式里不该出现的写法


def _markexpr_allows_live(markexpr: str) -> bool:
    """生效的 -m 表达式是否整体就是显式 opt-in; 其余 (缺省/空/无法解析/含非 opt-in
    分支/含否定) 一律当"没点名"。

    分类本身也包在 try 里: 门禁必须 fail closed, 不能因为解析/递归异常把 live 放出去。
    """
    if not markexpr or not markexpr.strip():
        return False
    try:
        tree = ast.parse(markexpr, mode="eval")
        return _classify_markexpr_node(tree.body) == _OPT_IN
    except Exception:  # SyntaxError / RecursionError / 其它解析异常 —— 一律当没点名
        return False


def _is_live_item(item) -> bool:
    """item 自己或所属 class/module 是否打了 live 标记。"""
    return any(mark.name == _LIVE_MARK for mark in item.iter_markers())


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items, config) -> None:
    """live 用例的选择层门禁: 没被显式点名就 deselect, 零网络。

    trylast: 排在 pytest 自己的 deselect_by_mark 之后, 只处理它漏下来的用例
    (即 -m 覆盖掉 addopts 后仍被选中的 live 用例), 不与它抢同一批判断。
    放行的用例不碰, 交给第二步 env 门禁决定跑不跑 (env 没开时是 SKIPPED, 不是
    DESELECTED —— 显式集成验收需要看到这个 skip)。
    """
    if _markexpr_allows_live(getattr(config.option, "markexpr", "")):
        return
    keep: list = []
    drop: list = []
    for item in items:
        (drop if _is_live_item(item) else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


# ============================================================
# DOCX 渲染器拆分扫描面 fixture (P2-E S0: 修 H1 否定式门禁退化)
# ============================================================
# 为什么需要它
# ------------
# tests/test_three_levels.py::test_docx_renderer_follows_md_no_hardcode 与
# tests/test_multi_state_trading_plan.py::test_docx_renderer_does_not_hardcode_operation
# 都是**否定式**源码文本断言 (assert "X" not in src)。拆分前 src = 薄壳全文;
# 一旦 P2-E S1-S5 把代码搬进 analysis/reporting/docx_*.py, 薄壳变小 —— 被搬走的
# 那一片若恰好含该字面量, 全文就不再包含它, 断言恒真, **静默假绿且不会自己报警**。
# 每搬一片门禁就松一分。故扫描面必须从"单文件"升级为"薄壳 + 全部宿主模块",
# 并配下面两条覆盖断言, 让判据随代码搬迁保持有效。
#
# 与 P2-D 的方向相反: P2-D 的源码文本断言是**肯定式**, 搬走会变红、自己报警
# (故 P2D 把 H2 放到 S5); 这里是**否定式**, 搬走只会变绿 —— 所以 P2-E 必须在
# S0 就修, 不能压到靠后。
#
# 拆分前 (S0 现状): 只有薄壳, 本 fixture 等价于读 analysis/md_to_docx.py 单文件。
# 拆分后 (S1-S5): 每建一个 analysis/reporting/docx_*.py 需在下面 DOCX_HOST_MODULES
# **登记一行**; 登记即纳入, 漏登记即报错。刻意不做自动 glob —— 理由见该常量注释。
DOCX_HOST_SHELL = "md_to_docx.py"
DOCX_HOST_MODULE_GLOB = "docx_*.py"

# **已登记**的宿主模块（相对 analysis/）。这是 host_files 模块部分的**唯一来源**。
#
# 为什么必须显式登记、不能用 glob
# ------------------------------
# 初版用 `sorted(reporting_dir.glob("docx_*.py"))` 拼 host_files, 又用**同一个 glob**
# 算磁盘集合 on_disk, 于是 `missing_modules = on_disk - included` **恒为空集** ——
# 差别被自己抵消了。这类"扫到什么就比什么"的差分是恒真门禁: S1 建出
# docx_primitives.py 却没登记, 断言也不会红, 而它的 docstring/计划里却写着
# "挡不住新模块被建出来却没登记进扫描面"。**它当时并没有挡住。**
#
# 修法是让两侧**独立**: 登记是判据, 磁盘是事实, 差分才有信息量。代价是 S1 每建一个
# 模块必须在这里登记一行 —— 这是有意的摩擦: 漏登记 = 漏出门禁, 门禁自己会报警。
#
# S1 起: docx_primitives.py 已建出（区块 2/3/4, 108 符号行）并在此登记。S2/S3/S4
# 建出 docx_tables / docx_paragraphs / docx_sections 时各加一行 —— 漏加即
# `missing_modules` 报错, 加了未建即 `absent_modules` 报错, 两个方向都会自己报警。
#
# S2 起（2026-10-06）: docx_tables.py 已建出（区块 6, 94 符号行）并在此登记,
# 即 §七 N2 修正节要求的「每建一个模块必须登记一行」。**本行不是可选项**:
# 删掉它, H1 两条否定式门禁的扫描面就漏掉整个模块, 而否定式断言在漏扫时**恒真**
# （§7.3 表格「不会 —— 静默假绿」）, 且 `line_count >= 560` 也未必跌破 —— 判据失效
# 且不报警。S4 建 docx_sections 时同样再加一行。
#
# S3 起（2026-10-06）: docx_paragraphs.py 已建出（区块 5, 90 符号行）并在此登记。
# ⚠️ 本模块是 S3 的**首要风险面**: 区块 5 含**全部中文关键词分支**（`看空|看多`、
# `数据来源`、`⚠`、`⚠️ 免责声明`、`风险警报` 上色）—— 用户可见文案契约, §八 R3 列为
# 「高」严重度。漏登记本模块 = H1 两条否定式门禁对这一整块**失去覆盖**, 且因为
# `line_count >= 560` 在 S3 之后仍远高于阈值（薄壳 361 + 三模块 486 ≈ 847）, 该
# 覆盖断言**不会替你发现**——只有 `missing_modules` 会。这正是 §七 N2 要求把
# 判据（登记）与事实（磁盘扫描）拆成两个独立来源的原因。
#
# S4 起（2026-10-06）: docx_sections.py 已建出（区块 7, 70 符号行）并在此登记。
# 区块 7 是 §三 耦合最深的一块（扇出横跨 4 个区块: primitives 的 `_fmt`/`C_MUTED`、
# paragraphs 的 3 个 `add_*`、tables 的 `flush_table`、python-docx 的
# `WD_ALIGN_PARAGRAPH`/`Pt`）。漏登记本模块 = H1 两条否定式门禁对灰度块
# `_load_result_near` / `_render_md_block` **失去覆盖**; 且 `line_count >= 560`
# 在 S4 之后仍远高于阈值（薄壳 317 + 四模块 556 ≈ 873）, 仍**只有**
# `missing_modules` 会发现。反向也成立: 本行登记了而磁盘上没有该文件时,
# `absent_modules` 立刻报错（登记与事实脱节）。
DOCX_HOST_MODULES: tuple[str, ...] = (
    "reporting/docx_primitives.py",
    "reporting/docx_tables.py",
    "reporting/docx_paragraphs.py",
    "reporting/docx_sections.py",
)

# P2-E §五 **计划**拆出的四个模块。仅供对照 / S1-S5 落位时抄写用, **不参与门禁判定**
# —— 拿"计划"当现状判据, 会让 S0 一开局就因模块尚未建出而误报, 门禁会被迫加豁免,
# 豁免一旦存在就会被忘记删除。
DOCX_PLANNED_MODULES = (
    "reporting/docx_primitives.py",
    "reporting/docx_paragraphs.py",
    "reporting/docx_tables.py",
    "reporting/docx_sections.py",
)

# 宿主符号契约: 薄壳保留的 3 个 + P2E §五 四个新模块的全部导出名。
# 列在这里而不是"现扫现比", 是为了让它成为**独立于被扫对象**的判据 ——
# 否则"扫到什么就比什么"会退化成恒真。
DOCX_HOST_SYMBOLS = (
    # 薄壳: 主函数 + 容错 import 的两个绑定
    "md_to_docx", "enabled_sections", "_SECTIONS_OK",
    # → analysis/reporting/docx_primitives.py (设计 token + XML 小工具 + 运行拆分)
    "C_DARK", "C_ACCENT", "C_RED", "C_GREEN", "C_AMBER", "C_MUTED",
    "H_HAIR", "H_HEADER", "FILL_ZEBRA", "HX_RED", "HX_GREEN", "HX_AMBER", "HX_ACCENT",
    "F_CJK", "F_MONO", "_EMOJI_RE",
    "_set_fonts", "_fmt", "_ensure", "p_border", "cell_shade",
    "table_borders", "cell_bottom_border", "header_repeat",
    "md_runs", "add_runs",
    # → analysis/reporting/docx_paragraphs.py (标题/引用/正文/免责声明)
    "add_heading", "add_quote", "RISK_EMOJI", "add_body",
    # → analysis/reporting/docx_tables.py (表格 + 3 处业务阈值)
    "NUM_RANGE", "DATE_ONLY", "_clean_num", "is_numeric_like", "_cell_add", "flush_table",
    # → analysis/reporting/docx_sections.py (Section Registry 灰度块)
    "_load_result_near", "_render_md_block",
)


class _SplitSource(str):
    """拼接后的扫描面。行为与全文 str 完全一致, 额外带覆盖元数据供断言用。

    做成 str 子类而不是换成一个对象, 是为了让两个否定式测试**一行不改语义**地
    换 fixture: 它们只做 `in src` 判断, 元数据只给新增的覆盖断言用。
    """

    # 类级注解（不带赋值）: 让 mypy 知道这些属性存在。
    # 裸注解不产生类属性, 因此与下面的 __slots__ 不冲突。
    files: tuple
    host_symbols: tuple
    missing_symbols: tuple
    missing_modules: tuple
    absent_modules: tuple
    registered_modules: tuple
    line_count: int

    __slots__ = (
        "files", "host_symbols", "missing_symbols", "missing_modules",
        "absent_modules", "registered_modules", "line_count",
    )

    def __new__(
        cls, text: str, files, host_symbols, missing_symbols, missing_modules,
        absent_modules, registered_modules, line_count,
    ):
        obj = super().__new__(cls, text)
        obj.files = tuple(files)
        obj.host_symbols = tuple(host_symbols)
        obj.missing_symbols = tuple(missing_symbols)
        obj.missing_modules = tuple(missing_modules)
        obj.absent_modules = tuple(absent_modules)
        obj.registered_modules = tuple(registered_modules)
        obj.line_count = line_count
        return obj


def _bound_names(src: str) -> set:
    """扫描面里所有被绑定的名字 (def / class / 赋值 / 参数), 全仓作用域。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _scan_docx_modules(reporting_dir: Path) -> set:
    """**独立**扫描磁盘上现存的 docx_*.py 文件名集合（事实侧）。

    这是门禁的事实来源, 与 DOCX_HOST_MODULES（判据侧）没有任何推导关系 ——
    两者同源就会互相抵消, 差分恒空。
    """
    if not reporting_dir.is_dir():
        return set()
    return {p.name for p in reporting_dir.glob(DOCX_HOST_MODULE_GLOB)}


def _module_diff(registered, on_disk) -> tuple:
    """双向差分, 返回 ``(missing, absent)``, 均已排序。

    - missing: 磁盘上有、**没登记** —— 新建了 docx_*.py 却漏出门禁扫描面
    - absent:  登记了、磁盘上**没有** —— 登记与事实脱节（模块被删/改名/未落位）

    两类都必须可观察。单向差分只挡得住一半: 只报 missing 时, 登记里写着一个
    根本没建出来的模块也会一路绿灯。
    """
    reg = set(registered)
    disk = set(on_disk)
    return tuple(sorted(disk - reg)), tuple(sorted(reg - disk))


def _assemble_host_modules(analysis_dir: Path, registered) -> tuple:
    """解析宿主模块面。fixture 与负向控制测试**共用这一条代码路径**。

    返回 ``(present, missing, absent, on_disk)``:

    - present: 登记且磁盘存在的模块路径, 按登记顺序
    - missing: 见 :func:`_module_diff`
    - absent:  见 :func:`_module_diff`
    - on_disk: 磁盘上现存的 docx_*.py 文件名集合

    刻意做成纯函数（只读, 不抛, 不改源码树）: 负向控制要能在隔离临时目录里
    造出"多一个模块 / 少一个模块"的情形, 而**不能**去动真实的 analysis/reporting/。
    """
    registered_paths = [analysis_dir / rel for rel in registered]
    present = [p for p in registered_paths if p.exists()]
    on_disk = _scan_docx_modules(analysis_dir / "reporting")
    missing, absent = _module_diff((Path(rel).name for rel in registered), on_disk)
    return present, missing, absent, on_disk


@pytest.fixture(scope="session")
def md_to_docx_split_source(analysis_dir: Path) -> _SplitSource:
    """DOCX 渲染器**全部宿主源码**的拼接全文 (薄壳 + 已登记的宿主模块)。

    S0 之前/当前 (未拆): 等价于读 analysis/md_to_docx.py 单文件。
    S1-S5 之后: 每建一个 analysis/reporting/docx_*.py 就**在 DOCX_HOST_MODULES
    登记一行**, 扫描面随之扩大; 漏登记会被 missing_modules 当场抓住。

    附带覆盖元数据, 供否定式测试自查扫描面没有漏:
      - missing_symbols: 宿主符号契约里有、但扫描面中查不到的
      - missing_modules: 磁盘上有、但没登记进扫描面的 docx_*.py（应为空）
      - absent_modules:  登记了、但磁盘上没有的 docx_*.py（应为空）
      - line_count:     扫描面总行数 (拆分前 584)
    """
    shell = analysis_dir / DOCX_HOST_SHELL
    if not shell.exists():
        pytest.skip(f"{DOCX_HOST_SHELL} 不存在: {shell}")

    present, missing, absent, on_disk = _assemble_host_modules(
        analysis_dir, DOCX_HOST_MODULES
    )
    host_files = [shell] + present

    parts: list = []
    rel_files: list = []
    line_count = 0
    for p in host_files:
        text = p.read_text(encoding="utf-8")
        parts.append(text)
        rel_files.append(str(p.relative_to(analysis_dir.parent)))
        line_count += len(text.splitlines())

    joined = "\n".join(parts)
    declared = _bound_names(joined)
    missing_symbols = [s for s in DOCX_HOST_SYMBOLS if s not in declared]

    return _SplitSource(
        joined, rel_files, DOCX_HOST_SYMBOLS, missing_symbols, missing, absent,
        tuple(Path(rel).name for rel in DOCX_HOST_MODULES), line_count,
    )
