from analysis.analytics.scope import _classify_north_scope


def test_north_scope_unknown_when_missing():
    assert _classify_north_scope(None) == ("unknown", "北向数据缺失")
    assert _classify_north_scope({}) == ("unknown", "北向数据缺失")


def test_north_scope_unknown_when_fields_do_not_identify_scope():
    assert _classify_north_scope({"data_points": []}) == (
        "unknown",
        "北向数据口径未明",
    )


def test_north_scope_market_preserves_current_label_contract():
    scope, label = _classify_north_scope(
        {
            "latest_hgt_yi": -9.3,
            "latest_sgt_yi": 379.8,
            "total_yi": 370.5,
        }
    )

    assert scope == "market"
    assert label == "北向资金(全市场口径): 沪股通 -9.3 亿 / 深股通 +379.8 亿 ｜ 合计 +370.5 亿"


def test_north_scope_market_supports_legacy_aliases():
    scope, label = _classify_north_scope({"hgt": 1.2, "sgt": -0.2, "total": 1.0})

    assert scope == "market"
    assert "沪股通 +1.2 亿" in label
    assert "深股通 -0.2 亿" in label
    assert "合计 +1.0 亿" in label


def test_north_scope_stock_preserves_current_label_contract():
    scope, label = _classify_north_scope(
        {"stock_change_pct": 1.25, "stock_holding_ratio": 3.4}
    )

    assert scope == "stock"
    assert label == "北向资金(个股口径): 持股变化 +1.25% ｜ 持股比例 3.40%"


def test_north_scope_mixed_preserves_current_label_contract():
    scope, label = _classify_north_scope(
        {"total_yi": 10.0, "stock_change_pct": -0.25}
    )

    assert scope == "mixed"
    assert label == "北向资金(混合): 全市场 +10.0 亿 + 个股持股 -0.25%"


def test_north_scope_market_non_numeric_values_fall_back_to_zero():
    scope, label = _classify_north_scope(
        {
            "latest_hgt_yi": "bad",
            "latest_sgt_yi": 1,
            "total_yi": 2,
        }
    )

    assert scope == "market"
    assert label == "北向资金(全市场口径): 沪股通 +0.0 亿 / 深股通 +0.0 亿 ｜ 合计 +0.0 亿"
