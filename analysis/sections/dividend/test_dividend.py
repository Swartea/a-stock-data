import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections.dividend import DividendSection
from sections.dividend.fetcher import fetch_dividend, _raw_fetch
from sections.dividend.render import render_html, render_md


def test_dividend_meta():
    """Meta 数据正确性"""
    s = DividendSection()
    assert s.label == "dividend"
    assert s.title == "💰 分红送转"
    assert s.source_ref == "§4.4"
    assert s.sort_order == 55
    assert "dividend_history" in s.data_sources


def test_dividend_fetch_600693(monkeypatch):
    """mock _raw_fetch 返回 5 年样本数据（None-safe 处理）"""
    fake = [
        {"report_date": "2026-07-17", "plan": "10派4元", "BONUS_RATIO": 0.4, "IT_RATIO": None},
        {"report_date": "2025-09-25", "plan": "10派5元", "BONUS_RATIO": 0.5, "IT_RATIO": None},
        {"report_date": "2025-07-04", "plan": "10派3元", "BONUS_RATIO": 0.3, "IT_RATIO": None},
        {"report_date": "2024-08-15", "plan": "10派2.5元", "BONUS_RATIO": 0.25, "IT_RATIO": None},
        {"report_date": "2023-09-10", "plan": "10派3元", "BONUS_RATIO": 0.3, "IT_RATIO": None},
    ]
    monkeypatch.setattr("sections.dividend.fetcher._raw_fetch", lambda code, limit: fake)
    result = fetch_dividend("600693", limit=10)
    assert "rows" in result
    assert len(result["rows"]) == 5
    assert result["rows"][0]["bonus_rmb"] == 0.4
    # None-safe: IT_RATIO=None → transfer_ratio=0
    assert result["rows"][0]["transfer_ratio"] == 0
    # bonus_rmb 字段映射
    assert result["rows"][0]["bonus_ratio"] == 0.4


def test_dividend_none_safe_bonus_ratio(monkeypatch):
    """None-safe: BONUS_RATIO=null 时字段映射要 None-safe（端点验证 Part A.3 标）"""
    fake = [
        {"report_date": "2020-08-01", "plan": "10派1元", "BONUS_RATIO": None, "IT_RATIO": None},
    ]
    monkeypatch.setattr("sections.dividend.fetcher._raw_fetch", lambda code, limit: fake)
    result = fetch_dividend("600693", limit=1)
    assert result["rows"][0]["bonus_ratio"] == 0  # null → 0（无送转）
    assert result["rows"][0]["transfer_ratio"] == 0


def test_dividend_render_html_with_data():
    """5 年数据 + 平均派息 + 解读"""
    result = {
        "rows": [
            {"report_date": "2026-07-17", "plan": "10派4元", "bonus_rmb": 0.4, "bonus_ratio": 0.4, "transfer_ratio": 0},
            {"report_date": "2025-09-25", "plan": "10派5元", "bonus_rmb": 0.5, "bonus_ratio": 0.5, "transfer_ratio": 0},
            {"report_date": "2025-07-04", "plan": "10派3元", "bonus_rmb": 0.3, "bonus_ratio": 0.3, "transfer_ratio": 0},
        ]
    }
    html = render_html(result, [])
    assert "💰 分红送转" in html
    assert "2026-07-17" in html
    assert "10派4元" in html
    # 平均派息 = (0.4+0.5+0.3)/3 = 0.4
    assert "0.40" in html
    # 解读：avg >= 0.3 → 持续回报能力强
    assert "持续回报能力强" in html


def test_dividend_render_md_with_data():
    """MD 渲染含表格 + 解读"""
    result = {
        "rows": [
            {"report_date": "2026-07-17", "plan": "10派4元", "bonus_rmb": 0.4, "bonus_ratio": 0.4, "transfer_ratio": 0},
            {"report_date": "2025-09-25", "plan": "10派5元", "bonus_rmb": 0.5, "bonus_ratio": 0.5, "transfer_ratio": 0},
        ]
    }
    md = render_md(result, [])
    assert "💰 分红送转" in md
    assert "2026-07-17" in md
    assert "10派4元" in md
    assert "0.45" in md  # (0.4+0.5)/2
    assert "持续回报能力强" in md


def test_dividend_handles_no_data():
    """无数据兜底（v2 端点未实现时返回空 rows）"""
    result = {"rows": []}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "暂无分红数据" in html
    assert "暂无分红数据" in md
    assert "fetch_dividend_history" in html  # 提示具体哪个端点未实现


def test_dividend_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "测试错误"}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "端点不可用" in html
    assert "端点不可用" in md
