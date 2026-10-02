import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import analysis.pipeline as pipeline
import analysis.sections as sections
from analysis.orchestration import fetching


SECTIONS_DIR = Path(sections.__file__).resolve().parent
SHIPPED_REGISTRY = SECTIONS_DIR / "registry.yaml"
EXPECTED_LABELS = ["irm", "holders", "dividend", "board", "dragon_market"]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


class FakeSection:
    def __init__(self, label, fetch_fn):
        self.label = label
        self._fetch_fn = fetch_fn

    def fetch(self, code, ctx):
        return self._fetch_fn(code, ctx)


def _base_result():
    return {
        "code": "600693",
        "name": "东百集团",
        "quote": {"price": 10.0},
        "valuation": {},
        "score": {"total": 50, "factors": {}},
        "chip_data": {},
        "valuation_hist": {},
        "blocks": [{"name": "测试概念"}],
        "fund": {"klines": [1]},
        "lockup": {},
        "dragon": {},
        "macro": {"hsgt": {"scope": "market"}},
        "sw_data": {},
        "advice": "中性",
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


def _run_pipeline_with_sections(monkeypatch, sections, clock=None):
    clock = clock or FakeClock()
    base_result = _base_result()
    pipeline._src_meta.clear()

    fake_time = SimpleNamespace(time=clock.time, sleep=clock.sleep)
    monkeypatch.setattr(pipeline, "time", fake_time)
    monkeypatch.setattr(fetching, "time", fake_time)
    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_restore_v2", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        pipeline.v2,
        "analyze_single",
        lambda *_args, **_kw: base_result,
    )
    monkeypatch.setattr(pipeline.v2, "_make_trading_plan", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline.v2, "_make_signal_list", lambda *_args, **_kw: ([], []))

    monkeypatch.setattr(pipeline, "compute_three_levels", lambda *_args, **_kw: {})
    monkeypatch.setattr(pipeline, "_call_new", lambda *_args, **_kw: None)
    monkeypatch.setattr(pipeline, "enabled_sections", lambda: sections)
    monkeypatch.setattr(pipeline, "_fetch_margin", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_supplements",
        lambda _recorder, run_log, *_args, **_kw: run_log.__setitem__(
            "supplements", {}
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_classify_north_scope",
        lambda *_args, **_kw: ("market", "市场口径"),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_scoring_breakdown",
        lambda *_args, **_kw: _scoring_breakdown(),
    )
    monkeypatch.setattr(
        pipeline,
        "_kline_freshness",
        lambda *_args, **_kw: {
            "last_bar": None,
            "expected": "2026-09-15",
            "level": "ok",
            "text": "fresh",
        },
    )
    monkeypatch.setattr(pipeline, "_emit", lambda *_args, **_kw: {"status": {}})

    result = pipeline.analyze_single_v3("600693", "东百集团")
    return result, base_result, clock


def test_sections_run_in_registry_order_with_exact_context_and_top_level_results(monkeypatch):
    calls = []
    clock = FakeClock()
    payload_a = {"value": "A"}
    payload_b = {"value": "B"}

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.125)
        return payload_a

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.250)
        return payload_b

    sections = [
        FakeSection("Section A", fetch_a),
        FakeSection("Section B", fetch_b),
    ]
    result, base_result, _ = _run_pipeline_with_sections(
        monkeypatch,
        sections,
        clock,
    )
    run_log = result["run_log"]

    assert [(label, code) for label, code, _ctx in calls] == [
        ("A", "600693"),
        ("B", "600693"),
    ]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert result["Section A"] is payload_a
    assert result["Section B"] is payload_b
    assert run_log["sections_count"] == 2
    assert run_log["sources"]["Section A"] == "ok, 125ms"
    assert run_log["sources"]["Section B"] == "ok, 250ms"
    assert not any(item.startswith("Section A:") for item in run_log["fallback_chain"])
    assert not any(item.startswith("Section B:") for item in run_log["fallback_chain"])


