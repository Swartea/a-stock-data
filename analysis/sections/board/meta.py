# analysis/sections/board/meta.py
from sections._base import Section
from .fetcher import fetch_board
from .render import render_html, render_md


class BoardSection(Section):
    """§8.1-8.3 打板情绪（市场维度，非单票）"""
    label = "board"
    title = "🎰 打板情绪"
    weight = 8
    sort_order = 60
    source_ref = "§8.1-8.3"
    data_sources = ["em_zt_pool", "em_zb_pool", "em_dt_pool", "em_yzt_pool",
                    "ths_limit_up_pool", "limit_up_sentiment"]

    def fetch(self, code: str, ctx: dict) -> dict:
        # board 是市场维度，code 不影响（用今日日期）
        from datetime import datetime
        date = datetime.now().strftime("%Y%m%d")
        return fetch_board(date=date)

    def render_html(self, result: dict, writer: list | None = None) -> str:
        return render_html(result, writer if writer is not None else [])

    def render_md(self, result: dict, writer: list | None = None) -> str:
        return render_md(result, writer if writer is not None else [])
