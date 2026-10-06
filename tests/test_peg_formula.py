"""PEG 公式与 spec §8.2 区间回归。

默认用例 (离线, 确定性) 读 tests/fixtures/golden/result_v3-600693-20261003.json ——
仓库内**已校验来源**: reports/600693_东百集团/2026-10-03/result_v3-1618.json 真实
跑批产物的 capture 裁剪版 (源 sha256 由 fixtures/golden/golden_fixtures.py 钉死,
出处与归一化口径见 fixtures/golden/README.md)。普通 pytest 不访问实时行情。

离线回归走**生产算式**: 复算调用 analysis/quant_analyzer_v2.compute_peg_metrics
(PEG 公式的唯一实现点), 而不是把公式抄一遍在本文件里 —— 抄写版对生产实现的改动
完全免疫, 生产公式改错了 fixture 用例照样全绿。fixture 缺失/损坏一律 **fail**,
不再 skip: 空洞通过 (skip → 退出码 0) 等于没有回归。

实时行情检查是**双重 opt-in**, 两步都满足才触网:

    pytest tests/test_peg_formula.py                            # 默认: live 用例不选中
    pytest tests/test_peg_formula.py -m integration              # 选中, 但 env 门禁没开 → skip
    DA_A_RUN_LIVE=1 pytest tests/test_peg_formula.py -m integration   # 真跑, 访问实时接口

  第一步 (选不选): live 用例必须被**显式点名**才进 items。
      默认值写在 pyproject addopts (`-m "not live"`), 但命令行任意 -m 会把它**完全
      覆盖** (后写的 -m 生效) —— `DA_A_RUN_LIVE=1 pytest -m "not slow"` 就能把 live
      用例选回来 (它没打 slow 标记, 匹配 "not slow"), 只剩第二步的 skipif 把关。
      所以真正的门禁在 tests/conftest.py 的 `pytest_collection_modifyitems`:
      口径是 fail-closed 的"**整表达式就是 opt-in**" —— 只有生效的 -m 完全由
      live/integration 这些名字合取或析取组成才算显式点名, 其余一律 deselect:
        排除式   ("not live" / "not (live or integration)")、点名别的标记
                  ("not slow" / "unit or slow")、以及**复合表达式里的非 opt-in 分支**
                  ("live or unit" / "live and slow") 与**否定混在 or/and 里**
                  ("not live or integration" / "integration and not live") 都不算点名。
                  按子串判断会把 "not live" 里的 "live" 误认成包含; 按 AST 的 any()
                  则会把 or 的另一条分支 ("live or unit" 的 unit 分支) 当成点名 ——
                  两个洞都已修, 回归见下面的 composite-or / opt-in 矩阵。
      结论: 默认 pytest 与任意自定义 -m 都不选 live, 与 DA_A_RUN_LIVE 无关。
      被显式点名时 (如 -m integration) 才留给第二步决定, 显式集成验收看到的是
      SKIPPED 而不是 DESELECTED。
  第二步 (跑不跑): 用例自己的 skipif 要求 DA_A_RUN_LIVE **精确等于 "1"**。
      =0 / 空值 / 未设置 / "true" 等一律关闭 —— 字符串 "0" 在 Python 里是真值,
      早期版本用 `not os.environ.get(...)` 判定, DA_A_RUN_LIVE=0 反而会打开网络。

`integration` / `live` 标记均已在 pyproject.toml 的 markers 里注册。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "golden"))

import golden_fixtures  # noqa: E402
import quant_analyzer_v2 as v2  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_THIS_FILE = "tests/test_peg_formula.py"
_LIVE_TEST_ID = "test_peg_600693_live_in_spec_range"

GOLDEN_600693 = "tests/fixtures/golden/result_v3-600693-20261003.json"
GOLDEN_CODE = "600693"

# 实时用例的显式开关。默认不设 → 不访问实时行情 (原用例靠接口是否返回 CAGR/EPS
# 决定 pass/skip, 接口抖动就会让 CI 结果在 PASS/SKIP/FAIL 之间跳)。
_LIVE_ENV = "DA_A_RUN_LIVE"

# 真实生产算式的引用。离线回归必须经由它; 口径回归用例用它当"未被改坏的"对照。
_REAL_COMPUTE_PEG = v2.compute_peg_metrics

# record 模式下喂给 live 用例的固定估值 (golden 同一份数值): 让
# "marker + env=1 确实执行到了 fetch_full_valuation" 这条验证不依赖网络可用性。
_LIVE_CANNED = {
    "name": "东百集团", "code": GOLDEN_CODE, "price": 9.32, "mcap_yi": 81.07,
    "pe_ttm": 165.65, "pb": 2.27, "eps_cur": 0.14, "eps_next": 0.17,
    "analyst_count": 1, "pe_fwd": 66.6, "cagr_pct": 21.0, "peg": 7.73,
    "digest_years": 8.8,
}


def _live_enabled(env=None) -> bool:
    """live gate 第二步的唯一真源: 只有 DA_A_RUN_LIVE **精确为 "1"** 才算开。

    必须精确比较, 不能用真值判断 —— "0" / "" / "false" 在 Python 里都是真值字符串,
    用 `not os.environ.get(...)` 判定会让 DA_A_RUN_LIVE=0 打开网络。
    """
    source = os.environ if env is None else env
    return source.get(_LIVE_ENV) == "1"


# ============================================================
# golden fixture 加载: 缺失/损坏必须失败, 不允许 skip 空洞通过
# ============================================================
def _load_golden_600693():
    """载入 600693 golden fixture; 缺失/损坏/结构不对一律 pytest.fail。

    刻意不接受"缺了就 skip": fixture 是版本化的回归基线, 它不见了就是回归失效,
    必须以非 0 退出码暴露出来, 而不是留一条 SKIPPED 让 CI 看起来是绿的。
    """
    path = golden_fixtures.golden_path(GOLDEN_CODE)
    if path is None or not path.exists():
        pytest.fail(
            f"600693 golden fixture 缺失: {GOLDEN_600693}\n"
            "这是版本化的离线回归基线, 缺失必须失败, 不允许 skip 空洞通过。"
        )
    try:
        result = golden_fixtures.load_golden_result(GOLDEN_CODE)
    except (OSError, ValueError) as e:  # ValueError 覆盖 json.JSONDecodeError
        pytest.fail(f"600693 golden fixture 损坏/无法解析: {GOLDEN_600693}: {e!r}")
    if not isinstance(result, dict) or result.get("code") != GOLDEN_CODE:
        pytest.fail(
            f"600693 golden fixture 身份不符: {GOLDEN_600693} "
            f"(code={result.get('code') if isinstance(result, dict) else type(result).__name__})"
        )
    if not isinstance(result.get("valuation"), dict):
        pytest.fail(f"600693 golden fixture 缺 valuation 块, 无法复算 PEG: {GOLDEN_600693}")
    return result


def _assert_peg_matches_production(v) -> None:
    """用**生产**算式 (v2.compute_peg_metrics) 复核产物里的 PEG / 增速 / PE消化。

    口径 (spec §8.2): peg = pe_ttm / 增速%, 且增速用**未取整**的 cagr
    (165.65 / 21.43 = 7.73)。误用落盘的取整展示值复算会得到 7.89 —— 那正是要卡的。
    """
    peg = v.get("peg")
    pe_ttm = v.get("pe_ttm")
    pe_fwd = v.get("pe_fwd")  # 仅用于显示, 已不参与 PEG
    eps_cur = v.get("eps_cur")
    eps_next = v.get("eps_next")
    cagr_pct = v.get("cagr_pct")

    print(
        f"pe_ttm={pe_ttm}, pe_fwd={pe_fwd}, eps_cur={eps_cur}, eps_next={eps_next}, "
        f"cagr_pct={cagr_pct}, peg={peg}"
    )
    assert peg is not None, "PEG 不应为 None"
    assert pe_ttm and eps_cur and eps_next, f"golden fixture 缺 PE/EPS, 无法复算 CAGR: {v}"

    m = v2.compute_peg_metrics(pe_ttm, eps_cur, eps_next)
    cagr_precise = m["cagr_pct"]
    assert round(m["peg"], 2) == peg, (
        f"PEG 公式不自洽: 生产算式 pe_ttm={pe_ttm} / cagr={cagr_precise:.4f} = "
        f"{m['peg']:.4f} → round2={round(m['peg'], 2)}, 但产物记录 peg={peg}"
    )
    assert round(cagr_precise, 0) == cagr_pct, (
        f"cagr_pct 应为 round(cagr, 0): 产物 {cagr_pct} vs 生产复算 {round(cagr_precise, 0)}"
    )
    if v.get("digest_years") is not None:
        got = m["digest_years"]
        expected = None if got == float("inf") else round(got, 1)
        assert expected == v["digest_years"], (
            f"digest_years 不自洽: 生产算式 {got} → {expected}, 产物记录 {v['digest_years']}"
        )


def test_peg_600693_in_spec_range():
    """600693 PEG 应在 1-12 范围（spec §8.2 第 4 条区间；fix round 1 改用 pe_ttm)

    离线确定性回归, 数据取自已校验 golden fixture (见模块 docstring), 不碰实时行情。
    断言两件事:
      1) 公式自洽 —— 按**生产算式** (v2.compute_peg_metrics, 即 fetch_full_valuation
         实际调用的那个函数) 从 pe_ttm / eps_cur / eps_next 重算 PEG, 必须逐位等于
         产物记录的 peg; 且落盘的 cagr_pct 就是 round(cagr, 0) 的展示值。
      2) 落在 spec §8.2 的 1-12 区间。

    诚实边界: 本用例锁的是"**已归档那一次**真实跑批的 PEG", 不保证未来实时 PEG 仍
    落在区间内 —— 后者由下面的 live integration 用例负责。
    """
    result = _load_golden_600693()
    _assert_peg_matches_production(result["valuation"])
    assert 1 <= result["valuation"]["peg"] <= 12, (
        f"PEG {result['valuation']['peg']} 应在 spec §8.2 区间（1-12）"
    )


# ============================================================
# 生产公式覆盖: 离线用例确实走生产路径, 且对口径回归敏感
# ============================================================
def test_fetch_full_valuation_delegates_to_pure_helper():
    """抓取函数必须委托给纯函数 —— 否则"离线走生产公式"只是测试自己的一厢情愿。

    走源码契约 (读 analysis/quant_analyzer_v2.py 全文) 而不是 inspect.getsource:
    gate 守卫会把 fetch_full_valuation 换成桩, inspect 到的会是桩的源码。
    """
    src = Path(v2.__file__).read_text(encoding="utf-8")
    assert "def compute_peg_metrics(" in src, "生产侧没有 compute_peg_metrics 纯函数"
    fetch_body = src.split("def fetch_full_valuation(", 1)[1].split("\ndef ", 1)[0]
    assert "compute_peg_metrics(" in fetch_body, "fetch_full_valuation 没有委托给纯函数"
    helper_body = src.split("def compute_peg_metrics(", 1)[1].split("\ndef ", 1)[0]
    for forbidden in ("requests", "urlopen", "http", "socket"):
        assert forbidden not in helper_body, f"compute_peg_metrics 必须无 I/O, 却引用了 {forbidden}"


def test_offline_regression_detects_production_formula_regression(monkeypatch):
    """把生产算式换成"用取整增速"的错口径, 离线 fixture 回归必须报错。

    这是对测试**自身灵敏度**的回归: 若 `_assert_peg_matches_production` 不经由生产
    函数, 无论生产公式怎么改这条都不会失败 —— 那离线回归就是装饰品。
    """
    def _rounded_cagr_variant(pe_ttm, eps_cur, eps_next):
        """错口径: 用 round(cagr, 0) 后的增速算 PEG (165.65 / 21 = 7.89 ≠ 7.73)。"""
        m = _REAL_COMPUTE_PEG(pe_ttm, eps_cur, eps_next)
        cagr = m["cagr_pct"]
        return {**m, "peg": (pe_ttm / round(cagr, 0)) if (pe_ttm and cagr > 0) else None}

    result = _load_golden_600693()
    _assert_peg_matches_production(result["valuation"])  # 未改坏时先通过

    monkeypatch.setattr(v2, "compute_peg_metrics", _rounded_cagr_variant)
    with pytest.raises(AssertionError, match="PEG 公式不自洽"):
        _assert_peg_matches_production(result["valuation"])


# ============================================================
# golden fixture 缺失/损坏必须失败 (不改仓库 fixture, 全部指向 tmp_path)
# ============================================================
@pytest.mark.parametrize("broken", ["absent", "truncated_json", "not_a_dict", "wrong_code"])
def test_missing_or_broken_golden_fixture_fails_loudly(tmp_path, monkeypatch, broken):
    """fixture 缺失/损坏/串票 → 明确失败 (退出码非 0), 绝不 skip。"""
    if broken == "absent":
        fake = tmp_path / "result_v3-600693-absent.json"
    elif broken == "truncated_json":
        fake = tmp_path / "result_v3-600693-truncated.json"
        fake.write_text('{"code": "600693", "valuation": {', encoding="utf-8")  # 截断的 JSON
    elif broken == "not_a_dict":
        fake = tmp_path / "result_v3-600693-list.json"
        fake.write_text("[1, 2, 3]", encoding="utf-8")
    else:
        fake = tmp_path / "result_v3-002353-mislabeled.json"
        fake.write_text(json.dumps({"code": "002353", "valuation": {"peg": 1.0}}),
                        encoding="utf-8")
    monkeypatch.setattr(golden_fixtures, "golden_path", lambda code: fake)

    with pytest.raises(pytest.fail.Exception):
        _load_golden_600693()


# ============================================================
# live gate 第二步: DA_A_RUN_LIVE 精确等于 1 才算开
# ============================================================
@pytest.mark.parametrize("raw,expected", [
    ("1", True),
    ("0", False),        # "0" 是真值字符串 —— 早期 `not os.environ.get()` 判反的坑
    ("", False),         # 空值
    ("01", False),
    ("true", False),
    ("yes", False),
    ("2", False),
])
def test_live_env_requires_exactly_one(raw, expected):
    """只有 DA_A_RUN_LIVE=1 开; 0 / 空 / 未设置 / 其它真值串一律关。"""
    assert _live_enabled({_LIVE_ENV: raw}) is expected
    assert _live_enabled({}) is False  # 未设置


# ============================================================
# live gate 端到端: 用独立子进程跑真 pytest, 配网络守卫
# ============================================================
# 守卫插件源码: 写进 tmp_path 后用 `-p` 注入子进程。
#   block  —— 建连接 / 调 fetch_full_valuation 都会被记进 sentinel 并直接失败
#   record —— fetch_full_valuation 换成固定桩并记录调用 (连接与 DNS 仍封死),
#            用于证明 "marker + env=1" 真的执行到了抓取函数
# 为什么用子进程: gate 的本质是"pytest 怎么选用例 + 环境变量怎么读", 同进程跑共享
# sys.path / 已导入模块, 证明不了任何事; 子进程还能拿到真实退出码 —— 空洞通过
# (skip) 的退出码是 0, 只有真失败才非 0。
# 覆盖 connect + create_connection + getaddrinfo/gethostbyname: 只封 connect 的话,
# 名字解析 (真实 DNS 请求) 仍能发生, "零网络" 就只是零建连。
# 注意: 只封这些**函数**, 不替换 socket.socket 这个**类对象** —— 替换掉它会让
# `import ssl` 里的 `class SSLSocket(socket)` 直接炸掉 (requests 依赖 ssl)。
_NETGUARD_SRC = '''
import json
import os
import socket

_SENTINEL = os.environ.get("DA_A_NETGUARD_SENTINEL", "")
_MODE = os.environ.get("DA_A_NETGUARD_MODE", "block")
_CANNED = os.environ.get("DA_A_NETGUARD_CANNED", "{}")


def _record(line):
    if _SENTINEL:
        with open(_SENTINEL, "a", encoding="utf-8") as fh:
            fh.write(line + "\\n")


def _blocked(name):
    def _f(*a, **k):
        _record(name)
        raise AssertionError("gate 验证失败: 触达 " + name + " —— 期望零网络")
    return _f


import quant_analyzer_v2 as _v2  # noqa: E402  先把 requests/ssl 等依赖导完

socket.socket.connect = _blocked("socket.connect")
socket.socket.connect_ex = _blocked("socket.connect_ex")
socket.create_connection = _blocked("socket.create_connection")
socket.getaddrinfo = _blocked("socket.getaddrinfo")
socket.gethostbyname = _blocked("socket.gethostbyname")
socket.gethostbyname_ex = _blocked("socket.gethostbyname_ex")


def _stub_fetch(code):
    _record("fetch_full_valuation:" + str(code))
    if _MODE == "record":
        return json.loads(_CANNED)
    raise AssertionError("gate 验证失败: live 用例触达 fetch_full_valuation —— 期望零网络")


_v2.fetch_full_valuation = _stub_fetch
'''

_NETGUARD_PLUGIN = "da_a_peg_netguard"

# 内层子进程标记。gate 用例会跑"整个测试文件", 若不加这层保护, 内层又会去跑这 4 个
# gate 用例 → 子进程套娃, 既挂死又拿不到结论。
_INNER_ENV = "DA_A_PEG_GATE_INNER"


def _skip_if_inner_run() -> None:
    if os.environ.get(_INNER_ENV):
        pytest.skip("递归保护: gate 验证的内层子进程不再嵌套验证 gate")


def _run_gated_pytest(tmp_path, *args, mode="block", env_extra=None):
    """跑一次受网络守卫的 pytest 子进程, 返回 (CompletedProcess, sentinel 路径)。"""
    plugin_dir = tmp_path / f"netguard_{mode}"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / f"{_NETGUARD_PLUGIN}.py").write_text(_NETGUARD_SRC, encoding="utf-8")
    sentinel = tmp_path / f"netguard_{mode}.log"

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_REPO_ROOT / "analysis"), str(_REPO_ROOT), str(plugin_dir),
                    env.get("PYTHONPATH", "")) if p
    )
    env["DA_A_NETGUARD_MODE"] = mode
    env["DA_A_NETGUARD_SENTINEL"] = str(sentinel)
    env[_INNER_ENV] = "1"               # 打断递归: 内层直接 skip 掉 gate 用例
    if mode == "record":
        env["DA_A_NETGUARD_CANNED"] = json.dumps(_LIVE_CANNED, ensure_ascii=False)
    env.pop(_LIVE_ENV, None)          # 每个用例显式声明自己的 env, 不受外层污染
    env.update(env_extra or {})

    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "-p", "no:cacheprovider", "-p", _NETGUARD_PLUGIN,
         "-c", str(_PYPROJECT), "--rootdir", str(_REPO_ROOT), *args],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, sentinel


def _network_attempts(sentinel):
    return sentinel.read_text(encoding="utf-8").strip() if sentinel.exists() else ""


# live 用例"被 env 门禁 skip"的精确特征: -ra 摘要里一条属于本文件、理由提到开关的 SKIPPED
_LIVE_SKIPPED_RE = rf"SKIPPED \[\d+\] {re.escape(_THIS_FILE)}:\d+: .*{re.escape(_LIVE_ENV)}"


def _passed_re(test_name: str) -> str:
    """pytest -v 的输出顺序是 node id 在前、状态在后。"""
    return rf"{re.escape(_THIS_FILE)}::{re.escape(test_name)}\s+PASSED"


def test_plain_pytest_excludes_live_even_when_env_misconfigured(tmp_path):
    """普通 pytest + DA_A_RUN_LIVE=1: live 用例必须被 deselect, 零网络。

    挡住"环境变量误设 1 就偷偷联网"这一类事故 —— integration 标记本身只是标签,
    真正决定选取的是 addopts 里的 `-m "not live"`。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(tmp_path, _THIS_FILE, env_extra={_LIVE_ENV: "1"})

    assert _network_attempts(sentinel) == "", "普通 pytest 竟然触网了"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"\d+ deselected", proc.stdout), f"live 用例没被 deselect:\n{proc.stdout}"
    assert _LIVE_TEST_ID not in proc.stdout, f"live 用例被默认选中了:\n{proc.stdout}"
    # 同一次运行里离线用例照常通过 —— 证明只是排除了 live, 没把整个文件废掉
    assert re.search(_passed_re("test_peg_600693_in_spec_range"), proc.stdout), proc.stdout