def test_section_exception_becomes_error_payload_and_does_not_stop_later_sections(monkeypatch):
    calls = []
    clock = FakeClock()

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.100)
        return {"value": "A"}

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.200)
        raise RuntimeError("boom")

    def fetch_c(code, ctx):
        calls.append(("C", code, ctx))
        clock.advance(0.250)
        return {"value": "C"}

    sections = [
        FakeSection("Section A", fetch_a),
        FakeSection("Section B", fetch_b),
        FakeSection("Section C", fetch_c),
    ]
    result, base_result, _ = _run_pipeline_with_sections(
        monkeypatch,
        sections,
        clock,
    )
    run_log = result["run_log"]

    assert [label for label, _code, _ctx in calls] == ["A", "B", "C"]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert result["Section B"] == {"error": "boom"}
    assert result["Section C"] == {"value": "C"}
    assert run_log["sections_count"] == 2
    assert run_log["sources"]["Section A"] == "ok, 100ms"
    assert run_log["sources"]["Section B"] == "error: boom"
    assert run_log["sources"]["Section C"] == "ok, 250ms"
    assert "Section B: boom" in run_log["fallback_chain"]


def test_empty_section_registry_keeps_count_zero_and_adds_no_section_results(monkeypatch):
    result, _base_result_obj, _clock = _run_pipeline_with_sections(monkeypatch, [])
    run_log = result["run_log"]

    assert run_log["sections_count"] == 0
    assert "Section A" not in result
    assert "Section B" not in result
    assert "Section A" not in run_log["sources"]
    assert "Section B" not in run_log["sources"]


# ---------------------------------------------------------------------------
# registry.yaml contract (docs design §6.2: disabled_sections: [] = 全启用)
#
# No network and no report fixtures: these tests only exercise the shipped
# config file, lazy registration, label filtering and the degraded paths.
# ---------------------------------------------------------------------------


def _reset_registry(monkeypatch):
    """给每个用例一个干净的注册表，避免模块级 SECTIONS 互相污染。"""
    monkeypatch.setattr(sections, "SECTIONS", [])


def _labels():
    return [section.label for section in sections.enabled_sections()]


def _write_registry(path, disabled):
    items = ", ".join(disabled)
    path.write_text(
        f"# test fixture\ndisabled_sections: [{items}]\n",
        encoding="utf-8",
    )


def _install_stub_yaml(monkeypatch, safe_load):
    """PyYAML 缺失时的最小替身，只覆盖已文档化的 disabled_sections schema。"""
    stub = types.ModuleType("yaml")
    stub.safe_load = safe_load
    monkeypatch.setitem(sys.modules, "yaml", stub)


def _ensure_yaml_importable(monkeypatch):
    try:
        import yaml  # noqa: F401
    except ImportError:
        def _safe_load(stream):
            text = stream.read()
            match = re.search(
                r"^disabled_sections:\s*\[(.*?)\]\s*$", text, re.MULTILINE
            )
            if match is None:
                return None
            items = [i.strip().strip("'\"") for i in match.group(1).split(",")]
            return {"disabled_sections": [i for i in items if i]}

        _install_stub_yaml(monkeypatch, _safe_load)


def test_shipped_registry_uses_documented_schema_with_no_sections_disabled():
    assert SHIPPED_REGISTRY.is_file(), "analysis/sections/registry.yaml must be shipped"

    text = SHIPPED_REGISTRY.read_text(encoding="utf-8")
    match = re.search(
        r"^disabled_sections:\s*\[(.*?)\]\s*$", text, re.MULTILINE
    )
    assert match is not None, "registry.yaml must declare a disabled_sections list"
    assert match.group(1).strip() == "", "default config must disable nothing"

    keys = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*):", text, re.MULTILINE)
    assert keys == ["disabled_sections"], "schema is disabled_sections only"


