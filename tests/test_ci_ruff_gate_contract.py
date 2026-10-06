"""契约测试: `.github/workflows/ci.yml` 里那道窄路径 Critical Ruff 门禁本身。

背景 (`docs/08-规范整改-P2D` 盲区的收口):

`pyproject.toml` 的 `[tool.ruff] exclude` 含 `analysis/sections` 与 `tests/sections`,
而既有那步 Critical 门禁传的是**目录** (`ruff check analysis tests`)。ruff 的 exclude
在**目录递归**时生效, 于是这两个文件从来没被 ruff 检查过 —— 它们的唯一实际门禁只有
pytest。为补这个洞, `lint` job 里新增了一步只点名这两个文件的窄门禁。

本文件给那道门禁上锁, 因为它的坏掉方式都是**静默**的:

1. **命令加了 `--show-files` → 变成永远绿的空门禁**。实测 (ruff 0.16.10): 同一份含
   F821 的文件, 带 `--show-files` 时 exit 0 且不输出任何诊断, 去掉它才 exit 1 报 F821。
2. **删掉这一步 / 改回目录入参 → 盲区静默复发**。
3. **所在 job 被加 `continue-on-error: true` → 门禁不再阻断下游 job**。
4. **命令加 `--force-exclude` → 与 `--isolated` 并存时会改用 ruff 默认 exclude 集**,
   这两个路径是否落在其中属于未验证假设, 不该由一条断言默认放行。

所以这里断言的是"门禁的配置形态", 不是 ruff 的检查结果 —— 后者要真跑 ruff 才算数,
不该由一条单测代理 (单测里跑 ruff 既慢又把门禁自身变成被测对象)。

**结构前置依赖**: 所有窄门禁断言都经 `_narrow_gate_command()` / `_narrow_gate_block()`
取值, 这两个函数会先断言"该 step 恰好存在一个、且带非空 ruff 命令"。这不是洁癖 ——
否定型断言 (`不含 X` / `无 >` / `无 if:`) 作用在空串上恒真, 若 step 缺失就会**空过**
(变异实测: 删掉整步时, 早期版本有 3 条仍然通过)。统一收口后, 失效点集中成一条
"step 缺失或同名重复" 的明确报错, 而不是让后面几条各自莫名其妙地绿。

**容许语义等价的写法**: 规则集按**集合**比较 (`--select=F82,F7,F63,E9` 与
`--select=E9,F63,F7,F82` 等价, 放行); flag 按**词元**判定 (`--isolated` / `--isolated=…`
都算, 但 `--no-show-files` 不算); stderr/stdout 的 fd 合并 (`2>&1` / `>&2`) 不算写文件,
真正的落盘重定向 (`>` `>>` `&>` `>|` `2>`) 与 `tee` 才算 —— 少一条 `2>&1` 不该被误判成
"门禁在写报告"。

零外部依赖: 不 import yaml (venv 未装 PyYAML), 纯文本解析, 与 `test_peg_formula.py`
读 `pyproject.toml` 的做法同源。
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# 既有那步 (目录入参, 覆盖面广) 与新增那步 (窄路径) 的 step 名
_EXISTING_GATE = "Critical Ruff gate"
_NARROW_GATE = "Critical Ruff gate (config-excluded paths, narrow)"
_ADVISORY_AFTER = "Full Ruff diagnostics (advisory)"

# 窄门禁只该管这两个文件: 盲区的两个来源 (registry 实现 + 它的门禁测试)
_TARGET_PATHS = (
    "analysis/sections/__init__.py",
    "tests/sections/test_registry_gate.py",
)
# 与既有 Critical 门禁同一套规则 (按集合比较, 顺序自由)
_CRITICAL_RULES = frozenset({"E9", "F63", "F7", "F82"})

_JOB_HEADER = re.compile(r"^  ([A-Za-z0-9_.-]+):(\s*#.*)?$")
# 真正落盘的重定向运算符; `>&` / `<` / 单独的 `&` 不在其中 (前者是 fd 合并, 后者是读)
_WRITE_OPS = ("&>>", "&>", ">>|", ">>", ">|", "<>", ">")
_TRUTHY = frozenset({"true", "yes", "on"})


def _lines() -> list[str]:
    return _CI.read_text(encoding="utf-8").splitlines()


def _indent_of(ln: str) -> int:
    return len(ln) - len(ln.lstrip())


def _collect_block(lines: list[str], start: int) -> list[str]:
    """从 start+1 起按缩进吃块, 到下一个同级或更浅的非空行为止。"""
    base = _indent_of(lines[start])
    out: list[str] = []
    for ln in lines[start + 1:]:
        if not ln.strip():
            out.append(ln)
            continue
        if _indent_of(ln) <= base:
            break
        out.append(ln)
    return out


def _step_occurrences(name: str) -> list[tuple[int, list[str]]]:
    """所有 `- name: <name>` 整行精确匹配的位置, 连同其缩进块。

    返回**全部**出现而不是第一个: 同名 step 重复会让"按名字找门禁"这件事本身失去
    唯一性, 必须报出来, 不能默默挑一个 (挑错了等于给错误配置开后门)。
    """
    lines = _lines()
    out: list[tuple[int, list[str]]] = []
    for i, ln in enumerate(lines):
        if ln.strip() == f"- name: {name}":
            out.append((i, _collect_block(lines, i)))
    return out


def _command_of_block(block: list[str]) -> str:
    """把 run 块压成一条命令串。

    关键: **必须先剔掉注释行**。窄门禁的注释里正正写着 `--show-files`
    ("不要加 --show-files"), 若不剔除, 禁 flag 那条断言会因注释里提到它而误报 ——
    那条注释恰恰是防呆, 不能当成违规。
    """
    parts: list[str] = []
    for ln in block:
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("run:"):
            continue
        parts.append(s[:-1].strip() if s.endswith("\\") else s)
    return " ".join(p for p in parts if p)


def _command_of(name: str) -> str:
    occ = _step_occurrences(name)
    assert occ, f"ci.yml 里找不到 step: {name}"
    return _command_of_block(occ[0][1])


# ---------------------------------------------------------------- 结构前置依赖

def _narrow_gate_occurrence() -> tuple[int, list[str]]:
    """窄门禁 step 的 (行号, 块)。缺失或同名重复即刻失败。"""
    occ = _step_occurrences(_NARROW_GATE)
    assert len(occ) == 1, (
        f"ci.yml 里名为 {_NARROW_GATE!r} 的 step 应恰好 1 个, 实际 {len(occ)} 个。"
        "缺失或同名重复都会让窄门禁断言失去作用对象 (否定断言会在空串上空过)"
    )
    return occ[0]


def _narrow_gate_block() -> list[str]:
    return _narrow_gate_occurrence()[1]


def _narrow_gate_command() -> str:
    cmd = _command_of_block(_narrow_gate_block())
    assert cmd.strip(), f"{_NARROW_GATE} 的 run 块里没有可执行命令"
    assert "ruff" in cmd, f"{_NARROW_GATE} 的命令不是 ruff 调用: {cmd!r}"
    return cmd


# ---------------------------------------------------------------- 命令词元解析

def _flag(cmd: str, flag: str) -> bool:
    """词元级判定: `--flag` 或 `--flag=值` 都算; `--no-flag` / 含该字样的路径不算。"""
    return any(tok == flag or tok.startswith(flag + "=") for tok in cmd.split())


def _select_rules(cmd: str) -> set[str]:
    """`--select` 的规则集合 (顺序 / 空白 / 引号均不敏感)。

    允许 `--select=F82,F7,F63,E9` (顺序换) 与 `--select="E9, F63, F7, F82"` (带空格)
    这类语义等价写法: 规则表里空格本就没有意义, 收集到 `.py` 或下一个 `-` 开头词元为止,
    再把空格并掉按逗号切。
    """
    toks = [t.replace("\"", "").replace("'", "") for t in cmd.split()]
    for i, tok in enumerate(toks):
        if not tok.startswith("--select="):
            continue
        parts = [tok[len("--select="):]]
        for nxt in toks[i + 1:]:
            if nxt.endswith(".py") or nxt.startswith("-"):
                break
            parts.append(nxt)
        return {r.strip() for r in "".join(parts).split(",") if r.strip()}
    raise AssertionError(f"命令里没有 --select=<规则>: {cmd!r}")


def _write_targets(cmd: str) -> list[tuple[str, str]]:
    """抽出命令里**真正落盘**的 (运算符, 目标)。

    必须与 fd 合并区分开:
      `2>&1` / `>&2`  —— 把一个 fd 复制到另一个, **不落盘**; 早期版本用 `">" not in cmd`
                          一刀切, 结果给命令补一个无害的 `2>&1` 就会被误判成"写文件"。
      `>` `>>` `&>` `&>>` `>|` `2>` `<>` 与 `| tee <path>` —— 真的写文件, 属于门禁红线。
      `<>` 是 bash 的**读写** fd: 它确实开文件, 故算落盘, 不能与纯读 `<` 混为一谈
      (早期版本把 `startswith("<")` 放在落盘匹配之前, 导致 `<>` 被当成纯读放行 —— 假阴性)。
    `/dev/*` 视为丢弃而非落盘, 否则 `2>/dev/null` 这类无害写法同样被误伤。
    """
    toks = cmd.split()
    out: list[tuple[str, str]] = []
    for i, tok in enumerate(toks):
        m = re.match(r"^(\d*)(.*)$", tok)
        rest = m.group(2)
        # 判定顺序要紧, 两头都不能让步:
        #   1) `>&N` 是 fd 复制 (`2>&1` / `>&2` / `0>&-`), 必须**先**判掉 —— 否则 `>&2`
        #      会被落盘运算符 `>` 命中, 把一个纯 fd 操作误报成写文件;
        #   2) 落盘运算符要在"纯读"分支**之前**匹配 —— bash 的 `<>file` 是**读写** fd,
        #      确实会开文件, 不能像纯读 `<` 那样被 `startswith("<")` 一起吞掉。
        if rest.startswith(">&"):
            continue
        op = next((c for c in _WRITE_OPS if rest.startswith(c)), None)
        if op is None:
            if rest.startswith("<") or rest in ("&", "&-", "&0"):
                continue                               # 纯读 / heredoc / 后台
            if tok == "tee":                            # `| tee <path>`
                out.extend(("|", nxt) for nxt in toks[i + 1:] if not nxt.startswith("-"))
            continue
        target = rest[len(op):]
        if not target and i + 1 < len(toks):
            target = toks[i + 1]
        if target.startswith("/dev/"):
            continue
        out.append((op, target or "(默认文件)"))
    return out


# ---------------------------------------------------------------- job 级解析

def _job_name_of_line(idx: int) -> str | None:
    for ln in reversed(_lines()[:idx]):
        m = _JOB_HEADER.match(ln)
        if m:
            return m.group(1)
    return None


def _job_block(name: str) -> list[str]:
    lines = _lines()
    for i, ln in enumerate(lines):
        m = _JOB_HEADER.match(ln)
        if m and m.group(1) == name:
            return _collect_block(lines, i)
    return []


def _job_level_continue_on_error(name: str) -> bool:
    """job 键的缩进是 4, step 键是 6 —— 据此只认 job 级, 不误伤 step 级 `continue-on-error`。"""
    for ln in _job_block(name):
        if _indent_of(ln) == 4 and ln.strip().startswith("continue-on-error:"):
            val = ln.strip().split(":", 1)[1].strip().lower()
            if val in _TRUTHY:
                return True
    return False


def _job_needs(name: str) -> set[str]:
    for ln in _job_block(name):
        if _indent_of(ln) == 4 and ln.strip().startswith("needs:"):
            return {n.strip() for n in ln.strip().split(":", 1)[1].split(",") if n.strip()}
    return set()


def _ruff_exclude_entries() -> list[str]:
    """`[tool.ruff]` 段里的 exclude 条目 (不是 `[tool.mypy]` 的那份)。"""
    text = _PYPROJECT.read_text(encoding="utf-8")
    seg = text.split("[tool.ruff]", 1)[1]
    m = re.search(r"^exclude\s*=\s*\[(.*?)\]", seg, re.S | re.M)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


# ---------------------------------------------------------------- 契约断言

def test_narrow_gate_step_is_uniquely_present_with_a_real_command():
    """地基: 该 step 恰好存在一个, 且带非空 ruff 命令。

    下面每条窄门禁断言都经 `_narrow_gate_command()` 取值, 依赖本条成立; 找不到就是
    最坏情况 —— 盲区静默复发, 而 CI 依然全绿 (既有那步传目录, 覆盖不到这两个文件)。
    """
    idx, block = _narrow_gate_occurrence()
    assert _command_of_block(block).strip(), f"{_NARROW_GATE} 的 run 块里没有可执行命令"
    assert "ruff" in _command_of_block(block)
    assert _job_name_of_line(idx) is not None, "窄门禁 step 不在任何 job 里"


def test_narrow_gate_names_exactly_the_two_target_files():
    """命令体必须恰好点名那两个文件, 不多不少。

    多个: 范围失控 (等于把被排除目录整个纳入)。少个: 盲区没关干净。
    """
    cmd = _narrow_gate_command()
    for target in _TARGET_PATHS:
        assert target in cmd, f"窄门禁没点名 {target}: {cmd!r}"
    named = re.findall(r"[\w./-]+\.py\b", cmd)
    assert sorted(named) == sorted(_TARGET_PATHS), (
        f"窄门禁点名的 .py 应恰好是 {_TARGET_PATHS}, 实际 {sorted(named)}"
    )


def test_narrow_gate_uses_isolated():
    """必须带 `--isolated`: 把"必被检查"做成结构性保证, 而不是靠隐式默认。

    ruff 对**显式路径**默认不应用 exclude, 但那是隐式行为 —— `--force-exclude` 一加就
    失效。`--isolated` 完全忽略 pyproject 配置, 才是"这两个文件一定被检查"的可靠依据。
    """
    cmd = _narrow_gate_command()
    assert _flag(cmd, "--isolated"), f"窄门禁缺 --isolated, 会退回隐式豁免: {cmd!r}"


def test_narrow_gate_must_not_pass_show_files():
    """命令体**禁止**出现 `--show-files`: 带上它这道门禁就永远绿。

    实测 (ruff 0.16.10, 同一份含 F821 的文件):
      带 --show-files -> 只输出文件路径, 无任何诊断, exit 0
      去掉 --show-files -> `F821 Undefined name ...`, exit 1
    即 `--show-files` 是查询模式, 会短路掉整条检查。把它当门禁用 = 装一个永远绿的空门禁,
    而这正是本门禁要消灭的失败模式, 不能自己再犯一次。

    取值走 `_narrow_gate_command()` (已绑定唯一那一步), 不再按名字"挑第一个同名 step" ——
    否则一个同名诱饵 step 就能让真正带 `--show-files` 的那一步躲过这条断言。
    """
    cmd = _narrow_gate_command()
    assert not _flag(cmd, "--show-files"), (
        f"窄门禁命令里出现 --show-files, 它会抑制诊断并强制 exit 0, 门禁将永远绿: {cmd!r}"
    )


def test_narrow_gate_must_not_use_force_exclude():
    """命令体禁止 `--force-exclude`。

    `--isolated` 下 pyproject 不被读取, 此时 `--force-exclude` 会改用 **ruff 默认**
    exclude 集。这两个路径是否落在默认集里, 是一条未验证的假设 (默认集含
    `.git` / `build` / `dist` / `venv` 等, 不含 `analysis/sections`, 但这是推断而非
    契约)。门禁的立身之本是"这两个文件必被检查", 不该把成败押在未验证的默认行为上,
    所以直接禁掉, 而不是留一条"大概没事"的断言。
    """
    cmd = _narrow_gate_command()
    assert not _flag(cmd, "--force-exclude"), (
        f"窄门禁带 --force-exclude: 在 --isolated 下它会改用 ruff 默认 exclude 集, "
        f"这两个路径是否被裁掉将不再有据可依: {cmd!r}"
    )


def test_narrow_gate_rule_set_matches_existing_critical_gate():
    """规则集必须与既有 Critical 门禁一致 (按**集合**比较, 顺序自由)。

    这步的存在理由只是"把既有门禁的覆盖范围补上", 不是另立一套标准; 规则漂移会让
    两步门禁对同一份代码给出不同结论。顺序不同但集合相同 (如 `--select=F82,F7,F63,E9`)
    是语义等价的写法, 放行 —— 刻意不做逐字比较, 免得为纯格式改动红一片。
    """
    narrow = _select_rules(_narrow_gate_command())
    existing = _select_rules(_command_of(_EXISTING_GATE))
    assert narrow == _CRITICAL_RULES, (
        f"窄门禁规则集应为 {sorted(_CRITICAL_RULES)}, 实际 {sorted(narrow)}"
    )
    assert narrow == existing, (
        f"两步门禁规则集应一致; 窄门禁 {sorted(narrow)} vs 既有 {sorted(existing)}"
    )


def test_narrow_gate_writes_no_file_at_all():
    """窄门禁只读, 不得落盘任何文件。

    `lint` job 里写文件的是后面两个 advisory 步骤 (`if: always()`, 诊断用途); 门禁步骤
    自己必须只读, 否则一次门禁执行就污染工作区。stderr/stdout 的 fd 合并 (`2>&1` /
    `>&2`) 与 `/dev/null` 丢弃不算落盘, 放行。
    """
    targets = _write_targets(_narrow_gate_command())
    assert not targets, (
        f"窄门禁命令里有落盘重定向 {[f'{op} {tgt}' for op, tgt in targets]}, "
        "门禁步骤应当只读"
    )


def test_narrow_gate_does_not_write_reports():
    """门禁不得把 `reports/` 当写入目标。

    `reports/` 里现有条目的 sha256 是 P2-D 收官验收项 (`docs/08-…P2D:418`) 的基线,
    门禁顺手往里写东西会悄悄改掉基线。与上一条一般性的"不得落盘"分开断言, 是为了让
    失败信息直接指向 `reports/`, 而不是让排查者自己去猜是哪条重定向。
    """
    targets = _write_targets(_narrow_gate_command())
    bad = [(op, tgt) for op, tgt in targets if "reports" in tgt]
    assert not bad, f"窄门禁把 reports/ 当写入目标 {bad}, 会污染报告目录的 sha256 基线"


def test_write_target_classifier_separates_file_writes_from_safe_redirects():
    """解析器自身的分类契约: 真正落盘 vs 安全重定向 (不碰 ci.yml)。

    为什么要有这条: 上面那些针对 ci.yml 的断言全靠 `_write_targets` 分类对不对, 解析器
    一旦退化, 契约断言会跟着一起失灵 —— 而那时 CI 仍是全绿的, 没有任何外部信号。
    曾真实发生过的退化: `_WRITE_OPS` 里列了 `"<>"`, 但 `startswith("<")` 排在落盘匹配
    之前, 把 bash 的**读写** fd `<> file` 当成纯读放行 (假阴性)。故把分类口径逐条钉死。
    """
    # (命令片段, 期望落盘处数, 说明)
    safe = [
        ("2>&1", 0, "fd 合并: stderr 并入 stdout"),
        ("1>&2", 0, "fd 合并: stdout 并入 stderr"),
        (">&2", 0, "fd 合并"),
        ("0>&-", 0, "关闭 fd"),
        ("&1", 0, "裸 & 不是重定向"),
        ("2>/dev/null", 0, "丢弃"),
        (">/dev/null", 0, "丢弃"),
        ("< input.txt", 0, "纯读"),
        ("2< in.txt", 0, "纯读"),
        ("<<EOF", 0, "heredoc, 非文件写入"),
    ]
    for frag, want, why in safe:
        got = _write_targets(frag)
        assert len(got) == want, f"{frag!r} ({why}) 期望落盘 {want} 处, 实际 {got}"

    writes = [
        ("> out.txt", ">"), (">out.txt", ">"), ("2> err.txt", ">"),
        (">> log.txt", ">>"), ("&> all.txt", "&>"), ("&>> all.txt", "&>>"),
        (">| force.txt", ">|"),
    ]
    for frag, op in writes:
        got = _write_targets(frag)
        assert len(got) == 1 and got[0][0] == op, f"{frag!r} 期望落盘 1 处且运算符为 {op}, 实际 {got}"

    # 读写 fd: 单独钉死, 防止再被纯读分支吞掉
    assert _write_targets("<> rw.txt") == [("<>", "rw.txt")], (
        f"`<> rw.txt` 是读写 fd, 确实开文件, 必须算落盘; 实际 {_write_targets('<> rw.txt')}"
    )
    # tee: 目标要算落盘, 但 `-a` 这类选项不是目标
    assert _write_targets("cmd | tee out.txt") == [("|", "out.txt")]
    assert _write_targets("cmd | tee -a out.txt") == [("|", "out.txt")]
    # 落盘与安全重定向混排时, 只报真正落盘的那一处
    assert _write_targets("cmd 2>&1 > reports/x.txt") == [(">", "reports/x.txt")]


def test_narrow_gate_has_no_if_so_it_can_fail_the_job():
    """这一步不能带 `if: always()` 之类的条件。

    带了就永远不失败 —— 门禁必须能真的把 job 打红, 才会沿 job 依赖链阻断下游。
    """
    block = _narrow_gate_block()
    conds = [ln.strip() for ln in block if ln.strip().startswith("if:")]
    assert not conds, f"{_NARROW_GATE} 带 if:, 可能永不执行: {conds}"


def test_narrow_gate_sits_in_a_blocking_job():
    """门禁所在 job 必须**能红**, 且真的挡在 `test` job 前面。

    两条都是"静默削弱"路径:
      - 所在 job 被加 `continue-on-error: true` → 门禁只出报告不阻断, 断言全绿;
      - 门禁被挪到一个不参与依赖链的 job (如 `typecheck`, 它本就 continue-on-error)
        → 同上。
    故除了查 job 级 `continue-on-error`, 还查 `test` 的 `needs` 确实包含该 job。
    """
    job = _job_name_of_line(_narrow_gate_occurrence()[0])
    assert job, "窄门禁 step 不在任何 job 里"
    assert not _job_level_continue_on_error(job), (
        f"job {job!r} 带 job 级 continue-on-error: true, 门禁失败不再阻断下游"
    )
    assert job in _job_needs("test"), (
        f"门禁在 job {job!r}, 但 test job 的 needs={sorted(_job_needs('test'))} 不含它, "
        "门禁挡不住测试"
    )


def test_narrow_gate_runs_after_existing_gate_and_before_advisory_steps():
    """顺序: 既有 Critical 门禁 -> 窄门禁 -> advisory 诊断。

    窄门禁放在既有门禁之后 (先跑覆盖面广的那步), 放在 advisory 之前 (门禁失败时
    advisory 仍靠 `if: always()` 产出诊断并上传, 不因门禁红而丢日志)。
    """
    lines = _lines()
    idx = {name: next((i for i, ln in enumerate(lines) if ln.strip() == f"- name: {name}"), None)
           for name in (_EXISTING_GATE, _NARROW_GATE, _ADVISORY_AFTER)}
    assert all(v is not None for v in idx.values()), f"ci.yml 缺步骤: {idx}"
    assert idx[_EXISTING_GATE] < idx[_NARROW_GATE] < idx[_ADVISORY_AFTER], (
        f"步骤顺序不对, 期望 {_EXISTING_GATE} < {_NARROW_GATE} < {_ADVISORY_AFTER}, 实际 {idx}"
    )


def test_narrow_gate_is_required_while_targets_remain_config_excluded():
    """只要这两个目录还在 ruff 的 exclude 里, 窄门禁就必须存在。

    这是盲区与门禁之间的因果锁: 既有门禁传目录 -> exclude 在递归时生效 -> 这两个文件
    从未被检查。哪天有人把它们从 exclude 里移出, 目录入参就能覆盖到, 这条断言随之失效
    (届时可考虑删掉窄门禁, 但那是人的决定, 不该自动发生)。
    """
    excluded = set(_ruff_exclude_entries())
    if not {"analysis/sections", "tests/sections"} <= excluded:
        # 目标已不被 exclude 覆盖 -> 目录入参即可覆盖, 本文件的其余断言仍应成立
        return
    assert _step_occurrences(_NARROW_GATE), (
        f"analysis/sections 与 tests/sections 仍在 pyproject 的 ruff exclude 里 "
        f"({sorted(excluded)}), 既有目录门禁覆盖不到它们, 窄门禁不可删"
    )
