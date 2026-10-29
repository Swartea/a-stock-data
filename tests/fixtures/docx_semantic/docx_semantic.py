"""P2-E S0 · DOCX 语义投影装置（semantic projection, **非**逐字节 golden）

为什么不用逐字节 golden
------------------------
`.docx` 是 zip 容器, 逐字节相等有三重不可复现（P2E §7.1）:

1. zip entry 头含落盘时间戳 —— 同一输入两次 `doc.save()` 字节就不同;
2. `docProps/core.xml` 的 `modified` 随落盘时刻变化;
3. 即便前两条都解决, `python-docx` / `lxml` 一次版本升级就会改动 zip 内 XML 的
   序列化细节, 而**版式语义一模一样** —— 这是假回归, 长期只会诱导"更新基线以
   掩盖回归", 比没有门禁更危险。

所以本装置锁「版式语义」而不是「容器字节」。

投影口径（P2E §7.2）
--------------------
- **必须**按 `word/document.xml` 的 **body 子元素顺序** 遍历。
  不能用 `doc.paragraphs` 与 `doc.tables` 两个独立列表 —— 那会丢掉段落与表格的
  **交错顺序**, 而顺序漂移正是拆分最易引入的回归。
- 段落 → 样式名 / 全文 / run 级 (文本, 加粗, 斜体, 拉丁字体, 东亚字体, 字号, 颜色)
  / 段落边框 `w:pBdr` 各边 (val, sz, space, color)
- 表格 → 行数 / 列数 / `w:tblBorders` 六边 (val, sz, space, color) /
  首行 `w:tblHeader` / 每个单元格 (文本, 段落对齐, `w:shd` fill, run 级属性)
- `sectPr` → 页脚段落文本（3 段）

归一化: **只做一件事** —— 页脚"生成时间"的取值。
--------------------------------------------------------------
该值来自输入 MD 的 mtime（`analysis/md_to_docx.py:465` → `:555`）。本装置:

1. 用 `os.utime` 把输入 MD 的 mtime **钉死**, 让真实代码路径完整走通
   （不是绕过代码、不是造一个假的 md_to_docx 调用）;
2. 再把该字段的取值替换成固定占位符 `<GEN_TIME>`。
   之所以在钉 mtime 之后**还要**替换: `datetime.fromtimestamp()` 取的是
   **本地时区**时间, 不钉时区则同一个 mtime 在 UTC+8 与 UTC 机器上产出不同字符串,
   基线就无法跨机复核。替换后与时区、与复制文件时的 mtime 漂移都无关。

除该字段外, 投影**不做**任何掩码 / 排序 / 截断 / 补白。替换次数必须恰好为 1,
否则直接抛错 —— 掩码一旦静默失效（模板改了字样）就会变成"永远绿"的空门禁。

输入
----
`minimal.md`: **手工合成**的最小样本。不从 `reports/` 搬运任何产物, 不依赖任何
真实标的、任何网络数据、任何当日跑批结果, 也不读同目录的 `result_v3-*.json`
（渲染器 `_load_result_near` 会去 MD 同目录找 result JSON, 故本装置一律把输入
复制到一次性工作目录再渲染, 并对"工作目录里出现 result_v3-*.json" fail loud）。

用法
----
    python docx_semantic.py <md_path> <workdir>                        # 打印 sha256
    python docx_semantic.py <md_path> <workdir> --emit-baseline f.json  # 写基线文件

基线文件的重新生成是一次**显式动作**, 不是测试的一部分: 先确认差异是
"volatile 字段漏掩码"还是"真行为漂移", 能指出是哪一处投影、对应哪一行模板、
为什么语义上等价于原行为, 才允许覆盖基线（沿用 docs/13 §十三-四 第 6 条）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

# 仓库根: 与 tests/conftest.py:30 同一口径（从本文件位置推导, 不硬编码个人路径,
# 支持 DA_A_DATA_DIR 覆盖）。
WORKDIR_DEFAULT = str(Path(__file__).resolve().parents[3])
WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", WORKDIR_DEFAULT)).resolve()
ANALYSIS_DIR = WORKDIR / "analysis"

# 输入 MD 的固定 mtime（S0 常量）。改它 = 改基线, 必须同片改 baseline.json。
PINNED_MTIME = 1704157440

# 页脚生成时间的唯一掩码值。
GEN_TIME_PLACEHOLDER = "<GEN_TIME>"
_GEN_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


# ============================================================
# 导入人格: md_to_docx 走裸名 `from sections import ...`, 故 analysis/ 必须在
# sys.path 上（与 .github/workflows/ci.yml 的 PYTHONPATH 同一前提）。
# ============================================================
def _ensure_import_paths() -> None:
    for p in (str(ANALYSIS_DIR), str(WORKDIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


# ============================================================
# 投影
# ============================================================
def _run_record(run) -> List[Any]:
    """run 级版式属性。None 一律保留为 null, 不做"等价归一"
    —— 「显式设成某值」与「继承样式」在版式上不等价。"""
    rPr = run._element.rPr
    east_asia = None
    if rPr is not None and rPr.rFonts is not None:
        east_asia = rPr.rFonts.get(qn("w:eastAsia"))
    size_pt = None
    if run.font.size is not None:
        size_pt = run.font.size.pt
    color = None
    try:
        rgb = run.font.color.rgb
    except (AttributeError, ValueError):
        rgb = None
    if rgb is not None:
        color = str(rgb)
    return [
        run.text,
        bool(run.bold),
        bool(run.italic),
        run.font.name,      # w:ascii（拉丁）
        east_asia,          # w:eastAsia（东亚）
        size_pt,
        color,
    ]


def _paragraph_borders(p_el) -> List[List[Any]]:
    """段落边框。语义上是"边的集合", 故按边名排序, 与写入顺序无关。"""
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        return []
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        return []
    out = []
    for e in pBdr:
        out.append([
            e.tag.split("}")[-1],
            e.get(qn("w:val")),
            e.get(qn("w:sz")),
            e.get(qn("w:space")),
            e.get(qn("w:color")),
        ])
    return sorted(out)


def _paragraph_record(p) -> Dict[str, Any]:
    return {
        "kind": "p",
        "style": p.style.name if p.style is not None else None,
        "text": p.text,
        "align": p.alignment.name if p.alignment is not None else None,
        "borders": _paragraph_borders(p._p),
        "runs": [_run_record(r) for r in p.runs],
    }


def _cell_record(cell) -> Dict[str, Any]:
    tcPr = cell._tc.find(qn("w:tcPr"))
    fill = None
    if tcPr is not None:
        shd = tcPr.find(qn("w:shd"))
        if shd is not None:
            fill = shd.get(qn("w:fill"))
    return {
        "text": cell.text,
        "fill": fill,
        "paragraphs": [
            {
                "align": p.alignment.name if p.alignment is not None else None,
                "runs": [_run_record(r) for r in p.runs],
            }
            for p in cell.paragraphs
        ],
    }


def _table_record(t) -> Dict[str, Any]:
    tbl = t._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    borders: Dict[str, Any] = {}
    if tblPr is not None:
        tb = tblPr.find(qn("w:tblBorders"))
        if tb is not None:
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                e = tb.find(qn("w:" + edge))
                borders[edge] = None if e is None else [
                    e.get(qn("w:val")),
                    e.get(qn("w:sz")),
                    e.get(qn("w:space")),
                    e.get(qn("w:color")),
                ]
    first_tr = tbl.tr_lst[0] if len(tbl.tr_lst) else None
    header_repeat = False
    if first_tr is not None:
        trPr = first_tr.find(qn("w:trPr"))
        header_repeat = trPr is not None and trPr.find(qn("w:tblHeader")) is not None
    return {
        "kind": "tbl",
        "nrows": len(t.rows),
        "ncols": len(t.columns),
        "borders": borders,
        "header_repeat": header_repeat,
        "cells": [[_cell_record(c) for c in row.cells] for row in t.rows],
    }


def _mask_gen_time(texts: List[str]) -> List[str]:
    """页脚"生成时间"是**唯一**允许归一化的字段。替换次数必须恰好为 1。"""
    hits = 0
    out = []
    for t in texts:
        t2, n = _GEN_TIME_RE.subn(GEN_TIME_PLACEHOLDER, t)
        hits += n
        out.append(t2)
    if hits != 1:
        raise AssertionError(
            f"页脚生成时间字段替换次数 = {hits}（应为 1）。"
            "模板若改了字样, 掩码会静默失效, 基线将不再覆盖该字段 —— "
            "请同步核对 md_to_docx.py:552-556 与本装置的 _GEN_TIME_RE。"
        )
    return out


def project(docx_path) -> Dict[str, Any]:
    """把一个 .docx 投影成纯 JSON 结构（段落/表格/页脚, 保持 body 交错顺序）。"""
    doc = Document(str(docx_path))
    blocks: List[Dict[str, Any]] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(_paragraph_record(Paragraph(child, doc)))
        elif child.tag == qn("w:tbl"):
            blocks.append(_table_record(Table(child, doc)))
        elif child.tag == qn("w:sectPr"):
            blocks.append({
                "kind": "sectPr",
                "footer": _mask_gen_time(
                    [p.text for p in doc.sections[0].footer.paragraphs]
                ),
            })
        else:
            # 不认识的 body 子元素必须显式暴露, 不能静默丢弃（否则新增块类型时
            # 投影会悄悄漏掉它, 门禁失守）。
            blocks.append({"kind": "unknown", "tag": child.tag})
    return {"schema": "p2e-s0-docx-semantic/1", "blocks": blocks}


# ============================================================
# 规范化 + 指纹
# ============================================================
def canonical_bytes(projection: Dict[str, Any]) -> bytes:
    """与 tests/fixtures/golden/golden_fixtures.py 的 dump() 同一序列化口径
    （sort_keys + indent=2 + 末尾换行; 末尾换行必须一起算进去）。"""
    return (json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_of_projection(projection: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(projection)).hexdigest()


def baseline_envelope(projection: Dict[str, Any]) -> Dict[str, Any]:
    """基线文件的内容: 指纹 + 完整投影。

    指纹是门禁契约（P2E 收官门槛 :333「语义 golden sha256 与 S0 基线逐字节相同」,
    以及跨进程双 PYTHONHASHSEED 自证比的就是它）; 完整投影是为了**门禁红了能看懂
    差在哪** —— 只存一个哈希, 失败时无法定位是哪一段版式漂移。

    两者必须同时成立: 指纹证明"与基线同一份数据", 投影证明"这份数据就是当时那份"。
    """
    return {
        "schema": "p2e-s0-docx-semantic-baseline/1",
        "sha256": sha256_of_projection(projection),
        "projection": projection,
    }


# ============================================================
# 渲染入口
# ============================================================
def render_to_projection(md_path, workdir) -> Dict[str, Any]:
    """复制输入 MD 到一次性工作目录 → 钉 mtime → 渲染 → 投影。

    复制到工作目录有两个理由:
    1. 渲染器 `_load_result_near`（md_to_docx.py:379-399）会去 **MD 同目录**
       glob `result_v3-*.json`, 命中就把 Section Registry 的 5 个灰度块追加进来
       —— 那是环境相关的, 会让基线不可复现;
    2. 复制后可以把 mtime 钉死, 原始 fixture 文件的 mtime 保持不动。
    """
    _ensure_import_paths()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    stray = sorted(workdir.glob("result_v3-*.json"))
    if stray:
        raise AssertionError(
            f"工作目录里出现 result_v3-*.json: {stray} —— 渲染器会把 Section "
            "Registry 灰度块追加进产物, 基线将依赖环境。装置假定工作目录是干净的。"
        )
    target = workdir / Path(md_path).name
    shutil.copyfile(str(md_path), str(target))
    os.utime(str(target), (PINNED_MTIME, PINNED_MTIME))

    from md_to_docx import md_to_docx  # 裸名导入: 与 artifact_writer.py:109 同一入口

    docx_path = workdir / (target.stem + ".docx")
    md_to_docx(str(target), str(docx_path))
    return project(docx_path)


# ============================================================
# CLI（跨进程确定性自证用: 两个独立子进程各跑一次, 只比 sha256）
# ============================================================
def main(argv: List[str]) -> int:
    if len(argv) not in (3, 5):
        print("Usage: docx_semantic.py <md_path> <workdir> "
              "[--emit-baseline <out.json>]", file=sys.stderr)
        return 1
    md_path, workdir = argv[1], argv[2]
    out_to = None
    if len(argv) == 5:
        if argv[3] != "--emit-baseline":
            print("Usage: docx_semantic.py <md_path> <workdir> "
                  "[--emit-baseline <out.json>]", file=sys.stderr)
            return 1
        out_to = argv[4]
    projection = render_to_projection(md_path, workdir)
    if out_to:
        Path(out_to).write_bytes(canonical_bytes(baseline_envelope(projection)))
    print(sha256_of_projection(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
