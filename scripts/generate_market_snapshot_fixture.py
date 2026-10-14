#!/usr/bin/env python3
"""Generate deterministic, offline Market Snapshot provenance fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.research.freshness import MaxAgePolicy
from analysis.research.global_daily_k_service import DailyKProvider
from analysis.research.global_indices import get_global_index
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE, MarketIndexUniverse
from analysis.research.market_snapshot_service import build_market_snapshot
from analysis.research.trading_calendar import TradingCalendar, TradingCalendarDay, TradingDayStatus

SCHEMA_VERSION = "2.0"
EVALUATION_TIME = "2026-10-14T16:00:00+08:00"
GENERATOR_COMMAND = "python -B scripts/generate_market_snapshot_fixture.py --output tests/fixtures/market_snapshot/golden.json"
START_DATE = "2026-10-09"
END_DATE = "2026-10-14"

# These provider payloads are synthetic test inputs, never copied from a live response.
SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "primary_success",
        "primary": {"status": "ok", "date": "2026-10-14", "close": 3912.34},
        "fallback": None,
    },
    {
        "id": "baostock_fallback_degraded_success",
        "primary": {"status": "error", "code": "SYNTHETIC", "message": "synthetic primary error"},
        "fallback": {"status": "ok", "date": "2026-10-14", "close": 3912.34},
    },
    {
        "id": "stale_delayed_data",
        "primary": {"status": "ok", "date": "2026-10-09", "close": 3888.0},
        "fallback": None,
    },
    {
        "id": "missing_empty_data",
        "primary": {"status": "empty"},
        "fallback": {"status": "empty"},
    },
    {
        "id": "provider_error",
        "primary": {"status": "error", "code": "SYNTHETIC", "message": "synthetic provider error"},
        "fallback": {"status": "error", "code": "SYNTHETIC", "message": "synthetic fallback error"},
    },
)


def _provider_envelope(input_record: dict[str, Any], *, provider_source: str) -> dict[str, Any]:
    status = input_record["status"]
    common = {
        "source": provider_source,
        "as_of": input_record.get("date", END_DATE),
        "fetched_at": EVALUATION_TIME,
        "scope": "market",
        "units": {"price": "index_points"},
    }
    if status == "ok":
        spec = get_global_index(A_SHARE_CORE_UNIVERSE.identities[0].index_id)
        close = input_record["close"]
        data = [{
            "index_id": spec.identity.index_id,
            "market": spec.market,
            "symbol": spec.identity.local_code,
            "name": spec.name,
            "date": input_record["date"],
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": None,
            "currency": spec.currency,
            "timezone": spec.timezone,
            "source": provider_source,
        }]
        return {**common, "status": "ok", "data": data, "error": None}
    if status == "empty":
        return {**common, "status": "empty", "data": None, "error": {"code": "VALIDATION", "message": "synthetic empty result", "retryable": False}}
    return {
        **common,
        "status": "error",
        "data": None,
        "error": {"code": input_record["code"], "message": input_record["message"], "retryable": False},
    }


def _serialize_snapshot(snapshot: Any) -> dict[str, Any]:
    observation = snapshot.observations[0]
    evidence = [
        {
            "evidence_id": item.evidence_id,
            "subject": item.subject.index_id,
            "metric": item.metric,
            "observation": item.observation,
            "provider": {
                "provider_id": item.provider.provider_id,
                "display_name": item.provider.display_name,
                "provider_family": item.provider.provider_family,
            },
            "time": item.time.to_dict(),
            "quality": {
                "freshness": item.quality.freshness.value,
                "completeness": item.quality.completeness.value,
                "degraded": item.quality.degraded,
                "quality_flags": list(item.quality.quality_flags),
            },
            "pit_status": item.pit_status.value,
            "status": item.status,
        }
        for item in observation.evidence
    ]
    return {
        "snapshot_id": snapshot.snapshot_id,
        "market": snapshot.market,
        "indexes": [identity.index_id for identity in snapshot.indexes],
        "trading_day_status": snapshot.trading_day_status.value,
        "observation": {
            "identity": observation.identity.index_id,
            "name": observation.name,
            "close": observation.close,
            "change": observation.change,
            "change_percent": observation.change_percent,
            "data_date": observation.data_date,
            "provider": observation.provider,
            "degraded": observation.degraded,
            "availability": observation.availability.value,
            "freshness": observation.freshness.value,
            "reason": observation.reason,
            "evidence": evidence,
        },
    }


def build_record() -> dict[str, Any]:
    identity = A_SHARE_CORE_UNIVERSE.identities[0]
    universe = MarketIndexUniverse((identity,), A_SHARE_CORE_UNIVERSE.aliases_for(identity.index_id))
    calendar = TradingCalendar((
        TradingCalendarDay("2026-10-09", TradingDayStatus.OPEN),
        TradingCalendarDay("2026-10-12", TradingDayStatus.CLOSED),
        TradingCalendarDay("2026-10-13", TradingDayStatus.CLOSED),
        TradingCalendarDay("2026-10-14", TradingDayStatus.OPEN),
    ))
    built_scenarios = []
    for scenario in SCENARIOS:
        attempts: list[dict[str, str]] = []

        def make_provider(
            provider_id: str,
            provider_source: str,
            input_record: dict[str, Any] | None,
            attempt_log: list[dict[str, str]],
        ) -> DailyKProvider:
            def fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
                if input_record is None:
                    raise AssertionError(f"unexpected provider call: {provider_id}")
                envelope = _provider_envelope(input_record, provider_source=provider_source)
                attempt_log.append({"provider": provider_id, "status": envelope["status"]})
                return envelope

            return DailyKProvider(provider_id, provider_source, fetch)

        providers = (
            make_provider("tencent", "Tencent", scenario["primary"], attempts),
            make_provider("baostock", "Baostock", scenario["fallback"], attempts),
        )
        snapshot = build_market_snapshot(
            evaluation_time=EVALUATION_TIME,
            start_date=START_DATE,
            end_date=END_DATE,
            calendar=calendar,
            max_age_policy=MaxAgePolicy(timedelta(days=3)),
            universe=universe,
            snapshot_id="market-snapshot-20261014",
            providers=providers,
        )
        built_scenarios.append({
            "id": scenario["id"],
            "fixture_inputs": {"primary": scenario["primary"], "fallback": scenario["fallback"]},
            "provider_attempts": attempts,
            "snapshot": _serialize_snapshot(snapshot),
        })
    return {
        "schema": "a_share_market_snapshot_golden",
        "schema_version": SCHEMA_VERSION,
        "fixture_kind": "offline_synthetic_service_output",
        "source_inputs": "Synthetic deterministic Daily-K provider envelopes and explicit calendar entries; no live response or network is used.",
        "evaluation_time": EVALUATION_TIME,
        "date_window": {"start_date": START_DATE, "end_date": END_DATE},
        "generator_command": GENERATOR_COMMAND,
        "scenarios": built_scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.dumps(build_record(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
