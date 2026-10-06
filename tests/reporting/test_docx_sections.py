"""P2-E S4 · analysis/reporting/docx_sections.py 的单元测试

只测**迁入的 2 个符号**（§2.2 区块 7 Section Registry 辅助），**不测主流程**
（§六 S4 第 2 步的边界）。`md_to_docx()` 本体属区块 8 / S5，不在本文件断言
范围内；区块 5 的 `add_*` 属 S3、区块 6 的 `flush_table` 属 S2，同样不在范围内。

本模块存在的原因：S0 的语义 golden 只锁住了「DOCX **产物**的版式语义」，但
**迁入符号自身的分支判定与取值**没有直接断言 —— 拆分时若某个分支抄错，
投影 golden 会红，但「红在哪一句」说不清。这里把每个迁入符号的契约单独钉住，
让 S4 的 diff 可被逐项复核。

S4 是 §三 里**耦合最深**的一片（扇出横跨 4 个区块）：`_render_md_block` 调
`docx_primitives` 的 `_fmt`/`C_MUTED`、`docx_paragraphs` 的 3 个 `add_*`、
`docx_tables` 的 `flush_table`、以及 `python-docx` 的 `WD_ALIGN_PARAGRAPH`/`Pt`。
扇入面一旦抄漏，本文件与语义 golden 会同时红。

**S4 的两个特有风险**：
1. **§八 R4 漂移风险** —— `_render_md_block` 与主流程的 `while` 循环是同一套
   Markdown 行解析器的两份拷贝（docstring 自述「逻辑等价」），§九 第 7 条
   **明确不去重**。因此本文件**不**断言两份拷贝的解析顺序一致（那是 S5 收官
   人工对读的项），只断言迁入的这一份**逐字未被改动**。
2. **H4 的 `sections` 依赖** —— 区块 7 全文检索 `sections` **零命中**（实测）。
   `enabled_sections` 的消费点在**薄壳**区块 8 的灰度循环，不在本模块。
   若将来有人顺手加进来又没套 try 降级，CI 矩阵会 ImportError（R7）——
   下面有可执行断言把它钉住。

零网络 / 零 live / 零外部数据：全部在内存里用 `python-docx` 建对象。涉及
`_load_result_near` 的用例一律用 `tmp_path` 造**一次性空目录**并显式保证
「目录里没有 `result_v3-*.json`」，**绝不读 `reports/`**、不依赖当日跑批
（§7.2 装置的同一条纪律：工作目录出现 result_v3 会让灰度块被追加进产物，
基线就会依赖环境）。

覆盖清单（2 个符号）：
- `_load_result_near`（就近读 result JSON 的两段式候选匹配 + 异常降级）
- `_render_md_block`（表格行累积/收尾 flush、标题与风险区状态机、分隔线、
  引用、免责声明分支、正文透传）
另加：薄壳 re-export 契约（H2/H3）、§六「禁止新旧两套实现并存」、
§2.1 符号行预算 70 的 AST 复算、扇入面与 H4 零 `sections` 断言。
"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))

from docx import Document  # noqa: E402  # analysis/ 靠上面的 sys.path 引导
from docx.oxml.ns import qn  # noqa: E402
from reporting import docx_sections as sec  # noqa: E402


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


def _east_asia(run):
    return run._element.rPr.rFonts.get(qn("w:eastAsia"))


def _align(p):
    return None if p.alignment is None else int(p.alignment)


# ============================================================
# 区块 7 · _load_result_near（就近读 result_v3-*.json）
# ============================================================
def test_returns_none_when_no_result_json_next_to_the_md(tmp_path):
    """空目录 → None。这是**降级路径**, 不是异常: 灰度块整体跳过, 主流程照常。"""
    md = tmp_path / "600693-东百集团-1616.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) is None


def test_nonexistent_path_returns_none_instead_of_raising(tmp_path):
    """md_path 根本不存在时也必须返回 None —— `except Exception` 兜住 IO 错误。

    判据是「不抛异常」: 若 try/except 被抄坏, 这里会直接 FileNotFoundError。
    """
    assert sec._load_result_near(str(tmp_path / "不存在.md")) is None


def test_matches_the_hhmms_stem_candidate_first(tmp_path):
    """两段式候选匹配的**第一段**: stem 末尾 `-HHMM` → 精确匹配同名 json。

    目录里同时放两个 json 时, 精确匹配必须**胜出** `result_v3-*.json` 兜底,
    否则就近读会拿到别的标的的 result —— 那是真实数据事故, 不是风格问题。
    """
    (tmp_path / "result_v3-1616.json").write_text('{"tag": "精确"}', encoding="utf-8")
    (tmp_path / "result_v3-9999.json").write_text('{"tag": "兜底"}', encoding="utf-8")
    md = tmp_path / "600693-东百集团-1616.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) == {"tag": "精确"}


def test_falls_back_to_any_result_v3_when_stem_has_no_timestamp(tmp_path):
    """第二段: stem 末尾无 `-HHMM` → 退回 `result_v3-*.json` 全量。"""
    (tmp_path / "result_v3-1200.json").write_text('{"tag": "兜底"}', encoding="utf-8")
    md = tmp_path / "报告.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) == {"tag": "兜底"}


def test_falls_back_when_stem_timestamp_matches_nothing(tmp_path):
    """stem 有 `-HHMM` 但该时间戳的 json 不存在 → 同样退回全量匹配。"""
    (tmp_path / "result_v3-0900.json").write_text('{"tag": "兜底"}', encoding="utf-8")
    md = tmp_path / "600693-东百集团-1616.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) == {"tag": "兜底"}


def test_picks_the_mtime_latest_candidate(tmp_path):
    """兜底段取 mtime 最新的那个候选（`max(..., key=st_mtime)`）。

    三个候选只按 mtime 决胜, 与文件名无关 —— 钉住「取最新」这个行为面。
    """
    import os

    for tag, mtime in (("old", 1_000_000_000), ("mid", 1_600_000_000), ("new", 1_700_000_000)):
        p = tmp_path / f"result_v3-{tag}.json"
        p.write_text('{"tag": "%s"}' % tag, encoding="utf-8")
        os.utime(p, (mtime, mtime))
    md = tmp_path / "报告.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) == {"tag": "new"}


def test_malformed_json_degrades_to_none(tmp_path):
    """坏 JSON → None（`except Exception` 兜住), 不得让灰度块炸掉整份报告。"""
    (tmp_path / "result_v3-1616.json").write_text("{ 这不是 JSON", encoding="utf-8")
    md = tmp_path / "600693-东百集团-1616.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) is None


def test_json_is_read_as_utf8(tmp_path):
    """读回编码必须是 utf-8 —— 中文 label 被按别的编码解会抛错降级成 None。"""
    (tmp_path / "result_v3-1616.json").write_text(
        '{"东百集团": "中文标签"}', encoding="utf-8"
    )
    md = tmp_path / "600693-东百集团-1616.md"
    md.write_text("# 标题\n", encoding="utf-8")
    assert sec._load_result_near(str(md)) == {"东百集团": "中文标签"}


# ============================================================
# 区块 7 · _render_md_block（Markdown 片段 → docx, 自带状态机）
# ============================================================
def test_heading_increments_headings_and_by_level():
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "## 小节", stats)
    assert stats["headings"] == 1
    assert stats["by_level"][2] == 1
    assert _text(doc.paragraphs[0]) == "小节"


def test_h2_clears_the_previous_risk_zone_state():
    """`cur_h2` / `risk_zone` 是**块内自带**状态: 风险区标题之后的普通 H2 必须复位。

    这是与主循环行为等价的关键分支（docstring 自述「自带 cur_h2 / risk_zone /
    table_rows 状态」）。若 `risk_zone` 没随 H2 重算, 风险区会污染后续整块。
    """
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(
        doc,
        "## 风险警报\n🔴 高风险\n## 下一个普通小节\n普通正文一行",
        stats,
    )
    colors = [(_text(p), _rgb(p.runs[0])) for p in doc.paragraphs if p.runs]
    by_text = dict(colors)
    assert str(by_text["🔴 高风险"]) == "DC2626", "风险区内行必须仍为红色"
    assert by_text["普通正文一行"] is None, "风险区外的普通行**不得**继承上色"
    assert stats["headings"] == 2


def test_h1_does_not_touch_risk_zone_state():
    """只有 `level == 2` 才更新 `cur_h2` / `risk_zone`; H1 不参与。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "# 一级标题\n正文", stats)
    assert stats["by_level"][1] == 1
    assert 2 not in stats["by_level"]


