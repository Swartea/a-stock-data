#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_to_docx.py — Markdown 决策报告 → 微信优选格式 DOCX（样式层 v2）

样式层按 docs/06-排版美化方案.md §2/§3 定稿规范改造（2026-09-06）：
  H1 报告名大字居中 / H2 章节强调色 #2563eb / H3 小节分级
  表格：hairline 细边框(E7E5E4) + 斑马纹(F5F5F4) + 数字单元格右对齐等宽(Consolas)
  三价位数值列：等宽加粗 11pt
  结论区（多空结论/评分）：14pt 加粗大字；看空→A股绿(跌)、看多→A股红(涨)
  风险警报区：🔴 行红色 #dc2626 / 🟡 行琥珀色 / 🟢 行绿色字体
  页脚：免责声明 + 数据来源 + 生成时间（真实 Word 页脚）
解析逻辑主体（逐行规则/分支顺序）保持 v1 不变，只增强样式层。

调用方式: bash scripts/run_in_venv.sh python analysis/md_to_docx.py <input.md> <output.docx>
"""
import re
import sys
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

# ---------------------------------------------------------------- Phase 1: Section Registry
# 容错 import: 缺则降级, 不阻断主流程 (Task 1.5: 6 块后追加 section 渲染)
try:
    from sections import enabled_sections
    _SECTIONS_OK = True
except Exception:  # noqa: BLE001
    enabled_sections = None
    _SECTIONS_OK = False

# ---------------------------------------------------------------- 设计 token
# docs/06 §2.1：禁纯黑；打印 AA 用加深过的警告/正色
C_DARK   = RGBColor(0x1C, 0x19, 0x17)   # 文字
C_ACCENT = RGBColor(0x25, 0x63, 0xEB)   # 强调（H2）
C_RED    = RGBColor(0xDC, 0x26, 0x26)   # 危险 / A股涨
C_GREEN  = RGBColor(0x15, 0x80, 0x3D)   # A股跌（#16a34a 加深到 AA）
C_AMBER  = RGBColor(0xB4, 0x53, 0x09)   # 警告（#d97706 加深到 AA）
C_MUTED  = RGBColor(0x57, 0x53, 0x4E)   # 次级文字/页脚
H_HAIR   = "E7E5E4"                      # hairline 分隔
H_HEADER = "D6D3D1"                      # 表头下加粗线
FILL_ZEBRA = "F5F5F4"
HX_RED, HX_GREEN, HX_AMBER = "DC2626", "15803D", "B45309"
HX_ACCENT = "2563EB"

F_CJK  = "Microsoft YaHei"   # 中文（微信/Word 通用）
F_MONO = "Consolas"          # 数字等宽

# emoji 拆段（只拆内容正文里出现的符号，标题里的不动；变体选择符 FE0F 并入同一 token，防止孤立 VS16）
_EMOJI_RE = re.compile("([\U0001F000-\U0001FAFF][️]?|[☀-➿][️]?|[⬀-⯿][️]?)")


# ---------------------------------------------------------------- XML 小工具
def _set_fonts(run, latin, cjk):
    """同时设拉丁与东亚字体"""
    run.font.name = latin
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cjk)


def _fmt(run, size=None, bold=None, color=None, mono=False, italic=None):
    """统一字体格式入口：默认 微软雅黑/常规黑字"""
    _set_fonts(run, F_MONO if mono else F_CJK, F_CJK)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    return run


def _ensure(parent, tag, successors):
    """按 OOXML 顺序插子元素（succ=必须排在后面的标签名列表）"""
    el = OxmlElement(tag)
    try:
        parent.insert_element_before(el, *successors)
    except Exception:
        parent.append(el)
    return el


def p_border(p, edge="bottom", color=H_HEADER, sz=6, space=2):
    """段落边框（hairline）"""
    pPr = p._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.insert_element_before(pBdr, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr")
    e = OxmlElement("w:" + edge)
    for k, v in (("w:val", "single"), ("w:sz", str(sz)), ("w:space", str(space)), ("w:color", color)):
        e.set(qn(k), v)
    pBdr.append(e)


def cell_shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.insert_element_before(shd, "w:noWrap", "w:tcMar", "w:vAlign", "w:textDirection", "w:tcFitText", "w:hideMark")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def table_borders(t, color=H_HAIR, sz=4):
    tblPr = t._tbl.tblPr
    borders = tblPr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tblPr.insert_element_before(borders, "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = borders.find(qn("w:" + edge))
        if e is None:
            e = OxmlElement("w:" + edge)
            borders.append(e)
        for k, v in (("w:val", "single"), ("w:sz", str(sz)), ("w:space", "0"), ("w:color", color)):
            e.set(qn(k), v)


def cell_bottom_border(cell, color=H_HEADER, sz=6):
    tcPr = cell._tc.get_or_add_tcPr()
    tcB = tcPr.find(qn("w:tcBorders"))
    if tcB is None:
        tcB = OxmlElement("w:tcBorders")
        tcPr.insert_element_before(tcB, "w:shd", "w:noWrap", "w:tcMar", "w:vAlign", "w:textDirection", "w:tcFitText", "w:hideMark")
    e = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", str(sz)), ("w:space", "0"), ("w:color", color)):
        e.set(qn(k), v)
    tcB.append(e)


def header_repeat(row):
    trPr = row._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    th.set(qn("w:val"), "true")
    trPr.append(th)


# ---------------------------------------------------------------- 内容运行拆分
def md_runs(content):
    """把 **加粗** 与 emoji 拆成 (text, bold, is_emoji) 元组流"""
    for seg in re.split(r"(\*\*[^*]+\*\*)", content):
        if not seg:
            continue
        bold = seg.startswith("**") and seg.endswith("**")
        if bold:
            seg = seg[2:-2]
        pos = 0
        for m in _EMOJI_RE.finditer(seg):
            if m.start() > pos:
                yield seg[pos:m.start()], bold, False
            yield m.group(1), bold, True
            pos = m.end()
        if pos < len(seg):
            yield seg[pos:], bold, False


def add_runs(p, content, size=10.5, color=None, bold_all=False, mono_all=False):
    """往段落追加内容运行；color 非空时非 emoji 文字上色，emoji 保持本色"""
    for text, bold, emoji in md_runs(content):
        r = p.add_run(text)
        rcol = None if (emoji or color is None) else color
        _fmt(r, size=size, bold=(bold_all or bold), color=rcol, mono=mono_all)


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


# ---------------------------------------------------------------- Section Registry 辅助
def _load_result_near(md_path):
    """从 md_path 同目录读 result_v3-*.json (Task 1.5: 不依赖 V3 caller 改签名)
    Returns: dict 或 None (任何 IO/JSON 错误均返回 None)
    """
    try:
        import json as _json
        d = Path(md_path).parent
        # 优先匹配 stem 末尾 -HHMM 时间戳的 json
        stem = Path(md_path).stem  # e.g. "600693-东百集团-1616"
        cand = []
        m = re.search(r"-(\d{4})$", stem)
        if m:
            cand = list(d.glob(f"result_v3-{m.group(1)}.json"))
        if not cand:
            cand = list(d.glob("result_v3-*.json"))
        if not cand:
            return None
        latest = max(cand, key=lambda p: p.stat().st_mtime)
        return _json.loads(latest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _render_md_block(doc, md_text, stats):
    """把一段 markdown 文本追加到 docx, 复用样式函数 (Task 1.5: section registry)
    逻辑与主流程的 while 循环等价, 但自带 cur_h2 / risk_zone / table_rows 状态
    """
    lines = md_text.split("\n")
    i = 0
    in_table = False
    table_rows = []
    cur_h2 = ""
    risk_zone = False
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_rows.append(line)
            in_table = True
            continue
        elif in_table:
            flush_table(doc, table_rows, stats)
            in_table = False
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            add_heading(doc, text, level, stats)
            if level == 2:
                cur_h2 = text
                risk_zone = bool(re.search(r"风险警报", cur_h2))
            continue
        if re.match(r"^-{3,}$", line.strip()):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run("─" * 40)
            _fmt(r, size=9, color=C_MUTED)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            stats["paragraphs"] += 1
            continue
        if line.startswith(">"):
            add_quote(doc, line[1:], stats, in_conclusion=(cur_h2.startswith("🎯")))
            continue
        if not line.strip():
            continue
        if line.startswith("⚠️ 免责声明") or line.startswith("⚠ 免责声明"):
            add_body(doc, line, stats, disclaimer=True)
            continue
        add_body(doc, line, stats, risk_zone=risk_zone)
    if in_table:
        flush_table(doc, table_rows, stats)


# ---------------------------------------------------------------- 主流程
def md_to_docx(md_path: str, docx_path: str) -> None:
    md = Path(md_path).read_text(encoding="utf-8")
    doc = Document()
    stats = {"headings": 0, "by_level": {}, "paragraphs": 0, "tables": 0, "cells": 0}

    style = doc.styles["Normal"]
    style.font.name = F_CJK
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), F_CJK)
    style.font.color.rgb = C_DARK

    gen_time = datetime.fromtimestamp(Path(md_path).stat().st_mtime).strftime("%Y-%m-%d %H:%M")

    lines = md.split("\n")
    i = 0
    in_table = False
    table_rows = []
    cur_h2 = ""
    risk_zone = False

    def local_flush():
        flush_table(doc, table_rows, stats)

    while i < len(lines):
        line = lines[i]
        i += 1

        # 表格行累积
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_rows.append(line)
            in_table = True
            continue
        elif in_table:
            local_flush()
            in_table = False

        # 标题（更新风险区状态）
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            add_heading(doc, text, level, stats)
            if level == 2:
                cur_h2 = text
                risk_zone = bool(re.search(r"风险警报", cur_h2))
            continue

        # 分隔线
        if re.match(r"^-{3,}$", line.strip()):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run("─" * 40)
            _fmt(r, size=9, color=C_MUTED)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            stats["paragraphs"] += 1
            continue

        # 引用
        if line.startswith(">"):
            add_quote(doc, line[1:], stats, in_conclusion=(cur_h2.startswith("🎯")))
            continue

        # 空行
        if not line.strip():
            continue

        # 末尾免责声明：置灰小字 + 顶部分隔线
        if line.startswith("⚠️ 免责声明") or line.startswith("⚠ 免责声明"):
            add_body(doc, line, stats, disclaimer=True)
            continue

        # 普通段落 / 列表行
        add_body(doc, line, stats, risk_zone=risk_zone)

    # 末尾表格
    if in_table:
        local_flush()

    # ---- §3.3 灰度: 6 块之后追加 Section Registry 渲染循环 ----
    # 5 新节(irm/holders/dividend/board/dragon_market)走注册表, 旧 6 块仍保留
    # writer 语义钉死: 不传 writer, 只取返回值 (Task 1.4 教训: writer 是 list 但实际不 append)
    if _SECTIONS_OK and enabled_sections is not None:
        result = _load_result_near(md_path)
        if result:
            for sec in enabled_sections():
                try:
                    sec_data = result.get(sec.label, {}) or {}
                    sec_md = sec.render_md(sec_data)
                    if sec_md:
                        _render_md_block(doc, sec_md, stats)
                except Exception:  # noqa: BLE001
                    # 单节失败不阻断其他渲染 (per-section isolation)
                    pass

    # ---------------------------------------------------------- 页脚
    sec = doc.sections[0]
    footer = sec.footer
    lines3 = [
        "数据来源: 腾讯实时行情 / 东方财富 / 同花顺 / baostock / 巨潮资讯 (公开数据)",
        "免责声明: 本报告由多因子量化模型自动生成, 仅供研究参考, 不构成投资建议; 市场有风险, 投资须谨慎。",
        "生成时间: %s ｜ A股扛把子 · V3 决策报告 (微信优选版)" % gen_time,
    ]
    first = True
    for ln in lines3:
        if first:
            fp = footer.paragraphs[0]
            first = False
        else:
            fp = footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fp.paragraph_format.space_after = Pt(2)
        fp.paragraph_format.space_before = Pt(0)
        r = fp.add_run(ln)
        _fmt(r, size=8, color=C_MUTED)

    out = Path(docx_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(docx_path)
    print(f"OK: {docx_path}")
    print("summary: headings=%d (H1:%d H2:%d H3:%d H4:%d) paragraphs=%d tables=%d cells=%d bytes=%d"
          % (stats["headings"], stats["by_level"].get(1, 0), stats["by_level"].get(2, 0),
             stats["by_level"].get(3, 0), stats["by_level"].get(4, 0),
             stats["paragraphs"], stats["tables"], stats["cells"], out.stat().st_size))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python md_to_docx.py <input.md> <output.docx>", file=sys.stderr)
        sys.exit(1)
    md_to_docx(sys.argv[1], sys.argv[2])
