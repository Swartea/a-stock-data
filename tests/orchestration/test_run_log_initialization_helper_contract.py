import analysis.orchestration.helpers as helpers
import analysis.pipeline as pipeline
from analysis.orchestration.helpers import _initialize_run_log


class FakeStarted:
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


def test_pipeline_uses_run_log_initialization_boundary():
    assert pipeline._initialize_run_log is helpers._initialize_run_log


def test_initialize_run_log_preserves_exact_initial_contract():
    started = FakeStarted("2026-09-18T01:23:36+00:00")

    run_log = _initialize_run_log(started)

    assert list(run_log) == [
        "started_at",
        "finished_at",
        "total_sec",
        "sources",
        "source_meta",
        "guard",
        "fallback_chain",
        "fatal",
    ]
    assert run_log == {
        "started_at": "2026-09-18T01:23:36+00:00",
        "finished_at": None,
        "total_sec": None,
        "sources": {},
        "source_meta": {},
        "guard": {
            "status": "N/A 单票流程不用池CSV",
            "kline_freshness": None,
        },
        "fallback_chain": [],
        "fatal": None,
    }
    assert started.astimezone_calls == 1
    assert started.isoformat_calls == ["seconds"]


def test_initialize_run_log_returns_fresh_mutable_containers():
    first = _initialize_run_log(FakeStarted("2026-09-18T01:23:36+00:00"))
    second = _initialize_run_log(FakeStarted("2026-09-18T01:23:37+00:00"))

    first["sources"]["行情"] = "ok"
    first["source_meta"]["行情"] = {"ms": 1}
    first["guard"]["kline_freshness"] = "fresh"
    first["fallback_chain"].append("fallback")

    assert second["sources"] == {}
    assert second["source_meta"] == {}
    assert second["guard"] == {
        "status": "N/A 单票流程不用池CSV",
        "kline_freshness": None,
    }
    assert second["fallback_chain"] == []
