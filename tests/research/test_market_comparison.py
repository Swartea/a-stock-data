"""Offline unit tests for the pure cross-market comparison computation.

No network, no provider access, no fixtures on disk: every case is a pure
in-process check of ``analysis.research.market_comparison`` against the
existing ``analysis/research`` identity contracts.
"""

from __future__ import annotations

import json
import math

import pytest

from analysis.research import market_comparison
from analysis.research.market_comparison import (
    BASE_VALUE,
    COMPARISON_PRODUCT_NAME,
    build_comparison,
    normalize_close_series,
)

CSI_300 = "cn.index.csi300"
CSI_300_ALIAS = "csi.300"
HSTECH = "hk.index.hang_seng.hstech"
NASDAQ = "us.index.nasdaq.composite"
SP500 = "us.index.sp_dji.sp500"


def _bars(pairs: list[tuple[str, float]]) -> list[dict[str, object]]:
    return [({"date": item[0], "close": item[1]} if isinstance(item, tuple) else item) for item in pairs]


def _payload(index_id: str, pairs: list[tuple[str, float]], **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "index_id": index_id,
        "market": "cn",
        "source": "tencent.daily_k",
        "bars": _bars(pairs),
    }
    payload.update(extra)
    return payload


def _point(result: dict, index_id: str, day: str) -> dict:
    series = next(item for item in result["series"] if item["index_id"] == index_id)
    position = result["dates"].index(day)
    return {
        "close": series["close"][position],
        "normalized100": series["normalized100"][position],
        "cumulative_return_pct": series["cumulative_return_pct"][position],
    }


# ---------------------------------------------------------------------------
# contract surface
# ---------------------------------------------------------------------------


def test_product_name_is_swartea_market_research():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["product"] == "Swartea Market Research"
    assert COMPARISON_PRODUCT_NAME == "Swartea Market Research"


def test_result_is_json_serializable_and_round_trips():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    encoded = json.dumps(result, ensure_ascii=False)
    assert json.loads(encoded) == result


def test_result_exposes_the_documented_top_level_keys():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert set(result) == {
        "product",
        "status",
        "error",
        "base_date",
        "base_value",
        "dates",
        "series",
        "excluded",
        "notes",
        "calendar_status",
    }
    assert result["status"] == "ok"
    assert result["error"] is None


def test_module_does_not_import_a_provider_transport():
    """The comparison math must stay offline: no requests client in the module."""

    assert "requests" not in vars(market_comparison)
    assert market_comparison.__doc__ is not None


def test_notes_state_the_local_date_and_price_return_limitations():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    notes = " ".join(result["notes"])
    assert "本地交易日期" in notes
    assert "不代表同一时间点的同步行情" in notes
    assert "不含分红派息等总回报成分" in notes
    assert "未做汇率调整" in notes
    assert "不做插值" in notes


def test_calendar_status_stays_unknown_without_evidence():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["calendar_status"] == "unknown"


# ---------------------------------------------------------------------------
# base selection and normalization math
# ---------------------------------------------------------------------------


def test_base_is_the_earliest_common_valid_date_and_is_100():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [("2026-01-05", 4000.0), ("2026-01-06", 4100.0), ("2026-01-07", 4200.0)],
            ),
            _payload(
                HSTECH,
                [("2026-01-06", 3000.0), ("2026-01-07", 3100.0), ("2026-01-08", 3200.0)],
            ),
        ]
    )

    assert result["status"] == "ok"
    assert result["base_date"] == "2026-01-06"
    assert result["base_value"] == BASE_VALUE == 100.0

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    hstech = next(item for item in result["series"] if item["index_id"] == HSTECH)
    assert csi["base_close"] == 4100.0
    assert hstech["base_close"] == 3000.0

    # both series are 100 on the shared base date
    assert _point(result, CSI_300, "2026-01-06")["normalized100"] == 100.0
    assert _point(result, HSTECH, "2026-01-06")["normalized100"] == 100.0


