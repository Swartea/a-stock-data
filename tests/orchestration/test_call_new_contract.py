import ast
import re

import pytest

import analysis.orchestration.fetching as fetching
import analysis.pipeline as pipeline
import analysis.report_md as report_md
import quant_analyzer_v2

TARGET_LABEL = "公告"
TARGET_KEY = "公告"


def _base_result():
    return {
        "code": "600693",
        "name": "东百集团",
        "quote": {"current_price": 10.0},
        "valuation": {},
        "blocks": [{"name": "测试板块"}],
        "fund": {"klines": ["ok"]},
        "valuation_hist": {},
        "lockup": {},
        "dragon": {},
        "macro": {"hsgt": {"scope": "market"}},
        "chip_data": {},
        "sw_data": {},
        "score": {"total": 50, "factors": {}},
        "advice": "观望",
        "emoji": "",
        "detail": {},
    }


def _scoring_breakdown():
    return {
        "total": {"score": 50, "max": 100},
        "tech": {"score": 14, "max": 28},
        "capital": {"score": 12.5, "max": 25},
        "valuation": {"score": 14.5, "max": 29},
        "sentiment": {"score": 4, "max": 8},
        "risk": {"score": 5, "max": 10},
    }


def _default_imports():
    imports = {}
    for key in ("公告", "财务", "研报", "新闻"):
        def fetcher(*args, _key=key, **kwargs):
            return {
                "status": "ok",
                "data": {"key": _key, "args": args, "kwargs": kwargs},
                "source": f"stub.{_key}",
            }

        imports[key] = {"ok": True, "err": "", "fn": fetcher}
    return imports


@pytest.fixture
def run_case(monkeypatch):
    pipeline._src_meta.clear()
    sleeps = []

    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *args, **kwargs: {})
    monkeypatch.setattr(pipeline, "_restore_v2", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline.v2,
        "analyze_single",
        lambda code, name, output_md=False: _base_result(),
    )
    monkeypatch.setattr(pipeline, "_v2_plan", lambda *args, **kwargs: {})
    monkeypatch.setattr(pipeline, "_v2_signals", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(pipeline.v2, "fetch_margin_trading", lambda code: {})
    monkeypatch.setattr(pipeline, "compute_three_levels", lambda *args, **kwargs: {})
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: [])
    monkeypatch.setattr(pipeline, "_fetch_fund_flow_daily", lambda *args: {})
    monkeypatch.setattr(pipeline, "_fetch_margin_history", lambda *args: {})
    monkeypatch.setattr(pipeline, "_fetch_concept_peers", lambda *args: {})
    monkeypatch.setattr(pipeline, "_classify_north_scope", lambda data: ("market", "市场口径"))
    monkeypatch.setattr(pipeline, "_build_scoring_breakdown", lambda score: _scoring_breakdown())
    monkeypatch.setattr(
        pipeline,
        "_kline_freshness",
        lambda chip_data: {
            "last_bar": None,
            "expected": "2026-09-15",
            "level": "ok",
            "text": "contract-test",
        },
    )
    monkeypatch.setattr(pipeline, "_emit", lambda code, name, result: {})
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    def _run(imports):
        pipeline._src_meta.clear()
        sleeps.clear()
        monkeypatch.setattr(pipeline, "_NEW_IMPORTS", imports)
        result = pipeline.analyze_single_v3("600693", "东百集团")
        return result, list(sleeps)

    yield _run
    pipeline._src_meta.clear()


def _target_fallbacks(run_log):
    return [
        item
        for item in run_log["fallback_chain"]
        if item.startswith(f"{TARGET_LABEL}:")
    ]


def _assert_timed_status(status, prefix):
    assert re.fullmatch(rf"{re.escape(prefix)}, \d+ms", status)


def test_call_new_missing_module_is_silent_and_returns_none(run_case):
    imports = _default_imports()
    imports.pop(TARGET_KEY)

    result, sleeps = run_case(imports)
    run_log = result["run_log"]

    assert result["announcements"] is None
    assert TARGET_LABEL not in run_log["sources"]
    assert TARGET_LABEL not in run_log["source_meta"]
    assert _target_fallbacks(run_log) == []
    assert TARGET_LABEL not in pipeline._src_meta
    assert sleeps == []


