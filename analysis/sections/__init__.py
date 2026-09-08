# analysis/sections/__init__.py
"""Section Registry — V3 报告章节插件注册表

公开 API:
- SECTIONS: 所有注册的 Section 实例列表
- enabled_sections(): 根据 registry.yaml 过滤后的启用列表
"""
import os
from typing import List
from ._base import Section

# 注册表（按 sort_order 排序）
SECTIONS: List[Section] = []

# 延迟导入具体 section（避免循环）
# 注意：5 个具体 section（irm/holders/dividend/board/dragon_market）将在
# Task 1.2 / 2.1-2.4 中逐个实现，本函数在 Phase 2 完成后才会真正被调用。
# 当前为空实现，确保 enabled_sections() 返回空列表，避免循环依赖。
def _register_sections():
    from .irm import IRMSection
    from .holders import HoldersSection
    from .dividend import DividendSection
    # from .board import BoardSection
    # from .dragon_market import DragonMarketSection
    SECTIONS.extend([
        IRMSection(),
        HoldersSection(),
        DividendSection(),
    ])
    SECTIONS.sort(key=lambda s: s.sort_order)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "registry.yaml")


def _load_disabled() -> list:
    """从 registry.yaml 读 disabled_sections"""
    if not os.path.exists(_REGISTRY_PATH):
        return []
    try:
        # 延迟导入 yaml（venv 可能未安装 pyyaml）
        import yaml
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("disabled_sections", []) or []
    except Exception:
        return []


def enabled_sections() -> List[Section]:
    """返回按 sort_order 排序的启用 section 列表"""
    if not SECTIONS:
        _register_sections()
    disabled = set(_load_disabled())
    return [s for s in SECTIONS if s.label not in disabled]


__all__ = ["Section", "SECTIONS", "enabled_sections"]
