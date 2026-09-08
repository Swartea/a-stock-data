# analysis/sections/holders/__init__.py
"""§4.3 股东户数 section — 季度股东户数变化趋势

数据源：datacenter-web.eastmoney.com RPT_HOLDERNUMLATEST
SKILL.md 章节：§4.3
"""
from .fetcher import fetch_holders
from .render import render_html, render_md
from .meta import HoldersSection

__all__ = ["HoldersSection", "fetch_holders", "render_html", "render_md"]
