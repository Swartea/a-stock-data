from analysis.orchestration.helpers import _finalize_run_log_timing


class FakeStarted:
    def __init__(self, timestamp_value):
        self.timestamp_value = timestamp_value

    def timestamp(self):
        return self.timestamp_value


class FakeFinish:
    def __init__(self, iso_text):
        self.iso_text = iso_text
        self.astimezone_calls = 0
        self.isoformat_calls = []

    def astimezone(self):
        self.astimezone_calls += 1
        return self

    def isoformat(self, *, timespec):
        self.isoformat_calls.append(timespec)
        return self.iso_text


def test_finalize_run_log_timing_preserves_exact_finished_at_and_rounding_contract():
    run_log = {"finished_at": None, "total_sec": None, "keep": "value"}
    started = FakeStarted(987.66)
    finish = FakeFinish("2026-09-16T01:00:12+00:00")
    events = []

    def now_fn():
        events.append("now")
        return finish

    def time_fn():
        events.append("time")
        return 1000.0

    result = _finalize_run_log_timing(run_log, started, now_fn, time_fn)

    assert result is None
    assert run_log["finished_at"] == "2026-09-16T01:00:12+00:00"
    assert run_log["total_sec"] == 12.3
    assert run_log["keep"] == "value"
    assert finish.astimezone_calls == 1
    assert finish.isoformat_calls == ["seconds"]
    assert events == ["now", "time"]


def test_finalize_run_log_timing_uses_wall_clock_not_finished_at_delta():
    run_log = {}
    started = FakeStarted(987.64)
    finish = FakeFinish("2099-12-31T23:59:59+00:00")

    _finalize_run_log_timing(
        run_log,
        started,
        lambda: finish,
        lambda: 1000.0,
    )

    assert run_log == {
        "finished_at": "2099-12-31T23:59:59+00:00",
        "total_sec": 12.4,
    }
