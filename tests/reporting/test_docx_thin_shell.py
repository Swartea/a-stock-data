"""薄壳收官门禁（P2-E S5 交付物, 本轮新建）

S5 本身**不搬任何代码**（§六 S5 行「薄壳收官 | re-export 块固化并**实测**残留行数;
三个死符号原样保留 | H1-H4 全部收口」）。它把前三片（S1-S4）留下的**收官态**变成
可执行断言, 使 §十 的收官门槛不再依赖「人工记得去看」:

| §十 收官门槛 | 本文件对应断言 |
|---|---|
| `< 400 残留文件行` | `test_thin_shell_residual_file_lines_under_400` |
| **符号行守恒 158 + 362 = 520** | `test_symbol_row_conservation_shell_plus_modules_is_520` |
| 四个模块预算 108/94/90/70 | `test_each_module_matches_its_plan_budget` |
| 落在 300-500 区间的模块 0 个 | `test_no_module_lands_in_300_500_band` |
| re-export 块固化（H2/H3 兼容面） | `test_reexport_block_covers_all_41_host_symbols` 等 |
| 三个死符号原样保留（R6） | `test_three_dead_symbols_are_still_present` |
| H1-H4 全部收口 | `test_h2_h3_h4_contract_surface_intact` 等 |

§六 每片统一形态第 2 步是「新模块建自己的单测」; S5 没有新模块, 故本文件测的是
**薄壳这一层契约**（不测主流程行为 —— 主流程行为由 §七 语义 golden 逐字覆盖）。
只测迁出符号与薄壳结构, 不重复 S1-S4 四个文件里已覆盖的模块内行为。
"""
import ast
import re
from pathlib import Path

from tests.conftest import (
    DOCX_HOST_MODULES,
    DOCX_HOST_SYMBOLS,
    DOCX_PLANNED_MODULES,
)

# ============================================================
# §十 收官门槛 1: 薄壳 < 400 残留文件行
# ============================================================
SHELL = "md_to_docx.py"


def _read(analysis_dir, rel):
    return (analysis_dir / rel).read_text(encoding="utf-8")


def _physical_lines(analysis_dir, rel):
    return len(_read(analysis_dir, rel).splitlines())


def test_thin_shell_residual_file_lines_under_400(analysis_dir):
    """§十 收官门槛第 1 条: 薄壳残留文件行 < 400（对标 P2A `docs/08-…-P2A-…:80`）。

    S3 后 361 → S4 后 **317**; S5 不搬码, 该值**不应再变**。锁住它有两个作用:
    ① 任何人往薄壳里塞回迁出符号会立刻红; ② §五 预估的「约 200-230 行」与
    实测 317 的差额（re-export 注释块占大头）被固定成事实, 不再是估算。
    """
    n = _physical_lines(analysis_dir, SHELL)
    assert n < 400, f"§十 门槛: 薄壳 {n} 行, 已达/超过 400"
    assert n == 317, f"S4 收官实测 317 行, S5 未搬码, 不应变化（现 {n}）"


def test_residual_is_far_below_the_p2a_400_threshold(analysis_dir):
    """门槛不是「刚好压线」: 317 行距 400 还有 83 行余量, 留得住后续真实改动。"""
    n = _physical_lines(analysis_dir, SHELL)
    assert n <= 400 - 50, f"余量仅 {400 - n} 行, 不再是健康余量"


# ============================================================
# §十 收官门槛 2: 符号行守恒 158 + 362 = 520
# ============================================================
#: §五 逐模块迁入符号行预算（符号行口径, §2.1）。
MODULE_BUDGETS = {
    "reporting/docx_primitives.py": 108,
    "reporting/docx_tables.py": 94,
    "reporting/docx_paragraphs.py": 90,
    "reporting/docx_sections.py": 70,
}

#: §五/§十 薄壳保留的符号行 = 区块 1 (29) + 区块 8 (124) + 区块 9 (5)。
SHELL_BUDGET = 158

