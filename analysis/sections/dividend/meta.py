# analysis/sections/dividend/meta.py
from sections._base import Section
from .fetcher import fetch_dividend
from .render import render_html, render_md


class DividendSection(Section):
    """§4.4 分红送转"""
    label = "dividend"
    title = "💰 分红送转"
    weight = 7
    sort_order = 55
    source_ref = "§4.4"
    data_sources = ["dividend_history"]

    def fetch(self, code: str, ctx: dict) -> dict:
        return fetch_dividend(code, limit=10)

    def render_html(self, result: dict, writer: list | None = None) -> str:
        return render_html(result, writer if writer is not None else [])

    def render_md(self, result: dict, writer: list | None = None) -> str:
        return render_md(result, writer if writer is not None else [])
