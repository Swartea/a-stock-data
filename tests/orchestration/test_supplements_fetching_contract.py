from types import SimpleNamespace

from analysis.orchestration import fetching
from analysis.orchestration.source_status import SourceStatusRecorder

SRC_DESC = {
    "资金面-5日主力": "近5日主力资金",
    "两融历史": "两融方向历史",
    "同业对比": "概念同业对比",
}


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


def _run(
    monkeypatch,
    *,
    fund_fetcher=None,
    margin_fetcher=None,
    peers_fetcher=None,
    clock=None,
    recorder=None,
    blocks=None,
):
    clock = clock or FakeClock()
    recorder = recorder or SourceStatusRecorder()
    blocks = blocks if blocks is not None else [{"name": "测试概念"}]
    monkeypatch.setattr(
        fetching,
        "time",
        SimpleNamespace(time=clock.time, sleep=clock.sleep),
    )

    run_log = {
        "sources": {"existing": "ok"},
        "source_meta": {},
        "fallback_chain": [],
    }
    fetched = {
        "fund_daily5": None,
        "margin_hist": None,
        "peers": None,
    }

    fetching._fetch_supplements(
        recorder,
        run_log,
        fetched,
        SRC_DESC,
        lambda ts: f"at:{ts:.2f}",
        "600693",
        blocks,
        fund_fetcher or (lambda _code: {"fund": "ok"}),
        margin_fetcher or (lambda _code: {"margin_hist": "ok"}),
        peers_fetcher or (lambda _code, _blocks: {"peers": "ok"}),
    )
    return fetched, run_log, recorder, clock


def test_fetch_supplements_success_forwards_arguments_and_records_status(monkeypatch):
    calls = []
    blocks = [{"name": "概念A"}, {"name": "概念B"}]
    clock = FakeClock()

    def fund_fetcher(code):
        calls.append(("fund", code))
        clock.advance(0.1)
        return {"fund": 1}

    def margin_fetcher(code):
        calls.append(("margin_hist", code))
        clock.advance(0.2)
        return {"margin_hist": 2}

    def peers_fetcher(code, seen_blocks):
        calls.append(("peers", code, seen_blocks))
        clock.advance(0.3)
        return {"peers": 3}

    fetched, run_log, _recorder, _clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
        margin_fetcher=margin_fetcher,
        peers_fetcher=peers_fetcher,
        clock=clock,
        blocks=blocks,
    )

    assert calls == [
        ("fund", "600693"),
        ("margin_hist", "600693"),
        ("peers", "600693", blocks),
    ]
    assert fetched == {
        "fund_daily5": {"fund": 1},
        "margin_hist": {"margin_hist": 2},
        "peers": {"peers": 3},
    }
    assert run_log["supplements"] == {
        "资金面-5日主力": "ok, 100ms",
        "两融历史": "ok, 200ms",
        "同业对比": "ok, 300ms",
    }
    assert run_log["sources"] == {"existing": "ok"}
    assert run_log["source_meta"]["资金面-5日主力"]["detail"] == "近5日主力资金"
    assert run_log["source_meta"]["两融历史"]["detail"] == "两融方向历史"
    assert run_log["source_meta"]["同业对比"]["detail"] == "概念同业对比"
    for label in SRC_DESC:
        assert run_log["source_meta"][label]["timeout_sec"] == 20.0
        assert run_log["source_meta"][label]["timed_out"] is False


def test_fund_error_dict_retries_once_after_1_5_seconds(monkeypatch):
    calls = []
    clock = FakeClock()
    success = {"fund": "recovered"}

    def fund_fetcher(code):
        calls.append(code)
        clock.advance(0.25)
        if len(calls) == 1:
            return {"error": "first error"}
        return success

    fetched, run_log, _recorder, returned_clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
        clock=clock,
    )
    meta = run_log["source_meta"]["资金面-5日主力"]

    assert calls == ["600693", "600693"]
    assert returned_clock.sleeps == [1.5]
    assert fetched["fund_daily5"] is success
    assert meta["ms"] == 2000
    assert meta["status"] == "ok, 2000ms"


def test_margin_history_error_dict_is_not_retried(monkeypatch):
    calls = []
    payload = {"error": "margin error"}

    def margin_fetcher(code):
        calls.append(code)
        return payload

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        margin_fetcher=margin_fetcher,
    )
    meta = run_log["source_meta"]["两融历史"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert fetched["margin_hist"] is payload
    assert meta["status"] == "error:margin error, 0ms"


def test_second_error_dict_keeps_first_error_payload(monkeypatch):
    calls = []

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        if len(calls) == 1:
            return {"error": "first error"}
        return {"error": "second error"}

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )
    meta = run_log["source_meta"]["同业对比"]

    assert len(calls) == 2
    assert clock.sleeps == [1.5]
    assert fetched["peers"] == {"error": "first error"}
    assert meta["status"] == "error:first error, 1500ms"


