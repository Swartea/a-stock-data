import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections.dragon_market import DragonMarketSection
from sections.dragon_market.fetcher import fetch_dragon_market, _raw_fetch
from sections.dragon_market.render import render_html, render_md


def test_dragon_market_meta():
    """Meta 数据正确性"""
    s = DragonMarketSection()
    assert s.label == "dragon_market"
    assert s.title == "🐉 龙虎榜动向（市场）"
    assert s.source_ref == "§3.9"
    assert s.sort_order == 65
    assert "daily_dragon_tiger" in s.data_sources


def test_dragon_market_fetch_with_data(monkeypatch):
    """mock _raw_fetch 返回 9-4 样本数据（66 条取 Top 20 + 排序）"""
    # 构造 25 条样本，B(500) > C(200) > A(100) 验证排序
    fake_stocks = [
        {"code": "A", "name": "A", "net_buy": 100.0, "reason": "r", "pct_chg": 5.0},
        {"code": "B", "name": "B", "net_buy": 500.0, "reason": "r", "pct_chg": 5.0},
        {"code": "C", "name": "C", "net_buy": 200.0, "reason": "r", "pct_chg": 5.0},
    ] + [
        {"code": f"X{i}", "name": f"X{i}", "net_buy": 50.0 - i,
         "reason": "r", "pct_chg": 5.0}
        for i in range(22)  # 凑足 25 条验证 Top 20 截取
    ]
    fake = {"stocks": fake_stocks, "total_records": 66}
    monkeypatch.setattr("sections.dragon_market.fetcher._raw_fetch", lambda date: fake)
    result = fetch_dragon_market(date="20260904", top_n=20)
    assert "stocks" in result
    assert "total_records" in result
    # Top 20: 应按 net_buy desc 截取到 20 条
    assert len(result["stocks"]) == 20
    # 排序后：B(500) > C(200) > A(100) 居前
    assert result["stocks"][0]["code"] == "B"
    assert result["stocks"][1]["code"] == "C"
    assert result["stocks"][2]["code"] == "A"
    # 总额 = 66 来自 mock 的 total_records
    assert result["total_records"] == 66


def test_dragon_market_fetch_handles_missing_endpoint(monkeypatch):
    """hasattr 兜底：_raw_fetch 抛错时 fetch_dragon_market 返回 error"""
    def boom(date):
        raise RuntimeError("daily_dragon_tiger 端点未就绪")
    monkeypatch.setattr("sections.dragon_market.fetcher._raw_fetch", boom)
    result = fetch_dragon_market(date="20260904")
    assert "error" in result
    assert "daily_dragon_tiger" in result["error"]


def test_dragon_market_render_html_with_data():
    """Top 20 净买额 + 总额 + 解读"""
    result = {
        "stocks": [
            {"code": "002402", "name": "和而泰", "net_buy": 6.71e8, "reason": "涨幅偏离值达7%", "pct_chg": 10.0},
            {"code": "000592", "name": "平潭发展", "net_buy": 4.84e8, "reason": "涨幅偏离值达7%", "pct_chg": 10.0},
            {"code": "600869", "name": "远东股份", "net_buy": 4.73e8, "reason": "换手率达20%", "pct_chg": 10.0},
        ],
        "total_records": 66,
    }
    html = render_html(result, [])
    assert "🐉 龙虎榜动向（市场）" in html
    assert "和而泰" in html
    assert "平潭发展" in html
    assert "远东股份" in html
    # 总额 6.71+4.84+4.73=16.28 亿
    assert "16.28" in html
    # total_records
    assert "66" in html
    # 解读：top3 净买总额 16.28亿 ≥ 10亿 → 主力大幅介入
    assert "主力大幅介入" in html


def test_dragon_market_render_md_with_data():
    """MD 渲染含表格 + 总额 + 解读"""
    result = {
        "stocks": [
            {"code": "002402", "name": "和而泰", "net_buy": 6.71e8, "reason": "涨幅偏离值达7%", "pct_chg": 10.0},
            {"code": "000592", "name": "平潭发展", "net_buy": 4.84e8, "reason": "涨幅偏离值达7%", "pct_chg": 10.0},
        ],
        "total_records": 66,
    }
    md = render_md(result, [])
    assert "🐉 龙虎榜动向（市场）" in md
    assert "和而泰" in md
    assert "平潭发展" in md
    # 净买额列
    assert "6.71亿" in md
    assert "4.84亿" in md
    # total_records
    assert "66" in md
    # 解读：top2 净买总额 11.55亿 ≥ 10亿 → 主力大幅介入
    assert "主力大幅介入" in md
    # 标题
    assert "Top 20 净买额个股" in md


def test_dragon_market_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "daily_dragon_tiger 端点未就绪"}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "端点不可用" in html
    assert "端点不可用" in md
    assert "daily_dragon_tiger" in html
    assert "daily_dragon_tiger" in md
