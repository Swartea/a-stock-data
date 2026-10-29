"""P2-E S3 · analysis/reporting/docx_paragraphs.py 的单元测试

只测**迁入的 4 个符号**（§2.2 区块 5 样式段落），**不测主流程**（§六 S3 第 2 步的
边界）。`md_to_docx()` 本体属区块 8 / S5，不在本文件断言范围内；区块 6 的
`flush_table` 属 S2、区块 7 的 `_render_md_block` 属 S4，同样不在范围内。

本模块存在的原因：S0 的语义 golden 只锁住了「DOCX **产物**的版式语义」，但
**迁入符号自身的分支判定与取值**没有直接断言 —— 拆分时若某个关键词分支抄错、
某个字号抄错，投影 golden 会红，但「红在哪一句」说不清。这里把每个迁入符号的
契约单独钉住，让 S3 的 diff 可被逐项复核。

S3 是本计划**风险最高的一片**（§八 R3「高」）：区块 5 含**全部中文关键词分支**
（`看空|看多` / `数据来源` / `⚠` / `⚠️ 免责声明` / 风险区 `🔴🟡🟢`），
这些是 `docs/08-规范整改-plan.md:75`「不修改业务口径」下的**用户可见文案契约**。
因此本文件对「分支顺序」「关键字面量」「字号/颜色」逐条钉死。

**关于颜色断言的一个重要口径**（实测自 S3 首次运行, 勿再改回去）：`add_runs` /
`add_body` 的 emoji 段**不上色**（`add_runs` 的 `rcol = None if (emoji or …)`，
即「emoji 保持本色」）。因此凡是以 `⚠` / `🔴` 开头的用例，`runs[0]` 是 emoji 段、
**颜色为 None**，真正的业务色在后续 run 上。本文件按此**实际行为**钉住。

零网络 / 零 live / 零外部数据：全部在内存里用 `python-docx` 建对象，不落盘、不读
`reports/`、不依赖当日跑批，也不读同目录 `result_v3-*.json`。

覆盖清单（4 个符号）：
- add_heading（1 个，含 `min(level, 4)` 截断与四档样式）
- add_quote（1 个，**五条分支**按 §7.2 门 4 的顺序逐条钉死）
- RISK_EMOJI（1 个常量三元组）
- add_body（1 个，含 disclaimer / risk_zone / 列表剥前缀三态）
另加：薄壳 re-export 契约（H2/H3）、§六「禁止新旧两套实现并存」、
§2.1 符号行预算 90 的 AST 复算、以及关键字面量的源码逐字留存。
"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))

from docx import Document  # noqa: E402  # analysis/ 靠上面的 sys.path 引导
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from reporting import docx_paragraphs as para  # noqa: E402


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


def _text(p):
    return "".join(r.text for r in p.runs)


def _colored_runs(p):
    """只取真正**上了色**的 run（滤掉 emoji 段）。"""
    return [r for r in p.runs if _rgb(r) is not None]


def _pbdr(p):
    """段落边框 → {edge: (val, sz, space, color)}; 无边框返回 {}。"""
    pBdr = p._p.get_or_add_pPr().find(qn("w:pBdr"))
    if pBdr is None:
        return {}
    out = {}
    for child in pBdr:
        out[child.tag.split("}")[-1]] = (
            child.get(qn("w:val")), child.get(qn("w:sz")),
            child.get(qn("w:space")), child.get(qn("w:color")),
        )
    return out


def _east_asia(run):
    return run._element.rPr.rFonts.get(qn("w:eastAsia"))


def _align(p):
    return None if p.alignment is None else int(p.alignment)


# ============================================================
# 区块 5 · add_heading
# ============================================================
def test_h1_is_centered_20pt_bold_dark_with_bottom_hairline():
    doc = Document()
    stats = _new_stats()
    p = para.add_heading(doc, "标题", 1, stats)
    r = p.runs[0]
    assert _align(p) == int(WD_ALIGN_PARAGRAPH.CENTER)
    assert _size_pt(r) == 20
    assert r.font.bold is True
    assert str(_rgb(r)) == "1C1917"
    assert _pbdr(p)["bottom"] == ("single", "8", "4", "E7E5E4")


def test_h2_is_14pt_bold_accent_with_no_border():
    doc = Document()
    p = para.add_heading(doc, "章节", 2, _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 14
    assert r.font.bold is True
    assert str(_rgb(r)) == "2563EB"
    assert _pbdr(p) == {}, "只有 H1 有下边框"


def test_h3_is_11_5pt_bold_dark():
    doc = Document()
    p = para.add_heading(doc, "小节", 3, _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 11.5
    assert r.font.bold is True
    assert str(_rgb(r)) == "1C1917"


def test_h4_and_deeper_fall_through_to_the_muted_else_branch():
    """`else` 分支兜住 lv>=4; `min(level, 4)` 保证 H5/H6 与 H4 同款。"""
    doc = Document()
    for lv in (4, 5, 6):
        r = para.add_heading(doc, "x", lv, _new_stats()).runs[0]
        assert _size_pt(r) == 10.5, f"lv={lv}"
        assert r.font.bold is True, f"lv={lv}"
        assert str(_rgb(r)) == "57534E", f"lv={lv}"


def test_level_is_clamped_to_4_before_any_branching():
    """`lv = min(level, 4)` 是先截断再分支 —— H9 走 else 而非 lv==4 专属路径。"""
    doc = Document()
    stats = _new_stats()
    para.add_heading(doc, "x", 9, stats)
    assert stats["by_level"] == {4: 1}, "by_level 的键必须是截断后的 lv"


def test_heading_increments_headings_and_by_level_counters():
    stats = _new_stats()
    doc = Document()
    for _ in range(3):
        para.add_heading(doc, "a", 2, stats)
    para.add_heading(doc, "b", 3, stats)
    assert stats["headings"] == 4
    assert stats["by_level"] == {2: 3, 3: 1}
    assert stats["paragraphs"] == 0, "add_heading 不碰 paragraphs 计数"


def test_heading_uses_cjk_font_for_latin_and_east_asia():
    doc = Document()
    r = para.add_heading(doc, "x", 1, _new_stats()).runs[0]
    assert r.font.name == "Microsoft YaHei"
    assert _east_asia(r) == "Microsoft YaHei"


# ============================================================
# 区块 5 · add_quote（五条分支, 顺序敏感）
# ============================================================
def test_quote_always_indents_and_counts_one_paragraph():
    doc = Document()
    stats = _new_stats()
    p = para.add_quote(doc, "普通行", stats)
    assert p.paragraph_format.left_indent.inches == 0.1
    assert stats["paragraphs"] == 1


def test_quote_bear_branch_is_14pt_bold_green_with_thick_green_left_border():
    """分支① 看空 → A股绿(跌)。左边框 sz=18 是全文件最粗的一条。"""
    doc = Document()
    p = para.add_quote(doc, "看空", _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 14
    assert r.font.bold is True
    assert str(_rgb(r)) == "15803D"
    assert _pbdr(p)["left"] == ("single", "18", "4", "15803D")


def test_quote_bull_branch_is_14pt_bold_red_with_thick_red_left_border():
    doc = Document()
    p = para.add_quote(doc, "看多", _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 14
    assert str(_rgb(r)) == "DC2626"
    assert _pbdr(p)["left"] == ("single", "18", "4", "DC2626")


def test_quote_conclusion_flag_triggers_branch_without_any_keyword():
    """`in_conclusion` 短路整个正则 —— 无「看空/看多」字样也进大字分支。"""
    doc = Document()
    p = para.add_quote(doc, "结论汇总", _new_stats(), in_conclusion=True)
    assert _size_pt(p.runs[0]) == 14
    assert _pbdr(p)["left"][3] == "DC2626", "无「看空」⇒ 落到 A股红"


def test_quote_score_token_takes_the_bull_bear_sentence_color():
    """`re.fullmatch(r"\\s*\\d+/\\d+\\s*", seg)` 把纯评分 segment 也上结论色。

    该规则作用在 `md_runs` 切出的**单个 segment** 上, 故用 `**3/5**` 让评分独占
    一个 segment; 无「看空」字样 ⇒ `bear=False` ⇒ 落到 A股红, 从而与 C_DARK 支
    **可区分**（若该规则被删, 这里会变成 1C1917）。
    """
    doc = Document()
    p = para.add_quote(doc, "**3/5**", _new_stats(), in_conclusion=True)
    assert len(p.runs) == 1, "**3/5** 切成一个 segment"
    assert p.runs[0].text == "3/5"
    assert str(_rgb(p.runs[0])) == "DC2626", "评分 token 走结论色, 而非 C_DARK"
    assert _size_pt(p.runs[0]) == 14


def test_quote_emoji_run_stays_uncolored_inside_the_conclusion_branch():
    """分支① 内 emoji 不上结论色 —— 走 `if emoji` 的 C_DARK 支, 与其余段可区分。"""
    doc = Document()
    p = para.add_quote(doc, "看空 ⚠️ 风险", _new_stats())
    emoji_runs = [r for r in p.runs if "⚠" in r.text]
    assert emoji_runs, "fixture 应产生一个含 ⚠️ 的 run"
    assert str(_rgb(emoji_runs[0])) == "1C1917"


def test_quote_data_source_branch_is_9pt_muted_with_hairline_border():
    doc = Document()
    p = para.add_quote(doc, "数据来源: 腾讯", _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 9
    assert str(_rgb(r)) == "57534E"
    assert _pbdr(p)["left"] == ("single", "6", "3", "E7E5E4")


def test_quote_warning_branch_is_10pt_amber_with_medium_border():
    """分支③: `⚠` 本身是 emoji 段（不上色）, 业务色落在其后的文字段。"""
    doc = Document()
    p = para.add_quote(doc, "⚠ 口径说明", _new_stats())
    assert _size_pt(p.runs[0]) == 10, "全段同为 10pt"
    assert _rgb(p.runs[0]) is None, "emoji 段保持本色"
    assert str(_rgb(_colored_runs(p)[0])) == "B45309"
    assert _pbdr(p)["left"] == ("single", "10", "3", "B45309")


def test_quote_default_branch_is_9_5pt_muted_with_hairline_border():
    doc = Document()
    p = para.add_quote(doc, "随便一句", _new_stats())
    r = p.runs[0]
    assert _size_pt(r) == 9.5
    assert str(_rgb(r)) == "57534E"
    assert _pbdr(p)["left"] == ("single", "6", "3", "E7E5E4")


def test_data_source_keyword_wins_over_the_warning_branch():
    """分支顺序契约: 「数据来源」先于「⚠」判定, 同时命中时走 ② 不走 ③。"""
    doc = Document()
    p = para.add_quote(doc, "⚠ 数据来源: 腾讯", _new_stats())
    assert _size_pt(p.runs[0]) == 9, "命中②的 9pt, 而非③的 10pt"
    assert str(_rgb(_colored_runs(p)[0])) == "57534E", "② 的 C_MUTED 而非③的 C_AMBER"


def test_bull_bear_keyword_wins_over_data_source():
    doc = Document()
    p = para.add_quote(doc, "看多 数据来源", _new_stats())
    assert _size_pt(p.runs[0]) == 14, "命中①的大字, 而非②的 9pt"


# ============================================================
# 区块 5 · RISK_EMOJI
# ============================================================
def test_risk_emoji_is_the_preserved_three_tuple():
    """RISK_EMOJI 是 `add_body` 的活依赖（不是死代码）, 但**元组字面不得改**:
    顺序决定 `for ... break` 的命中优先级, 三色是用户可见文案契约。

    注意 `RGBColor` 与 `str` 不相等, 故逐项取 `str()` 再比。
    """
    got = tuple((emoji, str(color)) for emoji, color in para.RISK_EMOJI)
    assert got == (("🔴", "DC2626"), ("🟡", "B45309"), ("🟢", "15803D"))


def test_risk_emoji_colors_are_identical_objects_not_copies():
    """元组里的颜色必须是 docx_primitives 的同一对象, 否则两套色值会漂。"""
    from reporting import docx_primitives as prim

    assert para.RISK_EMOJI[0][1] is prim.C_RED
    assert para.RISK_EMOJI[1][1] is prim.C_AMBER
    assert para.RISK_EMOJI[2][1] is prim.C_GREEN


# ============================================================
# 区块 5 · add_body
# ============================================================
def test_body_plain_line_is_10_5pt_with_no_explicit_color():
    """`add_runs(p, text, size=10.5)` 的 `color` 默认 None ⇒ run 不带显式色。

    这是迁入前的原行为（正文靠 Normal style 的深色兜底）, 按**实际行为**钉住,
    免得后续片"顺手补色" —— 那属行为面变更, 不在结构拆分授权内（§九 第 6 条）。
    """
    doc = Document()
    stats = _new_stats()
    p = para.add_body(doc, "普通正文", stats)
    r = p.runs[0]
    assert _size_pt(r) == 10.5
    assert _rgb(r) is None
    assert stats["paragraphs"] == 1
    assert _pbdr(p) == {}


def test_body_preserves_bold_markers():
    doc = Document()
    p = para.add_body(doc, "这是**重点**内容", _new_stats())
    assert [(r.text, r.font.bold) for r in p.runs] == [
        ("这是", False), ("重点", True), ("内容", False),
    ]


def test_body_disclaimer_is_9pt_muted_with_top_hairline_and_early_return():
    doc = Document()
    stats = _new_stats()
    p = para.add_body(doc, "⚠️ 免责声明: xxx", stats, disclaimer=True)
    assert _size_pt(p.runs[0]) == 9, "整段 9pt（含 emoji 段）"
    assert str(_rgb(_colored_runs(p)[0])) == "57534E", "文字段 C_MUTED, emoji 段本色"
    assert _pbdr(p)["top"] == ("single", "6", "4", "E7E5E4")
    assert stats["paragraphs"] == 1


def test_body_disclaimer_early_return_skips_risk_and_list_processing():
    """disclaimer=True 提前 return: 即便文本带 `- ` 前缀也不剥、不上风险色。"""
    doc = Document()
    p = para.add_body(doc, "- ⚠️ 免责声明", _new_stats(), disclaimer=True)
    assert _text(p) == "- ⚠️ 免责声明", "列表前缀**未**被剥掉"
    got = {str(_rgb(r)) for r in _colored_runs(p)}
    assert got == {"57534E"}, f"只应有免责声明的 C_MUTED, 实测 {got}"
    assert not (got & {"DC2626", "B45309", "15803D"}), "risk_zone 未参与, 无风险色"


def test_body_risk_zone_colors_red_amber_green_lines():
    for emo, hexcolor in (("🔴", "DC2626"), ("🟡", "B45309"), ("🟢", "15803D")):
        doc = Document()
        p = para.add_body(doc, f"{emo} 风险条目", _new_stats(), risk_zone=True)
        assert str(_rgb(p.runs[0])) == hexcolor, f"{emo}: emoji 段本身即 severity 色"
        assert _size_pt(p.runs[0]) == 10.5, emo


def test_body_risk_zone_detects_emoji_behind_a_list_marker():
    """`re.match(r"^\\s*[-*]\\s*")` 分支: 列表前缀后的风险 emoji 同样命中, 且前缀被剥。"""
    doc = Document()
    p = para.add_body(doc, "- 🔴 风险条目", _new_stats(), risk_zone=True)
    assert _text(p) == "🔴 风险条目", "列表前缀被剥掉"
    assert str(_rgb(p.runs[0])) == "DC2626", "且仍按 🔴 上色"


def test_body_outside_risk_zone_is_never_colored_by_emoji():
    doc = Document()
    p = para.add_body(doc, "🔴 只是正文里的符号", _new_stats(), risk_zone=False)
    assert _colored_runs(p) == [], "risk_zone=False ⇒ 整段不上色"


def test_body_strips_a_handwritten_dash_prefix():
    doc = Document()
    p = para.add_body(doc, "- 列表项", _new_stats())
    assert _text(p) == "列表项"


def test_body_strips_an_asterisk_prefix():
    doc = Document()
    p = para.add_body(doc, "* 列表项", _new_stats())
    assert _text(p) == "列表项"


def test_body_keeps_a_dash_without_following_space():
    """`re.match(r"^\\s*[-*]\\s", text)` 要求**确实**有空格, 故 `-5%` 不被剥。"""
    doc = Document()
    p = para.add_body(doc, "-5% 跌幅", _new_stats())
    assert _text(p) == "-5% 跌幅"


# ============================================================
# 薄壳 re-export 契约（H2 / H3）+ §六「禁止新旧两套实现并存」
# ============================================================
_MOVED_NAMES = {
    # 区块 5 样式段落（4 个符号 = 4 个名字, 无同行多合一）
    "add_heading", "add_quote", "RISK_EMOJI", "add_body",
}
_MOVED_FUNCS = ("add_heading", "add_quote", "add_body")
_MOVED_CONSTS = ("RISK_EMOJI",)


def test_moved_surface_is_exactly_4_names():
    assert len(_MOVED_NAMES) == 4, "§六 S3 行: 区块 5 共 4 个符号 / 4 个名字"
    assert len(_MOVED_FUNCS) == 3
    assert len(_MOVED_CONSTS) == 1


def test_shell_reexports_every_moved_name():
    """S3 之前的 4 个顶层名字必须逐名仍在薄壳上（H2 双人格 + H3 假模块面）。

    用 hasattr 而不是 `from md_to_docx import (...)`: 后者一旦缺名会在收集期直接
    ImportError, 且报错不告诉你是**哪个**名字丢了; hasattr 一次报全部缺失。
    """
    import md_to_docx as shell

    missing = sorted(n for n in _MOVED_NAMES if not hasattr(shell, n))
    assert not missing, f"薄壳丢失 re-export 名字: {missing}"


def test_shell_reexport_values_are_identical_objects_not_copies():
    """re-export 必须是同一对象而非复制品 —— 否则薄壳与新模块会各走各的样式值。"""
    import md_to_docx as shell

    assert shell.add_heading is para.add_heading
    assert shell.add_quote is para.add_quote
    assert shell.add_body is para.add_body
    assert shell.RISK_EMOJI is para.RISK_EMOJI


def test_shell_still_calls_the_three_moved_functions():
    """三个 add_* 在薄壳内**仍有调用点**, 不是"re-export 但无人调用"的空壳。

    当前实测调用点数: `add_heading` 2 / `add_quote` 2 / `add_body` 4
    （区块 7 `_render_md_block` 各 1/1/2 + 区块 8 主流程各 1/1/2）。
    判据取 `>= 1` 而非精确值: S4 把区块 7 搬进 `docx_sections.py` 后会各减 1-2,
    但主流程那几处必须一直在壳里, 否则薄壳连渲染都做不了。
    """
    import md_to_docx as shell

    src = Path(shell.__file__).read_text(encoding="utf-8")
    for name in _MOVED_FUNCS:
        calls = len(re.findall(rf"\b{name}\(", src))
        assert calls >= 1, f"{name} 在薄壳内已无调用点, 只剩 re-export 空壳"


def test_shell_no_longer_defines_moved_symbols_in_place(analysis_dir):
    """§六 硬规则「禁止新旧两套实现并存」: 薄壳不得再原地定义迁出符号。

    只查**定义**, 不查名字出现 —— re-export import 与调用点当然会出现这些名字。
    """
    src = (analysis_dir / "md_to_docx.py").read_text(encoding="utf-8")
    still_def = [n for n in _MOVED_FUNCS if re.search(rf"^def {n}\(", src, re.M)]
    assert not still_def, f"薄壳仍原地定义 {still_def} —— 新旧两套实现并存"
    still_assign = [n for n in _MOVED_CONSTS if re.search(rf"^{n}\s*=", src, re.M)]
    assert not still_assign, f"薄壳仍原地赋值 {still_assign} —— 新旧两套实现并存"


def test_module_declares_exactly_the_4_migrated_symbols(analysis_dir):
    """模块自身不得多出迁入范围外的符号（防止顺手加 helper 混进结构拆分）。"""
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert defined == set(_MOVED_FUNCS), f"多出/缺少符号: {defined ^ set(_MOVED_FUNCS)}"


# ============================================================
# §2.1 符号行预算（90）与 §十 符号行守恒的片级证据
# ============================================================
def test_migrated_symbol_lines_equal_the_plan_budget_90(analysis_dir):
    """§六 S3 行「搬 **90** 符号行」+ §五「90」+ §十 符号行守恒 —— 用 ast 复算。

    口径见 §2.1: 顶层符号的 `end_lineno - lineno + 1`; 文件头 docstring 与本模块
    自身的 import 块**不计入**迁入量（§五 明示「不含新文件自身的 import 块与文件头」）。
    """
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    spans = {}
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(n, ast.Expr):          # 模块 docstring = 文件头, 不计
            continue
        spans[getattr(n, "name", "<assign>")] = n.end_lineno - n.lineno + 1
    assert spans == {"add_heading": 28, "add_quote": 33, "<assign>": 1, "add_body": 28}
    assert sum(spans.values()) == 90, "§六 S3 预算 = 90 符号行"


# ============================================================
# 中文关键词契约逐字留存（§八 R3 / §九 第 10 条）
# ============================================================
def test_all_chinese_keyword_branches_are_present_verbatim(analysis_dir):
    """区块 5 的**全部**中文关键词分支逐字仍在被迁出的模块里。

    这些是用户可见的版式契约, 抄错会让语义 golden 红, 但「红在哪」需要人工比对;
    这里先把字面钉住, 让 R3 有独立的 fail-closed 判据。
    """
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    literals = [
        'if in_conclusion or re.search(r"(看空|看多)", t):',      # 分支① 判定
        'elif "数据来源" in t:',                                   # 分支② 判定
        'elif t.startswith("⚠"):',                                # 分支③ 判定
        'bear = "看空" in t',                                     # 分支① 涨跌取色
        'elif "看空" in seg or re.fullmatch(r"\\s*\\d+/\\d+\\s*", seg) or "看多" in seg:',
        'if text.lstrip().startswith(emo) or (re.match(r"^\\s*[-*]\\s*", text) '
        'and re.sub(r"^\\s*[-*]\\s*", "", text).startswith(emo)):',
    ]
    missing = [s for s in literals if s not in src]
    assert not missing, f"中文关键词分支被改动或丢失: {missing}"


def test_quote_branch_order_is_unchanged_after_the_move(analysis_dir):
    """`add_quote` 的分支顺序是契约的一部分: ① 结论 → ② 数据来源 → ③ ⚠ → ④ 默认。

    顺序错了会让同时命中的文本换分支, 而每一条单分支断言仍然全绿 —— 所以必须
    单独锁顺序。判据只扫 `add_quote` 函数体, 否则会命中 `add_heading` 里的 else。
    """
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    body = src[src.index("def add_quote("):src.index("RISK_EMOJI =")]
    order = [
        'if in_conclusion or re.search(r"(看空|看多)", t):',
        'elif "数据来源" in t:',
        'elif t.startswith("⚠"):',
        "\n    else:",
    ]
    positions = [body.index(s) for s in order]
    assert positions == sorted(positions), f"分支顺序被改动: {positions}"


def test_risk_emoji_tuple_literal_is_preserved_verbatim(analysis_dir):
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    assert 'RISK_EMOJI = (("🔴", C_RED), ("🟡", C_AMBER), ("🟢", C_GREEN))' in src


def test_module_does_not_depend_on_optional_sections_package(analysis_dir):
    """H4 的「裸名 + try 降级」只对 `sections` 可选依赖需要。

    本模块**不依赖** sections; 若将来有人顺手加进来又没套 try 降级, CI 矩阵会
    ImportError（R7）。这里把「零 sections 依赖」做成可执行断言。

    用 **ast 的 import 节点**判定而不是全文 grep —— 本模块 docstring 里就写着
    「`from sections import ...` 同一前提」这句说明, 全文 grep 会误报。
    """
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    imported = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        if isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    assert not any("sections" in m for m in imported), f"出现了 sections 依赖: {imported}"
    assert "sections" not in imported


def test_module_uses_bare_name_imports_not_dotted_paths(analysis_dir):
    """与薄壳 / docx_tables 同一前提: 裸名 import（`reporting.` 全路径在 CI 会 ImportError）。"""
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    assert "from reporting.docx_primitives import (" in src
    assert "from analysis.reporting" not in src
    assert "from reporting import" not in src


def test_module_imports_only_what_block_5_actually_needs(analysis_dir):
    """扇入面显式化: 14 个 primitives 依赖 + 3 个 python-docx 依赖, 多一个都算漂移。"""
    src = (analysis_dir / "reporting" / "docx_paragraphs.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            imported.update(a.name for a in n.names)
    assert imported == {
        "re", "WD_ALIGN_PARAGRAPH", "Inches", "Pt",
        "C_ACCENT", "C_AMBER", "C_DARK", "C_GREEN", "C_MUTED", "C_RED",
        "H_HAIR", "HX_AMBER", "HX_GREEN", "HX_RED",
        "_fmt", "add_runs", "md_runs", "p_border",
    }, f"扇入面漂移: {sorted(imported)}"
