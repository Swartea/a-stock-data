# analysis/sections/holders/meta.py
from sections._base import Section
from .fetcher import fetch_holders
from .render import render_html, render_md


class HoldersSection(Section):
    """§4.3 股东户数变化"""
    label = "holders"
    title = "📊 股东户数变化"
    weight = 6
    sort_order = 50
    source_ref = "§4.3"
    data_sources = ["holder_num_change"]

    def fetch(self, code: str, ctx: dict) -> dict:
        return fetch_holders(code, limit=4)

    def render_html(self, result: dict, writer: list | None = None) -> str:
        return render_html(result, writer if writer is not None else [])

    def render_md(self, result: dict, writer: list | None = None) -> str:
        return render_md(result, writer if writer is not None else [])