def test_cumulative_return_percent_matches_the_contract_formula():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 110.0)]),
            _payload(HSTECH, [("2026-01-05", 50.0), ("2026-01-06", 49.0)]),
        ]
    )

    csi = _point(result, CSI_300, "2026-01-06")
    assert csi["normalized100"] == pytest.approx(110.0)
    assert csi["cumulative_return_pct"] == pytest.approx(10.0)

    hstech = _point(result, HSTECH, "2026-01-06")
    assert hstech["normalized100"] == pytest.approx(98.0)
    assert hstech["cumulative_return_pct"] == pytest.approx(-2.0)


def test_every_compared_series_shares_one_base_date():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    assert {item["index_id"] for item in result["series"]} == {CSI_300, HSTECH, NASDAQ}
    for item in result["series"]:
        position = result["dates"].index(result["base_date"])
        assert item["normalized100"][position] == 100.0


def test_four_indices_are_supported():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
            _payload(SP500, [("2026-01-05", 400.0), ("2026-01-06", 404.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert len(result["series"]) == 4


def test_five_indices_are_rejected_with_too_many_indices():
    payloads = [
        _payload(index_id, [("2026-01-05", 100.0), ("2026-01-06", 101.0)])
        for index_id in (CSI_300, HSTECH, NASDAQ, SP500, "cn.index.sh_comp")
    ]

    result = build_comparison(payloads)

    assert result["status"] == "error"
    assert result["error"]["code"] == "too_many_indices"
    assert result["series"] == []


def test_one_index_is_rejected_with_too_few_indices():
    result = build_comparison([_payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)])])

    assert result["status"] == "error"
    assert result["error"]["code"] == "too_few_indices"


# ---------------------------------------------------------------------------
# union axis and gaps
# ---------------------------------------------------------------------------


def test_union_axis_keeps_gaps_without_forward_fill():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [("2026-01-05", 100.0), ("2026-01-07", 102.0), ("2026-01-08", 103.0)],
            ),
            _payload(
                HSTECH,
                [("2026-01-05", 200.0), ("2026-01-06", 201.0), ("2026-01-08", 203.0)],
            ),
        ]
    )

    assert result["dates"] == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]

    # 2026-01-06 is missing for the A-share series -> gap, not a carried value
    assert _point(result, CSI_300, "2026-01-06")["normalized100"] is None
    assert _point(result, CSI_300, "2026-01-06")["close"] is None
    assert _point(result, HSTECH, "2026-01-06")["normalized100"] is not None

    # 2026-01-07 is missing for the HK series -> gap
    assert _point(result, HSTECH, "2026-01-07")["normalized100"] is None
    assert _point(result, HSTECH, "2026-01-07")["cumulative_return_pct"] is None


def test_no_interpolation_is_invented_for_a_missing_session():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-08", 110.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-08", 210.0)]),
        ]
    )

    assert result["dates"] == ["2026-01-05", "2026-01-08"]
    assert _point(result, CSI_300, "2026-01-08")["normalized100"] == pytest.approx(110.0)


def test_series_value_lists_are_aligned_with_the_union_axis():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-07", 102.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 201.0)]),
        ]
    )

    for item in result["series"]:
        assert len(item["close"]) == len(result["dates"])
        assert len(item["normalized100"]) == len(result["dates"])
        assert len(item["cumulative_return_pct"]) == len(result["dates"])


# ---------------------------------------------------------------------------
# explicit no-common-base case
# ---------------------------------------------------------------------------


def test_disjoint_date_ranges_report_no_common_base():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-02-02", 200.0), ("2026-02-03", 202.0)]),
        ]
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "no_common_base"
    assert result["base_date"] is None
    assert result["series"] == []
    assert {item["reason"] for item in result["excluded"]} == {"no_common_base"}