#: §2.1 拆分前实测的符号行合计。
PRE_SPLIT_SYMBOL_ROWS = 520

#: §5 迁移后应保留的全部符号行（薄壳 + 四模块）。
TOTAL_BUDGET = 520


def _migrated_symbol_rows(analysis_dir, rel):
    """按 §5 口径复算某模块的「迁入符号行」。

    口径（§五「不含新文件自身的 import 块与文件头」+ §2.1）:
      - 模块 docstring（首个 Expr 常量）不计;
      - `import` / `from ... import` 节点不计;
      - 其余顶层符号按 `end_lineno - lineno + 1` 计入, 装饰器 / docstring /
        注释 / **块内空行**一并计入（§2.1 特别强调后者, 拆分最易漏算）。
    """
    tree = ast.parse(_read(analysis_dir, rel))
    rows = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue          # 模块级 docstring = 文件头
        rows += node.end_lineno - node.lineno + 1
    return rows


def test_each_module_matches_its_plan_budget(analysis_dir):
    """§五 四行预算逐个复算: 108 / 94 / 90 / 70。"""
    measured = {rel: _migrated_symbol_rows(analysis_dir, rel) for rel in MODULE_BUDGETS}
    assert measured == MODULE_BUDGETS, f"§五 预算偏离: {measured}"


def test_module_budgets_sum_to_362(analysis_dir):
    """§五 合计行: 362 = 520 − 留薄壳的 158。"""
    total = sum(_migrated_symbol_rows(analysis_dir, rel) for rel in MODULE_BUDGETS)
    assert total == 362, f"四模块合计 {total}, §五 记 362"


def test_shell_retained_symbol_rows_equal_158(analysis_dir):
    """薄壳保留 158 符号行 = 区块 1 (29) + 区块 8 (124) + 区块 9 (5)。

    re-export 的 4 条 `from reporting... import` **不计入** 158 —— 它们是 S1-S4
    新增的兼容面, 不是 §2.2 区块 1/8/9 的组成部分。§五 明示 re-export 块
    「估 30-60 行, UNVERIFIED」, 本片实测 46 条 import 语句行（见下一条）。
    """
    tree = ast.parse(_read(analysis_dir, SHELL))
    retained = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # 区分「原文件的依赖导入（区块 1）」与「S1-S4 的 re-export 块」
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("reporting."):
                continue
            retained += node.end_lineno - node.lineno + 1
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            retained += node.end_lineno - node.lineno + 1   # 文件头 docstring 14
            continue
        retained += node.end_lineno - node.lineno + 1       # try 6 + md_to_docx 124 + __main__ 5
    assert retained == SHELL_BUDGET, f"薄壳保留符号行 {retained}, §五/§十 记 158"


def test_symbol_row_conservation_shell_plus_modules_is_520(analysis_dir):
    """§十 收官门槛第 2 条（核心）: **符号行守恒**, 与 §2.1 拆分前实测完全一致。

    158 + 362 = 520。这条断言是「结构拆分没有丢代码也没有凭空多出代码」的
    唯一机械化证据 —— 行数只统计顶层符号, 逐符号的逐字节等价由 S1-S4 各自
    的测试文件负责。
    """
    modules = sum(_migrated_symbol_rows(analysis_dir, rel) for rel in MODULE_BUDGETS)
    shell = 0
    tree = ast.parse(_read(analysis_dir, SHELL))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("reporting."):
            continue
        shell += node.end_lineno - node.lineno + 1
    total = modules + shell
    assert shell == SHELL_BUDGET
    assert modules == 362
    assert total == PRE_SPLIT_SYMBOL_ROWS, f"符号行守恒破坏: {modules} + {shell} = {total}"
    assert total == TOTAL_BUDGET


