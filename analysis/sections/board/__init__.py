# analysis/sections/board/__init__.py
"""§8.1-8.3 打板情绪 section — 当日涨停 Top 10 + 炸板率 + 连板高度

数据源：
- em_zt_pool / em_zb_pool / em_dt_pool / em_yzt_pool（东财 push2ex 四池）
- ths_limit_up_pool（同花顺涨停原因）
- limit_up_sentiment（§8.3 由四池派生，0 额外网络）
SKILL.md 章节：§8.1 / §8.2 / §8.3
"""
from .fetcher import fetch_board
from .render import render_html, render_md
from .meta import BoardSection

__all__ = ["BoardSection", "fetch_board", "render_html", "render_md"]