def test_call_new_import_failure_records_zero_ms_and_full_fallback(run_case):
    err = "数据源暂缺:" + "x" * 90
    imports = _default_imports()
    imports[TARGET_KEY] = {"ok": False, "err": err, "fn": None}

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = f"error:{err[:60]}, 0ms"

    assert result["announcements"] is None
    assert run_log["sources"][TARGET_LABEL] == status
    assert run_log["source_meta"][TARGET_LABEL] == {
        "ms": 0,
        "at": None,
        "status": status,
        "detail": pipeline._SRC_DESC.get(TARGET_LABEL, ""),
    }
    assert _target_fallbacks(run_log) == [f"{TARGET_LABEL}: {err}"]
    assert TARGET_LABEL not in pipeline._src_meta
    assert sleeps == []


def test_call_new_exception_retries_three_times_without_creating_recorder_meta(run_case):
    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("legacy endpoint exploded")

    imports = _default_imports()
    imports[TARGET_KEY] = {"ok": True, "err": "", "fn": boom}

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = "error:调用异常 legacy endpoint exploded, ?ms"

    assert result["announcements"] is None
    assert len(calls) == 3
    assert sleeps == [1.0, 1.0, 1.0]
    assert run_log["sources"][TARGET_LABEL] == status
    assert run_log["source_meta"][TARGET_LABEL] == {
        "status": status,
        "detail": pipeline._SRC_DESC.get(TARGET_LABEL, ""),
        "timeout_sec": 20.0,
        "timed_out": False,
    }
    assert _target_fallbacks(run_log) == [
        f"{TARGET_LABEL}: 第3次后仍失败 — legacy endpoint exploded"
    ]
    assert TARGET_LABEL not in pipeline._src_meta


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "status": "error",
                "data": None,
                "source": "provider.contract",
                "error": {"message": "new-contract-error-" + "n" * 100},
            },
            "new-contract-error-" + "n" * 100,
        ),
        (
            {"error": "legacy-error-" + "l" * 100},
            "legacy-error-" + "l" * 100,
        ),
    ],
)
def test_call_new_error_result_preserves_new_and_legacy_error_messages(
    run_case, payload, message
):
    imports = _default_imports()
    imports[TARGET_KEY] = {
        "ok": True,
        "err": "",
        "fn": lambda *args, **kwargs: payload,
    }

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = run_log["sources"][TARGET_LABEL]

    assert result["announcements"] == payload
    assert re.fullmatch(
        rf"error:{re.escape(message[:60])}, \d+ms",
        status,
    )
    assert _target_fallbacks(run_log) == [f"{TARGET_LABEL}: {message[:100]}"]
    assert run_log["source_meta"][TARGET_LABEL]["status"] == status
    assert run_log["source_meta"][TARGET_LABEL]["detail"] == pipeline._SRC_DESC.get(
        TARGET_LABEL, ""
    )
    assert isinstance(run_log["source_meta"][TARGET_LABEL]["ms"], int)
    assert sleeps == []


def test_call_new_empty_result_is_not_added_to_fallback_chain(run_case):
    payload = {
        "status": "empty",
        "data": None,
        "source": "provider.empty",
        "error": {"message": "no rows"},
    }
    imports = _default_imports()
    imports[TARGET_KEY] = {
        "ok": True,
        "err": "",
        "fn": lambda *args, **kwargs: payload,
    }

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = run_log["sources"][TARGET_LABEL]

    assert result["announcements"] == payload
    _assert_timed_status(status, "empty:无记录")
    assert _target_fallbacks(run_log) == []
    assert run_log["source_meta"][TARGET_LABEL]["status"] == status
    assert sleeps == []