def test_hr_line_is_centered_muted_9pt_and_counts_one_paragraph():
    """分隔线分支: `─`×40 / 居中 / 9pt / C_MUTED / space_before=after=4pt。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "---", stats)
    p = doc.paragraphs[0]
    assert _text(p) == "─" * 40
    assert _align(p) == 1, "WD_ALIGN_PARAGRAPH.CENTER"
    assert _size_pt(p.runs[0]) == 9
    assert str(_rgb(p.runs[0])) == "57534E"
    assert p.paragraph_format.space_before.pt == 4
    assert p.paragraph_format.space_after.pt == 4
    assert stats["paragraphs"] == 1


def test_quote_branch_uses_the_block_local_h2_conclusion_flag():
    """`in_conclusion` 取自**块内** `cur_h2` 是否以 🎯 开头, 不是别处的状态。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "## 🎯 结论\n> 多空结论：看多", stats)
    quote = doc.paragraphs[1]
    assert quote.runs[0].bold is True, "结论区引用必须加粗（add_quote 的 conclusion 分支）"
    assert stats["paragraphs"] == 1


def test_quote_branch_outside_conclusion_is_not_bold():
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "## 普通小节\n> 随便一句引用", stats)
    assert doc.paragraphs[1].runs[0].bold is not True


def test_disclaimer_line_takes_the_disclaimer_branch():
    """`⚠️ 免责声明` / `⚠ 免责声明` 两种写法都走 disclaimer 分支。

    两种字面是**或**关系（`or`), 少写一个 Emoji 变体选择符就会漏判 → 整段
    免责声明不再置灰小字。

    ⚠️ 取色口径同 `test_docx_paragraphs.py` 已实测的那条: `⚠` 是 emoji,
    `add_body` 的 emoji 段**不上色**（"emoji 保持本色"）, 故 `runs[0]` 颜色为
    None, 真正的业务色在后续 run 上。本用例按此**实际行为**钉住。
    """
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "⚠ 免责声明: 本报告仅供参考", stats)
    p = doc.paragraphs[0]
    assert _size_pt(p.runs[0]) == 9, "免责声明 = 9pt 置灰"
    assert _size_pt(p.runs[1]) == 9
    assert _rgb(p.runs[0]) is None, "emoji 段保持本色（不取业务色）"
    assert str(_rgb(p.runs[1])) == "57534E", "正文段才是置灰 C_MUTED"

    doc2 = Document()
    stats2 = _new_stats()
    sec._render_md_block(doc2, "⚠️ 免责声明: 本报告仅供参考", stats2)
    assert _size_pt(doc2.paragraphs[0].runs[0]) == 9


