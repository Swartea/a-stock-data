import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections.board import BoardSection
from sections.board.fetcher import fetch_board, _raw_fetch
from sections.board.render import render_html, render_md


def test_board_meta():
    """Meta 数据正确性"""
    s = BoardSection()
    assert s.label == "board"
    assert s.title == "🎰 打板情绪"
    assert s.source_ref == "§8.1-8.3"
    assert s.sort_order == 60
    # 4 池 + 涨停原因 + 情绪派生 = 6 端点
    assert "em_zt_pool" in s.data_sources
    assert "em_zb_pool" in s.data_sources
    assert "em_dt_pool" in s.data_sources
    assert "em_yzt_pool" in s.data_sources
    assert "ths_limit_up_pool" in s.data_sources
    assert "limit_up_sentiment" in s.data_sources


def test_board_fetch_with_data(monkeypatch):
    """mock _raw_fetch 返回 9-4 样本数据（39 涨停 + 9 跌停）"""
    fake = {
        "zt": [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0, "pct": 10.0,
             "amount": 0, "float_cap": 0, "turnover": 1.0, "limit_days": 3,
             "first_seal": "09:31:00", "last_seal": "09:31:00",
             "seal_fund": 5.0e8, "break_times": 0, "industry": "白酒",
             "zt_stat": "3天3板"},
            {"code": "601318", "name": "中国平安", "price": 50.0, "pct": 10.0,
             "amount": 0, "float_cap": 0, "turnover": 2.0, "limit_days": 2,
             "first_seal": "10:00:00", "last_seal": "10:00:00",
             "seal_fund": 1.0e8, "break_times": 0, "industry": "保险",
             "zt_stat": "2天2板"},
        ],
        "dt": [
            {"code": "002400", "name": "省广集团", "price": 5.0, "pct": -10.0,
             "turnover": 0.5, "pe": 0, "seal_fund": 8.0e7,
             "last_seal": "14:00:00", "board_amount": 0, "dt_days": 1,
             "open_times": 0, "industry": "传媒"},
        ],
        "limit_up_reasons": [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0, "pct": 10.0,
             "reason": "白酒涨价+消费回暖", "board_type": "换手板",
             "seal_rate": 1.0, "break_times": 0, "seal_amount": 5.0e8,
             "high_days": "3天3板", "first_time": "09:31:00", "is_again": 0},
        ],
        "sentiment": {
            "date": "20260904", "zt_count": 39, "zb_count": 12, "dt_count": 9,
            "break_rate": 23.5, "max_height": 6, "ladder": {"1": 20, "2": 10, "3": 5, "6": 1},
        },
    }
    monkeypatch.setattr("sections.board.fetcher._raw_fetch", lambda date: fake)
    result = fetch_board(date="20260904")
    assert "zt" in result
    assert "dt" in result
    assert "limit_up_reasons" in result
    assert "sentiment" in result
    assert len(result["zt"]) == 2
    assert result["sentiment"]["zt_count"] == 39
    assert result["sentiment"]["max_height"] == 6


def test_board_fetch_handles_missing_endpoints(monkeypatch):
    """hasattr 兜底：_raw_fetch 抛错时 fetch_board 返回 error"""
    def boom(date):
        raise RuntimeError("打板端点未全部就绪: 缺 em_zt_pool")
    monkeypatch.setattr("sections.board.fetcher._raw_fetch", boom)
    result = fetch_board(date="20260904")
    assert "error" in result
    assert "未全部就绪" in result["error"]


def test_board_render_html_with_data():
    """情绪摘要 + Top 10 涨停 + 涨停原因 + 跌停池"""
    result = {
        "zt": [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0, "pct": 10.0,
             "amount": 0, "float_cap": 0, "turnover": 1.0, "limit_days": 3,
             "first_seal": "09:31:00", "last_seal": "09:31:00",
             "seal_fund": 5.0e8, "break_times": 0, "industry": "白酒",
             "zt_stat": "3天3板"},
            {"code": "601318", "name": "中国平安", "price": 50.0, "pct": 10.0,
             "amount": 0, "float_cap": 0, "turnover": 2.0, "limit_days": 2,
             "first_seal": "10:00:00", "last_seal": "10:00:00",
             "seal_fund": 1.0e8, "break_times": 0, "industry": "保险",
             "zt_stat": "2天2板"},
        ],
        "dt": [
            {"code": "002400", "name": "省广集团", "price": 5.0, "pct": -10.0,
             "turnover": 0.5, "pe": 0, "seal_fund": 8.0e7,
             "last_seal": "14:00:00", "board_amount": 0, "dt_days": 1,
             "open_times": 0, "industry": "传媒"},
        ],
        "limit_up_reasons": [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0, "pct": 10.0,
             "reason": "白酒涨价+消费回暖", "board_type": "换手板",
             "seal_rate": 1.0, "break_times": 0, "seal_amount": 5.0e8,
             "high_days": "3天3板", "first_time": "09:31:00", "is_again": 0},
        ],
        "sentiment": {
            "date": "20260904", "zt_count": 39, "zb_count": 12, "dt_count": 9,
            "break_rate": 23.5, "max_height": 6, "ladder": {"1": 20, "2": 10, "3": 5, "6": 1},
        },
    }
    html = render_html(result, [])
    assert "🎰 打板情绪" in html
    assert "贵州茅台" in html
    assert "中国平安" in html
    assert "省广集团" in html
    assert "白酒涨价+消费回暖" in html
    # 情绪摘要
    assert "39" in html  # zt_count
    assert "23.5" in html  # break_rate
    assert "6" in html  # max_height
    # 解读：zt_count=39 (>=20, <50) → 情绪中性偏暖
    assert "情绪" in html
    # 连板梯队
    assert "连板梯队" in html


def test_board_render_md_with_data():
    """MD 渲染含表格 + 情绪摘要 + 连板梯队"""
    result = {
        "zt": [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0, "pct": 10.0,
             "amount": 0, "float_cap": 0, "turnover": 1.0, "limit_days": 3,
             "first_seal": "09:31:00", "last_seal": "09:31:00",
             "seal_fund": 5.0e8, "break_times": 0, "industry": "白酒",
             "zt_stat": "3天3板"},
        ],
        "dt": [],
        "limit_up_reasons": [],
        "sentiment": {
            "date": "20260904", "zt_count": 39, "zb_count": 12, "dt_count": 9,
            "break_rate": 23.5, "max_height": 6, "ladder": {"1": 20, "2": 10, "3": 5, "6": 1},
        },
    }
    md = render_md(result, [])
    assert "🎰 打板情绪" in md
    assert "贵州茅台" in md
    assert "5.00亿" in md  # 封板资金
    assert "39" in md
    assert "23.5" in md
    assert "6" in md
    assert "连板梯队" in md
    assert "6板:1家" in md


def test_board_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "打板端点未全部就绪: 缺 em_zt_pool"}
    html = render_html(result, [])
    md = render_md(result, [])
    assert "端点不可用" in html
    assert "端点不可用" in md
    assert "未全部就绪" in html
    assert "未全部就绪" in md
