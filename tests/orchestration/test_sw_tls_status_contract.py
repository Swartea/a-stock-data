from analysis.orchestration.source_status import (
    SourceStatusRecorder,
    _record_sw_tls_failure,
)


def _run(base_result, recorder=None, run_log=None, source_desc=None):
    recorder = recorder or SourceStatusRecorder()
    run_log = run_log or {"fallback_chain": []}
    time_calls = []
    fmt_calls = []

    def time_fn():
        time_calls.append("time")
        return 123.456

    def fmt_time(value):
        fmt_calls.append(value)
        return "12:34:56"

    _record_sw_tls_failure(
        base_result,
        recorder,
        run_log,
        source_desc or {"申万分类": "申万行业稳定性"},
        fmt_time,
        time_fn,
    )
    return recorder, run_log, time_calls, fmt_calls


def test_non_error_sw_shapes_are_noop_and_do_not_read_clock():
    for base_result in (
        {},
        {"sw_data": None},
        {"sw_data": {}},
        {"sw_data": []},
        {"sw_data": "error"},
        {"sw_data": {"industry": "银行"}},
    ):
        recorder, run_log, time_calls, fmt_calls = _run(base_result)
        assert recorder.snapshot() == {}
        assert run_log == {"fallback_chain": []}
        assert time_calls == []
        assert fmt_calls == []


def test_error_key_triggers_even_when_error_value_is_none():
    recorder, run_log, time_calls, fmt_calls = _run({"sw_data": {"error": None}})

    assert recorder["申万分类"] == {
        "at": "12:34:56",
        "ms": 0,
        "status": "error:None (需 pip install -U certifi), 0ms",
        "detail": "申万行业稳定性",
        "tls_recommendation": "pip install -U certifi",
    }
    assert run_log["fallback_chain"] == [
        "申万分类: SSL 直连失败 (None) — 不再 verify=False 兜底 (§5); "
        "修复: pip install -U certifi  (申万行业因子按 v2 默认中性计)"
    ]
    assert run_log["tls_recommendations"] == [
        {
            "host": "swsresearch.com",
            "fix": "pip install -U certifi",
            "applies_to": ["申万分类"],
        }
    ]
    assert time_calls == ["time"]
    assert fmt_calls == [123.456]


def test_error_text_uses_current_eighty_forty_four_and_forty_char_truncation():
    error_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4
    recorder, run_log, _, _ = _run({"sw_data": {"error": error_text}})

    sw_err = error_text[:80]
    assert recorder["申万分类"]["status"] == (
        f"error:{sw_err[:40]} (需 pip install -U certifi), 0ms"
    )
    assert run_log["fallback_chain"] == [
        f"申万分类: SSL 直连失败 ({sw_err[:44]}) — 不再 verify=False 兜底 (§5); "
        "修复: pip install -U certifi  (申万行业因子按 v2 默认中性计)"
    ]


def test_existing_meta_keeps_at_and_extra_fields_but_overwrites_status_fields():
    recorder = SourceStatusRecorder()
    recorder["申万分类"] = {
        "at": "09:30:00",
        "ms": 88,
        "status": "old-status",
        "detail": "old-detail",
        "tls_recommendation": "old-fix",
        "extra": "keep",
    }

    recorder, _, time_calls, fmt_calls = _run(
        {"sw_data": {"error": "ssl boom"}},
        recorder=recorder,
    )

    assert recorder["申万分类"] == {
        "at": "09:30:00",
        "ms": 0,
        "status": "error:ssl boom (需 pip install -U certifi), 0ms",
        "detail": "申万行业稳定性",
        "tls_recommendation": "pip install -U certifi",
        "extra": "keep",
    }
    # Python evaluates setdefault's default argument even when the key exists.
    assert time_calls == ["time"]
    assert fmt_calls == [123.456]


def test_missing_meta_seeds_only_at_before_current_fields_are_added():
    recorder, _, _, _ = _run({"sw_data": {"error": "ssl"}})

    assert recorder["申万分类"]["at"] == "12:34:56"
    assert set(recorder["申万分类"]) == {
        "at",
        "ms",
        "status",
        "detail",
        "tls_recommendation",
    }


def test_existing_tls_recommendations_are_appended_not_replaced():
    existing = {
        "host": "example.com",
        "fix": "existing",
        "applies_to": ["其他源"],
    }
    run_log = {"fallback_chain": ["existing fallback"], "tls_recommendations": [existing]}

    _, run_log, _, _ = _run(
        {"sw_data": {"error": "ssl"}},
        run_log=run_log,
    )

    assert run_log["fallback_chain"][0] == "existing fallback"
    assert len(run_log["fallback_chain"]) == 2
    assert run_log["tls_recommendations"][0] is existing
    assert run_log["tls_recommendations"][1] == {
        "host": "swsresearch.com",
        "fix": "pip install -U certifi",
        "applies_to": ["申万分类"],
    }


def test_source_description_uses_current_default_when_label_missing():
    recorder, _, _, _ = _run(
        {"sw_data": {"error": "ssl"}},
        source_desc={"其他源": "unused"},
    )

    assert recorder["申万分类"]["detail"] == "申万行业稳定性"


def test_source_description_uses_supplied_label_description_when_present():
    recorder, _, _, _ = _run(
        {"sw_data": {"error": "ssl"}},
        source_desc={"申万分类": "custom description"},
    )

    assert recorder["申万分类"]["detail"] == "custom description"
