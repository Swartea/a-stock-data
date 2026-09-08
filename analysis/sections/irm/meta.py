# analysis/sections/irm/meta.py
from sections._base import Section
from .fetcher import fetch_irm
from .render import render_html, render_md


class IRMSection(Section):
    """§10.1 投资者互动问答"""
    label = "irm"
    title = "📞 投资者互动问答"
    weight = 5
    sort_order = 40
    source_ref = "§10.1"
    data_sources = ["cninfo_irm"]

    def fetch(self, code: str, ctx: dict) -> dict:
        return fetch_irm(code, limit=5)

    def render_html(self, result: dict, writer: list) -> str:
        return render_html(result, writer)

    def render_md(self, result: dict, writer: list) -> str:
        return render_md(result, writer)
