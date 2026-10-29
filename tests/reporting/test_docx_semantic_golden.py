"""P2-E S0 · DOCX 渲染器版式语义回归门禁（**零网络 / 零 live / 零外部数据**）

要解决的问题: S0 之前全仓库**没有任何测试**断言 `md_to_docx` 的输出 ——
唯一的 docx 读回测试（`tests/reporting/test_artifact_delivery_contract.py:466-496`）
自建了一个最小 docx，根本不经过 `md_to_docx`；`tests/conftest.py:344` 的
`"docx": 57114` 是**手写**的 run_log fixture 值，断言只覆盖 `md`/`result_json`/
`run_log` 三个键的 `> 0`，从不断言 docx。

本模块锁「版式语义」而不是「容器字节」——理由与投影口径见
`tests/fixtures/docx_semantic/README.md` 与
`docs/08-规范整改-P2E-文档渲染拆分-plan.md` §7.1-7.2。

四道门:

1. 投影指纹 == 基线指纹（P2E 收官门槛 :333 的基线契约）
2. 投影内容 == 基线投影（门禁红了能看懂差在哪）
3. **跨进程双 `PYTHONHASHSEED`** 两个独立子进程 sha256 相等（确定性自证；
   **同进程连跑两次不算** —— 共享 `sys.modules` 与模块级缓存）
4. 投影装置自身没退化：确实捕获了 H1 关注的关键版式动作
   （含 `add_quote` **五条分支**逐条可辨，以及「普通免责声明 ≠ ⚠ 琥珀 quote」的结构区分）

本模块另含一组 P2-E S0 宿主模块登记门禁的负向控制（见文末小节），锁的是
`tests/conftest.py` 扫描面的完整性，不锁产物语义。

输入是**手工合成**的 `minimal.md`，不从 `reports/` 搬运，不依赖当日跑批。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", Path(__file__).resolve().parents[2])).resolve()
FIXTURE_DIR = WORKDIR / "tests" / "fixtures" / "docx_semantic"
MINIMAL_MD = FIXTURE_DIR / "minimal.md"
BASELINE_JSON = FIXTURE_DIR / "baseline.json"
APPARATUS_PY = FIXTURE_DIR / "docx_semantic.py"


def _load_apparatus():
    """按路径加载装置模块。

    刻意用 importlib 而不是 sys.path.insert + import: 装置不是包内模块, 也不该
    往 sys.path 上留东西。
    """
    spec = importlib.util.spec_from_file_location("p2e_docx_semantic", APPARATUS_PY)
    assert spec is not None and spec.loader is not None, f"装置模块无法加载: {APPARATUS_PY}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APPARATUS = _load_apparatus()


@pytest.fixture(scope="session")
def baseline() -> Dict[str, Any]:
    assert BASELINE_JSON.exists(), f"语义基线缺失: {BASELINE_JSON}"
    return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def projection(tmp_path_factory) -> Dict[str, Any]:
    """渲染 + 投影（一次）。工作目录是一次性的, 保证没有 result_v3-*.json。"""
    workdir = tmp_path_factory.mktemp("docx_semantic")
    return APPARATUS.render_to_projection(MINIMAL_MD, workdir)


@pytest.fixture(scope="session")
def blocks(projection) -> List[Dict[str, Any]]:
    return projection["blocks"]


# ============================================================
# 门 1 + 门 2: 语义基线
# ============================================================
def test_semantic_golden_sha256_matches_baseline(projection, baseline):
    """投影指纹 == 基线指纹。S1-S5 每片收官都要过这一条。"""
    actual = APPARATUS.sha256_of_projection(projection)
    assert actual == baseline["sha256"], (
        f"DOCX 语义基线漂移: 期望 {baseline['sha256']}, 实际 {actual}。"
        "先判定是『volatile 字段漏掩码』还是『真行为漂移』; "
        "禁止通过更新基线掩盖回归（见 tests/fixtures/docx_semantic/README.md）。"
    )


def test_semantic_golden_projection_matches_baseline(projection, baseline):
    """投影内容逐块相同。指纹相同但内容不同 = 基线文件与自身不自洽。"""
    assert projection == baseline["projection"], (
        "投影内容与基线不一致。基线文件里的 sha256 与 projection 必须描述同一份数据。"
    )


# ============================================================
# 门 3: 跨进程双 PYTHONHASHSEED 确定性自证
# ============================================================
def _run_in_subprocess(seed: str, workdir: Path) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    # 显式传仓库根, 保证子进程与本会话解析到同一个 analysis/（md_to_docx 走裸名
    # `from sections import ...`, 依赖 analysis/ 在 sys.path 上）
    env["DA_A_DATA_DIR"] = str(WORKDIR)
    proc = subprocess.run(
        [sys.executable, str(APPARATUS_PY), str(MINIMAL_MD), str(workdir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"子进程失败 (PYTHONHASHSEED={seed}):\n{proc.stderr}"
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"子进程无输出 (PYTHONHASHSEED={seed})"
    return lines[-1]  # 装置最后一行才是 sha256（前面是 md_to_docx 自己的 print）


def test_semantic_golden_is_identical_across_processes_with_different_hashseed(baseline, tmp_path):
    """两个**独立子进程**、各自显式设不同 PYTHONHASHSEED, sha256 必须相等。

    同进程连跑两次**不构成**证据: 同一进程共享 sys.modules 与模块级缓存,
    PYTHONHASHSEED 只有一个值, dict/set 迭代序换进程才可能变。
    """
    seed_a = _run_in_subprocess("0", tmp_path / "seed0")
    seed_b = _run_in_subprocess("12345", tmp_path / "seed12345")
    assert seed_a == seed_b, (
        f"跨进程不确定: PYTHONHASHSEED=0 得 {seed_a}, =12345 得 {seed_b}。"
        "禁止用『同进程连跑两次相同』冒充本项证据。"
    )
    assert seed_a == baseline["sha256"], (
        f"跨进程指纹与基线不一致: 子进程得 {seed_a}, 基线 {baseline['sha256']}"
    )


# ============================================================
# 门 4: 投影装置自身没退化
# ============================================================
def _first_paragraph(blocks, needle: str) -> Dict[str, Any]:
    for b in blocks:
        if b["kind"] == "p" and needle in b["text"]:
            return b
    raise AssertionError(f"投影里找不到含 {needle!r} 的段落")


def _first_table(blocks) -> Dict[str, Any]:
    for b in blocks:
        if b["kind"] == "tbl":
            return b
    raise AssertionError("投影里找不到表格")


def test_projection_preserves_paragraph_and_table_interleaving(blocks):
    """body 子元素顺序必须被投影保留。

    若装置改用 `doc.paragraphs` + `doc.tables` 两个独立列表, 表格会被挪到所有段落
    之后, 这条先红 —— 而顺序漂移正是拆分最易引入的回归。
    """
    kinds = [b["kind"] for b in blocks]
    assert "tbl" in kinds, "投影里没有表格块"
    tbl_at = kinds.index("tbl")
    assert kinds.index("p") < tbl_at, "表格前的段落丢了"
    assert any(k == "p" for k in kinds[tbl_at + 1:]), "表格后的段落丢了（顺序被重排）"
    assert kinds[-1] == "sectPr", f"body 末尾应为 sectPr, 实际 {kinds[-1]}"


def test_projection_captures_quote_severity_colors(blocks):
    """看多 → 红, 看空 → 绿（A股涨跌配色）+ 左侧粗边框。这是用户可见契约。"""
    bull = _first_paragraph(blocks, "综合结论")
    bear = _first_paragraph(blocks, "由")
    bull_runs = {r[0]: r for r in bull["runs"]}
    assert "看多" in bull_runs, f"结论区引用未按 run 拆开: {bull['runs']}"
    assert bull_runs["看多"][6] == "DC2626", f"看多应为红: {bull_runs['看多']}"
    assert bull["borders"] and bull["borders"][0][0] == "left", "结论区应有左边框"
    assert bull["borders"][0][4] == "DC2626", f"看多左边框应为红: {bull['borders']}"
    assert bear["borders"] and bear["borders"][0][4] == "15803D", (
        f"含看空的引用左边框应为绿: {bear['borders']}"
    )


# ============================================================
# 门 4 续: add_quote 五条分支逐条可辨
# ============================================================
# add_quote (analysis/md_to_docx.py:205-236) 的分支判定**按顺序**是:
#   ① in_conclusion(当前 H2 以 🎯 开头) 或正文含 看空/看多 → 14pt 加粗大字 + 18sz 语义色左边框
#   ② 含「数据来源」                                    → 9pt  灰 + 6sz  hairline 左边框
#   ③ 以「⚠」开头                                      → 10pt 琥珀 + 10sz 琥珀左边框   ← S0 曾整条漏覆盖
#   ④ 其余                                             → 9.5pt 灰 + 6sz hairline 左边框
#
# 表里只登记**能区分分支**的字段: 边框 (edge, sz, space, color) + 正文字号 + 语义色。
# 不登记字体名等与分支判定无关的模板级样式 —— 那些由门 1/门 2 的整体比对兜底。
# 字号必须进签名: ② 与 ④ 的边框四元组**完全相同** (left/6/3/E7E5E4), 只靠边框无法分辨。
QUOTE_BRANCH_EXPECTATIONS = (
    # (分支名, 样本锚点文字, 边框四元组, 字号, 该分支必须出现的 run 颜色)
    ("① 结论区/看多红", "综合结论", ("left", "18", "4", "DC2626"), 14.0, "DC2626"),
    ("① 看空绿", "转为", ("left", "18", "4", "15803D"), 14.0, "15803D"),
    ("② 数据来源灰", "数据来源", ("left", "6", "3", "E7E5E4"), 9.0, "57534E"),
    ("③ ⚠ 琥珀", "风险提示", ("left", "10", "3", "B45309"), 10.0, "B45309"),
    ("④ 其余灰字", "合成数据", ("left", "6", "3", "E7E5E4"), 9.5, "57534E"),
)


def _non_emoji_runs(block: Dict[str, Any]) -> List[List[Any]]:
    """只取正文 run, 排除 `⚠` 这类 emoji 引导 run。

    `add_runs` 对 emoji run 不设颜色 (投影里是 null) —— 那是 emoji 处理的产物,
    与 add_quote 的分支语义无关。断言分支颜色/字号只看正文 run。
    """
    return [r for r in block["runs"] if r[0].strip() not in ("⚠", "⚠️")]


def test_quote_paragraph_count_matches_branch_table(blocks):
    """带**左边框**的段落 = add_quote 的产物, 数量应与分支表 5 条严格相等。

    这条是 S0 缺口的守门人: 缺了它, 有人把 amber 那行从 minimal.md 删掉后,
    其余断言仍全绿 (没人再去找那条分支), 门禁会退化成"只比剩下的文本"。
    多了则说明分支表漏登记, README 的覆盖清单会失真。
    """
    quoted = [
        b for b in blocks
        if b["kind"] == "p" and any(e[0] == "left" for e in b["borders"])
    ]
    assert len(quoted) == len(QUOTE_BRANCH_EXPECTATIONS) == 5, (
        f"fixture 里 add_quote 产物 {len(quoted)} 段, 分支表 {len(QUOTE_BRANCH_EXPECTATIONS)} 条。"
        "少 = 有分支没被覆盖; 多 = 分支表漏登记。"
    )


def test_add_quote_branches_are_each_distinguishable(blocks):
    """五条分支逐条断言, 且签名两两不同 —— 分支不可辨 = 门禁只剩文本比对。"""
    signatures = []
    for name, needle, border, size, color in QUOTE_BRANCH_EXPECTATIONS:
        q = _first_paragraph(blocks, needle)
        # 投影里的边框记录是 [edge, val, sz, space, color], 表里登记的是
        # (edge, sz, space, color) —— 中间的 w:val 恒为 p_border 写死的 "single"。
        expected_border = [[border[0], "single", border[1], border[2], border[3]]]
        assert q["borders"] == expected_border, (
            f"{name} 左边框 (edge, val, sz, space, color) 不符: "
            f"{q['borders']} != {expected_border}"
        )
        body = _non_emoji_runs(q)
        assert body, f"{name} 段落没有正文 run: {q['runs']}"
        assert {r[5] for r in body} == {size}, f"{name} 字号应为 {size}: {body}"
        assert color in {r[6] for r in body}, f"{name} 缺语义色 {color}: {body}"
        signatures.append((border, size))
    assert len(set(signatures)) == len(signatures), (
        f"分支签名有重复, 无法逐条区分: {signatures}"
    )


def test_amber_quote_branch_is_explicitly_covered(blocks):
    """S0 的实际缺口: `add_quote` 第 ③ 条 ⚠ 琥珀分支**整条没被覆盖**。

    原 minimal.md 只有末尾一行「⚠ 免责声明」, 那是 `add_body` 的正文段落
    (md_to_docx.py:522), 走不到 `add_quote` 的 ⚠ 分支; 而 README 却把它记成了
    "⚠ 琥珀" 已覆盖。故按字段逐项锁死, 缺任一条即红。
    """
    q = _first_paragraph(blocks, "风险提示")
    assert q["text"].startswith("⚠ "), f"琥珀 quote 应以 ⚠ 开头: {q['text']!r}"
    assert any(r[0] == "⚠" for r in q["runs"]), f"⚠ 应作为独立引导 run: {q['runs']}"
    assert len(q["borders"]) == 1 and q["borders"][0] == [
        "left", "single", "10", "3", "B45309"
    ], f"琥珀 quote 左边框应为 left/single/10/3/B45309: {q['borders']}"
    body = _non_emoji_runs(q)
    assert [r[5] for r in body] == [10.0], f"琥珀 quote 正文应 10pt: {body}"
    assert {r[6] for r in body} == {"B45309"}, (
        f"琥珀 quote 文字色应为 C_AMBER(B45309): {body}"
    )


def test_plain_disclaimer_is_not_the_amber_quote(blocks):
    """普通「⚠ 免责声明」是**正文段落**, 不是 ⚠ 琥珀 quote —— 两者都以「⚠ 」开头。

    区别是**结构**上的, 不只是颜色: 免责声明是**顶** hairline 分隔线
    (sz 6 / E7E5E4) + 9pt 灰字; 琥珀 quote 是**左** 10sz / B45309 边框 + 10pt 琥珀字。
    断言必须落到「哪一条边」, 只比颜色挡不住"把免责声明误当 quote 渲染"的回归。
    """
    disc = _first_paragraph(blocks, "免责声明: 本文件为 S0")
    assert disc["borders"] == [["top", "single", "6", "4", "E7E5E4"]], (
        f"普通免责声明应是**顶** hairline 分隔线: {disc['borders']}"
    )
    disc_body = _non_emoji_runs(disc)
    assert [r[5] for r in disc_body] == [9.0], f"免责声明应 9pt 灰字: {disc_body}"
    assert {r[6] for r in disc_body} == {"57534E"}, f"免责声明应为 C_MUTED: {disc_body}"

    amber = _first_paragraph(blocks, "风险提示")
    assert disc["borders"][0][0] == "top", "免责声明不该有左边框"
    assert amber["borders"][0][0] == "left", "琥珀 quote 应有左边框"
    assert disc["borders"][0][0] != amber["borders"][0][0], (
        "两者边框边名相同 = 结构上可能互相冒充, 区分断言失效"
    )


def test_projection_captures_table_style_actions(blocks):
    """flush_table 的全部样式动作都要在投影里可见。

    hairline 六边框 / 表头加粗 / 斑马纹 / 数字列右对齐等宽 / 「价位·数值」列 11pt
    加粗 / 「综合」行加粗 —— 任一项若漏投影, 门禁就退化成"只比文本"。
    """
    t = _first_table(blocks)
    assert (t["nrows"], t["ncols"]) == (4, 3), f"表格规模不对: {t['nrows']}x{t['ncols']}"
    assert t["header_repeat"] is True, "首行应有 tblHeader（跨页重复表头）"
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        assert t["borders"].get(edge) is not None, f"缺表格边框: {edge}"
        assert t["borders"][edge][3] == "E7E5E4", f"{edge} 边框色应为 hairline E7E5E4"

    header = t["cells"][0]
    assert header[0]["paragraphs"][0]["runs"][0][1] is True, "表头应加粗"

    # 斑马纹: 数据行 1/3 上 F5F5F4, 行 2 不上
    assert t["cells"][1][0]["fill"] == "F5F5F4", "第 1 数据行应有斑马纹"
    assert t["cells"][2][0]["fill"] is None, "第 2 数据行不应有斑马纹"

    # 数字列: 右对齐 + Consolas 等宽
    price = t["cells"][1][1]
    assert price["paragraphs"][0]["align"] == "RIGHT", "数值列应右对齐"
    run = price["paragraphs"][0]["runs"][0]
    assert run[3] == "Consolas", f"数值列应用等宽字体: {run[3]}"
    assert run[5] == 11.0, f"「价位·数值」列应 11pt: {run[5]}"
    assert run[1] is True, "「价位·数值」列应加粗"

    # 「综合」行加粗
    assert t["cells"][3][0]["paragraphs"][0]["runs"][0][1] is True, "「综合」行应加粗"


def test_projection_captures_footer_and_gen_time_mask(blocks):
    """页脚 3 段必须被投影, 且『生成时间』确实被掩码（非静默失效）。"""
    sect = [b for b in blocks if b["kind"] == "sectPr"]
    assert len(sect) == 1, f"应有且仅有一个 sectPr 块: {len(sect)}"
    footer = sect[0]["footer"]
    assert len(footer) == 3, f"页脚应为 3 段: {len(footer)}"
    assert footer[0].startswith("数据来源"), footer[0]
    assert footer[1].startswith("免责声明"), footer[1]
    assert APPARATUS.GEN_TIME_PLACEHOLDER in footer[2], (
        f"页脚生成时间未被掩码: {footer[2]}"
    )
    masked = sum(t.count(APPARATUS.GEN_TIME_PLACEHOLDER) for t in footer)
    assert masked == 1, f"掩码占位符应恰好出现 1 次, 实际 {masked}"


def test_h1_title_is_centered_with_bottom_hairline(blocks):
    """H1 报告名: 居中 + 下边框。这是模板层样式, 拆 thin-shell 时最容易丢。"""
    h1 = _first_paragraph(blocks, "合成样本")
    assert h1["style"] == "Heading 1", f"H1 样式名不对: {h1['style']}"
    assert h1["align"] == "CENTER", f"H1 应居中: {h1['align']}"
    edges = {b[0] for b in h1["borders"]}
    assert "bottom" in edges, f"H1 应有下边框: {h1['borders']}"


def test_minimal_md_is_synthetic_and_offline():
    """输入必须是手工合成样本: 不含本机路径 / 绝对路径 / http(s)。"""
    text = MINIMAL_MD.read_text(encoding="utf-8")
    for bad in ("/Users/", "/home/", "http://", "https://"):
        assert bad not in text, f"minimal.md 不应含 {bad}（要求离线、可跨机复核）"
    assert "000001" in text, "样本应使用合成代码, 不使用真实标的"


# ============================================================
# P2-E S0 · 宿主模块登记门禁 (tests/conftest.py 的 _assemble_host_modules)
# ============================================================
# 为什么这组测试住在本文件
# ----------------------
# 本轮只允许改 6 个既定文件, 宿主登记门禁的负向控制因此并入本模块。两者同属
# "P2-E S0 · DOCX 渲染器门禁", 但**关注点不同**: 上面四道门锁**产物语义**, 下面这组
# 锁**扫描面的完整性**。若日后允许新增文件, 应整组移到 tests/test_docx_split_source.py。
#
# 门禁本身在 tests/conftest.py 的 md_to_docx_split_source, 由
# tests/test_three_levels.py::test_docx_renderer_follows_md_no_hardcode 与
# tests/test_multi_state_trading_plan.py::test_docx_renderer_does_not_hardcode_operation
# 的 `not src.missing_modules` 覆盖断言实际执行。
CONFTEST_PY = WORKDIR / "tests" / "conftest.py"


def _load_conftest_helpers():
    """按路径取 conftest 里的三个纯 helper。

    conftest 不可直接 import (import 它会把 fixture 注册到本模块的命名空间, 且 pytest
    对 conftest 的 import 语义特殊), 故用 importlib 单独加载一份。
    """
    spec = importlib.util.spec_from_file_location("p2e_conftest_helpers", CONFTEST_PY)
    assert spec is not None and spec.loader is not None, f"conftest 无法加载: {CONFTEST_PY}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load_conftest_helpers()


def _make_fake_analysis(tmp_path: Path, module_names: List[str]) -> Path:
    """在隔离目录里造一个 analysis/reporting/, 塞入指定的 docx_*.py。

    **只写 tmp_path**: 真实 analysis/reporting/ 一律不动 —— 制造"多一个模块"必须靠
    隔离副本, 靠改源码树来造异常会把仓库搞脏, 且失败时无法还原。
    """
    analysis = tmp_path / "analysis"
    reporting = analysis / "reporting"
    reporting.mkdir(parents=True)
    (analysis / "md_to_docx.py").write_text("# fake shell\n", encoding="utf-8")
    for name in module_names:
        (reporting / name).write_text(f"# {name}\n", encoding="utf-8")
    return analysis


def test_host_module_registry_and_disk_scan_are_independent(tmp_path):
    """**回归锁定**: 磁盘上有 docx_ghost.py、但登记为空时,
    `present` 必须是空 (host_files 的模块部分只认登记), 同时 missing 必须报出 ghost。

    初版把同一个 glob 同时用于构造 host_files 与算磁盘集合, 差分恒空 —— 这条断言
    钉死的正是那个恒真: 若有人把 _assemble_host_modules 改回 glob, present 会变成
    [docx_ghost.py], 本条立刻红。
    """
    analysis = _make_fake_analysis(tmp_path, ["docx_ghost.py"])
    present, missing, absent, on_disk = GATE._assemble_host_modules(analysis, ())
    assert present == [], f"host_files 模块部分只认显式登记, 不该收进 {present}"
    assert on_disk == {"docx_ghost.py"}, f"独立磁盘扫描应看到 ghost: {on_disk}"
    assert missing == ("docx_ghost.py",), f"新增未登记模块必须报错: {missing}"
    assert absent == (), f"登记为空时不该有登记缺失: {absent}"


def test_host_module_registry_reports_absent_module(tmp_path):
    """反向: 登记了但磁盘上没有的模块必须报错 (否则登记与事实脱节一路绿灯)。"""
    analysis = _make_fake_analysis(tmp_path, ["docx_primitives.py"])
    registered = ("reporting/docx_primitives.py", "reporting/docx_tables.py")
    present, missing, absent, on_disk = GATE._assemble_host_modules(analysis, registered)
    assert [p.name for p in present] == ["docx_primitives.py"]
    assert on_disk == {"docx_primitives.py"}
    assert missing == (), f"已登记且存在, 不该报未登记: {missing}"
    assert absent == ("docx_tables.py",), f"登记缺失必须报错: {absent}"


def test_host_module_registry_matched_state_has_no_findings(tmp_path):
    """登记与磁盘完全一致 → 两类差分都空 (无误报)。"""
    analysis = _make_fake_analysis(tmp_path, ["docx_primitives.py", "docx_tables.py"])
    registered = ("reporting/docx_primitives.py", "reporting/docx_tables.py")
    _present, missing, absent, on_disk = GATE._assemble_host_modules(analysis, registered)
    assert on_disk == {"docx_primitives.py", "docx_tables.py"}
    assert (missing, absent) == ((), ()), f"一致态不应有任何发现: {missing} {absent}"


def test_host_module_diff_is_symmetric_and_ordered():
    """_module_diff 纯函数: 双向、对称、已排序 —— 不依赖磁盘即可验证。"""
    assert GATE._module_diff(set(), set()) == ((), ())
    assert GATE._module_diff({"a.py"}, {"a.py"}) == ((), ())
    assert GATE._module_diff({"a.py"}, {"a.py", "z.py", "b.py"}) == (("b.py", "z.py"), ())
    assert GATE._module_diff({"a.py", "m.py"}, {"a.py"}) == ((), ("m.py",))
    assert GATE._module_diff(set(), {"q.py"}) == (("q.py",), ())


def test_real_split_source_has_no_module_findings(md_to_docx_split_source, analysis_dir):
    """真实仓库当前状态: 零误报, 且扫描面 = 薄壳 + **全部已登记且存在**的宿主模块。

    这是"当前模块集通过"的正向控制 —— 若 N2 改成"登记了没建的模块"或反过来拿计划
    当现状, 这条会红。

    S1 起（2026-10-06）本条随拆分进度演进, 改了两处 S0 专属写法, **均不放松咬合**:

    1. `registered_modules` 的比对。S0 写的是
       `src.registered_modules == DOCX_HOST_MODULES`, 但前者是 fixture 报出的
       **basename** 元组（conftest: `tuple(Path(rel).name for rel in ...)`）,
       后者是**相对路径**元组 —— 两者类型本就不同, S0 因登记表为空而两边都是 `()`,
       断言**恒真从未真正比对过**。S1 登记表非空, 这个潜伏的类型错当场暴露。
       现改为按 basename 比对, 断言才第一次真的成立。
    2. `src.files` 的钉法。S0 把它写死成 `("analysis/md_to_docx.py",)`（"S0 未拆,
       扫描面应只有薄壳"）—— 那是 S0 的**状态**, 不是不变式, S1 建出第一个模块后必然失效,
       且硬编码模块名会要求每片都改本条。现改为**由登记表推导**的结构断言:
       不写死任何模块名（S2/S3/S4 不必再动本条）, 也不放松 —— 真正的咬合在下面两条
       missing/absent 差分上, 那是登记表与**独立磁盘扫描**之间的双向差分, 两侧不同源。
    """
    src = md_to_docx_split_source
    assert src.missing_modules == (), f"当前不该有未登记模块: {src.missing_modules}"
    assert src.absent_modules == (), f"当前不该有登记缺失: {src.absent_modules}"
    assert list(src.registered_modules) == [Path(rel).name for rel in GATE.DOCX_HOST_MODULES], (
        f"fixture 报出的登记名应等于登记表 basename 列表: {list(src.registered_modules)}"
    )
    expected_tail = [
        f"analysis/{rel}" for rel in GATE.DOCX_HOST_MODULES if (analysis_dir / rel).exists()
    ]
    assert list(src.files) == ["analysis/md_to_docx.py"] + expected_tail, (
        f"扫描面必须逐项等于「薄壳 + 已登记且存在的宿主模块」: {list(src.files)}"
    )


def test_negative_controls_never_touch_real_source_tree(tmp_path):
    """防呆: 负向控制全程只写 tmp_path, 真实 analysis/reporting/ 不得被新增/删除文件。

    S1 起（2026-10-06）把末尾那条 `assert not list(real.glob("docx_*.py"))` 换成
    **不变式**写法。原文断言的是"真实 reporting/ 下不存在 docx_*.py" —— 那是 S0 的
    **状态**（一个模块都还没建）, 不是本测试的**目的**（负向控制不得改动真实源码树）,
    S1 建出 docx_primitives.py 后必然失效。现改为「跑负向控制前后 docx_*.py 集合不变」,
    恰好就是本测试要证明的那件事, 且与上面 `before == after`（整个目录快照）互为补充。
    """
    real = WORKDIR / "analysis" / "reporting"
    before = {p.name for p in real.iterdir()}
    before_docx = {p.name for p in real.glob("docx_*.py")}
    analysis = _make_fake_analysis(tmp_path, ["docx_ghost.py", "docx_extra.py"])
    GATE._assemble_host_modules(analysis, ("reporting/docx_ghost.py",))
    GATE._assemble_host_modules(analysis, ())
    after = {p.name for p in real.iterdir()}
    after_docx = {p.name for p in real.glob("docx_*.py")}
    assert before == after, f"真实源码树被负向控制改动: {before ^ after}"
    assert before_docx == after_docx, (
        f"真实 reporting/ 下的 docx_*.py 被负向控制改动: {before_docx ^ after_docx}"
    )