@pytest.mark.parametrize("raw", ["0", ""], ids=["zero", "empty"])
def test_live_gate_off_when_env_is_not_one(tmp_path, raw):
    """DA_A_RUN_LIVE=0 / 空值 + -m integration: 用例被选中但 skip, 零网络。"""
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", "integration", env_extra={_LIVE_ENV: raw},
    )

    assert _network_attempts(sentinel) == "", f"DA_A_RUN_LIVE={raw!r} 竟然触网了"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(_LIVE_SKIPPED_RE, proc.stdout), (
        f"live 用例没因 env 门禁被 skip:\n{proc.stdout}"
    )


def test_live_runs_only_with_marker_and_env_one(tmp_path):
    """双重 opt-in 成立: -m integration 且 DA_A_RUN_LIVE=1 才执行到 fetch_full_valuation。"""
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", "integration", mode="record", env_extra={_LIVE_ENV: "1"},
    )

    assert "fetch_full_valuation:600693" in _network_attempts(sentinel), (
        f"live 用例没走到 fetch_full_valuation:\n{proc.stdout}"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(_passed_re(_LIVE_TEST_ID), proc.stdout), f"live 用例没真正执行:\n{proc.stdout}"


def test_live_runs_when_mark_expr_names_live_directly(tmp_path):
    """显式点名 live 本身 (不是 integration) 同样是合法出口: -m live + env=1 放行。

    守住"别把门禁修成死路": 选择层只认"正向点名 live/integration", 两种点名等价。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", "live", mode="record", env_extra={_LIVE_ENV: "1"},
    )

    assert "fetch_full_valuation:600693" in _network_attempts(sentinel), (
        f"-m live + env=1 竟没走到 fetch_full_valuation (门禁过严?):\n{proc.stdout}"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(_passed_re(_LIVE_TEST_ID), proc.stdout), f"live 用例没真正执行:\n{proc.stdout}"


# ============================================================
# 回归: 命令行 -m 覆盖 addopts 后, 不得把 live 用例重新选回来
# ============================================================
def test_mark_expr_not_slow_cannot_resurrect_live(tmp_path):
    """本次发现的洞: `DA_A_RUN_LIVE=1 pytest -m "not slow"` 曾选中 live 用例并真联网。

    机理: 命令行 -m **完全覆盖** addopts 的 `-m "not live"` (后写的 -m 生效);
    live 用例没打 slow 标记, 所以 "not slow" 匹配它 → pytest 自己就会选中它,
    剩下的只有 env 门禁, 而 env=1 恰好放行 → 真打 qt.gtimg.cn / 同花顺 (一次真实 DNS)。

    现在选择层门禁 (tests/conftest.py 的 pytest_collection_modifyitems) 兜住:
    "not slow" 没有正向点名 live/integration → live 用例被 deselect。
    证据要求两条: stdout 出现 deselect 计数 (确实是 collection 层摘掉的), 且守卫
    sentinel 里零记录 (没有建连、没有 DNS、没有 fetch_full_valuation)。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", "not slow", env_extra={_LIVE_ENV: "1"},
    )

    assert _network_attempts(sentinel) == "", (
        f"-m 'not slow' + {_LIVE_ENV}=1 竟然触网了:\n{_network_attempts(sentinel)}\n{proc.stdout}"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"\d+ deselected", proc.stdout), (
        f"live 用例没在 collection 层被 deselect:\n{proc.stdout}"
    )
    assert _LIVE_TEST_ID not in proc.stdout, f"live 用例被 -m 'not slow' 选回来了:\n{proc.stdout}"
    # 同一运行里离线用例照常通过 —— 只摘掉 live, 没有把整个文件废掉
    assert re.search(_passed_re("test_peg_600693_in_spec_range"), proc.stdout), proc.stdout