# ============================================================
# §十 收官门槛 3: 落在 300-500 符号行区间的模块 —— 0 个
# ============================================================
def test_no_module_lands_in_300_500_band(analysis_dir):
    """§十 第 3 条 + §五「关于 300-500 区间」。

    这是**已解释的偏差**而非未达标项: P2-A 的 300-500 门槛是为「2184 行拆 6 块」
    设计的; 520 符号行拆 4 块, 任何切法都进不去该区间（§一 第 1 条的算术依据）。
    硬凑只会引入填充代码（`docs/10-…:281`「本阶段的价值是边界与可测性, 不是行数」）。
    """
    measured = {rel: _migrated_symbol_rows(analysis_dir, rel) for rel in MODULE_BUDGETS}
    in_band = {rel: n for rel, n in measured.items() if 300 <= n <= 500}
    assert in_band == {}, f"§十 要求落在 300-500 的模块为 0 个, 实测 {in_band}"
    assert sorted(measured.values()) == [70, 90, 94, 108], f"模块行数漂移: {measured}"


# ============================================================
# §十 收官门槛 4: re-export 块固化（H2 双人格 / H3 假模块面）
# ============================================================
def test_reexport_block_covers_all_41_host_symbols(analysis_dir):
    """H2 + H3 的兼容面: 41 个宿主符号**逐名**仍在薄壳上。

    38 个来自四个模块（26 + 4 + 2 + 6）, 3 个是薄壳自有的
    `md_to_docx` / `enabled_sections` / `_SECTIONS_OK`。用 `hasattr` 而非
    `from md_to_docx import (...)`: 后者缺名会在收集期 ImportError 且不告诉你是哪个名字。
    """
    import md_to_docx as shell

    assert len(DOCX_HOST_SYMBOLS) == 41
    missing = sorted(n for n in DOCX_HOST_SYMBOLS if not hasattr(shell, n))
    assert not missing, f"薄壳丢失 re-export 名字: {missing}"


def test_reexport_values_are_the_same_objects_not_copies():
    """re-export 必须是**同一对象**而非复制品, 否则薄壳与新模块各走各的路径。"""
    import md_to_docx as shell
    from reporting import (
        docx_paragraphs,
        docx_primitives,
        docx_sections,
        docx_tables,
    )

    for mod, names in (
        (docx_primitives, (
            "C_DARK", "C_ACCENT", "C_RED", "C_GREEN", "C_AMBER", "C_MUTED",
            "H_HAIR", "H_HEADER", "FILL_ZEBRA", "HX_RED", "HX_GREEN", "HX_AMBER",
            "HX_ACCENT", "F_CJK", "F_MONO", "_EMOJI_RE", "_set_fonts", "_fmt", "_ensure",
            "p_border", "cell_shade", "table_borders", "cell_bottom_border",
            "header_repeat", "md_runs", "add_runs",
        )),
        (docx_paragraphs, ("add_heading", "add_quote", "RISK_EMOJI", "add_body")),
        (docx_tables, ("NUM_RANGE", "DATE_ONLY", "_clean_num", "is_numeric_like",
                       "_cell_add", "flush_table")),
        (docx_sections, ("_load_result_near", "_render_md_block")),
    ):
        for name in names:
            assert getattr(shell, name) is getattr(mod, name), f"{name} 不是同一对象"


def test_shell_defines_no_migrated_symbol_in_place(analysis_dir):
    """§六 硬规则「禁止新旧两套实现并存」: 薄壳不得再原地定义任何迁出符号。

    只查**定义**（`^def` / `^X =`）, 不查名字出现 —— re-export import 与调用点
    当然会出现这些名字。38 个迁出名逐一查, 不是抽样。
    """
    src = _read(analysis_dir, SHELL)
    defined = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
                elif isinstance(t, ast.Tuple):
                    defined.update(e.id for e in t.elts if isinstance(e, ast.Name))
    migrated = set(DOCX_HOST_SYMBOLS) - {"md_to_docx", "enabled_sections", "_SECTIONS_OK"}
    still = sorted(migrated & defined)
    assert not still, f"薄壳仍原地定义 {still} —— 新旧两套实现并存"