def test_call_new_success_with_source_exposes_actual_source(run_case):
    payload = {
        "status": "ok",
        "data": {"rows": [1]},
        "source": "eastmoney.announcement",
    }
    imports = _default_imports()
    imports[TARGET_KEY] = {
        "ok": True,
        "err": "",
        "fn": lambda *args, **kwargs: payload,
    }

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = run_log["sources"][TARGET_LABEL]

    assert result["announcements"] == payload
    _assert_timed_status(status, "ok:eastmoney.announcement")
    assert _target_fallbacks(run_log) == []
    assert run_log["source_meta"][TARGET_LABEL]["status"] == status
    assert sleeps == []


def test_call_new_plain_success_uses_generic_ok_status(run_case):
    payload = {"rows": [{"id": 1}]}
    imports = _default_imports()
    imports[TARGET_KEY] = {
        "ok": True,
        "err": "",
        "fn": lambda *args, **kwargs: payload,
    }

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = run_log["sources"][TARGET_LABEL]

    assert result["announcements"] == payload
    _assert_timed_status(status, "ok")
    assert _target_fallbacks(run_log) == []
    assert sleeps == []


def test_call_new_unsupported_currently_falls_through_to_ok_source(run_case):
    payload = {
        "status": "unsupported",
        "data": None,
        "source": "provider.unsupported",
        "error": {"message": "not supported"},
    }
    imports = _default_imports()
    imports[TARGET_KEY] = {
        "ok": True,
        "err": "",
        "fn": lambda *args, **kwargs: payload,
    }

    result, sleeps = run_case(imports)
    run_log = result["run_log"]
    status = run_log["sources"][TARGET_LABEL]

    assert result["announcements"] == payload
    # Current behavior is intentionally locked before extraction.  A future
    # semantic change may treat unsupported separately, but Phase 1G does not.
    _assert_timed_status(status, "ok:provider.unsupported")
    assert _target_fallbacks(run_log) == []
    assert run_log["source_meta"][TARGET_LABEL]["status"] == status
    assert sleeps == []


def test_call_new_timeout_kw_controls_retry_boundary_without_forwarding(monkeypatch):
    recorder = pipeline._src_meta
    recorder.clear()
    seen = {}

    def fake_retry(
        rec,
        label,
        fn,
        *args,
        tries,
        timeout,
        _timeout_state,
        **kwargs,
    ):
        _timeout_state["timeout_sec"] = float(timeout)
        _timeout_state["timed_out"] = False
        seen["recorder"] = rec
        seen["label"] = label
        seen["args"] = args
        seen["tries"] = tries
        seen["timeout"] = timeout
        seen["kwargs"] = kwargs
        return {"rows": [1]}, 1, None

    monkeypatch.setattr(fetching, "_retry_call", fake_retry)
    run_log = {"sources": {}, "source_meta": {}, "fallback_chain": []}
    imports = {
        TARGET_KEY: {
            "ok": True,
            "err": "",
            "fn": lambda *_args, **_kwargs: {"rows": [1]},
        }
    }

    value = fetching._call_new(
        recorder,
        run_log,
        imports,
        {TARGET_LABEL: "公告数据"},
        lambda _value: "ok",
        TARGET_LABEL,
        TARGET_KEY,
        "600693",
        timeout=7,
        custom="kept",
    )

    assert value == {"rows": [1]}
    assert seen["recorder"] is recorder
    assert seen["label"] == TARGET_LABEL
    assert seen["args"] == ("600693",)
    assert seen["tries"] == 3
    assert seen["timeout"] == 7
    assert seen["kwargs"] == {"custom": "kept"}
    assert run_log["source_meta"][TARGET_LABEL]["timeout_sec"] == 7.0
    assert run_log["source_meta"][TARGET_LABEL]["timed_out"] is False
def test_call_new_timeout_records_machine_readable_observability(run_case, monkeypatch):
    calls = []
    release = fetching.threading.Event()
    monkeypatch.setattr(fetching, "_NEW_FETCH_TIMEOUT_SEC", 0.01)

    def blocked(*args, **kwargs):
        calls.append((args, kwargs))
        release.wait(0.2)
        return {"late": True}

    imports = _default_imports()
    imports[TARGET_KEY] = {"ok": True, "err": "", "fn": blocked}

    result, sleeps = run_case(imports)
    release.set()

    meta = result["run_log"]["source_meta"][TARGET_LABEL]
    assert len(calls) == 3
    assert sleeps == [1.0, 1.0, 1.0]
    assert meta["timeout_sec"] == 0.01
    assert meta["timed_out"] is True
    assert meta["status"].startswith("error:调用异常 公告 调用超时(0.01s), ")


