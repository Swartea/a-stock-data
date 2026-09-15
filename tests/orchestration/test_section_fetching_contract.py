from types import SimpleNamespace

from analysis.orchestration import fetching


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSection:
    def __init__(self, label, fetch_fn):
        self.label = label
        self._fetch_fn = fetch_fn

    def fetch(self, code, ctx):
        return self._fetch_fn(code, ctx)


def _run(monkeypatch, sections, *, clock=None, base_result=None):
    clock = clock or FakeClock()
    base_result = base_result if base_result is not None else {"blocks": []}
    monkeypatch.setattr(fetching, "time", SimpleNamespace(time=clock.time))
    run_log = {
        "sources": {"existing": "ok"},
        "fallback_chain": ["existing fallback"],
    }
    sections_data = fetching._fetch_sections(
        run_log,
        sections,
        "600693",
        base_result,
    )
    return sections_data, run_log, clock, base_result


def test_fetch_sections_preserves_order_context_identity_payload_and_int_timing(monkeypatch):
    calls = []
    clock = FakeClock()
    base_result = {"blocks": [{"name": "概念A"}]}
    payload_a = {"value": "A"}
    payload_b = {"value": "B"}

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.125)
        return payload_a

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.250)
        return payload_b

    sections_data, run_log, _clock, returned_base = _run(
        monkeypatch,
        [FakeSection("Section A", fetch_a), FakeSection("Section B", fetch_b)],
        clock=clock,
        base_result=base_result,
    )

    assert returned_base is base_result
    assert [(label, code) for label, code, _ctx in calls] == [
        ("A", "600693"),
        ("B", "600693"),
    ]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert sections_data["Section A"] is payload_a
    assert sections_data["Section B"] is payload_b
    assert run_log["sections_count"] == 2
    assert run_log["sources"] == {
        "existing": "ok",
        "Section A": "ok, 125ms",
        "Section B": "ok, 250ms",
    }
    assert run_log["fallback_chain"] == ["existing fallback"]


def test_fetch_sections_exception_becomes_error_payload_and_later_section_still_runs(monkeypatch):
    calls = []
    clock = FakeClock()
    base_result = {"ctx": "same-object"}

    def fetch_a(code, ctx):
        calls.append(("A", code, ctx))
        clock.advance(0.125)
        return {"value": "A"}

    def fetch_b(code, ctx):
        calls.append(("B", code, ctx))
        clock.advance(0.250)
        raise RuntimeError("boom")

    def fetch_c(code, ctx):
        calls.append(("C", code, ctx))
        clock.advance(0.250)
        return {"value": "C"}

    sections_data, run_log, _clock, _returned_base = _run(
        monkeypatch,
        [
            FakeSection("Section A", fetch_a),
            FakeSection("Section B", fetch_b),
            FakeSection("Section C", fetch_c),
        ],
        clock=clock,
        base_result=base_result,
    )

    assert [label for label, _code, _ctx in calls] == ["A", "B", "C"]
    assert all(ctx is base_result for _label, _code, ctx in calls)
    assert sections_data["Section B"] == {"error": "boom"}
    assert sections_data["Section C"] == {"value": "C"}
    assert run_log["sections_count"] == 2
    assert run_log["sources"]["Section A"] == "ok, 125ms"
    assert run_log["sources"]["Section B"] == "error: boom"
    assert run_log["sources"]["Section C"] == "ok, 250ms"
    assert run_log["fallback_chain"] == ["existing fallback", "Section B: boom"]


def test_fetch_sections_empty_registry_returns_empty_and_sets_count_zero(monkeypatch):
    sections_data, run_log, _clock, _base_result = _run(monkeypatch, [])

    assert sections_data == {}
    assert run_log["sections_count"] == 0
    assert run_log["sources"] == {"existing": "ok"}
    assert run_log["fallback_chain"] == ["existing fallback"]
