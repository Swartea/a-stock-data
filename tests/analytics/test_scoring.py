"""Phase 1D scoring migration contract tests.

The staged analytics implementation must stay byte-for-byte equivalent at the
returned-data level to the current ``analysis.pipeline`` implementation before
pipeline cutover.
"""

import pytest

from analysis.analytics.scoring import (
    _SCORING_BREAKDOWN_GROUPS,
    _SCORE_DIM_MAX,
    _build_scoring_breakdown as staged_build_scoring_breakdown,
)
from analysis.pipeline import _build_scoring_breakdown as pipeline_build_scoring_breakdown


@pytest.mark.parametrize(
    "score",
    [
        {},
        {
            "trend": 1,
            "valuation": 2,
            "valuation_pctile": 3,
            "capital": 7,
            "momentum": 1,
            "sentiment": 4,
            "risk": 4,
            "chip": 4,
            "sw_stability": 5,
            "dragon": 3,
            "total": 34,
        },
        {
            "trend": 8,
            "valuation": 10,
            "valuation_pctile": 6,
            "capital": 6,
            "momentum": 3,
            "sentiment": 2,
            "risk": 8,
            "chip": 1,
            "sw_stability": 3,
            "dragon": 6,
            "total": 53,
        },
        {"trend": 99, "valuation": -3, "total": 50},
        {"capital": "bad", "dragon": 3, "total": "bad"},
        {"trend": None, "momentum": 4, "chip": 2, "total": None},
        None,
    ],
)
def test_staged_scoring_matches_pipeline(score):
    assert staged_build_scoring_breakdown(score) == pipeline_build_scoring_breakdown(score)


def test_scoring_groups_contract_is_unchanged():
    assert _SCORING_BREAKDOWN_GROUPS == (
        ("tech", "技术", ("trend", "momentum", "chip")),
        ("capital", "资金", ("capital", "dragon")),
        ("valuation", "估值", ("valuation", "valuation_pctile", "sw_stability")),
        ("sentiment", "情绪", ("sentiment",)),
        ("risk", "风险", ("risk",)),
    )


def test_score_dimension_max_contract_sums_to_100():
    assert _SCORE_DIM_MAX == {
        "trend": 12,
        "valuation": 15,
        "valuation_pctile": 8,
        "capital": 15,
        "momentum": 8,
        "sentiment": 8,
        "risk": 10,
        "chip": 8,
        "sw_stability": 6,
        "dragon": 10,
    }
    assert sum(_SCORE_DIM_MAX.values()) == 100