# ============================================================
# P1-2: V2 私有函数导入边界 (显式别名, 不用 v2._ 魔法查找)
# ============================================================

_V2_PRIVATE_NAMES = (
    "_interpret_pe",
    "_interpret_pctile",
    "_interpret_chips",
    "_make_trading_plan",
    "_make_signal_list",
)

# 本地别名 -> V2 私有函数名
_PIPELINE_ALIASES = {
    "_v2_plan": "_make_trading_plan",
    "_v2_signals": "_make_signal_list",
}
_REPORT_MD_ALIASES = {
    "_v2_pe": "_interpret_pe",
    "_v2_pctile": "_interpret_pctile",
    "_v2_chips": "_interpret_chips",
}


def _read_source(module_path):
    with open(module_path, encoding="utf-8") as handle:
        return handle.read()


def _v2_private_lookups(module_path):
    """真实 AST 上 ``v2.<private>`` 属性访问 (排除注释/文档字符串)。"""
    tree = ast.parse(_read_source(module_path))
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "v2"
            and node.attr in _V2_PRIVATE_NAMES
        ):
            found.append((node.lineno, node.attr))
    return found


@pytest.mark.parametrize("alias,attr", sorted(_PIPELINE_ALIASES.items()))
def test_pipeline_binds_every_v2_private_as_explicit_import_alias(alias, attr):
    """P1-2: pipeline 使用的两个 V2 helper 必须在 import 期绑定到真实函数。"""
    assert getattr(pipeline, alias) is getattr(quant_analyzer_v2, attr)


@pytest.mark.parametrize("alias,attr", sorted(_REPORT_MD_ALIASES.items()))
def test_report_md_binds_v2_interpret_helpers_as_explicit_import_alias(alias, attr):
    """P1-2: report_md 的 3 个 V2 别名必须在 import 期绑定到 V2 真实函数。"""
    assert getattr(report_md, alias) is getattr(quant_analyzer_v2, attr)


def test_pipeline_call_sites_do_not_use_v2_private_attribute_lookups():
    """P1-2: 调用处必须走显式别名, 不得回退到 v2._xxx 魔法查找。"""
    assert _v2_private_lookups(pipeline.__file__) == []


def test_report_md_call_sites_do_not_use_v2_private_attribute_lookups():
    assert _v2_private_lookups(report_md.__file__) == []


def test_pipeline_alias_is_import_time_snapshot_not_v2_attribute_lookup(monkeypatch):
    """P1-2: 别名是 import 期快照, 替换 V2 模块属性不会改写本地绑定。"""
    sentinel = object()
    monkeypatch.setattr(quant_analyzer_v2, "_make_trading_plan", sentinel)
    assert pipeline._v2_plan is not sentinel


def test_pipeline_alias_patch_does_not_mutate_shared_v2_module(monkeypatch):
    """P1-2: 测试桩打在本地别名上, 不污染 quant_analyzer_v2 共享模块。"""
    original = pipeline._v2_plan
    monkeypatch.setattr(pipeline, "_v2_plan", lambda *_a, **_kw: None)
    assert quant_analyzer_v2._make_trading_plan is original


def test_pipeline_keeps_shared_v2_module_for_public_bridge(monkeypatch):
    """模块兼容: v2 公共面 (analyze_single / fetch_margin_trading) 保持 v2.xxx 引用。"""
    def _analyze_single(*_args, **_kw):
        return {"error": "stop-here"}

    monkeypatch.setattr(pipeline.v2, "analyze_single", _analyze_single)
    assert pipeline.v2 is quant_analyzer_v2
    assert pipeline.v2.analyze_single is _analyze_single