@pytest.mark.parametrize("markexpr", [
    "not live",                     # 显式排除; 含 "live" 子串, 不能被误判成"点名"
    "not (live or integration)",    # 否定 + 括号组合
    "not integration and not slow", # 两个排除都点名了 live 的反面, 仍是排除
    "unit or slow",                 # 点名的是别的标记, 与 live 无关
    "integration and not live",     # 正向点名 integration 但同时排除 live
    "not integration or unit",      # 否定混在 or 里 (验收洞 2)
    "live or unit",                 # or 掺了非 opt-in 分支 (验收洞 1)
    "unit or live",                 # 同上, 分支顺序反过来
    "live or unit or integration",  # 掺非 opt-in 分支的多路 or
    "live and slow",                # 合取掺非 opt-in 名字
    "integration and not slow",     # 合取里带否定
], ids=["exclude-live", "exclude-paren", "exclude-both", "other-marks",
        "integration-minus-live", "negated-in-or", "or-mixed-marks", "or-mixed-reversed",
        "or-three-way", "and-mixed", "and-negated"])
def test_other_mark_exprs_never_select_live(tmp_path, markexpr):
    """任何"整体不是显式 opt-in"的 -m 表达式 + env=1: live 不选中, 零网络。

    env 故意给成 1 (最容易出事的取值): 只看表达式侧, 门禁就已经足够。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", markexpr, env_extra={_LIVE_ENV: "1"},
    )

    assert _network_attempts(sentinel) == "", (
        f"-m {markexpr!r} + {_LIVE_ENV}=1 竟然触网了:\n{_network_attempts(sentinel)}"
    )
    assert _LIVE_TEST_ID not in proc.stdout, f"-m {markexpr!r} 把 live 用例选回来了:\n{proc.stdout}"
    # 退出码 5 = 表达式把整个文件的用例都排除了 (no tests ran), 同样属预期:
    # 关键断言是 live 用例不在 items 里, 且零网络。0 = 还有其它用例照常跑。
    assert proc.returncode in (0, 5), proc.stdout + proc.stderr


@pytest.mark.parametrize("env_raw", [None, "", "0", "true"],
                         ids=["unset", "empty", "zero", "true"])
def test_plain_pytest_excludes_live_for_any_env_value(tmp_path, env_raw):
    """默认 pytest (走 addopts 的 `-m "not live"`) 在 env 缺省/空/0/真值串下都不选 live。

    契约 A 的四格。env=1 那格由 test_plain_pytest_excludes_live_even_when_env_misconfigured 覆盖。
    """
    _skip_if_inner_run()
    env_extra = {} if env_raw is None else {_LIVE_ENV: env_raw}
    proc, sentinel = _run_gated_pytest(tmp_path, _THIS_FILE, env_extra=env_extra)

    assert _network_attempts(sentinel) == "", f"{_LIVE_ENV}={env_raw!r} 竟然触网了"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _LIVE_TEST_ID not in proc.stdout, f"live 用例被默认选中了:\n{proc.stdout}"
    assert re.search(r"\d+ deselected", proc.stdout), proc.stdout


def test_live_gate_off_when_env_is_unset(tmp_path):
    """-m integration 但 DA_A_RUN_LIVE **未设置**: 用例被选中但 skip, 零网络。

    与 test_live_gate_off_when_env_is_not_one 的 0/"" 两格一起补齐契约 B 的 env 缺省格。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(tmp_path, _THIS_FILE, "-m", "integration")

    assert _network_attempts(sentinel) == "", f"{_LIVE_ENV} 未设置竟然触网了"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(_LIVE_SKIPPED_RE, proc.stdout), (
        f"live 用例没因 env 门禁被 skip:\n{proc.stdout}"
    )


