"""痛 7 修法测试 (报告质量债 2.0 批次 C, 2026-09-14): 5 维评分构成

覆盖:
  1. _build_scoring_breakdown 单元测试 (5 维聚合 / 缺失子维 / clamp / sum 守恒)
  2. report_md 简版 / 完整版 渲染 (含兜底)
  3. html_report_v3 卡片渲染 (含兜底)
  4. 3 只样本票 result_v3.json 端到端 (600693 / 002353 / 605162)

历史: docs/09-报告质量债2.0-plan.md 批次 C, 痛 7
"""
import os
import sys
import json
import re
import pytest
from pathlib import Path

WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", "/Users/swarteachou/Desktop/大A数据")).resolve()
sys.path.insert(0, str(WORKDIR))
sys.path.insert(0, str(WORKDIR / "analysis"))

_SAMPLE_RESULT_PATH = WORKDIR / "reports/600693_东百集团/2026-09-13/result_v3-0914.json"

def _load_sample_result():
    if not _SAMPLE_RESULT_PATH.exists():
        pytest.skip(f"未提供历史 result_v3 fixture: {_SAMPLE_RESULT_PATH}")
    return json.loads(_SAMPLE_RESULT_PATH.read_text(encoding="utf-8"))


# ============================================================
# 1. _build_scoring_breakdown 单元测试
# ============================================================
def test_breakdown_has_5_dims_plus_total():
    """5 维 + 顶层 total, 共 6 keys。"""
    from analysis.pipeline import _build_scoring_breakdown
    bd = _build_scoring_breakdown({"trend": 5, "valuation": 5, "valuation_pctile": 4,
                                   "capital": 7, "momentum": 4, "sentiment": 3,
                                   "risk": 5, "chip": 4, "sw_stability": 4, "dragon": 3,
                                   "total": 44})
    assert set(bd.keys()) == {"tech", "capital", "valuation", "sentiment", "risk", "total"}, (
        f"breakdown keys 错误: {list(bd.keys())}"
    )


@pytest.mark.parametrize("key,max", [
    ("tech", 28),       # trend(12) + momentum(8) + chip(8)
    ("capital", 25),    # capital(15) + dragon(10)
    ("valuation", 29),  # valuation(15) + valuation_pctile(8) + sw_stability(6)
    ("sentiment", 8),   # sentiment(8)
    ("risk", 10),       # risk(10)
])
def test_breakdown_max_values(key, max):
    """5 维 max 正确 (与 v2 10 维 max 守恒: 28+25+29+8+10=100)。"""
    from analysis.pipeline import _build_scoring_breakdown
    bd = _build_scoring_breakdown({})  # 全空 → 按 50% 中性
    assert bd[key]["max"] == max, f"{key} max={bd[key]['max']}, 期望 {max}"


def test_breakdown_total_max_is_100():
    """5 维 max 之和 = 100。"""
    from analysis.pipeline import _build_scoring_breakdown
    bd = _build_scoring_breakdown({})
    assert bd["total"]["max"] == 100, f"total max={bd['total']['max']}, 期望 100"


def test_breakdown_missing_dim_uses_50pct_neutral():
    """缺失子维按 50% 子维 max 中性计, dims 标 None。

    50% 规则是 per-sub-dim, 不是 per-group:
      - 缺 capital (sub_max=15) → 7.5
      - dragon 3 (provided)
      - capital group = 7.5 + 3 = 10.5
    """
    from analysis.pipeline import _build_scoring_breakdown
    score = {"trend": 5, "valuation": 5, "valuation_pctile": 4,
             "momentum": 4, "sentiment": 3, "risk": 5, "chip": 4,
             "sw_stability": 4, "dragon": 3, "total": 39}
    # 故意缺 capital
    bd = _build_scoring_breakdown(score)
    assert bd["capital"]["dims"]["capital"] is None
    # capital sub_max=15, 缺 → 7.5; dragon=3 → group=10.5
    assert bd["capital"]["score"] == 10.5, f"capital={bd['capital']['score']}, 期望 10.5"


