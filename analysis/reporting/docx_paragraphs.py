"""docx_paragraphs — 标题 / 引用（结论区）/ 正文列表 / 免责声明 四类段落样式

职责：四类段落样式的渲染，以及结论区与风险区的中文关键词上色分支。
本模块 90 符号行，拆分自单文件渲染器 `analysis/md_to_docx.py` 的样式段落区块：

| 迁入符号 | 符号行 |
|---|---|
| `add_heading` `add_quote` `RISK_EMOJI` `add_body` | 90 |

逐符号核算：`add_heading` 28 + `add_quote` 33 + `RISK_EMOJI` 1 + `add_body` 28 = **90**。

符号行口径（本文件与 tests/reporting/test_docx_thin_shell.py 共用同一口径）
----------------------------------------------------------------------
「符号行」= 顶层符号的 AST 声明行数 `end_lineno - lineno + 1`；装饰器、docstring、
注释与**块内空行**一律计入。本文件自身的 import 块与模块 docstring **不计入**迁入量。

改动本文件前必须成立的不变量
--------------------------
1. **函数体逐字未改** —— 这里只做「搬移 + 跨模块 import」，不做任何行为面清理。
   `RISK_EMOJI`（模块级常量）**原样保留**：它是 `add_body` 的活调用点，不是死代码。
2. **全部中文关键词分支逐字未改**（本项目「不修改业务口径」红线）——
   `add_quote` 的五条分支（`in_conclusion or 看空|看多` / `数据来源` / `⚠` / 其余）
   与 `add_body` 的 `⚠️ 免责声明` / `风险警报` 颜色分支，都是**用户可见文案契约**，
   一个字都不能动。拆分把「禁止顺手清理」做成可执行断言，见 `RISK_EMOJI` 的
   三元组字面与 `add_quote` 五条分支的顺序。
3. **扇入面已全部显式化** —— 本模块对 `docx_primitives` 的 14 个依赖
   （`C_ACCENT` `C_AMBER` `C_DARK` `C_GREEN` `C_MUTED` `C_RED` `H_HAIR`
   `HX_AMBER` `HX_GREEN` `HX_RED` `_fmt` `add_runs` `md_runs` `p_border`）与
   对 `python-docx` 的 3 个依赖（`WD_ALIGN_PARAGRAPH` `Inches` `Pt`）全部走
   **裸名 import**，与薄壳的 `from reporting.docx_primitives import ...` /
   `from sections import ...` 同一前提（`analysis/` 在 sys.path 上：脚本模式
   `sys.path[0]`、`artifact_writer.py:108` 显式 insert `_ANALYSIS_DIR`、CI
   `PYTHONPATH`）。「裸名 + try 降级」只对 `sections` 可选依赖需要，
   本模块不依赖 `sections`。
4. **薄壳 re-export** —— 这 **4 个名字**在 `analysis/md_to_docx.py`
   顶层**原样再导出**，使拆分前的旧调用路径（如
   `from md_to_docx import add_quote`）继续可用。四个在薄壳内
   **均仍有调用点**（`docx_sections._render_md_block` 的 4 处 + 薄壳主流程的 4 处），
   因此这条 import 既是兼容面也是薄壳自身的依赖面；仍挂 `# noqa: F401`
   以免后续改动把这些名字当成漏删而"顺手清理"。
"""
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from reporting.docx_primitives import (
    C_ACCENT,
    C_AMBER,
    C_DARK,
    C_GREEN,
    C_MUTED,
    C_RED,
    H_HAIR,
    HX_AMBER,
    HX_GREEN,
    HX_RED,
    _fmt,
    add_runs,
    md_runs,
    p_border,
)


# ---------------------------------------------------------------- 样式段落
def add_heading(doc, text, level, stats):
    lv = min(level, 4)
    p = doc.add_heading("", level=lv)
    if lv == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(12)
        r = p.add_run(text)
        _fmt(r, size=20, bold=True, color=C_DARK)
        p_border(p, edge="bottom", color=H_HAIR, sz=8, space=4)
    elif lv == 2:
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(text)
        _fmt(r, size=14, bold=True, color=C_ACCENT)
    elif lv == 3:
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(text)
        _fmt(r, size=11.5, bold=True, color=C_DARK)
    else:
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text)
        _fmt(r, size=10.5, bold=True, color=C_MUTED)
    stats["headings"] += 1
    stats["by_level"][lv] = stats["by_level"].get(lv, 0) + 1
    return p


def add_quote(doc, text, stats, in_conclusion=False):
    """> 引用行。结论区大字；⚠️ 警告琥珀；📡 数据来源灰小字；其余灰字"""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.1)
    t = text.strip()

    if in_conclusion or re.search(r"(看空|看多)", t):
        # ---- 结论大字：整行加粗 14pt，看空→A股绿 / 看多→A股红，评分同色
        bear = "看空" in t
        sent = C_GREEN if bear else C_RED
        sent_hx = HX_GREEN if bear else HX_RED
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        for seg, _bold, emoji in md_runs(t):
            r = p.add_run(seg)
            if emoji:
                _fmt(r, size=14, bold=True, color=C_DARK)
            elif "看空" in seg or re.fullmatch(r"\s*\d+/\d+\s*", seg) or "看多" in seg:
                _fmt(r, size=14, bold=True, color=sent)
            else:
                _fmt(r, size=14, bold=True, color=C_DARK)
        p_border(p, edge="left", color=sent_hx, sz=18, space=4)
    elif "数据来源" in t:
        add_runs(p, t, size=9, color=C_MUTED)
        p_border(p, edge="left", color=H_HAIR, sz=6, space=3)
    elif t.startswith("⚠"):
        add_runs(p, t, size=10, color=C_AMBER)
        p_border(p, edge="left", color=HX_AMBER, sz=10, space=3)
    else:
        add_runs(p, t, size=9.5, color=C_MUTED)
        p_border(p, edge="left", color=H_HAIR, sz=6, space=3)
    stats["paragraphs"] += 1
    return p


RISK_EMOJI = (("🔴", C_RED), ("🟡", C_AMBER), ("🟢", C_GREEN))


def add_body(doc, line, stats, risk_zone=False, disclaimer=False):
    """普通段落/列表行：保留 **加粗**；风险区按 🔴🟡🟢 上色"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    text = line
    if disclaimer:
        p.paragraph_format.space_before = Pt(10)
        add_runs(p, text, size=9, color=C_MUTED)
        p_border(p, edge="top", color=H_HAIR, sz=6, space=4)
        stats["paragraphs"] += 1
        return p
    severity = None
    if risk_zone:
        for emo, col in RISK_EMOJI:
            if text.lstrip().startswith(emo) or (re.match(r"^\s*[-*]\s*", text) and re.sub(r"^\s*[-*]\s*", "", text).startswith(emo)):
                severity = col
                break
    if re.match(r"^\s*[-*]\s", text):
        text = re.sub(r"^\s*[-*]\s*", "", text)  # 剥掉手写 "- "，内容排版
    # 内容上色：风险区带程度符号的行整行上色，其余正文默认深色
    if severity is not None:
        for seg, bold, _emoji in md_runs(text):
            r = p.add_run(seg)
            _fmt(r, size=10.5, bold=bold, color=severity)
    else:
        add_runs(p, text, size=10.5)
    stats["paragraphs"] += 1
    return p