def test_reexport_block_is_46_import_rows_closing_unverified_2(analysis_dir):
    """§十二 第 2 条 UNVERIFIED（re-export 块 30-60 行, 纯估算）**由本片实测关闭**。

    实测 = **46 条 import 语句行**（4 条 `from reporting... import (...)`）,
    落在原估算 30-60 的区间内 → 估算成立, 保留为事实。
    含横幅注释的 re-export 区物理行 = 144 行, 这是薄壳 317 行与 §五 预估
    200-230 行差额的主因（注释占大头, 属**有意**保留的迁移溯源, 见 §五）。
    """
    tree = ast.parse(_read(analysis_dir, SHELL))
    reexport = [
        n for n in tree.body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("reporting.")
    ]
    assert len(reexport) == 4, f"应为 4 条 re-export import, 实测 {len(reexport)}"
    rows = sum(n.end_lineno - n.lineno + 1 for n in reexport)
    assert rows == 46, f"re-export import 语句行实测 {rows}, 与 §十二 第 2 条估算区间不符"
    assert 30 <= rows <= 60, "原估算区间 30-60 被实测推翻, 需改写 §十二 第 2 条"


def test_reexport_blocks_sit_in_the_import_preamble(analysis_dir):
    """4 条 re-export 必须留在 import 前言区, 且全部排在任何 `def` 之前。

    放回原物理位置会排在 `md_to_docx` 之后 → E402「module level import not at
    top of file」, 而 E402 与 I001 都会被 §十 要求的 full ruff advisory 抓到
    （`All checks passed` 不能有新告警）。这条把该约束做成可执行断言。
    """
    tree = ast.parse(_read(analysis_dir, SHELL))
    first_def = min(
        (n.lineno for n in tree.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))),
        default=10 ** 9,
    )
    reexport = [
        n for n in tree.body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("reporting.")
    ]
    late = [n.module for n in reexport if n.lineno > first_def]
    assert not late, f"re-export 排在 def 之后会触发 E402: {late}"


def test_shell_uses_bare_name_imports_not_dotted_paths(analysis_dir):
    """H4 / R7: 薄壳走**裸名** `from reporting.docx_xxx import ...`。

    `from analysis.reporting ...` 在 CI 矩阵（`PYTHONPATH` 指向 `analysis/` 与仓库根,
    `ci.yml:145` / `:182`）下会 ImportError。三个 import 人格都必须成立:
    脚本模式 `sys.path[0]`、`artifact_writer.py:108` 显式 insert `analysis/`、CI PYTHONPATH。
    """
    src = _read(analysis_dir, SHELL)
    for mod in ("docx_paragraphs", "docx_primitives", "docx_sections", "docx_tables"):
        assert f"from reporting.{mod} import" in src, f"缺少裸名 import: {mod}"
    assert "from analysis.reporting" not in src
    assert "from reporting import" not in src


def test_shell_has_no_sys_path_manipulation(analysis_dir):
    """§三「文件内 import 人格」: 薄壳全文**无 `sys.path` 操作**。

    判据用 ast 的 **import / 属性访问节点**, 不用全文 grep —— S1-S4 的 re-export
    横幅注释里大量解释「analysis/ 在 sys.path 上」, 全文 grep 必然误报。
    """
    tree = ast.parse(_read(analysis_dir, SHELL))
    offenders = [
        f"L{n.lineno}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr in ("path", "path_hooks")
    ]
    assert not offenders, f"薄壳出现 sys.path 操作: {offenders}"


# ============================================================
# §十 收官门槛 5: 三个死符号原样保留（R6 / §十一 / §九 第 6 条）
# ============================================================
DEAD_SYMBOLS = ("_ensure", "NUM_RANGE", "HX_ACCENT")


def test_three_dead_symbols_are_still_present(analysis_dir):
    """§六 S5 行「三个死符号**原样保留**」+ R6。

    删除死符号是**行为面清理**, 混进结构拆分会让「行为不变」这个判据失效
    （P2-D `:431-432` 同源纪律）。§九 第 6 条把它们留给**另开单片**单独决策。
    """
    import md_to_docx as shell

    for name in DEAD_SYMBOLS:
        assert hasattr(shell, name), f"死符号 {name} 被删了 —— 违反 §九 第 6 条 / R6"