def test_breakdown_clamp_negative_and_overflow():
    """超过满分 clamp 到 max, 负数 clamp 到 0。"""
    from analysis.pipeline import _build_scoring_breakdown
    score = {"trend": 99, "valuation": -3, "valuation_pctile": 4,
             "capital": 7, "momentum": 4, "sentiment": 3, "risk": 5,
             "chip": 4, "sw_stability": 4, "dragon": 3, "total": 50}
    bd = _build_scoring_breakdown(score)
    # trend 上限 12
    assert bd["tech"]["dims"]["trend"] == 12, f"trend 应 clamp 到 12, 实际 {bd['tech']['dims']['trend']}"
    # valuation 下限 0
    assert bd["valuation"]["dims"]["valuation"] == 0, f"valuation 应 clamp 到 0, 实际 {bd['valuation']['dims']['valuation']}"


def test_breakdown_sum_equals_total():
    """5 维 score 之和 = total (允许 0 误差, 因为聚合口径一致)。"""
    from analysis.pipeline import _build_scoring_breakdown
    for score in [
        {"trend": 1, "valuation": 2, "valuation_pctile": 3, "capital": 7,
         "momentum": 1, "sentiment": 4, "risk": 4, "chip": 4, "sw_stability": 5,
         "dragon": 3, "total": 34},  # 600693 真实数据
        {"trend": 8, "valuation": 10, "valuation_pctile": 6, "capital": 6,
         "momentum": 3, "sentiment": 2, "risk": 8, "chip": 1, "sw_stability": 3,
         "dragon": 6, "total": 53},  # 002353
    ]:
        bd = _build_scoring_breakdown(score)
        five_sum = sum(bd[k]["score"] for k in ("tech", "capital", "valuation",
                                                 "sentiment", "risk"))
        assert abs(five_sum - bd["total"]["score"]) < 0.01, (
            f"5 维之和 {five_sum} != total {bd['total']['score']}, score={score}"
        )


def test_breakdown_empty_score():
    """完全空 score: 5 维按 50% 中性 (5 维=50), total 兜底 0。"""
    from analysis.pipeline import _build_scoring_breakdown
    bd = _build_scoring_breakdown({})
    # 全空 → 5 维都按 50% 中性: 14+12.5+14.5+4+5=50
    five_sum = sum(bd[k]["score"] for k in ("tech", "capital", "valuation",
                                            "sentiment", "risk"))
    assert five_sum == 50.0, f"全空时 5 维之和应为 50, 实际 {five_sum}"
    # total: raw_total=None → 0
    assert bd["total"]["score"] == 0


def test_breakdown_pct_in_range():
    """5 维 pct 应在 0-100 之间。"""
    from analysis.pipeline import _build_scoring_breakdown
    score = {"trend": 1, "valuation": 2, "valuation_pctile": 3, "capital": 7,
             "momentum": 1, "sentiment": 4, "risk": 4, "chip": 4, "sw_stability": 5,
             "dragon": 3, "total": 34}
    bd = _build_scoring_breakdown(score)
    for k in ("tech", "capital", "valuation", "sentiment", "risk", "total"):
        assert 0 <= bd[k]["pct"] <= 100, f"{k} pct={bd[k]['pct']} 越界"


# ============================================================
# 2. report_md 渲染测试
# ============================================================
def test_md_compact_has_scoring_breakdown():
    """简版 MD 应含"📊 评分构成"段, 在 30 秒决策卡后, 三价位前。"""
    from analysis.pipeline import _build_scoring_breakdown
    from analysis.report_md import write_markdown_report_v3
    r = _load_sample_result()
    r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    md = write_markdown_report_v3(r)
    assert "## 📊 评分构成" in md
    # 简版只显示一行汇总
    score_idx = md.find("## 📊 评分构成")
    three_idx = md.find("### 🎯 三价位", score_idx)
    section = md[score_idx:three_idx]
    assert "技术" in section and "资金" in section and "估值" in section
    assert "情绪" in section and "风险" in section
    assert "综合" in section


def test_md_full_has_scoring_breakdown_5dim_table():
    """完整版 MD 应含"📊 评分构成 (5 维拆解, 满分 100)"详细表。"""
    from analysis.pipeline import _build_scoring_breakdown
    from analysis.report_md import write_markdown_report_v3
    r = _load_sample_result()
    r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    r["_md_full"] = True
    md = write_markdown_report_v3(r)
    assert "## 📊 评分构成 (5 维拆解" in md
    # 详细表 5 行
    section = md[md.find("## 📊 评分构成 (5 维拆解"):md.find("## 🔬 10 因子打分明细")]
    assert "维度" in section and "得分" in section and "满分" in section
    assert "占比" in section
    # 5 行 (5 维) + 综合行
    rows = [l for l in section.split("\n") if l.startswith("|") and "**" in l]
    assert len(rows) == 6, f"5 维 + 综合 = 6 行, 实际 {len(rows)}"


