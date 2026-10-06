"""Phase 1J 接线测试: pipeline.py 必须走 run_v2_stage 阶段边界。

与 test_fetch_stage_wiring.py / test_result_builder_wiring.py 同构 —— V2 阶段抽离后,
主流程不允许再内联 3 次重试循环 / fatal 中止 / try-finally 恢复, 也不允许绕过
pipeline 自身的注入口。

⚠️ 契约测试一律 monkeypatch(pipeline, "_patch_v2_timers" / "_restore_v2" /
"_dump_run_log" / "_finalize_run_log_timing") 与 monkeypatch(pipeline.v2,
"analyze_single"), 所以 run_v2_stage 内部的注入口必须由 pipeline 显式传入;
若 v2_stage 模块自己绑定 import, 这些打桩会全部失效, 端到端契约测试将退化成
真实抓取 + 真实落盘。

本文件同样**不做裸子串匹配**: _fmt_time / _SRC_DESC 在主流程另有合法用法, 裸子串
既不能证明"传给了 run_v2_stage", 也无法区分参数与注释。全部用 AST 断言: 定位到
那一个 run_v2_stage 调用, 把实参按签名绑定到形参名, 再逐个比对"形参 <- pipeline 符号"。
"""

import ast
import inspect

import analysis.pipeline as pipeline
from analysis.orchestration import v2_stage

# ============================================================
# 期望接线: 形参名 -> pipeline 侧的符号 (ast.unparse 后的源码文本)
# ============================================================

# 6 个数据位置参数
EXPECTED_DATA_POSITIONALS = {
    "code": "code",
    "name": "name",
    "run_log": "run_log",
    "started": "started",
    "recorder": "_src_meta",
    "v2": "v2",
}

# 9 个注入口(全部以关键字传入, 便于阅读与防错位)
EXPECTED_SEAMS = {
    "patch_timers": "_patch_v2_timers",
    "restore_v2": "_restore_v2",
    "finalize_timing": "_finalize_run_log_timing",
    "dump_run_log": "_dump_run_log",
    "sleep": "time.sleep",
    "time_fn": "time.time",
    "now_fn": "datetime.now",
    "analyze_single": "v2.analyze_single",
    "fmt_time": "_fmt_time",
}

# 全部 15 个 seam
ALL_SEAMS = tuple(EXPECTED_DATA_POSITIONALS) + tuple(EXPECTED_SEAMS)


def _analyze_single_v3_node() -> ast.FunctionDef:
    return next(
        n
        for n in ast.parse(inspect.getsource(pipeline)).body
        if isinstance(n, ast.FunctionDef) and n.name == "analyze_single_v3"
    )


def _stage_call() -> ast.Call:
    """定位 analyze_single_v3 里唯一的 run_v2_stage(...) 调用。"""
    calls = [
        n
        for n in ast.walk(_analyze_single_v3_node())
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "run_v2_stage"
    ]
    assert len(calls) == 1, (
        f"analyze_single_v3 应恰好调用一次 run_v2_stage, 实际 {len(calls)} 次"
    )
    return calls[0]


def _signature_params() -> list:
    return list(inspect.signature(v2_stage.run_v2_stage).parameters)


