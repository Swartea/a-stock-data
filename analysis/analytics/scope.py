"""Northbound-capital scope classification.

Extracted from ``analysis.pipeline`` in Phase 1C. Keep the existing business
contract and rendered labels unchanged while moving the responsibility out of
the orchestration module.
"""


def _classify_north_scope(north_data) -> tuple:
    """根据北向接口返回字段推断 scope, 返回 (scope, label)。

    Args:
        north_data: dict — V2 同花顺 dayChart 返回值
                    实际 keys: latest_hgt_yi / latest_sgt_yi / total_yi / data_points
                    个股北向 (前向兼容): stock_change_pct / stock_holding_ratio 等

    Returns:
        (scope, label) — scope ∈ {"market", "stock", "mixed", "unknown"}
                          label — 渲染层直接用的中文描述 (含 scope 关键词)
    """
    if not north_data or not isinstance(north_data, dict):
        return ("unknown", "北向数据缺失")

    # 全市场北向特征字段 (V3 实际: total_yi + latest_hgt_yi/latest_sgt_yi)
    has_market = any(
        k in north_data
        for k in (
            "total_yi",
            "total",
            "north_net",
            "sh_net",
            "sz_net",
            "latest_hgt_yi",
            "latest_sgt_yi",
            "hgt",
            "sgt",
        )
    )
    # 个股北向持股变化特征字段 (前向兼容, V3 当前未启用)
    has_stock = any(
        k in north_data
        for k in (
            "stock_change_pct",
            "stock_holding_ratio",
            "holdings_change",
            "north_holding_pct",
            "holding_ratio_chg",
        )
    )

    if has_market and not has_stock:
        # 全市场 (V3 现状): 沪 + 深 净买入 (亿)
        hgt = (
            north_data.get("latest_hgt_yi")
            or north_data.get("hgt")
            or north_data.get("sh_net")
            or 0
        )
        sgt = (
            north_data.get("latest_sgt_yi")
            or north_data.get("sgt")
            or north_data.get("sz_net")
            or 0
        )
        total = (
            north_data.get("total_yi")
            or north_data.get("total")
            or north_data.get("north_net")
            or (hgt + sgt)
        )
        # type-safe: 兜底非数字 → 0
        try:
            hgt, sgt, total = float(hgt), float(sgt), float(total)
        except (TypeError, ValueError):
            hgt, sgt, total = 0.0, 0.0, 0.0
        return (
            "market",
            f"北向资金(全市场口径): 沪股通 {hgt:+.1f} 亿 / "
            f"深股通 {sgt:+.1f} 亿 ｜ 合计 {total:+.1f} 亿",
        )

    if has_stock and not has_market:
        # 个股北向持股变化 (前向兼容, 暂未启用)
        pct = north_data.get("stock_change_pct") or north_data.get("holdings_change") or 0
        ratio = (
            north_data.get("stock_holding_ratio")
            or north_data.get("north_holding_pct")
            or 0
        )
        try:
            pct, ratio = float(pct), float(ratio)
        except (TypeError, ValueError):
            pct, ratio = 0.0, 0.0
        return (
            "stock",
            f"北向资金(个股口径): 持股变化 {pct:+.2f}% ｜ 持股比例 {ratio:.2f}%",
        )

    if has_market and has_stock:
        # 混合: 同时返回全市场 + 个股
        total = float(north_data.get("total_yi", 0) or 0)
        pct = float(north_data.get("stock_change_pct", 0) or 0)
        return (
            "mixed",
            f"北向资金(混合): 全市场 {total:+.1f} 亿 + 个股持股 {pct:+.2f}%",
        )

    return ("unknown", "北向数据口径未明")
