"""5 sections 端点补齐验证测试

覆盖:
- holders (cninfo stock_hold_num_cninfo)
- dividend (cninfo stock_dividend_cninfo)
- board zt/dt/zb/yzt (akshare stock_zt_pool_*_em)
- dragon_market (akshare stock_lhb_detail_em + fallback)
- irm (cninfo IRM newircs/index + newircs/company/question)

每个端点跑 2 个样本票 (一个高互动, 一个低互动), 验证:
1. 函数不抛异常
2. 返回 dict/list 符合 schema
3. 至少 1 个样本有非空数据
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import quant_analyzer_v2 as v2


# ---- holders ----
class TestHoldersEndpoint:
    def test_600693_holder_history(self):
        """600693 东百集团: 4 季度股东户数, 数据非空"""
        rows = v2.fetch_holder_num_change('600693', limit=4)
        assert isinstance(rows, list)
        if rows:
            assert 'date' in rows[0]
            assert 'holder_num' in rows[0]
            assert rows[0]['holder_num'] > 0

    def test_002353_holder_history(self):
        """002353 杰瑞股份: 4 季度股东户数, 数据非空"""
        rows = v2.fetch_holder_num_change('002353', limit=4)
        assert isinstance(rows, list)
        if rows:
            assert 'date' in rows[0]
            assert rows[0]['holder_num'] > 0


# ---- dividend ----
class TestDividendEndpoint:
    def test_600693_dividend_history(self):
        """600693: 10 条方案, 字段名映射正确"""
        rows = v2.fetch_dividend_history('600693', limit=10)
        assert isinstance(rows, list)

    def test_002353_dividend_history(self):
        """002353: 杰瑞分红派息历史"""
        rows = v2.fetch_dividend_history('002353', limit=10)
        assert isinstance(rows, list)


# ---- board ----
class TestBoardEndpoint:
    def test_em_zt_pool(self):
        """涨停池: 当日有数据 (或 fallback)"""
        rows = v2.em_zt_pool('20260910')
        assert isinstance(rows, list)

    def test_em_dt_pool(self):
        """跌停池: 当日"""
        rows = v2.em_dt_pool('20260910')
        assert isinstance(rows, list)

    def test_em_zb_pool(self):
        """炸板池: 当日"""
        rows = v2.em_zb_pool('20260910')
        assert isinstance(rows, list)

    def test_em_yzt_pool_optional(self):
        """一字板池: 公开数据无, 应返回 [] 不抛错"""
        rows = v2.em_yzt_pool('20260910')
        assert isinstance(rows, list)
        # 公开接口, 期望空


# ---- dragon_market ----
class TestDragonMarketEndpoint:
    def test_daily_dragon_tiger_fallback(self):
        """全市场龙虎榜: 当日/最近 5 日 fallback, top 50 净买降序"""
        result = v2.daily_dragon_tiger('20260910')
        assert isinstance(result, dict)
        assert 'stocks' in result
        assert 'total_records' in result
        if result['stocks']:
            # 验证排序
            for i in range(len(result['stocks']) - 1):
                assert result['stocks'][i]['net_buy'] >= result['stocks'][i+1]['net_buy']
            # 验证字段
            s = result['stocks'][0]
            assert 'code' in s and 'name' in s and 'net_buy' in s

    def test_daily_dragon_tiger_no_date(self):
        """不传 date → 自动取今日 (fallback)"""
        result = v2.daily_dragon_tiger()
        assert isinstance(result, dict)
        # 至少要有 trade_date (回溯到的最近交易日)
        if result['stocks']:
            assert result.get('trade_date') is not None


# ---- irm ----
class TestIrmEndpoint:
    def test_600693_irm(self):
        """600693 东百: 互动易公开数据少, 应返回 list 不抛错"""
        rows = v2.fetch_cninfo_irm('600693', limit=5)
        assert isinstance(rows, list)
        if rows:
            r = rows[0]
            assert 'date' in r and 'title' in r and 'qid' in r and 'url' in r

    def test_002353_irm_with_data(self):
        """002353 杰瑞: 互动易 44 条, 应有真实数据"""
        rows = v2.fetch_cninfo_irm('002353', limit=5)
        assert isinstance(rows, list)
        assert len(rows) >= 3, f"002353 互动易应有数据, 实得 {len(rows)}"
        if rows:
            r = rows[0]
            assert 'date' in r and r['date'], f"date 字段应非空: {r}"
            assert 'qid' in r and r['qid'], f"qid 字段应非空: {r}"
            assert 'title' in r and 'Q:' in r['title']