def test_dead_symbols_still_live_in_their_owner_modules(analysis_dir):
    """死符号随所属区块搬走, 但**定义仍在新模块内**（不是只在薄壳留个名字）。"""
    from reporting import docx_primitives, docx_tables

    assert docx_primitives._ensure.__module__ == "reporting.docx_primitives"
    assert docx_primitives.HX_ACCENT == "2563EB"
    assert docx_tables.NUM_RANGE is not None


def test_dead_symbols_keep_their_original_definitions(analysis_dir):
    """逐字锁定: 死符号的定义行与 §2.2 记的原始内容一致（未被顺手清理或改写）。"""
    prim = _read(analysis_dir, "reporting/docx_primitives.py")
    tables = _read(analysis_dir, "reporting/docx_tables.py")
    assert "def _ensure(parent, tag, successors):" in prim
    assert 'HX_ACCENT = "2563EB"' in prim
    assert "NUM_RANGE" in tables
    # §十一 记的三者 grep -c 实测计数 = 1（只有定义行, 零调用点）—— 薄壳侧不得新增调用
    shell_src = _read(analysis_dir, SHELL)
    for name in DEAD_SYMBOLS:
        assert not re.search(rf"\b{name}\(", shell_src), f"薄壳新增了 {name} 的调用点"


# ============================================================
# §十 收官门槛 6: H1-H4 逐条仍绿（薄壳侧可执行部分）
# ============================================================
def test_h2_script_personality_preserved(analysis_dir):
    """H2: 薄壳必须**留在原路径**且同时满足双人格 —— 可 import 出 `md_to_docx`
    函数, 也可 `python <analysis>/md_to_docx.py <md> <docx>` 直接执行。

    `artifact_writer.py:115-127` 把本文件**当脚本路径**拼进 `subprocess.run`
    （`check=True` / `timeout=180`），薄壳一旦移走或改名, 降级路径直接失效。
    两条判据: `__main__` 块仍在 + 入口文件名逐字未变。
    """
    shell_path = analysis_dir / SHELL
    assert shell_path.exists(), "H2: 薄壳必须留在 analysis/md_to_docx.py 原路径"
    src = shell_path.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in src, "H2: __main__ 转发块丢失"
    assert "Usage: python md_to_docx.py <input.md> <output.docx>" in src
    assert "len(sys.argv) != 3" in src
    # H2 记录的 CLI 契约: argv 长度校验 + 报错 + 转发
    tree = ast.parse(src)
    ifblock = [n for n in tree.body if isinstance(n, ast.If)][-1]
    assert ifblock.end_lineno - ifblock.lineno + 1 == 5, "§2.2 区块 9 = 5 符号行"


def test_h2_artifact_writer_coupling_untouched(analysis_dir):
    """H2 的对侧: `artifact_writer.py` 的双路径引用**本轮零改动**（§九 第 3 条）。"""
    src = (analysis_dir / "reporting" / "artifact_writer.py").read_text(encoding="utf-8")
    assert "from md_to_docx import md_to_docx as _md2docx" in src, "H2: import 人格被改动"
    assert 'os.path.join(_ANALYSIS_DIR, "md_to_docx.py")' in src, "H2: 脚本路径拼接被改动"


def test_h3_fake_module_surface_still_exposes_only_md_to_docx(analysis_dir):
    """H3: `tests/reporting/test_artifact_delivery_contract.py` 有 **5 处**
    `monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)`, 假模块**只挂
    `md_to_docx` 一个属性**。故 `artifact_writer` 侧**不得**改成经
    `analysis.reporting.docx_*` 路径取渲染器, 薄壳顶层必须仍有 `md_to_docx` 这个名字。
    """
    tests_src = Path(__file__).parent / "test_artifact_delivery_contract.py"
    src = tests_src.read_text(encoding="utf-8")
    sites = re.findall(r'setitem\(sys\.modules, "md_to_docx"', src)
    assert len(sites) == 5, f"H3 记 5 处假模块注入, 实测 {len(sites)} 处"

    import md_to_docx as shell

    assert callable(shell.md_to_docx)
    writer = (analysis_dir / "reporting" / "artifact_writer.py").read_text(encoding="utf-8")
    assert "from analysis.reporting" not in writer, "H3: artifact_writer 不得走包路径取渲染器"


