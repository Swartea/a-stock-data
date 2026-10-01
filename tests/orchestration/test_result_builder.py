"""Phase 1H: V3 result assembly extraction contract tests.

These tests exercise ``analysis.orchestration.result_builder`` directly with
fixture dicts and injected callables.  No network access, no V2 monkey-patch
and no artifact writing is involved, so the assembly contract can be verified
in isolation.

Covered: output field names/values, macro north-scope enrichment, scoring
breakdown wiring, and section passthrough.  Written as ``unittest.TestCase`` so
the file is collected by both ``unittest discover`` and pytest.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.orchestration.result_builder import (  # noqa: E402
    apply_north_scope,
    apply_scoring_breakdown,
    build_result_v3,
)


def _base_result(**overrides):
    """Minimal V2 result shaped like the real contract."""
    data = {
        "code": "600693",
        "name": "东百集团",
        "quote": {"price": 12.34, "change_pct": 1.2},
        "valuation": {"pe": 18.5, "pb": 1.4},
        "score": {"total": 55, "factors": {"trend": 1}},
        "chip_data": {"peak_price": 12.1, "kline": []},
        "blocks": [{"name": "钴", "pct": 3.0}],
        "fund": {"main_net": 100},
        "valuation_hist": {"pe_percentile_3y": 42.0},
        "lockup": {"items": []},
        "dragon": {"active": 1},
        "macro": {"hsgt": {"total_yi": 12.5, "latest_hgt_yi": 5.0}},
        "sw_data": {"industry": "商贸零售"},
        "advice": "持有",
        "emoji": "🟡",
        "detail": "综合评分 55 分",
    }
    data.update(overrides)
    return data


def _fetched(**overrides):
    data = {
        "announcements": {"list": [1]},
        "finance": {"pe_ttm": 18.5},
        "news": {"items": []},
        "research": {"list": []},
        "margin": {"rz": 100},
        "peers": [{"code": "600094"}],
        "fund_daily5": {"klines": []},
        "margin_hist": {"rows": []},
    }
    data.update(overrides)
    return data


def _build(**overrides):
    kwargs = {
        "code": "600693",
        "name": "东百集团",
        "base_result": _base_result(),
        "fetched": _fetched(),
        "margin": {"rz": 100},
        "plan": {"entry_low": 11.8, "tp1": 13.2, "stop_loss": 11.1},
        "three_levels": {"support": 11.9, "resistance": 13.4, "stop_loss": 11.0},
        "good_signals": ["趋势向上"],
        "bad_signals": [],
        "run_log": {"sources": {}, "total_sec": 3},
        "sections_data": {"irm": {"label": "机构调研"}},
        "now_fn": lambda: datetime(2026, 10, 2, 14, 30),
    }
    kwargs.update(overrides)
    return build_result_v3(**kwargs)


class ResultFieldContractTest(unittest.TestCase):
    def test_top_level_identity_and_quote_fields(self):
        result = _build()

        self.assertEqual(result["code"], "600693")
        self.assertEqual(result["name"], "东百集团")
        self.assertEqual(result["quote"]["price"], 12.34)
        self.assertEqual(result["valuation"]["pe"], 18.5)
        self.assertEqual(result["chip_data"]["peak_price"], 12.1)
        self.assertEqual(result["report_date"], "2026-10-02")

    def test_optional_base_fields_default_to_empty_containers(self):
        base = _base_result()
        for key in ("blocks", "fund", "valuation_hist", "lockup", "dragon", "sw_data"):
            base.pop(key)
        base.pop("macro")

        result = _build(base_result=base)

        self.assertEqual(result["blocks"], [])
        self.assertEqual(result["fund"], {})
        self.assertEqual(result["valuation_hist"], {})
        self.assertEqual(result["lockup"], {})
        self.assertEqual(result["dragon"], {})
        self.assertEqual(result["sw_data"], {})
        self.assertEqual(result["macro"], {})

    def test_fetcher_and_supplement_fields_pass_through(self):
        result = _build()

        self.assertEqual(result["announcements"], {"list": [1]})
        self.assertEqual(result["finance"], {"pe_ttm": 18.5})
        self.assertEqual(result["news"], {"items": []})
        self.assertEqual(result["research"], {"list": []})
        self.assertEqual(result["margin"], {"rz": 100})
        self.assertEqual(result["peers"], [{"code": "600094"}])
        self.assertEqual(result["fund_daily5"], {"klines": []})
        self.assertEqual(result["margin_hist"], {"rows": []})

    def test_score_advice_emoji_detail_plan_and_levels(self):
        result = _build()

        self.assertEqual(result["score"]["total"], 55)
        self.assertEqual(result["advice"], "持有")
        self.assertEqual(result["emoji"], "🟡")
        self.assertEqual(result["detail"], "综合评分 55 分")
        self.assertEqual(result["trading_plan"]["entry_low"], 11.8)
        self.assertEqual(result["three_levels"]["support"], 11.9)
        self.assertEqual(result["signals"], {"good": ["趋势向上"], "bad": []})

    def test_run_log_is_passed_through_by_reference(self):
        run_log = {"sources": {}, "total_sec": 3}

        result = _build(run_log=run_log)

        self.assertIs(result["run_log"], run_log)

    def test_name_falls_back_to_argument_when_base_name_missing(self):
        result = _build(base_result=_base_result(name=""), name="备用名")

        self.assertEqual(result["name"], "备用名")

    def test_name_uses_base_name_when_present(self):
        result = _build(name="备用名")

        self.assertEqual(result["name"], "东百集团")

    def test_plan_may_be_none(self):
        result = _build(plan=None, three_levels=None)

        self.assertIsNone(result["trading_plan"])
        self.assertIsNone(result["three_levels"])


class SectionPassthroughTest(unittest.TestCase):
    def test_enabled_section_becomes_top_level_key(self):
        result = _build(sections_data={"irm": {"label": "机构调研"}})

        self.assertEqual(result["irm"], {"label": "机构调研"})

    def test_multiple_sections_pass_through(self):
        result = _build(
            sections_data={
                "irm": {"label": "机构调研"},
                "holders": {"label": "股东结构"},
            }
        )

        self.assertEqual(result["irm"], {"label": "机构调研"})
        self.assertEqual(result["holders"], {"label": "股东结构"})

    def test_empty_sections_data_adds_no_extra_keys(self):
        result = _build(sections_data={})

        self.assertNotIn("irm", result)
        self.assertIn("code", result)

    def test_section_keys_splat_after_explicit_fields(self):
        """sections_data is splatted last, so it still wins on key collision."""
        result = _build(sections_data={"score": {"sentinel": True}})

        self.assertEqual(result["score"], {"sentinel": True})


class NorthScopeEnrichmentTest(unittest.TestCase):
    def test_scope_written_into_macro_in_place(self):
        result = _build()
        macro = result["macro"]

        scope, label = apply_north_scope(result, lambda north: ("market", "全市场北向资金"))

        self.assertEqual(scope, "market")
        self.assertEqual(label, "全市场北向资金")
        self.assertEqual(result["macro"]["north_scope"], "market")
        self.assertEqual(result["macro"]["north_label"], "全市场北向资金")
        self.assertIs(result["macro"], macro, "must mutate in place, not replace")

    def test_classifier_receives_macro_hsgt_subtree(self):
        result = _build()
        seen = {}

        def capture(north):
            seen["north"] = north
            return ("market", "label")

        apply_north_scope(result, capture)

        self.assertEqual(seen["north"], {"total_yi": 12.5, "latest_hgt_yi": 5.0})

    def test_missing_hsgt_yields_empty_payload(self):
        result = _build(base_result=_base_result(macro={}))
        seen = {}

        def capture(north):
            seen["north"] = north
            return ("unknown", "北向数据缺失")

        scope, label = apply_north_scope(result, capture)

        self.assertEqual(seen["north"], {})
        self.assertEqual(scope, "unknown")
        self.assertEqual(label, "北向数据缺失")
        self.assertEqual(result["macro"]["north_scope"], "unknown")

    def test_existing_macro_keys_are_preserved(self):
        result = _build(base_result=_base_result(macro={"hsgt": {"total_yi": 1.0}, "hot_stocks": []}))

        apply_north_scope(result, lambda north: ("stock", "个股北向"))

        self.assertEqual(result["macro"]["hot_stocks"], [])
        self.assertEqual(result["macro"]["hsgt"], {"total_yi": 1.0})

    def test_scoping_does_not_touch_plan_or_three_levels(self):
        result = _build()

        apply_north_scope(result, lambda north: ("mixed", "混合口径"))

        self.assertEqual(result["trading_plan"]["entry_low"], 11.8)
        self.assertEqual(result["three_levels"]["support"], 11.9)


class ScoringBreakdownWiringTest(unittest.TestCase):
    def test_breakdown_attached_and_returned(self):
        result = _build()
        breakdown = {"total": {"score": 55, "max": 100}}

        returned = apply_scoring_breakdown(result, lambda score: breakdown)

        self.assertIs(returned, breakdown)
        self.assertIs(result["scoring_breakdown"], breakdown)

    def test_breakdown_receives_v2_score_object(self):
        result = _build()
        seen = {}

        def capture(score):
            seen["score"] = score
            return {}

        apply_scoring_breakdown(result, capture)

        self.assertIs(seen["score"], result["score"])
        self.assertEqual(seen["score"]["total"], 55)

    def test_real_scoring_builder_produces_five_dimensions(self):
        """Wire the real analytics builder, not a stub, to guard the contract."""
        from analysis.analytics.scoring import _build_scoring_breakdown

        result = _build()
        breakdown = apply_scoring_breakdown(result, _build_scoring_breakdown)

        for key in ("tech", "capital", "valuation", "sentiment", "risk", "total"):
            self.assertIn(key, breakdown)
            self.assertIn("score", breakdown[key])
            self.assertIn("max", breakdown[key])

    def test_enrichment_after_assembly_matches_pipeline_order(self):
        result = _build()
        apply_north_scope(result, lambda north: ("market", "全市场北向资金"))
        apply_scoring_breakdown(result, lambda score: {"total": {"score": 55, "max": 100}})

        self.assertEqual(result["macro"]["north_scope"], "market")
        self.assertEqual(result["scoring_breakdown"]["total"]["max"], 100)
        self.assertNotIn("north_scope", result["quote"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
