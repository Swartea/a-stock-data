"""Task 5.3 债 3 修法 — 北向资金口径分类 (market / stock / mixed / unknown) 测试

历史: docs/04-模板质量债.md 债 3
  - 美湖股份(603319) 报告 "北向净流入 370.5亿", 但流通市值 102 亿
  - 怀疑: 数据源把"全市场北向"当个股口径填入 (同花顺 dayChart 接口实际返回全市场)
  - 模板必须显式区分 scope, 杜绝误读

修法（Task 5.3）:
  - V3 主分析器加 _classify_north_scope(north_data) — 4 情况 (market/stock/mixed/unknown)
  - result.macro.north_scope + result.macro.north_label 注入 (与 trading_plan/three_levels 解耦)
  - MD 渲染器 (write_markdown_report_v3 "宏观底色" 段) 改读 north_label 替代 hardcode
  - HTML/DOCX 渲染器当前不渲染 宏观底色, 无须改动 (north_label 字段预留)

字段名映射 (实测 vs plan 假设 — 校准后):
  V3 实际 (同花顺 dayChart):  total_yi / latest_hgt_yi / latest_sgt_yi / data_points
  plan 假设 (已校准):          total / sh / sz
  个股北向特征 (前向兼容, 暂未启用):
    stock_change_pct / stock_holding_ratio / holdings_change / north_holding_pct
"""
import os
import sys

# 绝对 import: ROOT 加入 sys.path, 让 `from analysis.xxx import yyy` 生效
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")

import pytest

from analysis.quant_analyzer_v3 import _classify_north_scope


# ============================================================
# 4 情况覆盖 (market / stock / mixed / unknown) + 1 边界 (None)
# ============================================================
def test_market_only():
    """V3 实际: 同花顺 dayChart 返回 4 字段 (total_yi / latest_hgt_yi / latest_sgt_yi / data_points)
    → scope=market, label 含"全市场" + 沪/深/合计 三段数字。"""
    scope, label = _classify_north_scope({
        "total_yi": 370.5, "latest_hgt_yi": -9.3, "latest_sgt_yi": 379.8,
        "data_points": 262,
    })
    assert scope == "market"
    assert "全市场" in label
    assert "370.5" in label
    assert "沪股通" in label
    assert "深股通" in label


def test_market_only_alt_keys():
    """plan 假设字段名 (total/sh/sz) 也应兼容 — 兜底识别。"""
    scope, label = _classify_north_scope({"total": 100.0, "sh_net": 50.0, "sz_net": 50.0})
    assert scope == "market"
    assert "全市场" in label
    assert "100.0" in label


def test_stock_only():
    """个股北向持股变化 (前向兼容字段) → scope=stock。"""
    scope, label = _classify_north_scope({
        "stock_change_pct": 0.5, "stock_holding_ratio": 2.3,
    })
    assert scope == "stock"
    assert "个股" in label
    assert "+0.50" in label
    assert "2.30" in label


def test_stock_only_alt_keys():
    """plan 假设字段名 (holdings_change/north_holding_pct) 也兼容。"""
    scope, label = _classify_north_scope({
        "holdings_change": 0.8, "north_holding_pct": 1.5,
    })
    assert scope == "stock"
    assert "个股" in label
    assert "+0.80" in label


def test_mixed():
    """同时返回全市场 + 个股 → scope=mixed (前向兼容, V3 当前未启用)。"""
    scope, label = _classify_north_scope({
        "total_yi": 370.5, "stock_change_pct": 0.5,
    })
    assert scope == "mixed"
    assert "混合" in label or "全市场" in label
    assert "370.5" in label
    assert "0.50" in label or "+0.50" in label


def test_unknown_empty():
    """空 dict → scope=unknown, label 标"缺失"或"未明"。"""
    scope, label = _classify_north_scope({})
    assert scope == "unknown"
    assert "未明" in label or "缺失" in label


def test_unknown_ambiguous_keys():
    """非北向字段名 → scope=unknown, 不臆造市场/个股。"""
    scope, label = _classify_north_scope({"foo": 1.0, "bar": 2.0, "baz": "x"})
    assert scope == "unknown"
    assert "未明" in label or "缺失" in label


def test_unknown_none():
    """None 输入 → scope=unknown, label 标"缺失" (不抛异常)。"""
    scope, label = _classify_north_scope(None)
    assert scope == "unknown"
    assert "缺失" in label


def test_market_negative_values():
    """净流出场景 (latest_hgt_yi / latest_sgt_yi / total_yi 负数) 仍应 scope=market。"""
    scope, label = _classify_north_scope({
        "total_yi": -50.0, "latest_hgt_yi": -30.0, "latest_sgt_yi": -20.0,
        "data_points": 100,
    })
    assert scope == "market"
    assert "-50.0" in label
    assert "全市场" in label


def test_market_string_fallback():
    """异常值 (字符串) 不应崩, 兜底 0.0。"""
    scope, label = _classify_north_scope({
        "total_yi": "bad", "latest_hgt_yi": None, "latest_sgt_yi": "also bad",
    })
    assert scope == "market"
    # 字符串兜底为 0.0, label 仍生成 (不抛 KeyError/TypeError)
    assert "全市场" in label