def test_h4_bare_name_import_stays_inside_try_except(analysis_dir):
    """H4: `from sections import enabled_sections` 是**裸名**且包在模块级
    `try/except Exception` 里, 缺则降级为 `enabled_sections = None` /
    `_SECTIONS_OK = False`, 不阻断主流程。改走 `analysis.sections` 包路径在
    CI 矩阵下会 ImportError（R7）。
    """
    tree = ast.parse(_read(analysis_dir, SHELL))
    trys = [n for n in tree.body if isinstance(n, ast.Try)]
    assert len(trys) == 1, f"薄壳应只有 1 个模块级 try（区块 1）, 实测 {len(trys)}"
    tr = trys[0]
    assert tr.end_lineno - tr.lineno + 1 == 6, "§2.2 区块 1 的 try = 6 符号行"
    assert any(isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in tr.handlers)
    body_src = ast.get_source_segment(_read(analysis_dir, SHELL), tr)
    assert "from sections import enabled_sections" in body_src
    assert "_SECTIONS_OK = True" in body_src
    assert "enabled_sections = None" in body_src
    assert "_SECTIONS_OK = False" in body_src


def test_h1_source_text_gates_read_the_split_fixture_not_the_shell_alone(analysis_dir):
    """H1 的修复在 S0 完成: 两条**否定式**源码文本门禁必须读 `md_to_docx_split_source`
    （薄壳 + 全部已登记宿主模块）, 而不是只读薄壳 —— 否则薄壳变小会让断言恒真、
    **静默假绿**（§7.3 表格「不会 —— 静默假绿」）。
    """
    conftest_src = Path(__file__).parent.parent / "conftest.py"
    src = conftest_src.read_text(encoding="utf-8")
    assert "def md_to_docx_split_source" in src
    for test_file in ("test_three_levels.py", "test_multi_state_trading_plan.py"):
        t = (Path(__file__).parent.parent / test_file).read_text(encoding="utf-8")
        assert "md_to_docx_split_source" in t, f"{test_file} 未改读 split fixture"
        assert "assert not src.missing_symbols" in t
        assert "assert not src.missing_modules" in t
        assert "assert src.line_count >= 560" in t


def test_registry_lists_exactly_the_four_planned_modules():
    """§七 N2: `DOCX_HOST_MODULES` 必须与 §五 的四个规划模块**集合一致**。

    显式登记（判据侧）与磁盘扫描（事实侧）必须独立, 否则 `missing_modules`
    恒为空集 —— 那正是 S0 初版的恒真门禁。S5 收官时两侧应当一致。

    比**集合**不比元组顺序: 登记顺序记录的是各片的落位先后（primitives → tables →
    paragraphs → sections）, §五 表格按区块顺序（primitives → paragraphs → tables →
    sections）, 两者本就不同, 且顺序不影响 `_assemble_host_modules` 的判定。
    """
    assert set(DOCX_HOST_MODULES) == set(DOCX_PLANNED_MODULES), (
        f"登记与规划脱节: {set(DOCX_HOST_MODULES) ^ set(DOCX_PLANNED_MODULES)}"
    )
    assert len(DOCX_HOST_MODULES) == 4


# ============================================================
# §十 收官门槛 7: 语义 golden 基线未被篡改（指纹是门禁契约）
# ============================================================
GOLDEN_SHA256 = "a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93"


