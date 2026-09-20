from types import SimpleNamespace

from analysis.orchestration import fetching


SRC_DESC = {"融资融券": "融资融券明细"}


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


def _run(monkeypatch, fetcher, clock=None):
    clock = clock or FakeClock()
    monkeypatch.setattr(
        fetching,
        "time",
        SimpleNamespace(time=clock.time, sleep=clock.sleep),
    )
    run_log = {
        "sources": {},
        "source_meta": {},
        "fallback_chain": [],
    }
    margin = fetching._fetch_margin(
        run_log,
        SRC_DESC,
        lambda ts: f"at:{ts:.1f}",
        fetcher,
        "600693",
    )
    return margin, run_log, clock


def test_fetch_margin_success_first_try_records_total_elapsed(monkeypatch):
    calls = []
    payload = {"source": "eastmoney", "balance": 123}
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.25)
        return payload

    margin, run_log, returned_clock = _run(monkeypatch, fetcher, clock)
    meta = run_log["source_meta"]["融资融券"]

    assert returned_clock is clock
    assert calls == ["600693"]
    assert clock.sleeps == []
    assert margin is payload
    assert meta == {
        "ms": 250,
        "at": "at:1000.2",
        "status": "ok:eastmoney-datacenter, 250ms",
        "detail": "融资融券明细",
        "timeout_sec": 20.0,
        "timed_out": False,
    }
    assert run_log["sources"]["融资融券"] == meta["status"]
    assert run_log["fallback_chain"] == []


def test_fetch_margin_retries_exceptions_and_timer_includes_sleeps(monkeypatch):
    calls = []
    payload = {"balance": 456}
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.2)
        if len(calls) < 3:
            raise RuntimeError(f"boom-{len(calls)}")
        return payload

    margin, run_log, _ = _run(monkeypatch, fetcher, clock)
    meta = run_log["source_meta"]["融资融券"]

    assert calls == ["600693", "600693", "600693"]
    assert clock.sleeps == [1.0, 1.0]
    assert margin is payload
    assert meta["ms"] == 2600
    assert meta["status"] == "ok:eastmoney-datacenter, 2600ms"
    assert run_log["fallback_chain"] == []


def test_fetch_margin_all_exceptions_sleep_after_final_and_keep_last_error(monkeypatch):
    calls = []
    clock = FakeClock()

    def fetcher(code):
        calls.append(code)
        clock.advance(0.1)
        raise ValueError(f"failure-{len(calls)}")

    margin, run_log, _ = _run(monkeypatch, fetcher, clock)
    meta = run_log["source_meta"]["融资融券"]

    assert calls == ["600693", "600693", "600693"]
    assert clock.sleeps == [1.0, 1.0, 1.0]
    assert margin == {"error": "failure-3"}
    assert meta["ms"] == 3300
    assert meta["status"] == "error:failure-3, 3300ms"
    assert meta["timeout_sec"] == 20.0
    assert meta["timed_out"] is False
    assert run_log["fallback_chain"] == ["融资融券: failure-3"]


def test_fetch_margin_returned_error_dict_is_not_retried(monkeypatch):
    calls = []
    payload = {"error": "provider returned error"}

    def fetcher(code):
        calls.append(code)
        return payload

    margin, run_log, clock = _run(monkeypatch, fetcher)
    meta = run_log["source_meta"]["融资融券"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert margin is payload
    assert meta["status"] == "error:provider returned error, 0ms"
    assert run_log["fallback_chain"] == ["融资融券: provider returned error"]


def test_fetch_margin_none_is_currently_recorded_as_ok_without_retry(monkeypatch):
    calls = []

    def fetcher(code):
        calls.append(code)
        return None

    margin, run_log, clock = _run(monkeypatch, fetcher)
    meta = run_log["source_meta"]["融资融券"]

    assert calls == ["600693"]
    assert clock.sleeps == []
    assert margin is None
    assert meta["status"] == "ok:eastmoney-datacenter, 0ms"
    assert run_log["fallback_chain"] == []


def test_fetch_margin_timeout_budget_is_internal_and_not_forwarded(monkeypatch):
    seen = {}
    calls = []

    def fake_timeout(label, fn, *args, timeout, **kwargs):
        seen["label"] = label
        seen["args"] = args
        seen["timeout"] = timeout
        seen["kwargs"] = kwargs
        return fn(*args, **kwargs)

    def fetcher(code):
        calls.append(code)
        return {"balance": 789}

    monkeypatch.setattr(fetching, "_call_with_timeout", fake_timeout)

    margin, run_log, clock = _run(monkeypatch, fetcher)

    assert margin == {"balance": 789}
    assert calls == ["600693"]
    assert clock.sleeps == []
    assert seen == {
        "label": "融资融券",
        "args": ("600693",),
        "timeout": fetching._MARGIN_TIMEOUT_SEC,
        "kwargs": {},
    }
    assert run_log["source_meta"]["融资融券"]["status"] == (
        "ok:eastmoney-datacenter, 0ms"
    )


def test_fetch_margin_timeout_retries_three_times_and_keeps_exception_contract(monkeypatch):
    calls = []
    clock = FakeClock()
    release = fetching.threading.Event()
    monkeypatch.setattr(fetching, "_MARGIN_TIMEOUT_SEC", 0.01)

    def fetcher(code):
        calls.append(code)
        release.wait(0.2)
        return {"late": True}

    margin, run_log, _ = _run(monkeypatch, fetcher, clock)
    release.set()

    meta = run_log["source_meta"]["融资融券"]
    assert calls == ["600693", "600693", "600693"]
    assert clock.sleeps == [1.0, 1.0, 1.0]
    assert margin == {"error": "融资融券 调用超时(0.01s)"}
    assert meta["ms"] == 3000
    assert meta["status"] == "error:融资融券 调用超时(0.01s), 3000ms"
    assert meta["timeout_sec"] == 0.01
    assert meta["timed_out"] is True
    assert run_log["fallback_chain"] == ["融资融券: 融资融券 调用超时(0.01s)"]