def test_empty_and_blank_lines_are_skipped_without_counting():
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "\n\n   \n", stats)
    assert doc.paragraphs == []
    assert stats["paragraphs"] == 0


def test_table_rows_accumulate_until_a_non_table_line_then_flush():
    """表格分支: 连续的 `|...|` 行先累积, 遇到非表格行才 flush 一次。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(
        doc,
        "| 名称 | 数值 |\n| --- | --- |\n| 甲 | 12 |\n表格后面的正文",
        stats,
    )
    assert len(doc.tables) == 1, "累积的表格行必须被 flush 一次"
    assert stats["tables"] == 1
    assert stats["cells"] > 0


def test_trailing_table_is_flushed_at_the_end_of_the_block():
    """块**末尾**的表格由 `if in_table: flush_table(...)` 收尾。

    少了这一行, 文档以表格结尾时表格会被整段吞掉, 且 stats 少计一次。
    """
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "| 名称 | 数值 |\n| --- | --- |\n| 甲 | 12 |", stats)
    assert len(doc.tables) == 1, "结尾表格必须被收尾 flush"
    assert stats["tables"] == 1


def test_plain_line_is_forwarded_to_add_body():
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "普通正文一行", stats)
    assert _text(doc.paragraphs[0]) == "普通正文一行"
    assert stats["paragraphs"] == 1


def test_empty_md_text_is_a_no_op():
    """空文本 → 空文档, stats 零变动（不抛异常）。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "", stats)
    assert doc.paragraphs == []
    assert stats == _new_stats()