def test_semantic_golden_baseline_still_holds_the_s0_fingerprint(analysis_dir):
    """§十 第 4 条 + §7.2: 基线指纹必须仍是 S0 实测的权威值。

    指纹是门禁契约; §10.2 回滚条款明令「禁止通过更新基线 sha256 掩盖回归」。
    这里只读校验, 不重生成。
    """
    import json

    baseline = analysis_dir.parent / "tests" / "fixtures" / "docx_semantic" / "baseline.json"
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["sha256"] == GOLDEN_SHA256, (
        f"基线指纹被改动: {data['sha256']} —— §10.2 禁止以此掩盖回归"
    )


# ============================================================
# §八 R8: S5 逐条复查 re-export 面（5 处假模块 + 兼容名）
# ============================================================
def test_docx_compat_names_imported_before_s1_are_still_on_the_shell():
    """S1 之前薄壳顶层可见的 `OxmlElement` / `RGBColor` 等仍逐名在位。

    迁出后它们在薄壳内已无调用点, 但 §五「保留文件头 + import + 容错 try 块」
    的兼容意图要求顶层可导入命名空间**逐名不变**。R8 要求 S5 逐条复查这条。
    """
    import md_to_docx as shell

    for name in ("OxmlElement", "RGBColor", "Inches", "Pt", "qn",
                 "Document", "WD_ALIGN_PARAGRAPH", "re", "sys", "Path", "datetime"):
        assert hasattr(shell, name), f"兼容名 {name} 丢失"


def test_every_reexported_name_carries_the_intentional_noqa_marker(analysis_dir):
    """全部 4 条 re-export 必须挂 `# noqa: F401`。

    这是**有意**的兼容面, 不是漏删（2026-10-06 逐片拍板保留）。若有人「顺手清理」
    去掉 noqa, full ruff advisory 的 F401 会立刻变红 —— 反过来, 若有人删掉
    re-export 名字又留下 noqa, 本文件的 `test_reexport_block_covers_all_41_host_symbols`
    会红。两侧都锁, 才是 R8 要求的「逐条复查」。
    """
    src = _read(analysis_dir, SHELL)
    tree = ast.parse(src)
    reexport = [
        n for n in tree.body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("reporting.")
    ]
    lines = src.splitlines()
    for node in reexport:
        head = lines[node.lineno - 1]
        assert "noqa: F401" in head, f"L{node.lineno} 的 re-export 缺 noqa: F401: {head!r}"


# ============================================================
# §八 R4: 收官人工对读的两份拷贝仍分处两个文件（§九 第 7 条不去重）
# ============================================================
def test_r4_two_copies_still_live_in_two_separate_files(analysis_dir):
    """§八 R4 + §九 第 7 条: 拆分后两份 Markdown 行解析器拷贝**分处两文件**,
    漂移概率上升。本计划**不去重**（去重会改解析分支顺序, 属结构重设计）。

    收官时把「仍分处两处」这一事实做成断言: 若将来有人合并两份, 那是**另立议题**
    的决定, 不能悄悄发生。
    """
    shell = _read(analysis_dir, SHELL)
    sections = _read(analysis_dir, "reporting/docx_sections.py")
    assert "while i < len(lines):" in shell, "主流程拷贝应留在薄壳区块 8"
    assert "while i < len(lines):" in sections, "灰度块拷贝应在 docx_sections.py"
    assert "_render_md_block" in shell, "薄壳通过 re-export 引用灰度块"
    assert "def _render_md_block" not in shell, "薄壳不得原地定义（禁止新旧并存）"
    # 两份拷贝各自的分支顺序: 表格行 → 标题 → 分隔线 → 引用 → 空行 → 免责声明 → 正文
    for label, src in (("主流程", shell), ("灰度块", sections)):
        for needle in ('startswith("|")', 'r"^(#{1,6})\\s+(.+)$"', 'r"^-{3,}$"',
                       'startswith(">")', 'startswith("⚠️ 免责声明")'):
            assert needle in src, f"{label} 拷贝缺少分支 {needle}"
        # 顺序断言: 表格行分支必须排在标题分支之前（顺序漂移是最易引入的回归）
        assert src.index('startswith("|")') < src.index('r"^(#{1,6})'), f"{label} 分支顺序漂移"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("请用 pytest 运行本文件")
