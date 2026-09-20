import analysis.pipeline as pipeline
from analysis.orchestration import fetching
from analysis.orchestration.source_status import SourceStatusRecorder


LABEL = "公告"


def test_pipeline_uses_fetching_retry_boundary():
    assert pipeline._retry_call is fetching._retry_call


def test_retry_call_success_first_try_forwards_arguments_and_records_sparse_ms(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    seen = {}

    def fetcher(code, days=None, flag=False):
        seen["args"] = (code,)
        seen["days"] = days
        seen["flag"] = flag
        return {"ok": True}

    value, n_try, exc = fetching._retry_call(
        recorder,
        LABEL,
        fetcher,
        "600693",
        days=30,
        flag=True,
        timeout=7,
    )

    assert value == {"ok": True}
    assert n_try == 1
    assert exc is None
    assert seen == {"args": ("600693",), "days": 30, "flag": True}
    assert sleeps == []
    assert set(recorder[LABEL]) == {"ms"}
    assert isinstance(recorder[LABEL]["ms"], int)
    assert recorder[LABEL]["ms"] >= 0


def test_retry_call_retries_after_exception_and_returns_success_attempt(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls = []

    def flaky():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise RuntimeError(f"boom-{len(calls)}")
        return "ok"

    value, n_try, exc = fetching._retry_call(recorder, LABEL, flaky, tries=3)

    assert value == "ok"
    assert n_try == 3
    assert exc is None
    assert calls == [1, 2, 3]
    assert sleeps == [1.0, 1.0]
    assert set(recorder[LABEL]) == {"ms"}


def test_retry_call_all_failures_return_last_error_and_do_not_create_meta(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls = []

    def always_fails():
        calls.append(len(calls) + 1)
        raise ValueError(f"failure-{len(calls)}")

    value, n_try, exc = fetching._retry_call(recorder, LABEL, always_fails, tries=3)

    assert value is None
    assert n_try == 3
    assert exc == "failure-3"
    assert calls == [1, 2, 3]
    # Current behavior sleeps after every exception, including the final one.
    assert sleeps == [1.0, 1.0, 1.0]
    assert LABEL not in recorder


def test_retry_call_success_updates_existing_meta_without_normalizing_it(monkeypatch):
    recorder = SourceStatusRecorder()
    monkeypatch.setattr(fetching.time, "sleep", lambda _seconds: None)
    recorder[LABEL] = {"status": "existing", "detail": "keep"}

    value, n_try, exc = fetching._retry_call(recorder, LABEL, lambda: 42)

    assert (value, n_try, exc) == (42, 1, None)
    assert recorder[LABEL]["status"] == "existing"
    assert recorder[LABEL]["detail"] == "keep"
    assert isinstance(recorder[LABEL]["ms"], int)
    assert "at" not in recorder[LABEL]


def test_retry_call_timeout_is_active_and_not_forwarded(monkeypatch):
    recorder = SourceStatusRecorder()
    monkeypatch.setattr(fetching.time, "sleep", lambda _seconds: None)
    seen_kwargs = {}

    def fetcher(**kwargs):
        seen_kwargs.update(kwargs)
        return "ok"

    value, n_try, exc = fetching._retry_call(
        recorder,
        LABEL,
        fetcher,
        timeout=0.05,
        custom="forwarded",
    )

    assert (value, n_try, exc) == ("ok", 1, None)
    assert seen_kwargs == {"custom": "forwarded"}


def test_retry_call_timeout_retries_with_same_attempt_count(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))
    release = fetching.threading.Event()
    calls = []

    def blocked():
        calls.append(len(calls) + 1)
        release.wait(0.2)
        return "late"

    value, n_try, exc = fetching._retry_call(
        recorder,
        LABEL,
        blocked,
        tries=3,
        timeout=0.01,
    )

    release.set()
    assert value is None
    assert n_try == 3
    assert exc == "公告 调用超时(0.01s)"
    assert calls == [1, 2, 3]
    assert sleeps == [1.0, 1.0, 1.0]
    assert LABEL not in recorder


def test_retry_call_single_failed_try_still_sleeps_once(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fail_once():
        raise RuntimeError("single failure")

    value, n_try, exc = fetching._retry_call(recorder, LABEL, fail_once, tries=1)

    assert value is None
    assert n_try == 1
    assert exc == "single failure"
    assert sleeps == [1.0]
    assert LABEL not in recorder
def test_retry_call_timeout_observation_is_additive_and_type_based(monkeypatch):
    recorder = SourceStatusRecorder()
    sleeps = []
    state = {}
    monkeypatch.setattr(fetching.time, "sleep", lambda seconds: sleeps.append(seconds))

    def timeout_boundary(*_args, **_kwargs):
        raise TimeoutError("typed timeout")

    monkeypatch.setattr(fetching, "_call_with_timeout", timeout_boundary)

    value, n_try, exc = fetching._retry_call(
        recorder,
        LABEL,
        lambda: "never",
        tries=1,
        timeout=7,
        _timeout_state=state,
    )

    assert (value, n_try, exc) == (None, 1, "typed timeout")
    assert sleeps == [1.0]
    assert LABEL not in recorder
    assert state == {"timeout_sec": 7.0, "timed_out": True}