def test_h2_with_risk_keyword_alone_does_not_color_its_own_text():
    """`风险警报` 只设**状态**; 标题自身仍走 add_heading 的普通上色分支。"""
    doc = Document()
    stats = _new_stats()
    sec._render_md_block(doc, "## 风险警报", stats)
    p = doc.paragraphs[0]
    assert _text(p) == "风险警报"
    assert str(_rgb(p.runs[0])) == "2563EB", "H2 标题是强调色, 不是风险色"


# ============================================================
# 薄壳 re-export 契约（H2 / H3）+ §六「禁止新旧两套实现并存」
# ============================================================
_MOVED_NAMES = ("_load_result_near", "_render_md_block")


def test_moved_surface_is_exactly_2_names():
    assert len(_MOVED_NAMES) == 2, "§六 S4 行: 区块 7 共 2 个符号 / 2 个名字"


def test_shell_reexports_every_moved_name():
    """S4 之前的 2 个顶层名字必须逐名仍在薄壳上（H2 双人格 + H3 假模块面）。

    用 hasattr 而不是 `from md_to_docx import (...)`: 后者一旦缺名会在收集期
    直接 ImportError, 且报错不告诉你是**哪个**名字丢了; hasattr 一次报全部缺失。
    """
    import md_to_docx as shell

    missing = sorted(n for n in _MOVED_NAMES if not hasattr(shell, n))
    assert not missing, f"薄壳丢失 re-export 名字: {missing}"


def test_shell_reexport_values_are_identical_objects_not_copies():
    """re-export 必须是同一对象而非复制品 —— 否则薄壳与新模块会各走各的路径。"""
    import md_to_docx as shell

    assert shell._load_result_near is sec._load_result_near
    assert shell._render_md_block is sec._render_md_block


def test_shell_still_calls_both_moved_functions():
    """两个迁出符号在薄壳内**仍有调用点**, 不是「re-export 但无人调用」的空壳。

    实测调用点各 1 处: 都在 `md_to_docx` 的 §3.3 灰度循环内
    （`_load_result_near(md_path)` 与 `_render_md_block(doc, sec_md, stats)`）。
    """
    import md_to_docx as shell

    src = Path(shell.__file__).read_text(encoding="utf-8")
    for name in _MOVED_NAMES:
        calls = len(re.findall(rf"\b{name}\(", src))
        assert calls >= 1, f"{name} 在薄壳内已无调用点, 只剩 re-export 空壳"


def test_shell_no_longer_defines_moved_symbols_in_place(analysis_dir):
    """§六 硬规则「禁止新旧两套实现并存」: 薄壳不得再原地定义迁出符号。

    只查**定义**, 不查名字出现 —— re-export import 与调用点当然会出现这些名字。
    """
    src = (analysis_dir / "md_to_docx.py").read_text(encoding="utf-8")
    still_def = [n for n in _MOVED_NAMES if re.search(rf"^def {n}\(", src, re.M)]
    assert not still_def, f"薄壳仍原地定义 {still_def} —— 新旧两套实现并存"


def test_module_declares_exactly_the_2_migrated_symbols(analysis_dir):
    """模块自身不得多出迁入范围外的符号（防止顺手加 helper 混进结构拆分）。"""
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert defined == set(_MOVED_NAMES), f"多出/缺少符号: {defined ^ set(_MOVED_NAMES)}"


