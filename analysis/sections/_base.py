# analysis/sections/_base.py
"""Section 抽象基类 — V3 报告章节插件的基础接口

每节必须实现：
- label (str): 报告中显示的简短标签
- title (str): 报告中显示的完整标题
- weight (int): 排序权重（越小越靠前）
- sort_order (int): MD 渲染中的顺序
- source_ref (str): SKILL.md 章节引用（如 "§10.1"）
- data_sources (list[str]): 依赖的 a-stock-data 端点名
- fetch(code, ctx) -> dict: 拉数据，返回 result key
- render_html(result, writer) -> str: 渲染 HTML 片段
- render_md(result, writer) -> str: 渲染 MD 片段
"""
from abc import ABC, abstractmethod
from typing import Any


class Section(ABC):
    """Section 抽象类 — 单一职责：拉数据 + 渲染"""
    label: str = ""
    title: str = ""
    weight: int = 100
    sort_order: int = 50
    source_ref: str = ""
    data_sources: list[str] = []

    @abstractmethod
    def fetch(self, code: str, ctx: dict) -> dict:
        """拉数据，返回 dict 存入 result[self.label]

        Args:
            code: 6 位股票代码
            ctx: 上下文（如 v2.fetch_full_valuation 的结果）

        Returns:
            dict 数据，或 {"error": str(e)} 兜底
        """
        pass

    @abstractmethod
    def render_html(self, result: dict, writer: list | None = None) -> str:
        """渲染 HTML 片段到 result dict

        Args:
            result: 当前节的 result key
            writer: HTML 写入列表（append 字符串）。Phase 1 灰度: 可选, 多数 section 仅用返回值, writer 保留向后兼容

        Returns:
            完整 HTML 片段字符串
        """
        pass

    @abstractmethod
    def render_md(self, result: dict, writer: list | None = None) -> str:
        """渲染 MD 片段到 result dict

        Args:
            result: 当前节的 result key
            writer: MD 写入列表（append 字符串）。Phase 1 灰度: 可选, 多数 section 仅用返回值, writer 保留向后兼容

        Returns:
            完整 MD 片段字符串
        """
        pass

    def has_error(self, result: dict) -> bool:
        """检查 result 是否有 error"""
        return isinstance(result, dict) and "error" in result
