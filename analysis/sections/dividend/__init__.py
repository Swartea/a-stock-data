# analysis/sections/dividend/__init__.py
"""§4.4 分红送转 section — 5 年分红表 + 分红率均值

数据源：datacenter-web.eastmoney.com RPT_SHAREBONUS_DET
SKILL.md 章节：§4.4
"""
from .fetcher import fetch_dividend
from .render import render_html, render_md
from .meta import DividendSection

__all__ = ["DividendSection", "fetch_dividend", "render_html", "render_md"]