def actual_wiring() -> tuple:
    """返回 ((形参->实参) 位置参映射, {形参: 实参} 关键字映射)。"""
    call = _stage_call()
    params = _signature_params()
    # strict=True: 位置实参个数与位置形参数不符时必须炸
    assert len(call.args) == len(EXPECTED_DATA_POSITIONALS), (
        f"位置实参应有 {len(EXPECTED_DATA_POSITIONALS)} 个, 实际 {len(call.args)} 个"
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
        if param in EXPECTED_DATA_POSITIONALS:
            if param not in positional:
                problems.append(f"位置参数 {param} 未传入")
            elif positional[param] != EXPECTED_DATA_POSITIONALS[param]:
                problems.append(
                    f"位置参数 {param} 应接 {EXPECTED_DATA_POSITIONALS[param]}, "
                    f"实际 {positional[param]}"
                )
        else:
            if param not in keyword:
                problems.append(f"关键字参数 {param} 未传入")
            elif keyword[param] != EXPECTED_SEAMS[param]:
                problems.append(
                    f"关键字参数 {param} 应接 {EXPECTED_SEAMS[param]}, "
                    f"实际 {keyword[param]}"
                )
    return problems


# ============================================================
# 边界
# ============================================================


def test_pipeline_uses_v2_stage_boundary():
    assert pipeline.run_v2_stage is v2_stage.run_v2_stage


# ============================================================
# 接线: 形参 <- pipeline 符号
# ============================================================


def test_pipeline_wires_every_injected_seam():
    """15 个 seam 全部按签名绑定到正确的 pipeline 符号。"""
    positional, keyword = actual_wiring()

    assert wiring_problems(positional, keyword) == []


def test_recorder_seam_is_wired():
    """_src_meta 必须接到 recorder —— 契约测试与 recorder.clear 时机依赖它。"""
    positional, _ = actual_wiring()

    assert positional.get("recorder") == "_src_meta"


def test_v2_module_and_analyze_single_seam_are_wired():
    """v2 模块对象与 v2.analyze_single 都必须显式传入。

    测试是在 pipeline.v2 上打桩 analyze_single 的; 若阶段自己去 import v2 或自己取
    v2.analyze_single, 打桩会失效并退化成真实抓取。
    """
    positional, keyword = actual_wiring()

    assert positional.get("v2") == "v2"
    assert keyword.get("analyze_single") == "v2.analyze_single"


def test_clock_seams_are_wired_as_module_attribute_lookups():
    """time.sleep / time.time / datetime.now 必须写成属性查找形式。

    写成 from time import sleep 之类的绑定会破坏 tests 里对 pipeline.time /
    pipeline.datetime 的整体替换(fatal 时点契约测试依赖它)。
    """
    _, keyword = actual_wiring()

    assert keyword.get("sleep") == "time.sleep"
    assert keyword.get("time_fn") == "time.time"
    assert keyword.get("now_fn") == "datetime.now"


def test_no_unexpected_keyword_seams():
    """不得出现签名之外的关键字实参(拼错的形参名会在这里暴露)。"""
    _, keyword = actual_wiring()

    assert set(keyword) == set(EXPECTED_SEAMS), (
        f"关键字实参集合与预期不符: 多余 {set(keyword) - set(EXPECTED_SEAMS)}, "
        f"缺失 {set(EXPECTED_SEAMS) - set(keyword)}"
    )


def test_signature_still_declares_all_seams():
    """签名本身不得被悄悄删参。"""
    assert set(ALL_SEAMS) <= set(_signature_params())


# ============================================================
# v2_stage 侧反证: 阶段体内不得自绑模块级符号
# ============================================================


def test_v2_stage_does_not_rebind_pipeline_seams():
    """run_v2_stage 体内不得出现 pipeline 侧符号名。

    这些名字只应作为 pipeline 传入的形参出现; 一旦阶段内重新绑定, pipeline 上的
    monkeypatch 就会失效。
    """
    body = inspect.getsource(v2_stage.run_v2_stage)
    forbidden = (
        "_patch_v2_timers",
        "_restore_v2",
        "_dump_run_log",
        "_finalize_run_log_timing",
        "_fmt_time",
        "_src_meta",
    )

    for name in forbidden:
        assert name not in body, (
            f"run_v2_stage 体内不得绑定 pipeline 侧 {name!r}, "
            f"必须只用 pipeline 显式传入的形参"
        )


def test_v2_stage_does_not_import_pipeline_or_quant_analyzer_v2():
    """阶段不得反向 import pipeline / v2 —— 依赖方向必须单向。"""
    src = inspect.getsource(v2_stage)

    assert "import analysis.pipeline" not in src
    assert "import quant_analyzer_v2" not in src
    assert "from analysis.pipeline" not in src


def test_v2_stage_actually_calls_injected_params():
    """run_v2_stage 必须真的**调用**被注入的形参(而非形同虚设的占位参数)。

    ``time_fn`` / ``now_fn`` / ``fmt_time`` 只是转发给下游 primitive(见下一条用例),
    本身不直接调用, 因此不在此列。
    """
    fn = next(
        n
        for n in ast.parse(inspect.getsource(v2_stage)).body
        if isinstance(n, ast.FunctionDef) and n.name == "run_v2_stage"
    )
    called = {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

    for param in (
        "patch_timers",
        "restore_v2",
        "finalize_timing",
        "dump_run_log",
        "analyze_single",
        "sleep",
    ):
        assert param in called, f"run_v2_stage 未调用注入的形参 {param}"


def test_v2_stage_forwards_recorder_fmt_time_and_timing_seams():
    """recorder / fmt_time / 时点与时钟必须经形参转发给下游 primitive。"""
    fn = next(
        n
        for n in ast.parse(inspect.getsource(v2_stage)).body
        if isinstance(n, ast.FunctionDef) and n.name == "run_v2_stage"
    )
    calls = {
        n.func.id: n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

    patch_args = {ast.unparse(a) for a in calls["patch_timers"].args}
    assert {"recorder", "fmt_time"} <= patch_args, (
        "patch_timers 必须同时收到注入的 recorder 与 fmt_time"
    )

    timing_args = {ast.unparse(a) for a in calls["finalize_timing"].args}
    assert {"started", "now_fn", "time_fn"} <= timing_args, (
        "finalize_timing 必须收到注入的 started / now_fn / time_fn"
    )

    dump_args = {ast.unparse(a) for a in calls["dump_run_log"].args}
    assert {"code", "name", "run_log"} <= dump_args, (
        "dump_run_log 必须收到 code / name / run_log"
    )


# ============================================================
# 回归: 逐个删除必需 seam, 校验器必须报错 (证明断言非空转)
# ============================================================


def test_wiring_validator_flags_every_removed_seam():
    """变异测试: 少传任一 seam, wiring_problems 都必须报出来。"""
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


def test_v2_retry_loop_no_longer_inline_in_pipeline():
    """重试循环 / fatal 中止 / V2 恢复不得再留在主流程内联。"""
    src = inspect.getsource(pipeline.analyze_single_v3)

    for inline_marker in (
        "次尝试失败",
        "V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底)",
        "分析中止",
        "for attempt in range",
        "_restore_v2(v2, saved)",
    ):
        assert inline_marker not in src, (
            f"V2 阶段已抽离, 主流程不应再内联 {inline_marker!r}"
        )


def test_pipeline_still_unwraps_stage_result_before_continuing():
    """主流程必须显式处理 abort 并取出 base_result, 不得无视返回形状。"""
    src = inspect.getsource(pipeline.analyze_single_v3)

    assert "v2_stage.abort" in src, "主流程必须检查 abort 并原样返回"
    assert "v2_stage.base_result" in src, "主流程必须从阶段结果取出 base_result"


def test_pipeline_keeps_legacy_re_exports():
    """既有测试仍从 pipeline 取这些名字, 不得因抽离而消失。"""
    for name in (
        "_patch_v2_timers",
        "_restore_v2",
        "_dump_run_log",
        "_finalize_run_log_timing",
        "_src_meta",
        "_fmt_time",
        "v2",
    ):
        assert hasattr(pipeline, name), f"pipeline 透传契约丢失: {name}"