def test_series_without_the_base_date_is_excluded_with_its_own_reason():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
            _payload(NASDAQ, [("2026-03-02", 300.0), ("2026-03-03", 303.0)]),
        ]
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "no_common_base"
    assert result["series"] == []

    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded[NASDAQ]["reason"] == "no_common_base"
    assert "2026-03-02" in excluded[NASDAQ]["detail"]


# ---------------------------------------------------------------------------
# invalid, non-finite and non-positive prices
# ---------------------------------------------------------------------------


def test_non_positive_and_non_finite_closes_are_dropped_and_reported():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [
                    ("2026-01-05", 100.0),
                    ("2026-01-06", 0.0),
                    ("2026-01-07", float("nan")),
                    ("2026-01-08", 103.0),
                ],
            ),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 201.0), ("2026-01-07", 202.0), ("2026-01-08", 203.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert result["base_date"] == "2026-01-05"
    assert result["dates"] == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    codes = {issue["code"] for issue in csi["issues"]}
    assert "invalid_close" in codes
    assert _point(result, CSI_300, "2026-01-06")["normalized100"] is None
    assert _point(result, CSI_300, "2026-01-07")["normalized100"] is None
    assert _point(result, CSI_300, "2026-01-08")["normalized100"] == pytest.approx(103.0)


def test_boolean_close_is_not_treated_as_a_price():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", True), ("2026-01-07", 102.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert _point(result, CSI_300, "2026-01-06")["normalized100"] is None


def test_series_without_any_valid_close_is_excluded_with_a_reason():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 0.0), ("2026-01-06", -5.0)]),
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert {item["index_id"] for item in result["series"]} == {CSI_300, NASDAQ}

    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded[HSTECH]["reason"] == "no_valid_rows"


# ---------------------------------------------------------------------------
# duplicate and unsorted dates
# ---------------------------------------------------------------------------


def test_duplicate_dates_are_excluded_instead_of_picking_an_arbitrary_winner():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [
                    {"date": "2026-01-05", "close": 100.0},
                    {"date": "2026-01-05", "close": 999.0},
                    {"date": "2026-01-06", "close": 101.0},
                    {"date": "2026-01-07", "close": 102.0},
                ],
            ),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert result["base_date"] == "2026-01-06"

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    assert "duplicate_date" in {issue["code"] for issue in csi["issues"]}
    assert _point(result, CSI_300, "2026-01-05")["normalized100"] is None
    assert _point(result, CSI_300, "2026-01-06")["normalized100"] == pytest.approx(100.0)


def test_duplicate_date_handling_is_deterministic_regardless_of_row_order():
    rows = [
        {"date": "2026-01-05", "close": 100.0},
        {"date": "2026-01-05", "close": 999.0},
        {"date": "2026-01-06", "close": 101.0},
    ]
    hstech = _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)])

    first = build_comparison([_payload(CSI_300, []) | {"bars": rows}, hstech])
    second = build_comparison([_payload(CSI_300, []) | {"bars": list(reversed(rows))}, hstech])

    assert first == second


def test_unsorted_rows_are_sorted_deterministically():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [("2026-01-08", 103.0), ("2026-01-05", 100.0), ("2026-01-06", 101.0)],
            ),
            _payload(HSTECH, [("2026-01-08", 203.0), ("2026-01-05", 200.0)]),
        ]
    )

    assert result["dates"] == ["2026-01-05", "2026-01-06", "2026-01-08"]
    assert result["base_date"] == "2026-01-05"


# ---------------------------------------------------------------------------
# malformed rows
# ---------------------------------------------------------------------------


def test_malformed_rows_are_counted_and_do_not_break_the_comparison():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [
                    {"date": "2026-01-05", "close": 100.0},
                    {"date": "20260106", "close": 101.0},
                    {"date": "2026-01-07", "close": "abc"},
                    {"date": "2026-02-30", "close": 102.0},
                    "not-a-row",
                    {"close": 103.0},
                    {"date": "2026-01-08", "close": 104.0},
                ],
            ),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-08", 204.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert result["dates"] == ["2026-01-05", "2026-01-08"]

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    assert "invalid_row" in {issue["code"] for issue in csi["issues"]}