def test_first_exception_is_not_retried(monkeypatch):
    calls = []

    def fund_fetcher(code):
        calls.append(code)
        raise RuntimeError("fund exploded")

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )
    meta = run_log["source_meta"]["资金面-5日主力"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert fetched["fund_daily5"] == {"error": "fund exploded"}
    assert meta["status"] == "error:fund exploded, 0ms"


def test_retry_exception_replaces_first_error_payload(monkeypatch):
    calls = []

    def fund_fetcher(code):
        calls.append(code)
        if len(calls) == 1:
            return {"error": "first error"}
        raise RuntimeError("retry exploded")

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )
    meta = run_log["source_meta"]["资金面-5日主力"]

    assert calls == ["600693", "600693"]
    assert clock.sleeps == [1.5]
    assert fetched["fund_daily5"] == {"error": "retry exploded"}
    assert meta["status"] == "error:retry exploded, 1500ms"


def test_existing_sparse_meta_is_reused_without_normalizing(monkeypatch):
    recorder = SourceStatusRecorder()
    recorder["资金面-5日主力"] = {
        "at": "preexisting-at",
        "custom": "keep-me",
        "status": "old",
    }

    _fetched, run_log, returned_recorder, _clock = _run(
        monkeypatch,
        recorder=recorder,
    )
    meta = run_log["source_meta"]["资金面-5日主力"]

    assert returned_recorder is recorder
    assert meta["at"] == "preexisting-at"
    assert meta["custom"] == "keep-me"
    assert meta["status"] == "ok, 0ms"
    assert meta["detail"] == "近5日主力资金"


def test_fetch_supplements_timeout_sets_typed_observability(monkeypatch):
    calls = []
    release = fetching.threading.Event()
    monkeypatch.setattr(fetching, "_SUPPLEMENT_TIMEOUT_SEC", 0.01)

    def blocked(code):
        calls.append(code)
        release.wait(0.2)
        return {"late": True}

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        fund_fetcher=blocked,
    )
    release.set()

    meta = run_log["source_meta"]["资金面-5日主力"]
    assert calls == ["600693"]
    assert clock.sleeps == []
    assert fetched["fund_daily5"] == {"error": "资金面-5日主力 调用超时(0.01s)"}
    assert meta["timeout_sec"] == 0.01
    assert meta["timed_out"] is True
    assert run_log["source_meta"]["两融历史"]["timed_out"] is False
    assert run_log["source_meta"]["同业对比"]["timed_out"] is False


# --- known business-empty results must not spend a second request ---


def test_fund_daily5_no_data_error_is_not_retried(monkeypatch):
    calls = []
    payload = {"error": "近5日主力资金无数据", "rows": []}

    def fund_fetcher(code):
        calls.append(code)
        return payload

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )
    meta = run_log["source_meta"]["资金面-5日主力"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert fetched["fund_daily5"] is payload
    assert meta["ms"] == 0
    assert meta["status"] == "error:近5日主力资金无数据, 0ms"
    assert run_log["supplements"]["资金面-5日主力"] == meta["status"]


def test_fund_daily5_transient_error_still_retries(monkeypatch):
    calls = []
    recovered = {"rows": [{"date": "2026-09-04"}]}

    def fund_fetcher(code):
        calls.append(code)
        if len(calls) == 1:
            return {"error": "HTTPSConnectionPool timeout", "rows": []}
        return recovered

    fetched, _run_log, _recorder, clock = _run(
        monkeypatch,
        fund_fetcher=fund_fetcher,
    )

    assert calls == ["600693", "600693"]
    assert clock.sleeps == [1.5]
    assert fetched["fund_daily5"] is recovered


def test_peers_missing_concept_input_error_is_not_retried(monkeypatch):
    calls = []
    payload = {
        "error": "无概念板块数据(概念归属缺失), 无法取成分股做同业对比",
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return payload

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
        blocks="not-a-list",
    )
    meta = run_log["source_meta"]["同业对比"]

    assert calls == [("600693", "not-a-list")]
    assert clock.sleeps == []
    assert fetched["peers"] is payload
    assert meta["status"] == (
        "error:无概念板块数据(概念归属缺失), 无法取成分股做同业对比, 0ms"
    )


def test_peers_empty_concept_list_error_is_not_retried(monkeypatch):
    calls = []
    payload = {
        "error": "概念板块列表为空(东财 slist 返回 0 条, 可能风控), 无法做同业对比",
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return payload

    fetched, _run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
        blocks=[],
    )

    assert calls == [("600693", [])]
    assert clock.sleeps == []
    assert fetched["peers"] is payload


def test_peers_not_in_top100_with_answered_concept_is_not_retried(monkeypatch):
    calls = []
    payload = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [
            {
                "concept": "白酒",
                "code": "BK0896",
                "total": 100,
                "fetched": 100,
                "rank": None,
            }
        ],
        "rows": None,
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return payload

    fetched, _run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
        blocks=[{"name": "白酒", "code": "BK0896"}],
    )

    assert calls == [("600693", [{"name": "白酒", "code": "BK0896"}])]
    assert clock.sleeps == []
    assert fetched["peers"] is payload


