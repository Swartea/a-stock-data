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
from docx.oxml import OxmlElement  # noqa: F401  # S1 迁出后薄壳无调用点; 为兼容保留的顶层 re-export
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor  # noqa: F401  # 同上: RGBColor 迁至 docx_primitives

# ---------------------------------------------------------------- Phase 1: Section Registry
# 容错 import: 缺则降级, 不阻断主流程 (Task 1.5: 6 块后追加 section 渲染)
try:
    from sections import enabled_sections
    _SECTIONS_OK = True
except Exception:  # noqa: BLE001
    enabled_sections = None
    _SECTIONS_OK = False

# ---------------------------------------------------------------- P2-E S3 re-export
# 区块 5（样式段落, 90 符号行 / 4 个符号）已按 docs/08-规范整改-P2E-文档渲染拆分-plan.md
# §六 S3 迁入 analysis/reporting/docx_paragraphs.py。此处**原样 re-export** 全部 4 个名字:
#
# - add_heading / add_quote / add_body 在薄壳内**仍有调用点**（区块 7 `_render_md_block`
#   的 4 处 + 区块 8 主流程的 4 处）;
# - RISK_EMOJI 迁出后薄壳内已无调用点（它唯一的调用点 `add_body` 已随区块 5 迁走）,
#   保留它可让 S3 之前的顶层可导入命名空间**逐名不变**（H2/H3 的兼容意图, §五
#   「保留文件头 + import + 容错 try 块」）, 故整条 import 挂 noqa: F401 —— 这是
#   **有意**的兼容面, 不是漏删（2026-10-06 拍板保留, 同 S1 的 HX_ACCENT/_ensure、
#   S2 的 NUM_RANGE）。
#
# 裸名 import（不写 reporting.* 全路径）: 与薄壳 `from sections import ...` 同一前提,
# analysis/ 在 sys.path 上。三条路径都成立 —— 脚本模式 sys.path[0] 即本文件所在目录
# （H2 的 `python <analysis>/md_to_docx.py <md> <docx>`）、artifact_writer.py:108 显式
# insert _ANALYSIS_DIR、CI PYTHONPATH（ci.yml:145 / :182）。
#
# 本块排在 S1/S2 两条**之前**是 isort 规范要求（I001 门禁）: 模块名按字典序
# docx_paragraphs < docx_primitives < docx_tables, 与片号先后无关。
#
# 本块**必须留在 import 前言区**（紧跟容错 try 块, 位于任何 def 之前）: 若放回
# 区块 5 的原物理位置, 它会排在 _load_result_near / md_to_docx 之后, 触发 E402
# 「module level import not at top of file」—— §十 收官门槛要求 full ruff advisory
# **无新增告警**, 而 E402 与 I001 属 pyproject `select` 的 E / I 规则, 都会被 advisory
# 抓到。移位不改任何行为（import 语句的位置不参与 §2.1 符号行口径的迁入量计算）。
from reporting.docx_paragraphs import (  # noqa: F401
    RISK_EMOJI,
    add_body,
    add_heading,
    add_quote,
)

# ---------------------------------------------------------------- P2-E S1 re-export
# 区块 2/3/4（设计 token / XML 小工具 / 内容运行拆分, 合计 108 符号行 / 24 个符号）
# 已按 docs/08-规范整改-P2E-文档渲染拆分-plan.md §六 S1 迁入
# analysis/reporting/docx_primitives.py。此处**原样 re-export** 全部 26 个名字
# （24 个符号 = 26 个名字: 区块 2 的 13 行常量赋值含 15 个常量名, HX_RED/HX_GREEN/
# HX_AMBER 同行三合一, 故 24 符号对应 26 名字）:
#
# - 区块 5/6/7/8 仍在薄壳内, 直接使用其中 20 个;
# - F_MONO / H_HEADER / _EMOJI_RE / _set_fonts 这 4 个是迁入符号的依赖面
#   （_fmt 的默认字体、p_border/cell_bottom_border 的默认色、md_runs 的拆段正则）;
# - HX_ACCENT / _ensure 这 2 个是 §十一 点名的死符号, 计划明确要求
#   「随所属区块原样搬走, 并在 md_to_docx 顶层 re-export」（§九 第 6 条 / §八 R6）。
#
# 这 6 个在薄壳内已无调用点, 保留它们可让 S1 之前的顶层可导入命名空间**逐名不变**
# （H2/H3 的兼容意图, §五「保留文件头 + import + 容错 try 块」）, 故整条 import 挂
# noqa: F401 —— 这是**有意**的兼容面, 不是漏删（2026-10-06 拍板保留, 不删这两个名字）。
# 同理, 上面 docx import 里的 OxmlElement / RGBColor 也一并保留并挂 noqa: F401。
#
# 裸名 import（不写 reporting.* 全路径）: 与薄壳 `from sections import ...` 同一前提,
# analysis/ 在 sys.path 上。三条路径都成立 —— 脚本模式 sys.path[0] 即本文件所在目录
# （H2 的 `python <analysis>/md_to_docx.py <md> <docx>`）、artifact_writer.py:108 显式
# insert _ANALYSIS_DIR、CI PYTHONPATH（ci.yml:145 / :182）。
#
# 名字顺序按 ruff isort 规范排（I001 门禁）, 故与 §2.2 区块顺序不同; 区块归属见上。
from reporting.docx_primitives import (  # noqa: F401
    _EMOJI_RE,
    C_ACCENT,
    C_AMBER,
    C_DARK,
    C_GREEN,
    C_MUTED,
    C_RED,
    F_CJK,
    F_MONO,
    FILL_ZEBRA,
    H_HAIR,
    H_HEADER,
    HX_ACCENT,
    HX_AMBER,
    HX_GREEN,
    HX_RED,
    _ensure,
    _fmt,
    _set_fonts,
    add_runs,
    cell_bottom_border,
    cell_shade,
    header_repeat,
    md_runs,
    p_border,
    table_borders,
)