def test_non_mapping_payload_is_excluded_with_a_reason():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            "not-a-payload",
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert len(result["series"]) == 2
    excluded = {item["reason"] for item in result["excluded"]}
    assert "invalid_payload" in excluded


# ---------------------------------------------------------------------------
# insufficient history
# ---------------------------------------------------------------------------


def test_single_day_series_is_reported_as_insufficient():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0)]),
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert {item["index_id"] for item in result["series"]} == {CSI_300, NASDAQ}

    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded[HSTECH]["reason"] == "insufficient_dates"
    assert "2 valid dates" in excluded[HSTECH]["detail"]


def test_fewer_than_two_usable_series_is_an_explicit_error():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0)]),
        ]
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "insufficient_usable_indices"
    assert result["series"] == []
    assert result["excluded"][0]["reason"] == "insufficient_dates"


# ---------------------------------------------------------------------------
# partial index failure
# ---------------------------------------------------------------------------


def test_partial_index_failure_keeps_the_remaining_comparison_usable():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            {
                "index_id": HSTECH,
                "status": "error",
                "error": {"code": "NET_TIMEOUT", "message": "provider timeout"},
            },
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert {item["index_id"] for item in result["series"]} == {CSI_300, NASDAQ}

    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded[HSTECH]["reason"] == "index_unavailable"
    assert "provider timeout" in excluded[HSTECH]["detail"]


def test_empty_status_is_reported_as_unavailable():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            {"index_id": HSTECH, "status": "empty", "data": []},
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert {item["reason"] for item in result["excluded"]} == {"index_unavailable"}


def test_missing_bars_are_reported_as_no_bars():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            {"index_id": HSTECH},
            _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
        ]
    )

    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded[HSTECH]["reason"] == "no_bars"


# ---------------------------------------------------------------------------
# canonical identity handling
# ---------------------------------------------------------------------------


def test_alias_is_normalized_through_the_existing_identity_layer():
    result = build_comparison(
        [
            _payload(CSI_300_ALIAS, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert [item["index_id"] for item in result["series"]] == [CSI_300, HSTECH]
    assert result["excluded"] == []


def test_duplicate_canonical_index_is_deduplicated_with_a_reason():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(CSI_300_ALIAS, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    assert [item["index_id"] for item in result["series"]] == [CSI_300, HSTECH]
    assert len(result["excluded"]) == 1
    assert result["excluded"][0]["reason"] == "duplicate_index"
    assert result["excluded"][0]["index_id"] == CSI_300


def test_unknown_index_is_excluded_with_its_own_reason():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload("us.index.nikkei225", [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded["us.index.nikkei225"]["reason"] == "unknown_index"


def test_non_canonical_casing_is_rejected_as_an_invalid_index_id():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload("CN.INDEX.CSI300", [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    assert result["status"] == "ok"
    excluded = {item["index_id"]: item for item in result["excluded"]}
    assert excluded["CN.INDEX.CSI300"]["reason"] == "invalid_index_id"


def test_display_name_and_market_come_from_the_registry():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)], name="错误名"),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)], market="xx"),
        ]
    )

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    hstech = next(item for item in result["series"] if item["index_id"] == HSTECH)
    assert csi["name"] == "沪深300"
    assert csi["market"] == "cn"
    assert hstech["name"] == "恒生科技指数"
    assert hstech["market"] == "hk"


def test_source_is_echoed_back_for_provenance():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [("2026-01-05", 100.0), ("2026-01-06", 101.0)],
                source="baostock.daily_k",
            ),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        ]
    )

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    assert csi["source"] == "baostock.daily_k"


def test_data_date_range_is_reported_per_series():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [("2026-01-05", 100.0), ("2026-01-07", 102.0), ("2026-01-08", 103.0)],
            ),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-08", 203.0)]),
        ]
    )

    csi = next(item for item in result["series"] if item["index_id"] == CSI_300)
    assert csi["first_date"] == "2026-01-05"
    assert csi["last_date"] == "2026-01-08"
    assert csi["data_points"] == 3


