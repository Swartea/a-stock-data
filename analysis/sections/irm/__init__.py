# analysis/sections/irm/__init__.py
"""§10.1 互动易 section — 投资者互动问答

数据源：cninfo 巨潮 irm.cninfo.com.cn
SKILL.md 章节：§10.1
"""
from .fetcher import fetch_irm
from .render import render_html, render_md
from .meta import IRMSection

__all__ = ["IRMSection", "fetch_irm", "render_html", "render_md"]
