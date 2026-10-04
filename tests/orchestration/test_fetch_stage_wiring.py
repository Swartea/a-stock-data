"""Phase 1I 接线测试: pipeline.py 必须走 fetch_v3_blocks 阶段边界。

与 test_result_builder_wiring.py 同构 —— fetch 阶段抽离后, 主流程不允许再内联
4 个 _call_new / Section Registry / 两融 / supplements 的编排, 也不允许绕过
pipeline 自身的注入口。

⚠️ 契约测试(9 处)一律 monkeypatch(pipeline, "_call_new" / "enabled_sections" /
"_fetch_margin" / "_fetch_fund_flow_daily" / ...), 所以 fetch_v3_blocks 内部的
注入口必须由 pipeline 显式传入; 若 fetching 模块自己绑定 import, 这些打桩会失效,
端到端契约测试将退化成真实抓取 + 真实落盘。

本文件刻意**不做裸子串匹配**。早期版本用 `"_SRC_DESC" in src` 之类的断言, 而
`_SRC_DESC` 在 analyze_single_v3 里另有 _record_sw_tls_failure 一处合法用法 ——
裸子串既不能证明"传给了 fetch_v3_blocks", 也无法区分参数与注释。这里全部改成
AST 断言: 定位到那一个 fetch_v3_blocks 调用, 把实参按签名绑定到形参名, 再逐个
比对"形参 <- pipeline 符号"。另外 _SRC_DESC / _fmt_time 这两个 seam 的正确性
由 fetching 侧反证: fetch_v3_blocks 函数体内不得出现这两个模块级名字。
"""

import ast
import inspect

import analysis.pipeline as pipeline
from analysis.orchestration import fetching

# ============================================================
# 期望接线: 形参名 -> pipeline 侧的符号 (ast.unparse 后的源码文本)
# ============================================================

# 8 个位置参数(含被漏掉的 _src_meta recorder seam)
EXPECTED_POSITIONALS = {
    "code": "code6",
    "base_result": "base_result",
    "run_log": "run_log",
    "recorder": "_src_meta",          # ← 原版测试漏掉的位置 seam
    "new_imports": "_NEW_IMPORTS",
    "src_desc": "_SRC_DESC",
    "status_of": "status_of",
    "fmt_time": "_fmt_time",
}

# 9 个关键字参数
EXPECTED_KEYWORDS = {
    "call_new": "_call_new",
    "enabled_sections": "enabled_sections",
    "fetch_sections": "_fetch_sections",
    "fetch_margin": "_fetch_margin",
    "fetch_supplements": "_fetch_supplements",
    "fund_flow_fetcher": "_fetch_fund_flow_daily",
    "margin_history_fetcher": "_fetch_margin_history",
    "peers_fetcher": "_fetch_concept_peers",
    "margin_fetcher": "v2.fetch_margin_trading",
}

# 全部 17 个 seam
ALL_SEAMS = tuple(EXPECTED_POSITIONALS) + tuple(EXPECTED_KEYWORDS)


def _analyze_single_v3_node() -> ast.FunctionDef:
    return next(
        n
        for n in ast.parse(inspect.getsource(pipeline)).body
        if isinstance(n, ast.FunctionDef) and n.name == "analyze_single_v3"
    )


def _fetch_call() -> ast.Call:
    """定位 analyze_single_v3 里唯一的 fetch_v3_blocks(...) 调用。"""
    calls = [
        n
        for n in ast.walk(_analyze_single_v3_node())
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "fetch_v3_blocks"
    ]
    assert len(calls) == 1, (
        f"analyze_single_v3 应恰好调用一次 fetch_v3_blocks, 实际 {len(calls)} 次"
    )
    return calls[0]


def _signature_params() -> list:
    return list(inspect.signature(fetching.fetch_v3_blocks).parameters)


