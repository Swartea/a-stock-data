"""docx_tables — Markdown 表格 → docx 表格

职责：Markdown 表格行 → docx 表格，含数字列右对齐等宽、斑马纹、表头重复等样式动作。
本模块 94 符号行，拆分自单文件渲染器 `analysis/md_to_docx.py` 的表格区块：

| 迁入符号 | 符号行 |
|---|---|
| `NUM_RANGE` `DATE_ONLY` `_clean_num` `is_numeric_like` `_cell_add` `flush_table` | 94 |

符号行口径（本文件与 tests/reporting/test_docx_thin_shell.py 共用同一口径）
----------------------------------------------------------------------
「符号行」= 顶层符号的 AST 声明行数 `end_lineno - lineno + 1`；装饰器、docstring、
注释与**块内空行**一律计入。本文件自身的 import 块与模块 docstring **不计入**迁入量。

改动本文件前必须成立的不变量
--------------------------
1. **函数体逐字未改** —— 这里只做「搬移 + 跨模块 import」，不做任何行为面清理。
   零调用点的死符号 `NUM_RANGE`（1 符号行）**原样保留**：删除死代码属行为面清理，
   混进结构拆分会让「行为不变」这个判据失效，必须另开单片。
2. **3 处业务阈值逐字未改**（本项目「不修改业务口径」红线）——
   数字列 60% 判定（「≥60% 数字形」）、`[ci for ci in numeric_cols if header[ci].strip("*") == "数值"]`
   的价位/数值列特判（含 `price_cols = [1]` 兜底）、`"综合"` 行加粗。
   这三处是**用户可见的版式契约**，一个字都不能动。
3. **扇入面已全部显式化** —— 本模块对同仓库 `docx_primitives` 的 8 个依赖
   （`C_DARK` `FILL_ZEBRA` `_fmt` `cell_bottom_border` `cell_shade` `header_repeat`
   `md_runs` `table_borders`）全部走**裸名 import**，与薄壳的
   `from reporting.docx_primitives import ...` / `from sections import ...` 同一前提
   （`analysis/` 在 sys.path 上：脚本模式 `sys.path[0]`、`artifact_writer.py:108`
   显式 insert `_ANALYSIS_DIR`、CI `PYTHONPATH`）。「裸名 + try 降级」只对
   `sections` 可选依赖需要，本模块不依赖 `sections`。
4. **薄壳 re-export** —— 这 **6 个名字**在 `analysis/md_to_docx.py`
   顶层**原样再导出**，使拆分前的旧调用路径（如 `from md_to_docx import flush_table`）
   继续可用。其中只有 `flush_table` 在薄壳内仍有调用点
   （`docx_sections._render_md_block` 与薄壳主流程的 `local_flush` 闭包），
   其余 5 个迁出后薄壳内已无调用点，保留它们是**有意的兼容面**，挂 `# noqa: F401`。
"""
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from reporting.docx_primitives import (
    C_DARK,
    FILL_ZEBRA,
    _fmt,
    cell_bottom_border,
    cell_shade,
    header_repeat,
    md_runs,
    table_borders,
)

# ---------------------------------------------------------------- 表格
NUM_RANGE = re.compile(r"[0-9%元亿~~/,\s.+\-−—]+$")
DATE_ONLY = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")


def _clean_num(s):
    """剥掉 ** 加粗标记与 元/亿 单位，供数字判定用"""
    return s.strip().replace("**", "").strip().rstrip("元亿").strip()


def is_numeric_like(s):
    s = _clean_num(s)
    if not s or DATE_ONLY.match(s) or re.search(r"[A-Za-z一-鿿:]", s):
        return False
    tokens = [x for x in re.split(r"[\s~/]+", s.replace("~", " ")) if x]
    if not tokens:
        return False
    ok = re.compile(r"^[+\-−]?[\d,]+(?:\.\d+)?%?$")
    for tk in tokens:
        if tk in ("—", "-", "−"):
            continue
        if not ok.match(tk):
            return False
    return True


def _cell_add(cell, content, stats, numeric_cols=None, price_cols=None, bold_row=False):
    """写单元格内容：解析 **加粗**；数字等宽右对齐"""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    for text, bold, _emoji in md_runs(content):
        r = p.add_run(text)
        _fmt(r, size=10.5, bold=(bold or bold_row))
    return p


def flush_table(doc, table_rows, stats):
    """渲染一张表格：hairline 边框 + 斑马纹 + 表头加粗 + 数字右对齐等宽"""
    data_rows = [r for r in table_rows if not re.match(r"^\s*\|?\s*[-:]+", r)]
    if not data_rows:
        table_rows.clear()
        return
    grid = []
    for r in data_rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        grid.append(cells)
    ncols = max(len(c) for c in grid)
    grid = [c + [""] * (ncols - len(c)) for c in grid]
    header, body = grid[0], grid[1:]

    t = doc.add_table(rows=len(grid), cols=ncols)
    table_borders(t)
    header_repeat(t.rows[0])

    # 数字列 = 该列数据格子 ≥60% 数字形 → 右对齐等宽（三价位“数值”列另加粗）
    numeric_cols = []
    for ci in range(ncols):
        vals = [r[ci] for r in body]
        if vals and sum(1 for v in vals if is_numeric_like(v)) * 100 >= 60 * len(vals):
            numeric_cols.append(ci)
    price_cols = []
    if len(header) >= 2 and header[0].strip("*") == "价位":
        price_cols = [ci for ci in numeric_cols if header[ci].strip("*") == "数值"]
        if not price_cols:
            price_cols = [1]

    for ri, row in enumerate(grid):
        is_header = ri == 0
        bold_row = row[0].strip("*").strip() == "综合" and not is_header
        for ci in range(ncols):
            content = row[ci] if ci < len(row) else ""
            cell = t.rows[ri].cells[ci]
            _cell_add(cell, content, stats)
            p0 = cell.paragraphs[0]
            numeric = (not is_header) and (ci in numeric_cols)
            if numeric:
                p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                for r in p0.runs:
                    _fmt(r, size=None, bold=None, color=None, mono=True)
            if ci in price_cols and not is_header:
                for r in p0.runs:
                    _fmt(r, size=11, bold=True, color=None, mono=True)
            if is_header:
                for r in p0.runs:
                    _fmt(r, size=10, bold=True, color=C_DARK)
                cell_bottom_border(cell)
            if bold_row:
                for r in p0.runs:
                    _fmt(r, size=10.5, bold=True, color=C_DARK)
            if not is_header and ri % 2 == 1:
                cell_shade(cell, FILL_ZEBRA)
            stats["cells"] += 1

    # 表后紧凑空段
    sp = doc.add_paragraph()
    sr = sp.add_run("")
    sr.font.size = Pt(2)
    sp.paragraph_format.space_before = Pt(4)
    sp.paragraph_format.space_after = Pt(4)
    stats["tables"] += 1
    stats["paragraphs"] += 1  # 空段占位
    table_rows.clear()
