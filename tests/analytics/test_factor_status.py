"""因子数据缺失显式标注测试 (2026-09-22)

背景: 数据源失败时 v2 打分沿用中性兜底分 (典型: 申万表加载失败 → 申万=5),
此前报告/CLI 未标注, mock 分被误读为真实评分。

覆盖:
  1. factor_notes_from_sources: run_log sources error/fallback → 标注; ok → 不标
  2. factor_notes_from_data: v2 CLI 用数据级判定 (与 source_status 同口径)
  3. cli_note / notes_summary 文案
  4. MD 渲染: 10 因子打分明细表内标注 (打分不变)
  5. HTML 渲染: 雷达图轴标签 ⚠ + 卡片脚注
"""
import sys
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKDIR))
sys.path.insert(0, str(WORKDIR / "analysis"))

from analysis.analytics.factor_status import (  # noqa: E402
    cli_note,
    factor_notes_from_data,
    factor_notes_from_sources,
    notes_summary,
)

# ============================================================
# 1. factor_notes_from_sources (MD/HTML 渲染路径)
# ============================================================

_SCORE = {"trend": 6, "valuation": 7, "valuation_pctile": 4, "capital": 8,
          "momentum": 4, "sentiment": 4, "risk": 5, "chip": 4,
          "sw_stability": 5, "dragon": 5, "total": 50}


def test_sources_ok_no_notes():
    sources = {"申万分类": "ok, 123ms", "概念板块": "ok, 45ms"}
    assert factor_notes_from_sources(sources, _SCORE) == {}


def test_sources_error_annotated_with_actual_fallback_score():
    sources = {"申万分类": "error:申万表加载失败, 0ms"}
    notes = factor_notes_from_sources(sources, _SCORE)
    assert notes == {"sw_stability": "⚠数据缺失，按中性 5 分计入"}


def test_sources_fallback_annotated():
    sources = {"概念板块": "fallback:接口返回0条(可能风控), 210ms"}
    notes = factor_notes_from_sources(sources, _SCORE)
    assert notes == {"sentiment": "⚠数据缺失，按中性 4 分计入"}


def test_sources_multiple_degraded_and_missing_labels_ignored():
    sources = {
        "申万分类": "error:申万表加载失败, 0ms",
        "当日资金流": "fallback:当日无成交或分钟数据, 5ms",
        "行情": "ok, 30ms",
        # 其余因子源标签缺席 (老 result JSON) → 不标注
    }
    notes = factor_notes_from_sources(sources, _SCORE)
    assert set(notes) == {"sw_stability", "capital"}
    assert "按中性 8 分计入" in notes["capital"]


def test_sources_non_dict_tolerated():
    assert factor_notes_from_sources(None, _SCORE) == {}
    assert factor_notes_from_sources({"申万分类": "error:x"}, None) == {
        "sw_stability": "⚠数据缺失，按中性 ? 分计入"
    }


# ============================================================
# 2. factor_notes_from_data (v2 CLI 因子明细路径)
# ============================================================

def test_data_sw_error_annotated():
    data = {"sw_data": {"error": "申万表加载失败"}}
    notes = factor_notes_from_data(data, _SCORE)
    # sw_data error → 申万稳定标注; 其余字段缺席也视为未拉取 (v2 打分走中性兜底)
    assert notes["sw_stability"] == "⚠数据缺失，按中性 5 分计入"


def test_data_all_healthy_no_notes():
    data = {
        "quote": {"price": 10.0},
        "valuation": {"pe_fwd": 12.0},
        "valuation_hist": {"pe_percentile_3y": 30},
        "fund": {"klines": [1, 2, 3]},
        "blocks": [{"name": "零售"}],
        "lockup": {"items": []},
        "chip_data": {"profit_ratio": 0.5},
        "sw_data": {"n_changes": 1, "median_changes": 5},
        "dragon": {"n_records": 0},
    }
    assert factor_notes_from_data(data, _SCORE) == {}


def test_data_blocks_empty_is_fallback():
    notes = factor_notes_from_data({"blocks": []}, _SCORE)
    assert "sentiment" in notes


def test_data_fund_without_klines_is_fallback():
    notes = factor_notes_from_data({"fund": {"note": "no klines"}}, _SCORE)
    assert "capital" in notes


def test_data_blocks_with_error_item_is_degraded():
    notes = factor_notes_from_data({"blocks": [{"error": "接口异常"}]}, _SCORE)
    assert "sentiment" in notes


# ============================================================
# 3. 文案辅助
# ============================================================

def test_cli_note_suffix():
    notes = {"sw_stability": "⚠数据缺失，按中性 5 分计入"}
    assert cli_note("sw_stability", notes) == " (⚠数据缺失，按中性 5 分计入)"
    assert cli_note("trend", notes) == ""
    assert cli_note("sw_stability", None) == ""


def test_notes_summary_uses_cn_labels():
    notes = {"sw_stability": "⚠数据缺失，按中性 5 分计入",
             "capital": "⚠数据缺失，按中性 8 分计入"}
    s = notes_summary(notes)
    assert "申万稳定: ⚠数据缺失，按中性 5 分计入" in s
    assert "资金: ⚠数据缺失，按中性 8 分计入" in s
    assert notes_summary({}) == ""


# ============================================================
# 4. MD 渲染集成 (10 因子打分明细表)
# ============================================================

