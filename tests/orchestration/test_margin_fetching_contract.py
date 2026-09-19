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