# ---------------------------------------------------------------- P2-E S4 re-export
# 区块 7（Section Registry 辅助, 70 符号行 / 2 个符号）已按
# docs/08-规范整改-P2E-文档渲染拆分-plan.md §六 S4 迁入
# analysis/reporting/docx_sections.py。此处**原样 re-export** 全部 2 个名字:
#
# - _load_result_near / _render_md_block 在薄壳内**仍有调用点**（区块 8 主流程
#   §3.3 灰度循环内的 `_load_result_near(md_path)` 与 `_render_md_block(...)` 各 1 处）,
#   因此这条 import 既是兼容面（H2/H3）, 也是薄壳自身的依赖面; 仍挂 noqa: F401,
#   以免 S5 收官时把这两个名字当成漏删而"顺手清理"。
#
# 裸名 import（不写 reporting.* 全路径）: 与薄壳 `from sections import ...` 同一前提,
# analysis/ 在 sys.path 上。三条路径都成立 —— 脚本模式 sys.path[0] 即本文件所在目录
# （H2 的 `python <analysis>/md_to_docx.py <md> <docx>`）、artifact_writer.py:108 显式
# insert _ANALYSIS_DIR、CI PYTHONPATH（ci.yml:145 / :182）。
#
# 本块排在 S2 那条**之前**是 isort 规范要求（I001 门禁）: 模块名按字典序
# docx_paragraphs < docx_primitives < docx_sections < docx_tables, 与片号先后无关。
#
# 本块**必须留在 import 前言区**（紧跟 S1 那条 re-export, 位于任何 def 之前）:
# 若放回区块 7 的原物理位置, 它会排在 md_to_docx 之后, 触发 E402
# 「module level import not at top of file」—— §十 收官门槛要求 full ruff advisory
# **无新增告警**, 而 E402 与 I001 属 pyproject `select` 的 E / I 规则, 都会被 advisory
# 抓到。移位不改任何行为（import 语句的位置不参与 §2.1 符号行口径的迁入量计算）。
#
# H4 核对: 区块 7 全文检索 `sections` **零命中**（`enabled_sections` 的消费点在区块 8
# 的灰度循环, 不在迁出的两个函数里）, 故本模块**不需要**「裸名 + try 降级」那层包装;
# 本条 import 走的是与薄壳同前提的**裸名**形式, H4 满足。
from reporting.docx_sections import (  # noqa: F401
    _load_result_near,
    _render_md_block,
)

# ---------------------------------------------------------------- P2-E S2 re-export
# 区块 6（表格, 94 符号行 / 6 个符号）已按 docs/08-规范整改-P2E-文档渲染拆分-plan.md
# §六 S2 迁入 analysis/reporting/docx_tables.py。此处**原样 re-export** 全部 6 个名字:
#
# - flush_table 在薄壳内**仍有调用点**（区块 8 主流程的 local_flush 闭包）;
# - NUM_RANGE / DATE_ONLY / _clean_num / is_numeric_like / _cell_add 这 5 个迁出后
#   薄壳内已无调用点, 保留它们可让 S2 之前的顶层可导入命名空间**逐名不变**
#   （H2/H3 的兼容意图, §五「保留文件头 + import + 容错 try 块」）, 故整条 import 挂
#   noqa: F401 —— 这是**有意**的兼容面, 不是漏删（2026-10-06 拍板保留, 同 S1）。
# - NUM_RANGE 是 §十一 点名的死符号, 计划明确要求「随所属区块原样搬走, 并在
#   md_to_docx 顶层 re-export」（§九 第 6 条 / §八 R6）。
#
# 裸名 import（不写 reporting.* 全路径）: 与薄壳 `from sections import ...` 同一前提,
# analysis/ 在 sys.path 上。三条路径都成立 —— 脚本模式 sys.path[0] 即本文件所在目录
# （H2 的 `python <analysis>/md_to_docx.py <md> <docx>`）、artifact_writer.py:108 显式
# insert _ANALYSIS_DIR、CI PYTHONPATH（ci.yml:145 / :182）。
#
# 本块**必须留在 import 前言区**（紧跟 S1 那条 re-export, 位于任何 def 之前）:
# 若放回区块 6 的原物理位置, 它会排在 add_heading/add_quote/add_body 之后, 触发
# E402「module level import not at top of file」—— §十 收官门槛要求 full ruff
# advisory **无新增告警**, 而 E402 属 pyproject `select` 的 E 规则, 会被 advisory 抓到。
# 移位不改任何行为（import 语句的位置不参与 §2.1 符号行口径的迁入量计算）。
from reporting.docx_tables import (  # noqa: F401
    DATE_ONLY,
    NUM_RANGE,
    _cell_add,
    _clean_num,
    flush_table,
    is_numeric_like,
)


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
    table_rows: list[str] = []   # 当前表格的原始行文本（以 | 开头且以 | 结尾）
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
