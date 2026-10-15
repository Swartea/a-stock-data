from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.research.market_snapshot_view import load_snapshot_json, render_market_snapshot

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "fixtures" / "market_snapshot" / "golden.json"
HTML = ROOT / "examples" / "market_snapshot" / "market_snapshot.html"
PAIRED_JSON = ROOT / "examples" / "market_snapshot" / "market_snapshot.json"


def test_golden_snapshot_renders_deterministically_and_preserves_json() -> None:
    raw = GOLDEN.read_bytes()
    record = json.loads(raw)
    rendered = render_market_snapshot(record)
    assert HTML.read_text(encoding="utf-8") == rendered
    assert PAIRED_JSON.read_bytes() == raw
    assert rendered == render_market_snapshot(record)
    assert "primary_success" in rendered
    assert "baostock_fallback_degraded_success" in rendered
    assert "stale_delayed_data" in rendered
    assert "missing_empty_data" in rendered
    assert "provider_error" in rendered
    assert "降级回退" in rendered
    assert "腾讯财经" in rendered
    assert "Baostock" in rendered
    assert "2026-10-09" in rendered
    assert "市场日历状态" in rendered
    for label in ("上涨 ↑", "下跌 ↓", "持平 →", "延迟", "不可用", "未知"):
        assert label in rendered


def test_statuses_and_evidence_are_textual_and_rendered_data_is_escaped() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    record["scenarios"][0]["snapshot"]["observation"].update(
        {"change": 1.25, "change_percent": 0.1}
    )
    record["scenarios"][1]["snapshot"]["observation"].update(
        {"change": -1.25, "change_percent": -0.1}
    )
    unchanged = json.loads(json.dumps(record["scenarios"][0]))
    unchanged["id"] = "unchanged_case"
    unchanged["snapshot"]["observation"].update({"change": 0, "change_percent": 0})
    record["scenarios"].append(unchanged)
    html = render_market_snapshot(record)
    for label in ("上涨", "下跌", "持平", "延迟", "不可用", "未知"):
        assert label in html
    assert "synthetic fallback error" in html
    assert "PIT allow" in html
    record["source_inputs"] = '<img src=x onerror="alert(1)">'
    first = record["scenarios"][0]
    first["id"] = '<img src="scenario">'
    observation = first["snapshot"]["observation"]
    observation["name"] = '<b>index</b>'
    first["provider_attempts"] = [{"provider": "<em>p&x</em>", "status": '<i>ok</i>'}]
    observation["evidence"][0]["evidence_id"] = '<strong>evidence</strong>'
    observation["evidence"][0]["provider"]["display_name"] = '<u>source</u>'
    rendered = render_market_snapshot(record)
    for escaped in (
        "&lt;img src=&quot;scenario&quot;&gt;",
        "&lt;b&gt;index&lt;/b&gt;",
        "&lt;em&gt;p&amp;x&lt;/em&gt;: &lt;i&gt;ok&lt;/i&gt;",
        "&lt;strong&gt;evidence&lt;/strong&gt;",
        "&lt;u&gt;source&lt;/u&gt;",
        "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
    ):
        assert escaped in rendered
    assert "&amp;lt;" not in rendered


def test_malformed_numeric_fields_render_unknown_without_raising() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    observation = record["scenarios"][0]["snapshot"]["observation"]
    observation.update({"change": "not-a-number", "change_percent": True})
    rendered = render_market_snapshot(record)
    assert 'class="state unknown">持平/涨跌未知' in rendered
    assert "not-a-number" not in rendered
    assert "不可用" in rendered


def test_hero_metadata_does_not_hide_conflicting_scenario_values() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    record["scenarios"].insert(0, {"id": "unavailable_first", "snapshot": {"observation": {"availability": "unavailable"}}})
    rendered = render_market_snapshot(record)
    assert "市场：cn" in rendered
    assert "市场日历状态：各场景不同" in rendered
    assert "快照 ID：market-snapshot-20261014" in rendered


def test_malformed_nested_objects_render_without_crashing() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    observation = record["scenarios"][0]["snapshot"]["observation"]
    observation["evidence"] = [
        {"provider": "provider text", "quality": [], "time": 7},
        None,
        "malformed evidence",
    ]
    record["scenarios"][0]["provider_attempts"] = [None, "malformed attempt", {"provider": "tencent"}]
    record["scenarios"].append({"id": "malformed_payload", "snapshot": ["not", "an object"]})
    rendered = render_market_snapshot(record)
    assert "tencent: 未知" in rendered
    assert "malformed evidence" not in rendered
    assert "未知" in rendered


def test_render_rejects_non_object_root() -> None:
    with pytest.raises(ValueError, match="record must be an object"):
        render_market_snapshot([])


def test_mobile_layout_is_offline_responsive_and_has_no_chart_or_external_assets() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "@media(max-width:520px)" in html
    assert "grid-template-columns:1fr 1fr" in html
    assert "min-width:0" in html
    assert "<script" not in html.lower()
    assert "<canvas" not in html.lower()
    assert "<svg" not in html.lower()
    assert "https://" not in html
    assert "cdn" not in html.lower()


def test_load_snapshot_json_rejects_malformed_json_and_non_object_root() -> None:
    with pytest.raises(json.JSONDecodeError):
        load_snapshot_json('{"scenarios":')
    with pytest.raises(ValueError, match="root must be an object"):
        load_snapshot_json("[]")


def test_scenarios_must_be_objects() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    record["scenarios"].append("not an object")
    with pytest.raises(ValueError, match="scenarios must contain only objects"):
        render_market_snapshot(record)