# ---------------------------------------------------------------------------
# date range handling
# ---------------------------------------------------------------------------


def test_date_range_filters_rows_before_aggregation():
    result = build_comparison(
        [
            _payload(
                CSI_300,
                [
                    ("2026-01-05", 100.0),
                    ("2026-01-06", 101.0),
                    ("2026-01-07", 102.0),
                ],
            ),
            _payload(
                HSTECH,
                [("2026-01-05", 200.0), ("2026-01-06", 201.0), ("2026-01-07", 202.0)],
            ),
        ],
        start_date="2026-01-06",
        end_date="2026-01-07",
    )

    assert result["dates"] == ["2026-01-06", "2026-01-07"]
    assert result["base_date"] == "2026-01-06"


def test_date_range_can_leave_too_few_dates_for_a_comparison():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 201.0)]),
        ],
        start_date="2026-01-06",
        end_date="2026-01-06",
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "insufficient_usable_indices"


@pytest.mark.parametrize(
    "bad_value",
    ["2026-1-5", "20260105", "2026-W02-1", "not-a-date", 20260105],
)
def test_non_strict_range_dates_are_rejected(bad_value):
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 201.0)]),
        ],
        start_date=bad_value,
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"


def test_reversed_date_range_is_rejected():
    result = build_comparison(
        [
            _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
            _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 201.0)]),
        ],
        start_date="2026-01-06",
        end_date="2026-01-05",
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"


def test_invalid_payloads_type_is_rejected():
    result = build_comparison({"index_id": CSI_300})  # type: ignore[arg-type]

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"


def test_series_accepts_the_daily_k_service_data_key():
    result = build_comparison(
        [
            {
                "index_id": CSI_300,
                "data": [{"date": "2026-01-05", "close": 100.0}, {"date": "2026-01-06", "close": 101.0}],
            },
            {
                "index_id": HSTECH,
                "data": [{"date": "2026-01-05", "close": 200.0}, {"date": "2026-01-06", "close": 201.0}],
            },
        ]
    )

    assert result["status"] == "ok"
    assert len(result["series"]) == 2


# ---------------------------------------------------------------------------
# pure helper
# ---------------------------------------------------------------------------


def test_normalize_close_series_aligns_with_the_given_axis():
    values = normalize_close_series(
        {"2026-01-05": 100.0, "2026-01-06": 110.0},
        "2026-01-05",
        axis=["2026-01-05", "2026-01-06", "2026-01-07"],
    )

    assert values["close"] == [100.0, 110.0, None]
    assert values["normalized100"] == [100.0, 110.0, None]
    assert values["cumulative_return_pct"] == [0.0, 10.0, None]


def test_normalize_close_series_rejects_an_unusable_base():
    with pytest.raises(ValueError):
        normalize_close_series({"2026-01-05": 0.0}, "2026-01-05")

    with pytest.raises(ValueError):
        normalize_close_series({"2026-01-05": 100.0}, "2026-01-06")


def test_normalize_close_series_returns_finite_values_only():
    values = normalize_close_series({"2026-01-05": 1e-300, "2026-01-06": 1e300}, "2026-01-05")

    for item in values["normalized100"]:
        assert item is None or math.isfinite(item)
    for item in values["cumulative_return_pct"]:
        assert item is None or math.isfinite(item)


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_same_input_produces_the_same_output():
    payloads = [
        _payload(CSI_300, [("2026-01-05", 100.0), ("2026-01-06", 101.0)]),
        _payload(HSTECH, [("2026-01-05", 200.0), ("2026-01-06", 202.0)]),
        _payload(NASDAQ, [("2026-01-05", 300.0), ("2026-01-06", 303.0)]),
    ]

    assert build_comparison(payloads) == build_comparison(payloads)
