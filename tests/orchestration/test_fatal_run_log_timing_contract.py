from types import SimpleNamespace

import analysis.pipeline as pipeline


class FakeStarted:
    def __init__(self, timestamp_value):
        self.timestamp_value = timestamp_value

    def timestamp(self):
        return self.timestamp_value


class FakeDateTime:
    _started = FakeStarted(1000.0)
    _finish = None

    @classmethod
    def now(cls):
        if cls._finish is None:
            return cls._started
        return cls._finish


class FakeFinish:
    def __init__(self, iso_text):
        self.iso_text = iso_text

    def astimezone(self):
        return self

    def isoformat(self, *, timespec):
        assert timespec == "seconds"
        return self.iso_text


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_fatal_path_finalizes_run_log_before_dump_and_return(monkeypatch):
    clock = FakeClock()
    FakeDateTime._finish = None
    calls = {"analyze": 0, "restore": 0}
    dumped = []

    monkeypatch.setattr(pipeline, "datetime", FakeDateTime)
    monkeypatch.setattr(
        pipeline,
        "time",
        SimpleNamespace(time=clock.time, sleep=clock.sleep),
    )
    monkeypatch.setattr(pipeline, "_patch_v2_timers", lambda *_args, **_kw: {"saved": True})

    def restore(*_args, **_kw):
        calls["restore"] += 1

    monkeypatch.setattr(pipeline, "_restore_v2", restore)

    def analyze(*_args, **_kw):
        calls["analyze"] += 1
        if calls["analyze"] == 3:
            FakeDateTime._finish = FakeFinish("2026-09-18T01:23:45+00:00")
        return {"error": "行情失败"}

    monkeypatch.setattr(pipeline.v2, "analyze_single", analyze)
    monkeypatch.setattr(
        pipeline,
        "_dump_run_log",
        lambda code, name, run_log: dumped.append((code, name, dict(run_log))),
    )

    result = pipeline.analyze_single_v3("600693", "东百集团")

    assert calls["analyze"] == 3
    assert calls["restore"] == 1
    assert clock.sleeps == [3, 3, 3]

    assert result["error"] == "V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底): 行情失败"
    assert result["run_log"]["fatal"] == result["error"]
    assert result["run_log"]["finished_at"] == "2026-09-18T01:23:45+00:00"
    assert result["run_log"]["total_sec"] == 9.0

    assert len(dumped) == 1
    code, name, dumped_run_log = dumped[0]
    assert code == "600693"
    assert name == "东百集团"
    assert dumped_run_log["fatal"] == result["error"]
    assert dumped_run_log["finished_at"] == "2026-09-18T01:23:45+00:00"
    assert dumped_run_log["total_sec"] == 9.0
