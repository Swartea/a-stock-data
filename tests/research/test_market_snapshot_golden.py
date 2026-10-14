"""Offline deterministic golden fixture contract for A-share Market Snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_market_snapshot_fixture.py"
GOLDEN = ROOT / "tests" / "fixtures" / "market_snapshot" / "golden.json"


def _generate(destination: Path) -> bytes:
    env = dict(os.environ)
    env.pop("DA_A_RUN_LIVE", None)
    result = subprocess.run(
        [sys.executable, "-B", str(GENERATOR), "--output", str(destination)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    assert result.stdout == b""
    return destination.read_bytes()


def test_golden_record_has_required_offline_service_scenarios_and_provenance() -> None:
    record = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert record["schema"] == "a_share_market_snapshot_golden"
    assert record["schema_version"] == "2.0"
    assert record["fixture_kind"] == "offline_synthetic_service_output"
    assert record["evaluation_time"] == "2026-10-14T16:00:00+08:00"
    assert "no live response" in record["source_inputs"]
    assert "generate_market_snapshot_fixture.py" in record["generator_command"]
    assert record["date_window"] == {"start_date": "2026-10-09", "end_date": "2026-10-14"}
    scenarios = {scenario["id"]: scenario for scenario in record["scenarios"]}
    assert set(scenarios) == {
        "primary_success",
        "baostock_fallback_degraded_success",
        "stale_delayed_data",
        "missing_empty_data",
        "provider_error",
    }

    primary = scenarios["primary_success"]
    assert primary["provider_attempts"] == [{"provider": "tencent", "status": "ok"}]
    assert primary["snapshot"]["observation"]["provider"] == "tencent"
    assert primary["snapshot"]["observation"]["close"] == 3912.34
    assert primary["snapshot"]["observation"]["evidence"][0]["provider"]["provider_id"] == "tencent"

    fallback = scenarios["baostock_fallback_degraded_success"]
    assert [attempt["provider"] for attempt in fallback["provider_attempts"]] == ["tencent", "baostock"]
    assert fallback["snapshot"]["observation"]["provider"] == "baostock"
    assert fallback["snapshot"]["observation"]["degraded"] is True
    assert fallback["snapshot"]["observation"]["evidence"][0]["quality"]["degraded"] is True

    stale = scenarios["stale_delayed_data"]["snapshot"]["observation"]
    assert stale["availability"] == "delayed"
    assert stale["freshness"] == "stale"
    assert stale["data_date"] == "2026-10-09"

    missing = scenarios["missing_empty_data"]
    assert [attempt["provider"] for attempt in missing["provider_attempts"]] == ["tencent", "baostock"]
    assert missing["snapshot"]["observation"]["availability"] == "unavailable"
    assert missing["snapshot"]["observation"]["close"] is None

    failed = scenarios["provider_error"]
    assert [attempt["provider"] for attempt in failed["provider_attempts"]] == ["tencent", "baostock"]
    assert failed["snapshot"]["observation"]["availability"] == "unavailable"
    assert failed["snapshot"]["observation"]["reason"] == "SYNTHETIC: synthetic fallback error"


def test_independent_subprocess_generations_match_golden_bytes_and_digest(tmp_path: Path) -> None:
    first = _generate(tmp_path / "first.json")
    second = _generate(tmp_path / "second.json")
    golden = GOLDEN.read_bytes()
    assert first == second == golden
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest() == hashlib.sha256(golden).digest()