# ============================================================
# §2.1 符号行预算（70）与 §十 符号行守恒的片级证据
# ============================================================
def test_migrated_symbol_lines_equal_the_plan_budget_70(analysis_dir):
    """§六 S4 行「搬 **70** 符号行」+ §五「70」+ §十 符号行守恒 —— 用 ast 复算。

    口径见 §2.1: 顶层符号的 `end_lineno - lineno + 1`; 文件头 docstring 与本模块
    自身的 import 块**不计入**迁入量（§五 明示「不含新文件自身的 import 块与文件头」）。
    逐符号: `_load_result_near` 21 + `_render_md_block` 49 = 70。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    spans = {}
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(n, ast.Expr):          # 模块 docstring = 文件头, 不计
            continue
        spans[getattr(n, "name", "<assign>")] = n.end_lineno - n.lineno + 1
    assert spans == {"_load_result_near": 21, "_render_md_block": 49}
    assert sum(spans.values()) == 70, "§六 S4 预算 = 70 符号行"


# ============================================================
# 扇入面显式化 + H4 的零 sections 依赖
# ============================================================
def test_module_does_not_depend_on_optional_sections_package(analysis_dir):
    """H4 的「裸名 + try 降级」只对 `sections` 这个可选依赖需要。

    区块 7 全文检索 `sections` **零命中**（`enabled_sections` 的消费点在薄壳
    区块 8 的灰度循环里), 故本模块不需要那层 try 包装。若将来有人顺手加进来
    又没套 try 降级, CI 矩阵会 ImportError（R7）。这里把「零 sections 依赖」
    做成可执行断言。

    用 **ast 的 import 节点**判定而不是全文 grep —— 本模块 docstring 里就写着
    「`from sections import ...` 同一前提」这句说明, 全文 grep 会误报。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    imported = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        if isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    assert not any("sections" in m for m in imported), f"出现了 sections 依赖: {imported}"


def test_module_uses_bare_name_imports_not_dotted_paths(analysis_dir):
    """与薄壳 / docx_tables / docx_paragraphs 同一前提: 裸名 import。

    `from analysis.reporting ...` / `from reporting import ...` 在 CI 矩阵下会
    ImportError（H4 / R7）。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    assert "from reporting.docx_primitives import" in src
    assert "from reporting.docx_paragraphs import" in src
    assert "from reporting.docx_tables import" in src
    assert "from analysis.reporting" not in src
    assert "from reporting import" not in src


def test_module_imports_only_what_block_7_actually_needs(analysis_dir):
    """扇入面显式化: §三 说区块 7「横跨 4 个区块」, 多一个都算漂移。

    §三 的「4 个区块」= 区块 3(`_fmt`/分隔线用 `C_MUTED`) + 区块 4(经
    `add_*` 间接, 不直接 import) + 区块 5(3 个 `add_*`) + 区块 6(`flush_table`),
    另加 `python-docx` 与标准库。本断言锁死**直接** import 集合。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            imported.update(a.name for a in n.names)
    assert imported == {
        "re", "Path",
        "WD_ALIGN_PARAGRAPH", "Pt",
        "C_MUTED", "_fmt",
        "add_body", "add_heading", "add_quote",
        "flush_table",
    }, f"扇入面漂移: {sorted(imported)}"


