"""V3 Markdown 当前渲染契约测试。

所有断言都基于 deterministic result fixture 实时渲染，不读取 reports/ 历史产物。
"""


def test_md_has_30s_decision_card(rendered_markdown_v3):
    md = rendered_markdown_v3

    assert "## 🎯 30 秒决策卡" in md
    assert "💰 现价" in md
    assert "📊 涨跌" in md
    assert "🏭 流通市值" in md
    assert "📈 PE(TTM)" in md
    assert "📉 PB" in md
    assert "📊 PE 分位" in md
    assert "🎯 PEG" in md


def test_md_has_current_three_levels_table(rendered_markdown_v3):
    """当前三价位契约是现价 + 操作支撑/压力 + 参考支撑/压力 + 止损。"""
    md = rendered_markdown_v3

    assert "### 🎯 三价位" in md
    assert "💰 **现价**" in md
    assert "🟢 **操作支撑位**" in md
    assert "🔴 **操作压力位**" in md
    assert "📌 **参考支撑位**" in md
    assert "📌 **参考压力位**" in md
    assert "🟡 **止损位**" in md
    assert "距现价" in md
    assert "0% (参考)" in md


def test_md_has_operation_proverb_5state(rendered_markdown_v3):
    md = rendered_markdown_v3

    assert "### 💰 操作口诀" in md
    assert "【结论】" in md
    assert "【操作】" in md
    assert "【风险】" in md
    assert "多目标价" in md
    assert "买入区间" in md
    assert "周期" in md
    assert "🔒" in md
    assert "V2 同源实时模型" in md


def test_md_peg_4tier_threshold(rendered_markdown_v3):
    md = rendered_markdown_v3

    decision_section = md.split("## 🚨 风险警报区")[0]
    assert "极贵" in decision_section


def test_md_has_candidates_blockquote(rendered_markdown_v3):
    md = rendered_markdown_v3

    for cand in ["ma60", "recent_low", "chip_peak", "boll_lower"]:
        assert cand in md

    for cand in ["ma250_or_ma120", "recent_high", "boll_upper"]:
        assert cand in md
