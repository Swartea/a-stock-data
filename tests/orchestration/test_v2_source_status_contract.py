from analysis.orchestration.source_status import (
    SourceStatusRecorder,
    _record_v2_source_statuses,
)

FIELD_OF = {
    "行情": "quote",
    "估值一致预期": "valuation",
    "概念板块": "blocks",
    "当日资金流": "fund",
    "宏观底色": "macro",
}

SOURCE_DESC = {
    "行情": "腾讯实时行情",
    "估值一致预期": "估值与一致预期",
    "概念板块": "概念板块",
    "当日资金流": "当日资金流",
    "宏观底色": "宏观底色",
}


def _run(results, recorder=None, field_of=None, source_desc=None):
    recorder = recorder or SourceStatusRecorder()
    run_log = {"sources": {}, "source_meta": {}, "fallback_chain": []}
    _record_v2_source_statuses(
        results,
        recorder,
        run_log,
        field_of or FIELD_OF,
        source_desc or SOURCE_DESC,
    )
    return recorder, run_log


def test_generic_error_has_priority_and_truncates_message_to_sixty_characters():
    recorder = SourceStatusRecorder()
    recorder["估值一致预期"] = {"ms": 17, "at": "12:34:56"}
    message = "x" * 80

    recorder, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {"error": message},
            "blocks": [{"name": "AI"}],
            "fund": {"klines": [1]},
            "macro": {"hsgt": {"north": 1}},
        },
        recorder,
    )

    expected = f"error:{'x' * 60}, 17ms"
    assert run_log["sources"]["估值一致预期"] == expected
    assert run_log["source_meta"]["估值一致预期"] == {
        "ms": 17,
        "at": "12:34:56",
        "status": expected,
        "detail": "估值与一致预期",
    }
    assert run_log["fallback_chain"] == [f"估值一致预期: {expected}"]
    assert recorder["估值一致预期"] == {"ms": 17, "at": "12:34:56"}


def test_empty_quote_is_error_and_missing_timing_uses_question_mark():
    _, run_log = _run(
        {
            "quote": None,
            "valuation": {},
            "blocks": [{"name": "AI"}],
            "fund": {"klines": [1]},
            "macro": {"industries": ["bank"]},
        }
    )

    status = "error:行情为空, ?ms"
    assert run_log["sources"]["行情"] == status
    assert run_log["source_meta"]["行情"] == {
        "status": status,
        "detail": "腾讯实时行情",
    }
    assert run_log["fallback_chain"] == [f"行情: {status}"]


def test_concept_block_embedded_error_beats_normal_list_handling():
    recorder = SourceStatusRecorder()
    recorder["概念板块"] = {"ms": 33}

    _, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {},
            "blocks": [{"name": "AI"}, {"error": "blocked"}],
            "fund": {"klines": [1]},
            "macro": {"hot_stocks": ["600000"]},
        },
        recorder,
    )

    status = "error:接口异常, 33ms"
    assert run_log["sources"]["概念板块"] == status
    assert run_log["fallback_chain"] == [f"概念板块: {status}"]


def test_empty_concept_blocks_are_fallback_not_error():
    recorder = SourceStatusRecorder()
    recorder["概念板块"] = {"ms": 21}

    _, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {},
            "blocks": [],
            "fund": {"klines": [1]},
            "macro": {"hsgt": {"north": 1}},
        },
        recorder,
    )

    status = "fallback:接口返回0条(可能风控), 21ms"
    assert run_log["sources"]["概念板块"] == status
    assert run_log["fallback_chain"] == [f"概念板块: {status}"]


def test_fund_dict_without_klines_is_fallback():
    recorder = SourceStatusRecorder()
    recorder["当日资金流"] = {"ms": 8}

    _, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {},
            "blocks": [{"name": "AI"}],
            "fund": {"main": 123},
            "macro": {"hsgt": {"north": 1}},
        },
        recorder,
    )

    status = "fallback:当日无成交或分钟数据, 8ms"
    assert run_log["sources"]["当日资金流"] == status
    assert run_log["fallback_chain"] == [f"当日资金流: {status}"]


def test_macro_dict_with_all_three_subsources_empty_is_error():
    recorder = SourceStatusRecorder()
    recorder["宏观底色"] = {"ms": 44}

    _, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {},
            "blocks": [{"name": "AI"}],
            "fund": {"klines": [1]},
            "macro": {"hsgt": {}, "industries": [], "hot_stocks": None},
        },
        recorder,
    )

    status = "error:北向/行业/强势股子源全空, 44ms"
    assert run_log["sources"]["宏观底色"] == status
    assert run_log["fallback_chain"] == [f"宏观底色: {status}"]


def test_ok_projection_preserves_extra_meta_without_mutating_recorder():
    recorder = SourceStatusRecorder()
    recorder["行情"] = {
        "ms": 5,
        "at": "09:30:00",
        "tls_recommendation": "keep-extra",
    }

    recorder, run_log = _run(
        {
            "quote": {"price": 10},
            "valuation": {},
            "blocks": [{"name": "AI"}],
            "fund": {"klines": [1]},
            "macro": {"industries": ["bank"]},
        },
        recorder,
    )

    assert run_log["sources"]["行情"] == "ok, 5ms"
    assert run_log["source_meta"]["行情"] == {
        "ms": 5,
        "at": "09:30:00",
        "tls_recommendation": "keep-extra",
        "status": "ok, 5ms",
        "detail": "腾讯实时行情",
    }
    assert recorder["行情"] == {
        "ms": 5,
        "at": "09:30:00",
        "tls_recommendation": "keep-extra",
    }
    assert run_log["fallback_chain"] == []


def test_non_ok_fallback_chain_follows_field_mapping_order():
    field_of = {
        "概念板块": "blocks",
        "行情": "quote",
        "当日资金流": "fund",
    }
    source_desc = {label: label for label in field_of}

    _, run_log = _run(
        {"blocks": [], "quote": None, "fund": {}},
        field_of=field_of,
        source_desc=source_desc,
    )

    assert list(run_log["sources"]) == ["概念板块", "行情", "当日资金流"]
    assert run_log["fallback_chain"] == [
        "概念板块: fallback:接口返回0条(可能风控), ?ms",
        "行情: error:行情为空, ?ms",
        "当日资金流: fallback:当日无成交或分钟数据, ?ms",
    ]


def test_source_description_falls_back_to_label():
    field_of = {"自定义源": "custom"}
    recorder = SourceStatusRecorder()

    _, run_log = _run(
        {"custom": "value"},
        recorder,
        field_of=field_of,
        source_desc={},
    )

    assert run_log["source_meta"]["自定义源"] == {
        "status": "ok, ?ms",
        "detail": "自定义源",
    }