# ============================================================
# 灰度块的行为面契约逐字留存（§八 R3 / R4 / §九 第 7 条）
# ============================================================
def test_candidate_matching_two_stage_logic_is_preserved_verbatim(analysis_dir):
    """`_load_result_near` 的两段式候选匹配是**行为契约**, 抄错会读到别的标的。

    顺序也是契约: 精确匹配优先, 兜底在后。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    literals = [
        'm = re.search(r"-(\\d{4})$", stem)',
        'cand = list(d.glob(f"result_v3-{m.group(1)}.json"))',
        'cand = list(d.glob("result_v3-*.json"))',
        'latest = max(cand, key=lambda p: p.stat().st_mtime)',
        'return _json.loads(latest.read_text(encoding="utf-8"))',
    ]
    missing = [s for s in literals if s not in src]
    assert not missing, f"两段式候选匹配被改动或丢失: {missing}"


def test_json_import_stays_function_local(analysis_dir):
    """`import json as _json` 必须在**函数体内**: 模块级 import 会改变导入面,
    且 §2.1 口径下会算进迁入量（模块自身的 import 块不计入）。

    改判据: 该 import 出现在 `_load_result_near` 函数体内, 而不是模块顶层。
    """
    tree = ast.parse(
        (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    )
    top_level_imports = {
        a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names
    }
    assert "json" not in top_level_imports, "json 被提升到模块顶层 —— 改变了导入面"
    fn = next(n for n in tree.body if getattr(n, "name", "") == "_load_result_near")
    inner = {a.asname or a.name for n in ast.walk(fn) if isinstance(n, ast.Import) for a in n.names}
    assert "_json" in inner, "函数体内的 `import json as _json` 丢失"


def test_render_md_block_branch_order_is_unchanged_after_the_move(analysis_dir):
    """`_render_md_block` 的分支顺序是契约的一部分:

    ① 表格行累积 ② 标题 ③ 分隔线 ④ 引用 ⑤ 空行 ⑥ 免责声明 ⑦ 正文。

    顺序错了会让同时命中的文本换分支, 而每一条单分支断言仍然全绿 ——
    所以必须单独锁顺序。判据只扫 `_render_md_block` 函数体。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    body = src[src.index("def _render_md_block("):]
    order = [
        'if line.strip().startswith("|") and line.strip().endswith("|"):',
        'm = re.match(r"^(#{1,6})\\s+(.+)$", line)',
        'if re.match(r"^-{3,}$", line.strip()):',
        'if line.startswith(">"):',
        'if not line.strip():',
        'if line.startswith("⚠️ 免责声明") or line.startswith("⚠ 免责声明"):',
        'add_body(doc, line, stats, risk_zone=risk_zone)',
    ]
    positions = [body.index(s) for s in order]
    assert positions == sorted(positions), f"分支顺序被改动: {positions}"


def test_trailing_table_flush_is_preserved_verbatim(analysis_dir):
    """块末尾的收尾 flush 是 §六 S4 迁移必须逐字保留的行为面。"""
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    body = src[src.index("def _render_md_block("):]
    assert body.rstrip().endswith(
        "    if in_table:\n        flush_table(doc, table_rows, stats)"
    )


def test_risk_zone_keyword_is_preserved_verbatim(analysis_dir):
    """`风险警报` 关键词是用户可见文案契约（§九 第 10 条「不修改业务口径」）。"""
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    assert 'risk_zone = bool(re.search(r"风险警报", cur_h2))' in src


def test_conclusion_emoji_flag_is_preserved_verbatim(analysis_dir):
    """`🎯` 前缀判定是引用分支进 conclusion 态的唯一条件, 逐字钉住。"""
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    assert 'in_conclusion=(cur_h2.startswith("🎯"))' in src


def test_broad_except_degradation_is_preserved_verbatim(analysis_dir):
    """`except Exception: return None` 是灰度块的隔离契约:

    任一节读盘失败都只跳过该节, 不得让整份报告渲染中断。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    body = src[src.index("def _load_result_near("):src.index("def _render_md_block(")]
    assert "    except Exception:  # noqa: BLE001\n        return None" in body


def test_render_md_block_keeps_its_equivalence_docstring(analysis_dir):
    """docstring 自述「逻辑与主流程的 while 循环等价」—— 这条**已知债**（§八 R4）

    的唯一可执行标记。§九 第 7 条明确不去重, 因此 S4 迁入时必须连 docstring
    一起逐字搬走; 若有人趁搬移「顺手」改掉这句, R4 就不再有文档锚点。
    """
    src = (analysis_dir / "reporting" / "docx_sections.py").read_text(encoding="utf-8")
    assert "逻辑与主流程的 while 循环等价" in src
    assert "自带 cur_h2 / risk_zone / table_rows 状态" in src
