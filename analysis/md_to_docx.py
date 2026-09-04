#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_to_docx.py — 把 quant_analyzer_v2.py 输出的 Markdown 报告转成 DOCX
调用方式: venv/bin/python md_to_docx.py <input.md> <output.docx>
"""
import sys
import re
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

def md_to_docx(md_path: str, docx_path: str) -> None:
    md = Path(md_path).read_text(encoding="utf-8")
    doc = Document()

    # 默认字体
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    lines = md.split("\n")
    i = 0
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        # 解析 markdown 表格
        ncols = len(table_rows[0].split("|")) - 2  # 去掉首尾空
        # 第二行是分隔线
        data_rows = [r for r in table_rows if not re.match(r"^\s*\|?\s*[-:]+", r)]
        t = doc.add_table(rows=len(data_rows), cols=ncols)
        t.style = "Light Grid Accent 1"
        for ri, row in enumerate(data_rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            for ci, cell in enumerate(cells):
                if ci < ncols:
                    t.rows[ri].cells[ci].text = cell
        table_rows = []
        doc.add_paragraph()  # 表格后空行

    for line in lines:
        # 表格检测
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_rows.append(line)
            in_table = True
            continue
        elif in_table:
            flush_table()
            in_table = False

        # 标题
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            p = doc.add_heading(text, level=min(level, 4))
            continue

        # 分隔线
        if re.match(r"^-{3,}$", line.strip()):
            doc.add_paragraph("─" * 40)
            continue

        # 引用
        if line.startswith(">"):
            p = doc.add_paragraph(line[1:].strip(), style="Intense Quote")
            continue

        # 空行
        if not line.strip():
            continue

        # 普通段落
        p = doc.add_paragraph()
        # 简单处理加粗 **xxx**
        parts = re.split(r"(\*\*[^*]+\*\*)", line)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                run = p.add_run(part[2:-2])
                run.bold = True
            else:
                p.add_run(part)

    # 末尾表格
    if in_table:
        flush_table()

    doc.save(docx_path)
    print(f"OK: {docx_path}")

def qn(tag):
    return "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}" + tag.split(":")[1]

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python md_to_docx.py <input.md> <output.docx>", file=sys.stderr)
        sys.exit(1)
    md_to_docx(sys.argv[1], sys.argv[2])
