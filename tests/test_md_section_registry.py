"""V3 Markdown Section Registry 当前渲染契约测试。

测试直接渲染 deterministic result fixture，避免依赖本地 reports/ 历史报告。
"""


SECTION_TITLES = {
    "irm": "📞 投资者互动问答",
    "holders": "📊 股东户数变化",
    "dividend": "💰 分红送转",
    "board": "🎰 打板情绪",
    "dragon_market": "🐉 龙虎榜动向（市场）",
}


def test_md_report_has_5_sections_in_body(rendered_markdown_v3):
    md = rendered_markdown_v3

    for sec_id, sec_title in SECTION_TITLES.items():
        assert sec_title in md, f"{sec_id} section 缺失 (title='{sec_title}')"


def test_md_sections_have_data_lines(rendered_markdown_v3):
    md = rendered_markdown_v3

    for sec_id, sec_title in SECTION_TITLES.items():
        idx = md.find(sec_title)
        assert idx > 0, f"{sec_id} section title 缺失"
        snippet = md[idx:idx + 500]
        has_content = (
            "###" in snippet
            or "⚠️" in snippet
            or "数据来源" in snippet
            or "数据源" in snippet
            or "📡" in snippet
            or "— " in snippet
            or "|" in snippet
        )
        assert has_content, (
            f"{sec_id} section 标题后无数据行\n"
            f"snippet: {snippet[:200]}"
        )


def test_sections_appear_before_run_log(rendered_markdown_v3):
    md = rendered_markdown_v3

    run_log_idx = md.find("## 🔗 数据链路与运行记录")
    assert run_log_idx > 0, "链路运行记录 (## 🔗) 缺失"

    for sec_id, sec_title in SECTION_TITLES.items():
        idx = md.find(sec_title)
        assert idx > 0, f"{sec_id} section 缺失"
        assert idx < run_log_idx, (
            f"{sec_id} section 位置错: 应在 run_log 之前, "
            f"但 idx={idx} > run_log_idx={run_log_idx}"
        )


def test_locked_fields_unchanged(rendered_markdown_v3):
    md = rendered_markdown_v3

    state_5 = ["🟢 强烈看多", "🟢 偏多", "🟡 中性", "🟠 偏空", "🔴 强烈看空"]
    assert any(state in md for state in state_5), "5 状态机缺失"
    assert "三价位" in md, "三价位段缺失"
    assert "宏观底色" in md, "宏观底色段缺失"
