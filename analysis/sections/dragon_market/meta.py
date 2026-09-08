# analysis/sections/dragon_market/meta.py
from sections._base import Section
from .fetcher import fetch_dragon_market
from .render import render_html, render_md


class DragonMarketSection(Section):
    """§3.9 全市场龙虎榜（市场维度，非单票）"""
    label = "dragon_market"
    title = "🐉 龙虎榜动向（市场）"
    weight = 9
    sort_order = 65
    source_ref = "§3.9"
    data_sources = ["daily_dragon_tiger"]

    def fetch(self, code: str, ctx: dict) -> dict:
        # dragon_market 是市场维度，code 不影响（用今日日期）
        from datetime import datetime
        date = datetime.now().strftime("%Y%m%d")
        return fetch_dragon_market(date=date, top_n=20)

    def render_html(self, result: dict, writer: list | None = None) -> str:
        return render_html(result, writer if writer is not None else [])

    def render_md(self, result: dict, writer: list | None = None) -> str:
        return render_md(result, writer if writer is not None else [])