def test_peers_all_attempted_concepts_api_failure_still_retries(monkeypatch):
    calls = []
    first = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [
            {"concept": "白酒", "code": "BK0896", "error": "502 Bad Gateway"},
            {"concept": "食品", "code": "BK0437", "error": "read timeout"},
        ],
        "rows": None,
    }
    recovered = {"block_used": "白酒", "rank": 3, "rows": [{"code": "600693"}]}

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        if len(calls) == 1:
            return first
        return recovered

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )

    assert calls == [("600693", [{"name": "测试概念"}]), ("600693", [{"name": "测试概念"}])]
    assert clock.sleeps == [1.5]
    assert fetched["peers"] is recovered
    assert run_log["source_meta"]["同业对比"]["status"] == "ok, 1500ms"


def test_peers_mixed_attempts_count_as_answered_and_skip_retry(monkeypatch):
    """One answered concept is enough: the missing self-stock is business-empty."""
    calls = []
    first = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [
            {"concept": "白酒", "code": "BK0896", "error": "502 Bad Gateway"},
            {"concept": "食品", "code": "BK0437", "total": 100, "fetched": 100,
             "rank": None},
        ],
        "rows": None,
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return first

    fetched, _run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )

    assert len(calls) == 1
    assert clock.sleeps == []
    assert fetched["peers"] is first


def test_peers_ambiguous_payload_without_tried_keeps_current_retry(monkeypatch):
    calls = []
    first = {"error": "未知接口错误", "rows": []}

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        if len(calls) == 1:
            return first
        return {"error": "未知接口错误", "rows": []}

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )
    meta = run_log["source_meta"]["同业对比"]

    assert len(calls) == 2
    assert clock.sleeps == [1.5]
    assert fetched["peers"] is first
    assert meta["status"] == "error:未知接口错误, 1500ms"


def test_peers_empty_tried_list_keeps_current_retry_behavior(monkeypatch):
    calls = []
    first = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [],
        "rows": None,
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return first

    _fetched, _run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )

    assert len(calls) == 2
    assert clock.sleeps == [1.5]


def test_peers_retried_error_keeps_first_business_payload(monkeypatch):
    calls = []
    first = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [{"concept": "白酒", "code": "BK0896", "error": "502 Bad Gateway"}],
        "rows": None,
    }
    second = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [{"concept": "白酒", "code": "BK0896", "error": "503"}],
        "rows": None,
    }

    def peers_fetcher(code, blocks):
        calls.append((code, blocks))
        return first if len(calls) == 1 else second

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        peers_fetcher=peers_fetcher,
    )
    meta = run_log["source_meta"]["同业对比"]

    assert len(calls) == 2
    assert clock.sleeps == [1.5]
    assert fetched["peers"] is first
    assert meta["status"] == (
        "error:本票未进入所查概念的市值前100或接口失败, 1500ms"
    )


def test_margin_history_error_dict_stays_single_call_under_supplement_rules(monkeypatch):
    calls = []
    payload = {"error": "两融历史无数据", "rows": []}

    def margin_fetcher(code):
        calls.append(code)
        return payload

    fetched, run_log, _recorder, clock = _run(
        monkeypatch,
        margin_fetcher=margin_fetcher,
    )
    meta = run_log["source_meta"]["两融历史"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert fetched["margin_hist"] is payload
    assert meta["status"] == "error:两融历史无数据, 0ms"


def test_supplement_retryable_classification_matches_fetchers():
    fund_empty = {"error": "近5日主力资金无数据", "rows": []}
    peers_top100 = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [{"concept": "白酒", "code": "BK0896", "total": 100,
                   "fetched": 100, "rank": None}],
        "rows": None,
    }
    peers_api_fail = {
        "error": "本票未进入所查概念的市值前100或接口失败",
        "tried": [{"concept": "白酒", "code": "BK0896", "error": "502"}],
        "rows": None,
    }

    assert fetching._supplement_retryable("fund_daily5", fund_empty) is False
    assert fetching._supplement_retryable("peers", peers_top100) is False
    assert fetching._supplement_retryable("peers", peers_api_fail) is True
    assert fetching._supplement_retryable("margin_hist", fund_empty) is False
    assert fetching._supplement_retryable("fund_daily5", {"rows": []}) is False
    assert fetching._supplement_retryable("peers", None) is False
