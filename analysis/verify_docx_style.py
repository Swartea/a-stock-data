#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_docx_style.py — 对 md_to_docx 新版 DOCX 做样式层实测校验
用法: bash scripts/run_in_venv.sh python analysis/verify_docx_style.py <input.md> <output.docx>
输出: key=value 逐行, 供排版美化验收核对
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


def hex_of(rgb):
    return "%02X%02X%02X" % (rgb[0], rgb[1], rgb[2])


def main():
    md_path, docx_path = sys.argv[1], sys.argv[2]
    md = Path(md_path).read_text(encoding="utf-8")

    # ---------- MD 侧结构（独立统计，用于交叉核对完整性） ----------
    md_head = 0
    md_by = {}
    md_tables = 0
    md_table_lines = 0
    for ln in md.split("\n"):
        m = re.match(r"^(#{1,6})\s+", ln)
        if m:
            lv = len(m.group(1))
            md_head += 1
            md_by[lv] = md_by.get(lv, 0) + 1
            continue
        if ln.strip().startswith("|") and re.match(r"^\s*\|?\s*[-:]+", ln):
            md_tables += 1
        if ln.strip().startswith("|"):
            md_table_lines += 1
    content_lines = [ln for ln in md.split("\n") if ln.strip() and not ln.strip().startswith("|")]
    md_para_blocks = len(content_lines) - md_head  # 段落式行(含引用/列表/空段标记外)
    # 期望的 docx 顶层段落 = md_para_blocks + 表格(表) - 表格自身行(已是 table 对象)
    # 具体: 段落块中不含表格行; 表后每个表加 1 个空段, 共 +md_tables
    expect_paras = md_para_blocks + md_tables

    # ---------- DOCX 侧 ----------
    doc = Document(docx_path)
    paras = doc.paragraphs
    headings = [p for p in paras if p.style.name.startswith("Heading")]
    h_count = {}
    for p in headings:
        lv = int(p.style.name.split()[-1])
        h_count[lv] = h_count.get(lv, 0) + 1
    tables = doc.tables

    # 残留 ** 标记检查（全文档: 顶层段 + 表格所有单元格）
    leftovers = 0
    for p in paras:
        leftovers += p.text.count("**")
    for t in tables:
        for row in t.rows:
            for c in row.cells:
                leftovers += c.text.count("**")

    # 结论区: 找 "综合评分" 段
    concl = None
    for p in paras:
        if "综合评分" in p.text:
            concl = p
            break
    concl_bolds = sum(1 for r in concl.runs if r.font.bold) if concl else 0
    concl_colors = sorted({hex_of(r.font.color.rgb) for r in concl.runs
                           if r.font.color and r.font.color.rgb}) if concl else []

    # 风险警报区红色行
    red_lines = []
    for p in paras:
        if "极高估, 泡沫风险" in p.text or "平均净卖出" in p.text:
            red_lines.append((p.text[:22], [hex_of(r.font.color.rgb) for r in p.runs
                                            if r.font.color and r.font.color.rgb]))

    # 三价位表: 找表头首格为 价位 的表
    price_tbl = None
    for t in tables:
        h0 = t.rows[0].cells[0].text.strip("*").strip()
        if h0 == "价位":
            price_tbl = t
            break
    if price_tbl is not None:
        p_cells = price_tbl.rows[1].cells
        p_val = p_cells[1]
        p_runs = p_val.paragraphs[0].runs
        mono_ok = all("Consolas" in (r.font.name or "") for r in p_runs)
        size_ok = all(r.font.size and r.font.size.pt == 11.0 for r in p_runs)
        bold_ok = all(bool(r.font.bold) for r in p_runs)
        align_right = p_val.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
        price_col2 = p_cells[1].text
    else:
        mono_ok = size_ok = bold_ok = align_right = False
        price_col2 = "NOT FOUND"

    # 数字单元格统计: 右对齐段 + 等宽字体 run 数
    right_align = 0
    mono_runs = 0
    for t in tables:
        for row in t.rows:
            for c in row.cells:
                for p0 in c.paragraphs:
                    if p0.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                        right_align += 1
                    for r in p0.runs:
                        if r.font.name == "Consolas":
                            mono_runs += 1

    # 斑马纹: 抽样第一张表 row2 是否有 F5F5F4 底纹
    zebra_ok = "no-tables"
    if tables:
        from docx.oxml import OxmlElement  # noqa
        t0 = tables[0]
        hits = []
        for ri in range(len(t0.rows)):
            for c in t0.rows[ri].cells:
                tcPr = c._tc.find(qn("w:tcPr"))
                if tcPr is not None:
                    shd = tcPr.find(qn("w:shd"))
                    if shd is not None:
                        hits.append((ri, shd.get(qn("w:fill"))))
        zebra_ok = sorted(set(hits))[:6]

    # 表头行加粗 + 表头下加粗线抽样
    header_bold = all(r.font.bold for r in tables[0].rows[0].cells[0].paragraphs[0].runs) if tables else None

    # 页脚
    footer_text = "\n".join(p.text for p in doc.sections[0].footer.paragraphs)

    # 结论段字号最大 run
    concl_max = max((r.font.size.pt for r in concl.runs if r.font.size), default=0) if concl else 0

    out = []
    out.append(f"md_headings={md_head} by_level={sorted(md_by.items())}")
    out.append(f"docx_headings={len(headings)} by_level={sorted(h_count.items())}")
    out.append(f"md_tables={md_tables}")
    out.append(f"docx_tables={len(tables)}")
    out.append(f"docx_paragraphs={len(paras)} expect_paragraphs={expect_paras}")
    out.append(f"asterisk_leftovers={leftovers}")
    out.append(f"conclusion_found={'yes' if concl else 'no'}")
    out.append(f"conclusion_max_size={concl_max} bold_runs={concl_bolds} colors={concl_colors}")
    out.append(f"risk_red_lines={red_lines}")
    out.append(f"price_tbl_col2='{price_col2}' mono={mono_ok} size11={size_ok} bold={bold_ok} rightalign={align_right}")
    out.append(f"right_aligned_cells={right_align} mono_runs={mono_runs}")
    out.append(f"zebra_shading_first_tbl={zebra_ok}")
    out.append(f"header_bold_first_tbl={header_bold}")
    out.append(f"footer_lines={len([ln for ln in footer_text.splitlines() if ln.strip()])}")
    out.append("footer_first_line=" + (footer_text.splitlines()[0] if footer_text.strip() else "EMPTY"))
    print("\n".join(out))


if __name__ == "__main__":
    main()