def test_md_fallback_when_scoring_breakdown_missing():
    """scoring_breakdown 字段缺失时, MD 兜底"评分构成数据缺失"。"""
    from analysis.report_md import write_markdown_report_v3
    r = _load_sample_result()
    r.pop("scoring_breakdown", None)
    md = write_markdown_report_v3(r)
    assert "## 📊 评分构成" in md
    assert "⚠️" in md
    assert "评分构成数据缺失" in md


# ============================================================
# 3. html_report_v3 卡片渲染测试
# ============================================================
def test_html_card_has_5_cols():
    """HTML 5 维评分构成卡片应含 5 列 (bd-col)。"""
    from analysis.pipeline import _build_scoring_breakdown
    from analysis.html_report_v3 import _render_scoring_breakdown
    r = _load_sample_result()
    r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    html = _render_scoring_breakdown(r)
    # 5 列
    n_cols = html.count('class="bd-col')
    assert n_cols == 5, f"应有 5 列, 实际 {n_cols}"
    # 5 个 label
    for label in ("技术", "资金", "估值", "情绪", "风险"):
        assert label in html, f"缺 label: {label}"


def test_html_card_color_thresholds():
    """HTML 卡片颜色: ≥70% 绿 (dim-good) / 40-70% 黄 (dim-warn) / <40% 红 (dim-bad)。"""
    from analysis.html_report_v3 import _scoring_breakdown_color
    assert _scoring_breakdown_color(80) == "dim-good"
    assert _scoring_breakdown_color(70) == "dim-good"
    assert _scoring_breakdown_color(50) == "dim-warn"
    assert _scoring_breakdown_color(40) == "dim-warn"
    assert _scoring_breakdown_color(20) == "dim-bad"
    assert _scoring_breakdown_color(0) == "dim-bad"
    # 缺失兜底
    assert _scoring_breakdown_color(None) == "dim-warn"


def test_html_card_fallback_when_scoring_breakdown_missing():
    """scoring_breakdown 字段缺失时, HTML 卡片兜底"评分构成数据缺失"。"""
    from analysis.html_report_v3 import _render_scoring_breakdown
    r = _load_sample_result()
    r.pop("scoring_breakdown", None)
    html = _render_scoring_breakdown(r)
    assert "评分构成数据缺失" in html
    assert "missing-module" in html  # 批次 B 痛 5 复用的占位样式


def test_html_card_positioned_after_hero():
    """HTML 5 维卡片应位于 hero 之后, 操作检查清单之前 (源码级顺序检查)。

    静态检查 write_html_report_v3 源码里的拼接顺序, 不调 PDF 渲染 (~15s/票)。
    动态渲染验证已由 test_e2e_html_report_renders_breakdown 覆盖。
    """
    import inspect
    from analysis.html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    # 找 3 个关键锚点在源码中的出现位置
    hero_pos = src.find("html.append(hero_html)")
    bd_pos = src.find("html.append(_render_scoring_breakdown(result))")
    checklist_pos = src.find('html.append(_render_checklist(')
    assert hero_pos != -1, "源码中未找到 hero 注入点"
    assert bd_pos != -1, "源码中未找到 5 维评分构成注入点"
    assert checklist_pos != -1, "源码中未找到 checklist 注入点"
    # 顺序: hero < 5 维 < 操作检查清单
    assert hero_pos < bd_pos < checklist_pos, (
        f"源码顺序错误: hero={hero_pos}, bd={bd_pos}, checklist={checklist_pos}"
    )


# ============================================================
# 4. 端到端: 3 只样本票 (600693 / 002353 / 605162)
# ============================================================
SAMPLE_TICKERS = [
    ("600693_东百集团", "600693", "东百集团"),
    ("002353_杰瑞股份", "002353", "杰瑞股份"),
    ("605162_新中港", "605162", "新中港"),
]


