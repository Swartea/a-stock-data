"""P2-E S2 · analysis/reporting/docx_tables.py 的单元测试

只测**迁入的 6 个符号**（§2.2 区块 6 表格 + 3 处业务阈值），**不测主流程**
（§六 S2 第 2 步的边界）。`md_to_docx()` 本体属区块 8 / S5，不在本文件断言范围内；
区块 5 的 `add_*` 属 S3、区块 7 的 `_render_md_block` 属 S4，同样不在范围内。

本模块存在的原因：S0 只锁住了「DOCX **产物**的版式语义」（语义 golden 投影），但
**迁入符号自身的取值与行为**没有任何直接断言 —— 拆分时若某个阈值抄错、某个正则
抄错，投影 golden 会红，但红在哪一句说不清。这里把每个迁入符号的契约单独钉住，
让 S2 的 diff 可被逐项复核。

零网络 / 零 live / 零外部数据：全部在内存里用 `python-docx` 建对象，不落盘、不读
`reports/`、不依赖当日跑批，也不读同目录 `result_v3-*.json`。

覆盖清单（6 个符号）：
- NUM_RANGE DATE_ONLY（2 个正则常量）
- _clean_num（1 个）
- is_numeric_like（1 个）
- _cell_add（1 个）
- flush_table（1 个，**含 3 处业务阈值逐条钉死**）
另加一组**薄壳 re-export 契约**（H2/H3）与 §六「禁止新旧两套实现并存」两条结构性断言。

死符号保留（P2E §十一 / §八 R6 / §九 第 6 条）：`NUM_RANGE` 全仓零调用点，
但本计划**一律不删**（删除属行为面清理，另开单片）。`test_dead_symbol_num_range_is_preserved`
把这条纪律变成可执行断言，防止后续片顺手删掉。

3 处业务阈值（§八 R3 / §九 第 10 条「不修改业务口径」——用户可见的版式契约）：
① 数字列 ≥60% 判定；② 「价位」表头下的「数值」列特判（含 `price_cols = [1]` 兜底）；
③ 「综合」行加粗。这三处**一个字都不能改**，本文件逐条钉住。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))

from docx import Document  # noqa: E402  # analysis/ 靠上面的 sys.path 引导
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from reporting import docx_tables as tbl  # noqa: E402


# ============================================================
# 工具
# ============================================================
def _rgb(run):
    """run 颜色; 未设色时 python-docx 抛 ValueError, 归一为 None。"""
    try:
        return run.font.color.rgb
    except (AttributeError, ValueError):
        return None


def _size_pt(run):
    return None if run.font.size is None else run.font.size.pt


def _new_stats():
    return {"headings": 0, "by_level": {}, "paragraphs": 0, "tables": 0, "cells": 0}


def _new_doc():
    return Document()


def _render(rows, doc=None, stats=None):
    """把一组 markdown 表格行喂给 flush_table, 返回 (doc, stats)。"""
    doc = doc or _new_doc()
    stats = stats if stats is not None else _new_stats()
    tbl.flush_table(doc, list(rows), stats)
    return doc, stats


def _align(p):
    return None if p.alignment is None else int(p.alignment)


def _shd_fill(cell):
    shd = cell._tc.get_or_add_tcPr().find(qn("w:shd"))
    return None if shd is None else shd.get(qn("w:fill"))


def _has_tbl_header(row):
    trPr = row._tr.find(qn("w:trPr"))
    return trPr is not None and trPr.find(qn("w:tblHeader")) is not None


# ============================================================
# 区块 6 · 两个正则常量
# ============================================================
def test_num_range_is_the_preserved_compiled_pattern():
    """NUM_RANGE 是 §十一 点名的死符号: 零调用点, 但**一律不删**（§八 R6）。"""
    assert tbl.NUM_RANGE.pattern == r"[0-9%元亿~~/,\s.+\-−—]+$"
    assert isinstance(tbl.NUM_RANGE, re.Pattern)


def test_num_range_still_matches_numeric_payloads():
    """死符号的**行为**也钉住: 迁出不得改变它的匹配面。"""
    assert tbl.NUM_RANGE.search("12.5")
    assert tbl.NUM_RANGE.search("1,234")
    assert tbl.NUM_RANGE.match("abc") is None


def test_date_only_accepts_one_or_two_digit_month_and_day():
    assert tbl.DATE_ONLY.match("2024-10-05")
    assert tbl.DATE_ONLY.match("2024-1-5")
    assert tbl.DATE_ONLY.match("2024-01-05"), "`\\d{1,2}` 允许前导零, 「01」同样匹配"
    assert tbl.DATE_ONLY.match("2024-10-055") is None, "必须锚定到串尾"
    assert tbl.DATE_ONLY.match("24-10-05") is None, "年份必须满 4 位"


# ============================================================
# 区块 6 · _clean_num
# ============================================================
def test_clean_num_strips_bold_markers():
    assert tbl._clean_num("**12.5**") == "12.5"


def test_clean_num_strips_a_whole_trailing_run_of_unit_chars():
    """`rstrip("元亿")` 削的是**结尾整段**单位字符, 故「亿元」两个字都被削掉。

    这不是笔误而是原实现的既定行为（迁入前即如此），本文件按**实际行为**钉住,
    免得后续片"顺手修正"它 —— 那属于行为面清理, 另开单片（§九 第 6 条）。
    """
    assert tbl._clean_num("12亿元") == "12"
    assert tbl._clean_num("12元") == "12"
    assert tbl._clean_num("3.2亿") == "3.2"
    assert tbl._clean_num("元12") == "元12", "只削结尾, 不削开头"


# ============================================================
# 区块 6 · is_numeric_like
# ============================================================
def test_is_numeric_like_accepts_plain_and_grouped_numbers():
    assert tbl.is_numeric_like("12.5")
    assert tbl.is_numeric_like("1,234")
    assert tbl.is_numeric_like("-3.2%")


def test_is_numeric_like_rejects_date_only_values():
    """DATE_ONLY 的语义: 日期不是数字（否则日期列会被误判成右对齐等宽列）。"""
    assert tbl.is_numeric_like("2024-10-05") is False


def test_is_numeric_like_rejects_letters_and_cjk():
    assert tbl.is_numeric_like("abc") is False
    assert tbl.is_numeric_like("12元/股") is False


def test_is_numeric_like_rejects_empty_and_whitespace():
    assert tbl.is_numeric_like("") is False
    assert tbl.is_numeric_like("   ") is False


def test_is_numeric_like_accepts_dash_placeholders():
    """占位破折号在 tokens 里被显式 continue 跳过 ⇒ 该 token 单独出现时算数字形。"""
    assert tbl.is_numeric_like("-") is True
    assert tbl.is_numeric_like("—") is True


def test_is_numeric_like_splits_on_slash_tilde_and_space():
    """区间值「1.5~2」「10/20」「1 2」按 token 逐个校验, 全部合法才算数字形。"""
    assert tbl.is_numeric_like("1.5~2") is True
    assert tbl.is_numeric_like("10/20") is True
    assert tbl.is_numeric_like("1 2") is True
    assert tbl.is_numeric_like("1.5~abc") is False, "任一 token 非法即整体非数字"


def test_is_numeric_like_ignores_bold_markers():
    """**加粗** 标记先由 _clean_num 剥掉, 否则加粗数字列会被判成非数字。"""
    assert tbl.is_numeric_like("**12.5**") is True


# ============================================================
# 区块 6 · _cell_add
# ============================================================
def test_cell_add_writes_first_paragraph_with_zero_spacing():
    doc = _new_doc()
    t = doc.add_table(rows=1, cols=1)
    p = tbl._cell_add(t.rows[0].cells[0], "x", _new_stats())
    cell_p = t.rows[0].cells[0].paragraphs[0]
    assert p._p is cell_p._p, (
        "必须写进单元格的**第一个**段落, 不得新建段落"
        "（比较底层 XML 元素: python-docx 每次访问 .paragraphs 都新建 Paragraph 代理）"
    )
    assert p.paragraph_format.space_after.pt == 0
    assert p.paragraph_format.space_before.pt == 0


def test_cell_add_defaults_to_cjk_10_5pt_non_bold():
    doc = _new_doc()
    t = doc.add_table(rows=1, cols=1)
    p = tbl._cell_add(t.rows[0].cells[0], "普通", _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 10.5
    assert r.font.bold is False
    assert r.font.name == "Microsoft YaHei", "默认走 F_CJK（docx_tables 不 import 该 token, 故钉字面量）"


def test_cell_add_parses_bold_markers_into_separate_runs():
    """**加粗** 拆成独立 run: flush_table 后续按 run 逐个改样式, 不拆就没法只加粗片段。"""
    doc = _new_doc()
    t = doc.add_table(rows=1, cols=1)
    p = tbl._cell_add(t.rows[0].cells[0], "a**b**c", _new_stats())
    assert [r.text for r in p.runs] == ["a", "b", "c"]
    assert [bool(r.font.bold) for r in p.runs] == [False, True, False]


def test_cell_add_does_not_count_stats_itself():
    """cells 计数只由 flush_table 递增（_cell_add 递增会导致双计数）。"""
    stats = _new_stats()
    doc = _new_doc()
    t = doc.add_table(rows=1, cols=1)
    tbl._cell_add(t.rows[0].cells[0], "x", stats)
    assert stats["cells"] == 0


# ============================================================
# 区块 6 · flush_table: 结构与计数器
# ============================================================
def test_flush_table_filters_markdown_separator_row():
    """`---` 分隔行不是数据行, 必须被滤掉, 否则会渲染出一条空行。"""
    doc, stats = _render(["| 价位 | 数值 |", "| --- | --- |", "| 低 | 10.5 |"])
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert len(t.rows) == 2, "表头 1 行 + 数据 1 行"
    assert [c.text for c in t.rows[1].cells] == ["低", "10.5"]


def test_flush_table_drops_table_on_all_separator_input():
    """只有分隔行（无数据）⇒ 不建表, 且必须清空入参, 否则主循环会反复重试。"""
    doc, stats = _render(["| --- | --- |"])
    assert doc.tables == [] or len(doc.tables) == 0
    assert stats["tables"] == 0
    assert stats["cells"] == 0


def test_flush_table_clears_input_rows_list():
    doc, stats = _render(["| a | b |", "| 1 | 2 |"])
    rows = ["| a | b |", "| 1 | 2 |"]
    tbl.flush_table(doc, rows, stats)
    assert rows == [], "flush_table 末尾必须 clear 入参（主循环复用同一个 list）"


def test_flush_table_pads_ragged_rows_to_max_column_count():
    doc, stats = _render(["| a | b | c |", "| 1 |"])
    t = doc.tables[0]
    assert len(t.columns) == 3
    assert t.rows[1].cells[2].text == "", "缺列补空串, 不得 IndexError"


def test_flush_table_counts_cells_tables_and_trailing_paragraph():
    doc, stats = _render(["| a | b |", "| 1 | 2 |", "| 3 | 4 |"])
    assert stats["cells"] == 6, "2 行 × 2 列 = 6 个单元格"
    assert stats["tables"] == 1
    assert stats["paragraphs"] == 1, "表后紧凑空段只加 1 段"


def test_flush_table_appends_compact_2pt_spacer_paragraph():
    doc, stats = _render(["| a |", "| 1 |"])
    last = doc.paragraphs[-1]
    assert _size_pt(last.runs[0]) == 2
    assert last.paragraph_format.space_before.pt == 4
    assert last.paragraph_format.space_after.pt == 4


def test_flush_table_marks_first_row_as_repeating_header():
    doc, stats = _render(["| a | b |", "| 1 | 2 |"])
    assert _has_tbl_header(doc.tables[0].rows[0])
    assert not _has_tbl_header(doc.tables[0].rows[1])


# ============================================================
# 区块 6 · 业务阈值 ①: 数字列 ≥60% 判定
# ============================================================
def _numeric_aligned_rows(num_numeric, total, ncols=2):
    """造一张 markdown 表, 第 1 列有 num_numeric/total 个数字形, 其余为文本。

    flush_table 的入参是**原始 markdown 行文本**（主循环里就是这么攒的）,
    不是已切好的单元格 —— 切分是 flush_table 自己的职责。
    """
    rows = ["| 名称 | 值 |"]
    for i in range(total):
        rows.append(f"| r{i} | {'1.5' if i < num_numeric else 'abc'} |")
    return rows


def test_threshold_60_percent_is_inclusive_exactly_at_boundary():
    """3/5 = 60% 必须**算**数字列（`* 100 >= 60 * len(vals)` 是含等号）。"""
    doc, _ = _render(_numeric_aligned_rows(3, 5))
    cell = doc.tables[0].rows[1].cells[1]
    assert _align(cell.paragraphs[0]) == int(WD_ALIGN_PARAGRAPH.RIGHT)


def test_threshold_just_below_60_percent_is_not_numeric_column():
    """2/5 = 40% ⇒ 不右对齐。这条与上一条一起把 60% 边界钉死在含等号一侧。"""
    doc, _ = _render(_numeric_aligned_rows(2, 5))
    cell = doc.tables[0].rows[1].cells[1]
    assert _align(cell.paragraphs[0]) != int(WD_ALIGN_PARAGRAPH.RIGHT)


def test_threshold_just_above_60_percent_is_numeric_column():
    doc, _ = _render(_numeric_aligned_rows(4, 5))
    cell = doc.tables[0].rows[1].cells[1]
    assert _align(cell.paragraphs[0]) == int(WD_ALIGN_PARAGRAPH.RIGHT)


def test_numeric_column_is_mono_but_keeps_cjk_east_asia_and_size():
    """数字列「右对齐等宽」: 只换**拉丁**字体, 字号保持 _cell_add 的 10.5pt。"""
    doc, _ = _render(_numeric_aligned_rows(3, 5))
    r = doc.tables[0].rows[1].cells[1].paragraphs[0].runs[0]
    assert r.font.name == "Consolas"
    assert r._element.rPr.rFonts.get(qn("w:eastAsia")) == "Microsoft YaHei"
    assert _size_pt(r) == 10.5


def test_header_row_is_never_treated_as_numeric_column():
    """表头行**永不**右对齐（`(not is_header)` 是硬条件）。"""
    doc, _ = _render(["| 1 | 2 |", "| 3 | 4 |", "| 5 | 6 |"])
    assert _align(doc.tables[0].rows[0].cells[0].paragraphs[0]) != int(
        WD_ALIGN_PARAGRAPH.RIGHT
    )


# ============================================================
# 区块 6 · 业务阈值 ②: 「价位」表头下的「数值」列特判
# ============================================================
def test_price_value_column_gets_11pt_bold_mono():
    """阈值②: 表头 [0]=='价位' 且某数值列表头=='数值' ⇒ 该列 11pt 加粗等宽。"""
    doc, _ = _render([
        "| 价位 | 数值 | 备注 |",
        "| --- | --- | --- |",
        "| 低 | 10.5 | x |",
        "| 中 | 11.0 | y |",
    ])
    cell = doc.tables[0].rows[1].cells[1]
    r = cell.paragraphs[0].runs[0]
    assert _size_pt(r) == 11
    assert r.font.bold is True
    assert r.font.name == "Consolas", "11pt 加粗同时是等宽"


def test_price_value_column_falls_back_to_index_1_when_not_numeric():
    """阈值②的兜底: 「数值」列没被判成数字列时, 仍强制 `price_cols = [1]`。"""
    doc, _ = _render([
        "| 价位 | 结论 | 备注 |",
        "| --- | --- | --- |",
        "| 低 | 偏空 | x |",
        "| 中 | 偏多 | y |",
    ])
    cell = doc.tables[0].rows[1].cells[1]
    r = cell.paragraphs[0].runs[0]
    assert _size_pt(r) == 11, "兜底列同样吃 11pt 加粗"
    assert r.font.bold is True


def test_price_styling_does_not_apply_to_header_row():
    """`(not is_header)` 硬条件: 表头不吃 11pt 加粗。"""
    doc, _ = _render([
        "| 价位 | 数值 |",
        "| --- | --- |",
        "| 低 | 10.5 |",
        "| 中 | 11.0 |",
    ])
    r = doc.tables[0].rows[0].cells[1].paragraphs[0].runs[0]
    assert _size_pt(r) == 10, "表头恒为 10pt（表头样式先于 price 判定执行）"


def test_non_price_table_never_gets_11pt_bold_column():
    """表头[0] 不是「价位」⇒ price_cols 为空, 任何列都不该吃 11pt。"""
    doc, _ = _render([
        "| 名称 | 数值 |",
        "| --- | --- |",
        "| 低 | 10.5 |",
        "| 中 | 11.0 |",
    ])
    r = doc.tables[0].rows[1].cells[1].paragraphs[0].runs[0]
    assert _size_pt(r) == 10.5, "非「价位」表 ⇒ 数值列只是普通数字列"


def test_price_header_match_tolerates_asterisk_prefix():
    """`strip("*")`: 表头写成 `*数值` / `*价位` 也照样命中（迁入前的原实现语义）。"""
    doc, _ = _render([
        "| *价位 | *数值 |",
        "| --- | --- |",
        "| 低 | 10.5 |",
        "| 中 | 11.0 |",
    ])
    r = doc.tables[0].rows[1].cells[1].paragraphs[0].runs[0]
    assert _size_pt(r) == 11
    assert r.font.bold is True


# ============================================================
# 区块 6 · 业务阈值 ③: 「综合」行加粗
# ============================================================
def test_comprehensive_row_is_bolded_10_5pt_dark():
    """阈值③: 行首 `strip("*").strip() == "综合"` ⇒ 该行 10.5pt 加粗深色。"""
    doc, _ = _render([
        "| 项目 | 结论 |",
        "| --- | --- |",
        "| **综合** | 偏多 |",
    ])
    r = doc.tables[0].rows[1].cells[1].paragraphs[0].runs[0]
    assert _size_pt(r) == 10.5
    assert r.font.bold is True
    assert str(_rgb(r)) == "1C1917"


def test_comprehensive_row_also_bolds_its_own_label_cell():
    doc, _ = _render([
        "| 项目 | 结论 |",
        "| --- | --- |",
        "| **综合** | 偏多 |",
    ])
    r = doc.tables[0].rows[1].cells[0].paragraphs[0].runs[0]
    assert r.font.bold is True


def test_normal_row_is_not_bolded():
    doc, _ = _render([
        "| 项目 | 结论 |",
        "| --- | --- |",
        "| 一般 | 中性 |",
    ])
    r = doc.tables[0].rows[1].cells[1].paragraphs[0].runs[0]
    assert r.font.bold is False


def test_comprehensive_row_is_not_the_header_row():
    """表头恰好叫「综合」时不得吃 bold_row（`and not is_header` 硬条件）。"""
    doc, _ = _render([
        "| 综合 | 结论 |",
        "| --- | --- |",
        "| 偏多 | 中性 |",
    ])
    r = doc.tables[0].rows[0].cells[0].paragraphs[0].runs[0]
    assert _size_pt(r) == 10, "表头恒 10pt, 不受 bold_row 影响"


# ============================================================
# 区块 6 · 表头样式与斑马纹
# ============================================================
def test_header_cells_are_10pt_bold_dark_with_bottom_border():
    doc, _ = _render(["| a | b |", "| 1 | 2 |"])
    cell = doc.tables[0].rows[0].cells[0]
    r = cell.paragraphs[0].runs[0]
    assert _size_pt(r) == 10
    assert r.font.bold is True
    assert str(_rgb(r)) == "1C1917"
    tcB = cell._tc.get_or_add_tcPr().find(qn("w:tcBorders"))
    assert tcB is not None and tcB.find(qn("w:bottom")) is not None


def test_body_cells_have_no_bottom_border():
    doc, _ = _render(["| a | b |", "| 1 | 2 |"])
    cell = doc.tables[0].rows[1].cells[0]
    tcPr = cell._tc.get_or_add_tcPr()
    tcB = tcPr.find(qn("w:tcBorders"))
    assert tcB is None, "下边框只加在表头行"


def test_zebra_shading_applies_to_odd_body_rows_only():
    """`ri % 2 == 1` 且非表头 ⇒ 第 1、3…个数据行上 FILL_ZEBRA 斑马纹。"""
    doc, _ = _render([
        "| a | b |",
        "| 1 | 2 |",
        "| 3 | 4 |",
        "| 5 | 6 |",
    ])
    t = doc.tables[0]
    assert _shd_fill(t.rows[0].cells[0]) is None, "表头不上斑马纹"
    assert _shd_fill(t.rows[1].cells[0]) == "F5F5F4"
    assert _shd_fill(t.rows[2].cells[0]) is None
    assert _shd_fill(t.rows[3].cells[0]) == "F5F5F4"


# ============================================================
# 薄壳 re-export 契约（H2 / H3）+ §六「禁止新旧两套实现并存」
# ============================================================
_MOVED_NAMES = {
    # 区块 6 表格（6 个符号 = 6 个名字, 无同行多合一）
    "NUM_RANGE", "DATE_ONLY", "_clean_num", "is_numeric_like", "_cell_add", "flush_table",
}
_MOVED_FUNCS = ("_clean_num", "is_numeric_like", "_cell_add", "flush_table")
_MOVED_CONSTS = ("NUM_RANGE", "DATE_ONLY")


def test_moved_surface_is_exactly_6_names():
    assert len(_MOVED_NAMES) == 6, "§六 S2 行: 区块 6 共 6 个符号 / 6 个名字"
    assert len(_MOVED_FUNCS) == 4
    assert len(_MOVED_CONSTS) == 2


def test_shell_reexports_every_moved_name():
    """S2 之前的 6 个顶层名字必须逐名仍在薄壳上（H2 双人格 + H3 假模块面）。

    用 hasattr 而不是 `from md_to_docx import (...)`: 后者一旦缺名会在收集期直接
    ImportError, 且报错不告诉你是**哪个**名字丢了; hasattr 一次报全部缺失。
    """
    import md_to_docx as shell

    missing = sorted(n for n in _MOVED_NAMES if not hasattr(shell, n))
    assert not missing, f"薄壳丢失 re-export 名字: {missing}"


def test_shell_reexport_values_are_identical_objects_not_copies():
    """re-export 必须是同一对象而非复制品 —— 否则薄壳与新模块会各走各的样式值。"""
    import md_to_docx as shell

    assert shell.NUM_RANGE is tbl.NUM_RANGE
    assert shell.DATE_ONLY is tbl.DATE_ONLY
    assert shell.flush_table is tbl.flush_table
    assert shell.is_numeric_like is tbl.is_numeric_like


def test_shell_no_longer_defines_moved_symbols_in_place(analysis_dir):
    """§六 硬规则「禁止新旧两套实现并存」: 薄壳不得再原地定义迁出符号。

    只查**定义**, 不查名字出现 —— re-export import 与调用点当然会出现这些名字。
    """
    src = (analysis_dir / "md_to_docx.py").read_text(encoding="utf-8")
    still_def = [n for n in _MOVED_FUNCS if re.search(rf"^def {n}\(", src, re.M)]
    assert not still_def, f"薄壳仍原地定义 {still_def} —— 新旧两套实现并存"
    still_assign = [n for n in _MOVED_CONSTS if re.search(rf"^{n}\s*=", src, re.M)]
    assert not still_assign, f"薄壳仍原地赋值 {still_assign} —— 新旧两套实现并存"


def test_three_business_thresholds_are_present_verbatim(analysis_dir):
    """3 处业务阈值逐字仍在被迁出的模块里（§八 R3 / §九 第 10 条）。

    抄错阈值会让语义 golden 红, 但「红在哪」需要人工比对; 这里先把字面钉住。
    """
    src = (analysis_dir / "reporting" / "docx_tables.py").read_text(encoding="utf-8")
    assert "is_numeric_like(v)) * 100 >= 60 * len(vals)" in src, "阈值① 60% 判定被改动"
    assert 'header[0].strip("*") == "价位"' in src, "阈值② 价位表头判定被改动"
    assert 'header[ci].strip("*") == "数值"' in src, "阈值② 数值列判定被改动"
    assert "price_cols = [1]" in src, "阈值② 兜底列被改动"
    assert 'row[0].strip("*").strip() == "综合"' in src, "阈值③ 综合行判定被改动"
