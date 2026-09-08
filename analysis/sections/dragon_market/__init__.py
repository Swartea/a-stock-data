# analysis/sections/dragon_market/__init__.py
"""§3.9 全市场龙虎榜 section — 当日全市场龙虎榜 Top 20 净买额

数据源：datacenter-web.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW
（端点验证 Part A.6 标记 datacenter-web 200/66 条，风控面独立）

SKILL.md 章节：§3.9
"""
from .fetcher import fetch_dragon_market
from .render import render_html, render_md
from .meta import DragonMarketSection

__all__ = ["DragonMarketSection", "fetch_dragon_market", "render_html", "render_md"]