def _latest_result_v3_for(code_name: str) -> str:
    """取 code_name 下最新 result_v3.json 路径, 缺失则 pytest.skip。"""
    base = WORKDIR / f"reports/{code_name}"
    if not base.exists():
        pytest.skip(f"{code_name} 报告目录不存在")
    days = sorted([d for d in os.listdir(str(base)) if re.match(r"\d{4}-\d{2}-\d{2}", d)])
    if not days:
        pytest.skip(f"{code_name} 无日期目录")
    day_dir = base / days[-1]
    files = [f for f in os.listdir(str(day_dir)) if f.startswith("result_v3-")]
    if not files:
        pytest.skip(f"{code_name} 无 result_v3-*.json")
    latest = max(files, key=lambda f: (day_dir / f).stat().st_mtime)
    return str(day_dir / latest)


@pytest.mark.parametrize("code_name,code,name", SAMPLE_TICKERS)
def test_e2e_breakdown_in_result_json(code_name, code, name):
    """端到端: 3 只样本票 result_v3.json 注入 scoring_breakdown, 5 维 sum 守恒。"""
    from analysis.pipeline import _build_scoring_breakdown
    path = _latest_result_v3_for(code_name)
    r = json.load(open(path))
    # 老 result JSON 可能没 scoring_breakdown, 注入
    if "scoring_breakdown" not in r:
        r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    bd = r["scoring_breakdown"]
    # 5 维
    for k in ("tech", "capital", "valuation", "sentiment", "risk"):
        assert k in bd, f"{code} 缺 {k} 维"
        assert "score" in bd[k] and "max" in bd[k] and "pct" in bd[k]
    # sum 守恒
    five_sum = sum(bd[k]["score"] for k in ("tech", "capital", "valuation",
                                            "sentiment", "risk"))
    assert abs(five_sum - bd["total"]["score"]) < 0.01, (
        f"{code} 5 维之和 {five_sum} != total {bd['total']['score']}"
    )


@pytest.mark.parametrize("code_name,code,name", SAMPLE_TICKERS)
def test_e2e_html_report_renders_breakdown(code_name, code, name):
    """端到端: HTML 5 维卡片在 3 只样本票 result 上正确渲染。

    复用 _render_scoring_breakdown 单函数 (不调 write_html_report_v3) —
    完整 write_html_report_v3 会触发 Chrome headless PDF 渲染 (~15s/票),
    对 3 票 × 多个 e2e 测试会拖到 >1min, 单函数验证足以覆盖 5 维逻辑。
    全量端到端 (含 PDF) 由 _render_html_to_pdf 单独测试覆盖, 不在此重复。
    """
    from analysis.pipeline import _build_scoring_breakdown
    from analysis.html_report_v3 import _render_scoring_breakdown
    path = _latest_result_v3_for(code_name)
    r = json.load(open(path))
    if "scoring_breakdown" not in r:
        r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    html = _render_scoring_breakdown(r)
    assert "5 维评分构成 (技术/资金/估值/情绪/风险)" in html, f"{code} HTML 缺 5 维卡片"
    # 5 列
    assert html.count('class="bd-col') == 5, f"{code} bd-col 应有 5 列"
    # 进度条
    assert "bd-fill" in html
    # 颜色
    assert "dim-good" in html or "dim-warn" in html or "dim-bad" in html
    # 综合
    assert "bd-total" in html


@pytest.mark.parametrize("code_name,code,name", SAMPLE_TICKERS)
def test_e2e_md_report_renders_breakdown(code_name, code, name):
    """端到端: 完整版 MD 含 5 维拆解详细表。"""
    from analysis.pipeline import _build_scoring_breakdown
    from analysis.report_md import write_markdown_report_v3
    path = _latest_result_v3_for(code_name)
    r = json.load(open(path))
    if "scoring_breakdown" not in r:
        r["scoring_breakdown"] = _build_scoring_breakdown(r["score"])
    r["_md_full"] = True
    md = write_markdown_report_v3(r)
    assert "## 📊 评分构成 (5 维拆解" in md, f"{code} MD 缺 5 维拆解段"
    # 5 维 + 综合 = 6 行
    section = md[md.find("## 📊 评分构成 (5 维拆解"):md.find("## 🔬 10 因子打分明细")]
    rows = [l for l in section.split("\n") if l.startswith("|") and "**" in l]
    assert len(rows) == 6, f"{code} 5 维 + 综合 = 6 行, 实际 {len(rows)}"