def test_shipped_default_config_enables_all_five_sections(monkeypatch):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)

    assert sections._REGISTRY_PATH == str(SHIPPED_REGISTRY)
    assert _labels() == EXPECTED_LABELS


def test_five_sections_register_lazily_in_sort_order(monkeypatch):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)

    assert sections.SECTIONS == [], "registration must stay lazy until first use"
    assert sections.enabled_sections() is not None
    assert _labels() == EXPECTED_LABELS

    sort_orders = [section.sort_order for section in sections.SECTIONS]
    assert sort_orders == sorted(sort_orders)
    assert sort_orders == [40, 50, 55, 60, 65]


def test_registered_labels_match_every_section_meta_json():
    shipped = {}
    for meta_file in sorted(SECTIONS_DIR.glob("*/meta.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        shipped[meta["label"]] = meta["sort_order"]

    assert sorted(shipped) == sorted(EXPECTED_LABELS)
    assert sorted(shipped.values()) == [40, 50, 55, 60, 65]


def test_disabled_label_is_filtered_out_and_order_is_preserved(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    registry = tmp_path / "registry.yaml"
    _write_registry(registry, ["board", "dragon_market"])
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    assert _labels() == ["irm", "holders", "dividend"]
    assert _labels() == ["irm", "holders", "dividend"], "filtering must be stable"


def test_disabling_one_middle_section_keeps_the_other_four(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    registry = tmp_path / "registry.yaml"
    _write_registry(registry, ["dividend"])
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    assert _labels() == ["irm", "holders", "board", "dragon_market"]


def test_disabling_all_labels_empties_the_registry(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    registry = tmp_path / "registry.yaml"
    _write_registry(registry, EXPECTED_LABELS)
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    assert _labels() == []


def test_unknown_disabled_label_is_ignored(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    registry = tmp_path / "registry.yaml"
    _write_registry(registry, ["not_a_section"])
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    assert _labels() == EXPECTED_LABELS


def test_absent_registry_file_enables_all_five_sections(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    missing = tmp_path / "does-not-exist.yaml"
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(missing))

    assert not missing.exists()
    assert _labels() == EXPECTED_LABELS


def test_missing_pyyaml_degrades_gracefully_to_all_sections(monkeypatch):
    _reset_registry(monkeypatch)
    # sys.modules["yaml"] = None makes `import yaml` raise ImportError.
    monkeypatch.setitem(sys.modules, "yaml", None)

    with pytest.raises(ImportError):
        import yaml  # noqa: F401

    assert _labels() == EXPECTED_LABELS


def test_unreadable_registry_file_degrades_gracefully(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    registry = tmp_path / "registry.yaml"
    registry.write_text("disabled_sections: not-a-list\n", encoding="utf-8")
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    def _boom(_stream):
        raise RuntimeError("unreadable registry")

    _install_stub_yaml(monkeypatch, _boom)

    assert _labels() == EXPECTED_LABELS


def test_non_mapping_registry_payload_degrades_gracefully(monkeypatch, tmp_path):
    """A payload that is not a mapping (no .get) must not propagate."""
    _reset_registry(monkeypatch)
    registry = tmp_path / "registry.yaml"
    registry.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    def _returns_list(_stream):
        return ["board", "irm"]

    _install_stub_yaml(monkeypatch, _returns_list)

    assert _load_disabled_list() == []
    assert _labels() == EXPECTED_LABELS


def test_empty_registry_file_enables_all_five_sections(monkeypatch, tmp_path):
    _reset_registry(monkeypatch)
    _ensure_yaml_importable(monkeypatch)
    registry = tmp_path / "registry.yaml"
    registry.write_text("", encoding="utf-8")
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(registry))

    assert _load_disabled_list() == []
    assert _labels() == EXPECTED_LABELS


def _load_disabled_list():
    return list(sections._load_disabled())

