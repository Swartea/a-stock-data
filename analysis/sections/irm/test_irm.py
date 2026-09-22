import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sections.irm import IRMSection
from sections.irm.fetcher import fetch_irm
from sections.irm.render import render_html, render_md

def test_irm_meta():
    s = IRMSection()
    assert s.label == "irm"
    assert s.title == "📞 投资者互动问答"
    assert s.source_ref == "§10.1"
    assert s.sort_order == 40

def test_irm_fetch_600693(monkeypatch):
    """mock fetch 返回样本数据"""
    from sections.irm.fetcher import fetch_irm
    fake = {
        "rows": [
            {"date": "2026-09-05", "asker": "投资者A", "question": "Q1", "answer": "A1"},
        ]
    }
    monkeypatch.setattr("sections.irm.fetcher._raw_fetch", lambda code, limit: fake["rows"])
    result = fetch_irm("600693", limit=5)
    assert "rows" in result
    assert len(result["rows"]) >= 1
    assert result["rows"][0]["question"] == "Q1"

def test_irm_render_html():
    result = {"rows": [{"date": "2026-09-05", "asker": "A", "question": "Q", "answer": "A"}]}
    html = render_html(result, [])
    assert "📞 投资者互动问答" in html
    assert "投资者互动" in html or "互动易" in html
    assert "Q" in html

def test_irm_render_md():
    result = {"rows": [{"date": "2026-09-05", "asker": "A", "question": "Q", "answer": "A"}]}
    md = render_md(result, [])
    assert "📞 投资者互动问答" in md
    assert "Q" in md

def test_irm_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "测试错误"}
    html = render_html(result, [])
    assert "端点不可用" in html or "⚠️" in html