# 不打网络的 integration 用例 (LibreOffice 转换, 见
# tests/reporting/test_artifact_delivery_contract.py::test_real_libreoffice_converts_minimal_docx_to_nonempty_pdf):
# 选择层门禁只认 live 标记, 不能为了挡 live 把整个 integration 一起误伤 (契约 D)。


# ============================================================
# 回归: 复合 -m 表达式 (or 的非 opt-in 分支 / 否定混在 or 里) 不得放行 live
# ============================================================
# 这两条是上一轮独立只读验收判 FAIL 的用例。它们与其它拒绝用例的关键差别在于
# **record 模式**: fetch_full_valuation 被换成返回合法数值的桩, 网络与 DNS 仍封死。
# block 模式下逃逸会直接 AssertionError 变红 (容易发现), record 模式下逃逸会让
# live 用例**静默 PASS** —— 那才是验收看到的形态, 也更危险。所以这两条用 record 跑。
@pytest.mark.parametrize("markexpr", [
    "live or unit",             # 验收洞 1: any() 看到 live 就放行, 或的 unit 分支同样能选中
    "not live or integration",  # 验收洞 2: 左边是排除信号, 被右边 integration 字样洗白
], ids=["or-mixed-marks", "or-negated-live"])
def test_composite_or_mark_expr_cannot_opt_in_live(tmp_path, markexpr):
    """`DA_A_RUN_LIVE=1 pytest -m "<含 or 的复合表达式>"` 曾选中 live 用例并执行到抓取。

    机理都是 conftest 选择层按 AST 的 any() 判"是否点名 live":
      -m "live or unit"            or 的语义是任一分支匹配即选中; unit 分支同样能
                                   独立命中打了 live 的用例, 选取与"显式点名 live"无关,
                                   无法证明是 opt-in → 必须当没点名 (fail closed)。
      -m "not live or integration" "not live" 是明确的排除信号, 不能被同一表达式里的
                                   integration 字样洗白; 出现否定即一票否决。

    现在整表达式必须由 live/integration 名字合取或析取组成才算 opt-in, 两者都
    只能在 collection 层被摘掉 (deselect 计数为证), 剩下用例照常通过。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", markexpr, mode="record", env_extra={_LIVE_ENV: "1"},
    )

    assert _network_attempts(sentinel) == "", (
        f"-m {markexpr!r} + {_LIVE_ENV}=1 下到了抓取/网络:\n{_network_attempts(sentinel)}\n{proc.stdout}"
    )
    assert _LIVE_TEST_ID not in proc.stdout, f"-m {markexpr!r} 把 live 用例选回来了:\n{proc.stdout}"
    assert proc.returncode in (0, 5), proc.stdout + proc.stderr
    assert re.search(r"\d+ deselected", proc.stdout), (
        f"live 用例不是被 collection 层摘掉的 (难道是用例内 skipif 挡的?):\n{proc.stdout}"
    )


@pytest.mark.parametrize("markexpr", [
    "live",                # 直接点名 live 本身
    "integration",         # 常用出口
    "live and integration",  # 两个 opt-in 名字合取
    "live or integration",   # 两个 opt-in 名字析取
], ids=["live", "integration", "and", "or"])
def test_explicit_opt_in_mark_exprs_still_run_live(tmp_path, markexpr):
    """别把门禁修成死路: 整表达式就是显式 opt-in 的四种写法都必须放行到 env 门禁。

    fetch 换成固定桩 (record 模式), socket/DNS 仍封死 —— 证明的是"选取 + env 门禁
    真的执行到了抓取函数", 与网络可用性无关。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, _THIS_FILE, "-m", markexpr, mode="record", env_extra={_LIVE_ENV: "1"},
    )

    assert "fetch_full_valuation:600693" in _network_attempts(sentinel), (
        f"-m {markexpr!r} + {_LIVE_ENV}=1 没走到 fetch_full_valuation (门禁过严?):\n{proc.stdout}"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(_passed_re(_LIVE_TEST_ID), proc.stdout), (
        f"-m {markexpr!r} 下 live 用例没真正执行:\n{proc.stdout}"
    )


def test_non_live_integration_test_is_still_collected(tmp_path):
    """非 live 的 integration 用例在 `-m integration` 下照常被收集 (契约 D)。

    用 --collect-only: 断言"能选中、能收集"即可, 不真去转 PDF (那属于显式集成验收,
    不该由这条回归顺带触发)。
    """
    _skip_if_inner_run()
    proc, sentinel = _run_gated_pytest(
        tmp_path, "tests/reporting/test_artifact_delivery_contract.py",
        "-m", "integration", "--collect-only", "-q",
    )

    assert _network_attempts(sentinel) == "", "collect-only 不该有任何网络动作"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "test_real_libreoffice_converts_minimal_docx_to_nonempty_pdf" in proc.stdout, (
        f"非 live 的 integration 用例没被收集:\n{proc.stdout}"
    )
    # 同一份收集结果里不应混入 live 用例 (它是别的文件, 传的是单个路径; 防呆断言)
    assert _LIVE_TEST_ID not in proc.stdout, proc.stdout


# ============================================================
# 纯算术 (不依赖任何行情源)
# ============================================================
@pytest.mark.parametrize("pe_ttm,cagr_pct,expected", [
    (20, 20, 1.0),    # pe_ttm=20, cagr_pct=20% → PEG = 1.0
    (40, 20, 2.0),    # pe_ttm=40, cagr_pct=20% → PEG = 2.0
    # pe_ttm=205, cagr_pct=21% → PEG = 9.76（spec §8.2 区间）
    # 注: 原注释写的是 "≈ 9.57", 但 205/21 = 9.7619; 9.57 需 pe_ttm=201。
    # 那行注释在一个 `pass` 空壳里, 从未被执行, 所以错值一直没被发现。
    # 这里保留原输入 (205/21) 并按真实算术纠正结果 —— 不为了让断言通过而改输入。
    (205, 21, 9.76),
])
def test_peg_calculation_uses_pe_ttm_and_cagr_pct(pe_ttm, cagr_pct, expected):
    """PEG = pe_ttm / cagr_pct（pe_ttm 是 TTM PE；cagr_pct 已是百分数，不是小数）

    纯算术, 不依赖任何行情源。真实数据的公式回归在
    test_peg_600693_in_spec_range (golden fixture, 走生产算式) 与
    test_peg_600693_live_in_spec_range (实时) 里。
    """
    assert round(pe_ttm / cagr_pct, 2) == expected


def test_peg_calculation_rejects_decimal_cagr():
    """cagr_pct 是百分数 (21) 而非小数 (0.21): 当小数用会把 PEG 放大 100 倍。"""
    assert round(205 / 0.21, 2) != 9.76
    assert round(205 / 0.21, 2) == 976.19


def test_production_formula_matches_documented_arithmetic():
    """生产算式自身在几个代表输入上等于手算结果 (含退化输入)。"""
    assert round(v2.compute_peg_metrics(20, 1.0, 1.2)["peg"], 2) == 1.0
    assert round(v2.compute_peg_metrics(40, 1.0, 1.2)["peg"], 2) == 2.0
    assert round(v2.compute_peg_metrics(205, 1.0, 1.21)["peg"], 2) == 9.76
    # 增速为负 / 缺 EPS → 无 PEG (而不是负数或除零)
    assert v2.compute_peg_metrics(20, 1.0, 0.8)["peg"] is None
    assert v2.compute_peg_metrics(20, None, 1.2)["peg"] is None
    assert v2.compute_peg_metrics(20, 1.0, 1.2)["cagr_pct"] == pytest.approx(20.0)


# ============================================================
# 实时用例 (双重 opt-in: 选不选 = -m integration, 跑不跑 = DA_A_RUN_LIVE=1)
# ============================================================
@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    not _live_enabled(),
    reason=(f"实时行情检查: 需显式加 -m integration 且 {_LIVE_ENV}=1 才会访问实时接口 "
            f"({_LIVE_ENV}=0/空/未设置 均视为关闭)"),
)
def test_peg_600693_live_in_spec_range():
    """600693 **实时** PEG 应在 1-12 范围（spec §8.2 第 4 条区间；fix round 1 改用 pe_ttm）

    显式 integration 用例, 会打 qt.gtimg.cn + 同花顺。原用例的判定逻辑逐字保留,
    只是从"默认跑"挪到"显式跑", 默认 pytest 不再因此抖动。

        DA_A_RUN_LIVE=1 pytest tests/test_peg_formula.py -m integration
    """
    v = v2.fetch_full_valuation("600693")
    peg = v.get("peg")
    pe_ttm = v.get("pe_ttm")
    pe_fwd = v.get("pe_fwd")  # 仅用于显示，已不再参与 PEG
    cagr_pct = v.get("cagr_pct")
    if cagr_pct is None and (
        v.get("eps_next") is None or v.get("eps_cur") in (None, 0)
    ):
        pytest.skip("实时估值接口未返回 CAGR/EPS，跳过依赖实时数据的 PEG 区间检查")
    cagr_pct = cagr_pct or ((v.get("eps_next", 0) / v.get("eps_cur", 1)) - 1) * 100
    print(f"pe_ttm={pe_ttm}, pe_fwd={pe_fwd}, eps_cur={v.get('eps_cur')}, eps_next={v.get('eps_next')}, cagr_pct={cagr_pct}, peg={peg}")
    assert peg is not None, "PEG 不应为 None"
    assert 1 <= peg <= 12, f"PEG {peg} 应在 spec §8.2 区间（1-12）"