def _make_md_result(sources):
    """最小完整 result (对齐 tests/conftest.rendered_markdown_v3 fixture 字段)。"""
    result = {
        "code": "600693",
        "name": "东百集团",
        "report_date": "2026-09-22",
        "quote": {"price": 10.00, "pe_ttm": 88.0, "pb": 2.40, "float_mcap": 86.4,
                  "limit_up": 11.00, "limit_down": 9.00, "amplitude": 3.20,
                  "turnover_rate": 4.10, "vol_ratio": 1.20},
        "valuation": {"peg": 4.20, "analyst_count": 5, "digest_years": 5},
        "valuation_hist": {"pe_percentile_3y": 92.0, "pb_percentile_3y": 55.0},
        "score": dict(_SCORE, change_pct=1.25, factors=[]),
        "advice": "中性",
        "emoji": "🟡",
        "detail": "因子缺失标注测试",
        "_md_full": True,
        "trading_plan": {
            "entry_low": 9.50, "entry_high": 9.80,
            "tp1": 10.80, "tp2": 11.50, "tp3": 12.20,
            "stop_loss": 9.20, "stop_loss_pct": -8.0,
            "position": "轻仓", "period": "1-2 周",
            "state": "neutral",
            "template_used": "【结论】中性 ｜ 【操作】分批 ｜ 【风险】止损",
        },
        "three_levels": {
            "support": 9.50, "resistance": 10.80, "stop_loss": 9.20,
            "stop_loss_method": "trading_plan",
            "support_candidates": {"ma60": 9.50},
            "resistance_candidates": {"boll_upper": 10.80},
        },
        "signals": {"good": [], "bad": []},
        "blocks": [], "fund": {}, "chip_data": {}, "lockup": {}, "dragon": {},
        "macro": {"north_label": "北向资金：市场口径"},
        "sw_data": {}, "announcements": None, "finance": None, "research": None,
        "news": None, "margin": None, "margin_hist": {}, "fund_daily5": {},
        "peers": {}, "irm": {}, "holders": {}, "dividend": {}, "board": {},
        "dragon_market": {},
        "run_log": {
            "sources": sources,
            "source_meta": {},
            "fallback_chain": [],
            "guard": {"status": "ok", "kline_freshness": {"last_bar": "2026-09-18"}},
            "started_at": "2026-09-22T10:00:00+08:00",
            "finished_at": "2026-09-22T10:00:01+08:00",
            "total_sec": 1.0,
        },
    }
    return result


def test_md_factor_table_annotates_degraded_factor():
    from analysis.report_md import write_markdown_report_v3
    r = _make_md_result({"申万分类": "error:申万表加载失败, 0ms"})
    md = write_markdown_report_v3(r)
    section = md[md.find("## 🔬 10 因子打分明细"):]
    # 申万稳定行: 得分旁标注兜底中性分 (打分不变, 仍是 5/6)
    assert "| 申万稳定 | 5 ⚠数据缺失，按中性 5 分计入 | 6 |" in section
    # 健康因子不标注
    assert "| 趋势 | 6 | 12 |" in section
    # 综合行不受影响
    assert "| **综合** | **50** | **100** |" in section


def test_md_factor_table_no_annotation_when_sources_ok():
    from analysis.report_md import write_markdown_report_v3
    r = _make_md_result({"申万分类": "ok, 123ms"})
    md = write_markdown_report_v3(r)
    section = md[md.find("## 🔬 10 因子打分明细"):]
    assert "⚠数据缺失" not in section
    assert "| 申万稳定 | 5 | 6 |" in section


def test_md_factor_table_fallback_status_also_annotated():
    from analysis.report_md import write_markdown_report_v3
    r = _make_md_result({"概念板块": "fallback:接口返回0条(可能风控), 210ms"})
    md = write_markdown_report_v3(r)
    section = md[md.find("## 🔬 10 因子打分明细"):]
    assert "| 情绪 | 4 ⚠数据缺失，按中性 4 分计入 | 8 |" in section


# ============================================================
# 5. HTML 渲染集成 (雷达图轴标签 ⚠ + 卡片脚注)
# ============================================================

def test_html_radar_marks_degraded_axis():
    import html_report as hr
    svg = hr._svg_radar(_SCORE, factor_notes={"sw_stability": "⚠数据缺失，按中性 5 分计入"})
    assert "申万⚠" in svg
    # 健康轴不加 ⚠
    assert ">趋势<" in svg
    svg_ok = hr._svg_radar(_SCORE)
    assert "申万⚠" not in svg_ok
    # 向后兼容: 旧签名 (无 factor_notes) 仍可用
    assert hr._svg_radar(_SCORE, 380, 340) == svg_ok


def test_html_radar_card_footnote_lists_missing_factors(tmp_path, monkeypatch):
    """write_html_report_v3 全量渲染: 雷达卡片脚注含缺失因子标注。

    monkeypatch 掉 Chrome PDF 渲染 (~15s/次), 只验 HTML 内容;
    PDF 链路由 tests/reporting 契约测试覆盖。
    """
    import analysis.html_report_v3 as hrv3
    monkeypatch.setattr(
        hrv3, "_render_html_to_pdf",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("pdf stubbed in test")),
    )
    r = _make_md_result({"申万分类": "error:申万表加载失败, 0ms"})
    path = hrv3.write_html_report_v3(r, str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert "申万⚠" in html
    assert "申万稳定: ⚠数据缺失，按中性 5 分计入" in html


def test_html_radar_card_no_annotation_when_sources_ok(tmp_path, monkeypatch):
    import analysis.html_report_v3 as hrv3
    monkeypatch.setattr(
        hrv3, "_render_html_to_pdf",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("pdf stubbed in test")),
    )
    r = _make_md_result({"申万分类": "ok, 123ms"})
    path = hrv3.write_html_report_v3(r, str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert "申万⚠" not in html
    assert "⚠数据缺失，按中性" not in html