def actual_wiring() -> tuple:
    """返回 ((形参->实参) 位置参映射, {形参: 实参} 关键字映射)。"""
    call = _fetch_call()
    params = _signature_params()
    # strict=True: 位置实参个数与位置形参数不符时必须炸, 否则 zip 静默截断会放过少传的 seam
    assert len(call.args) == len(EXPECTED_POSITIONALS), (
        f"位置实参应有 {len(EXPECTED_POSITIONALS)} 个, 实际 {len(call.args)} 个"
    )
    positional = {
        p: ast.unparse(a)
        for p, a in zip(params[: len(call.args)], call.args, strict=True)
    }
    keyword = {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
    return positional, keyword


def wiring_problems(positional, keyword, *, required=ALL_SEAMS) -> list:
    """纯函数: 返回接线问题清单(空 == 正确)。供断言与回归变异测试共用。"""
    problems = []
    for param in required:
        if param in EXPECTED_POSITIONALS:
            if param not in positional:
                problems.append(f"位置参数 {param} 未传入")
            elif positional[param] != EXPECTED_POSITIONALS[param]:
                problems.append(
                    f"位置参数 {param} 应接 {EXPECTED_POSITIONALS[param]}, "
                    f"实际 {positional[param]}"
                )
        else:
            if param not in keyword:
                problems.append(f"关键字参数 {param} 未传入")
            elif keyword[param] != EXPECTED_KEYWORDS[param]:
                problems.append(
                    f"关键字参数 {param} 应接 {EXPECTED_KEYWORDS[param]}, "
                    f"实际 {keyword[param]}"
                )
    return problems


# ============================================================
# 边界
# ============================================================


def test_pipeline_uses_fetch_v3_blocks_boundary():
    assert pipeline.fetch_v3_blocks is fetching.fetch_v3_blocks


# ============================================================
# 接线: 形参 <- pipeline 符号 (逐个绑定, 不用裸子串)
# ============================================================


def test_pipeline_wires_every_injected_seam():
    """17 个 seam 全部按签名绑定到正确的 pipeline 符号。"""
    positional, keyword = actual_wiring()

    assert wiring_problems(positional, keyword) == []


def test_src_meta_recorder_seam_is_wired():
    """_src_meta 必须作为第 4 个位置参数接到 recorder —— 契约测试打桩依赖它。"""
    positional, _ = actual_wiring()

    assert positional.get("recorder") == "_src_meta"


def test_src_desc_and_fmt_time_are_passed_as_declared_positionals():
    """_SRC_DESC / _fmt_time 必须按位置接到 src_desc / fmt_time 形参。"""
    positional, keyword = actual_wiring()

    assert positional.get("src_desc") == "_SRC_DESC"
    assert positional.get("fmt_time") == "_fmt_time"
    # 不得改用关键字形式绕过签名绑定
    assert "src_desc" not in keyword
    assert "fmt_time" not in keyword


def test_no_unexpected_keyword_seams():
    """不得出现签名之外的关键字实参(拼错的形参名会在这里暴露)。"""
    _, keyword = actual_wiring()

    assert set(keyword) == set(EXPECTED_KEYWORDS), (
        f"关键字实参集合与预期不符: 多余 {set(keyword) - set(EXPECTED_KEYWORDS)}, "
        f"缺失 {set(EXPECTED_KEYWORDS) - set(keyword)}"
    )


def test_signature_still_declares_all_seams():
    """签名本身不得被悄悄删参。"""
    assert set(ALL_SEAMS) <= set(_signature_params())


# ============================================================
# fetching 侧反证: 阶段体内不得自绑模块级符号
# ============================================================


def test_fetch_stage_does_not_rebind_module_level_seams():
    """fetch_v3_blocks 体内不得出现 _SRC_DESC / _fmt_time / _NEW_IMPORTS 等模块名。

    这些名字只应作为 pipeline 传入的形参(src_desc / fmt_time / new_imports)使用;
    一旦阶段内重新绑定模块级符号, pipeline 上的 monkeypatch 就会失效。
    """
    body = inspect.getsource(fetching.fetch_v3_blocks)
    forbidden = ("_SRC_DESC", "_fmt_time", "_NEW_IMPORTS", "_call_new", "_fetch_margin")

    for name in forbidden:
        assert name not in body, (
            f"fetch_v3_blocks 体内不得绑定模块级 {name!r}, "
            f"必须只用 pipeline 显式传入的形参"
        )


def test_fetch_stage_actually_calls_injected_params():
    """fetch_v3_blocks 必须真的调用被注入的形参(而非形同虚设的占位参数)。"""
    fn = next(
        n
        for n in ast.parse(inspect.getsource(fetching)).body
        if isinstance(n, ast.FunctionDef) and n.name == "fetch_v3_blocks"
    )
    called = {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

    for param in ("call_new", "enabled_sections", "fetch_sections",
                  "fetch_margin", "fetch_supplements"):
        assert param in called, f"fetch_v3_blocks 未调用注入的形参 {param}"


def test_fetch_stage_passes_src_desc_and_fmt_time_through():
    """_SRC_DESC / _fmt_time 必须经 src_desc / fmt_time 形参转发给下游 primitive。"""
    fn = next(
        n
        for n in ast.parse(inspect.getsource(fetching)).body
        if isinstance(n, ast.FunctionDef) and n.name == "fetch_v3_blocks"
    )
    for target in ("fetch_margin", "fetch_supplements"):
        call = next(
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == target
        )
        forwarded = {ast.unparse(a) for a in call.args} | {
            kw.arg for kw in call.keywords if kw.arg
        }
        assert "src_desc" in forwarded, f"{target} 未收到注入的 src_desc"
        assert "fmt_time" in forwarded, f"{target} 未收到注入的 fmt_time"


# ============================================================
# 回归: 逐个删除必需 seam, 校验器必须报错 (证明断言非空转)
# ============================================================


def test_wiring_validator_flags_every_removed_seam():
    """变异测试: 少传任一 seam, wiring_problems 都必须报出来。

    没有这一条, 上面的断言可能在 wiring_problems 恒返回 [] 时依然全绿。
    """
    positional, keyword = actual_wiring()
    assert wiring_problems(positional, keyword) == [], "基线接线本应正确"

    for param in ALL_SEAMS:
        p2, k2 = dict(positional), dict(keyword)
        if param in p2:
            del p2[param]
        else:
            del k2[param]

        problems = wiring_problems(p2, k2)
        assert problems, f"删掉 {param} 后校验器竟未报错 —— 断言空转"
        assert any(param in m for m in problems), (
            f"删掉 {param} 后的报错未点名该 seam: {problems}"
        )


# ============================================================
# 内联残留
# ============================================================


def test_fetch_block_no_longer_inline_in_pipeline():
    """4 个 _call_new 标签与两融/supplements 编排不得再留在主流程内联。"""
    src = inspect.getsource(pipeline.analyze_single_v3)

    for inline_marker in (
        '"财务摘要"',
        '"研报观点"',
        '"新闻舆情"',
        "sections = enabled_sections()",
    ):
        assert inline_marker not in src, (
            f"fetch 阶段已抽离, 主流程不应再内联 {inline_marker!r}"
        )


def test_pipeline_keeps_legacy_re_exports():
    """既有测试仍从 pipeline 取这些名字, 不得因抽离而消失。"""
    for name in (
        "_call_new",
        "_fetch_margin",
        "_fetch_sections",
        "_fetch_supplements",
        "_retry_call",
        "_fetch_fund_flow_daily",
        "_fetch_margin_history",
        "_fetch_concept_peers",
        "_src_meta",
        "_NEW_IMPORTS",
        "_SRC_DESC",
        "_fmt_time",
        "status_of",
        "enabled_sections",
    ):
        assert hasattr(pipeline, name), f"pipeline 透传契约丢失: {name}"
