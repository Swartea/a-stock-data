import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections.holders import HoldersSection
from sections.holders.fetcher import fetch_holders, _raw_fetch
from sections.holders.render import render_html, render_md


def test_holders_meta():
    """Meta 数据正确性"""
    s = HoldersSection()
    assert s.label == "holders"
    assert s.title == "📊 股东户数变化"
    assert s.source_ref == "§4.3"
    assert s.sort_order == 50
    assert "holder_num_change" in s.data_sources


def test_holders_fetch_600693(monkeypatch):
    """mock _raw_fetch 返回 4 季样本数据"""
    fake = [
        {"date": "2026-06-30", "holder_num": 86517, "change_ratio": -6.80, "avg_shares_per_holder": 10054},
        {"date": "2026-03-31", "holder_num": 92831, "change_ratio": -2.10, "avg_shares_per_holder": 9367},
        {"date": "2025-12-31", "holder_num": 94823, "change_ratio": 1.20, "avg_shares_per_holder": 9171},
        {"date": "2025-09-30", "holder_num": 93700, "change_ratio": 0.50, "avg_shares_per_holder": 9280},
    ]
    monkeypatch.setattr("sections.holders.fetcher._raw_fetch", lambda code, limit: fake)
    result = fetch_holders("600693", limit=4)
    assert "rows" in result
    assert len(result["rows"]) == 4
    assert result["rows"][0]["holder_num"] == 86517
    assert result["rows"][0]["change_ratio"] == -6.80


def test_holders_render_html_with_data():
    """4 季数据 + 一句话解读"""
    result = {
        "rows": [
            {"date": "2026-06-30", "holder_num": 86517, "change_ratio": -6.80, "avg_shares_per_holder": 10054},
            {"date": "2026-03-31", "holder_num": 92831, "change_ratio": -2.10, "avg_shares_per_holder": 9367},
        ]
    }
    html = render_html(result, [])
    assert "📊 股东户数变化" in html
    assert "2026-06-30" in html
    assert "86517" in html
    # 户数↓ = 集中度上升（吸筹）
    assert "筹码集中度上升" in html or "吸筹" in html


def test_holders_render_md_with_data():
    """MD 渲染含表格 + 解读"""
    result = {
        "rows": [
            {"date": "2026-06-30", "holder_num": 86517, "change_ratio": -6.80, "avg_shares_per_holder": 10054},
            {"date": "2026-03-31", "holder_num": 92831, "change_ratio": -2.10, "avg_shares_per_holder": 9367},
        ]
    }
    md = render_md(result, [])
    assert "📊 股东户数变化" in md
    assert "2026-06-30" in md
    assert "86517" in md
    assert "筹码集中度上升" in md or "吸筹" in md


def test_holders_handles_no_data():
    """无数据兜底（v2 端点未实现时返回空 rows）"""
    result = {"rows": []}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "暂无股东户数数据" in html
    assert "暂无股东户数数据" in md
    assert "fetch_holder_num_change" in html  # 提示具体哪个端点未实现


def test_holders_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "测试错误"}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "端点不可用" in html
    assert "端点不可用" in md
