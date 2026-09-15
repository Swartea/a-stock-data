import analysis.pipeline as pipeline


LABEL = "公告"


def setup_function():
    pipeline._src_meta.clear()


def teardown_function():
    pipeline._src_meta.clear()


def test_retry_call_success_first_try_forwards_arguments_and_records_sparse_ms(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: sleeps.append(seconds))

    seen = {}

    def fetcher(code, days=None, flag=False):
        seen["args"] = (code,)
        seen["days"] = days
        seen["flag"] = flag
        return {"ok": True}

    value, n_try, exc = pipeline._retry_call(
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
    assert set(pipeline._src_meta[LABEL]) == {"ms"}
    assert isinstance(pipeline._src_meta[LABEL]["ms"], int)
    assert pipeline._src_meta[LABEL]["ms"] >= 0


def test_retry_call_retries_after_exception_and_returns_success_attempt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls = []

    def flaky():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise RuntimeError(f"boom-{len(calls)}")
        return "ok"

    value, n_try, exc = pipeline._retry_call(LABEL, flaky, tries=3)

    assert value == "ok"
    assert n_try == 3
    assert exc is None
    assert calls == [1, 2, 3]
    assert sleeps == [1.0, 1.0]
    assert set(pipeline._src_meta[LABEL]) == {"ms"}


def test_retry_call_all_failures_return_last_error_and_do_not_create_meta(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls = []

    def always_fails():
        calls.append(len(calls) + 1)
        raise ValueError(f"failure-{len(calls)}")

    value, n_try, exc = pipeline._retry_call(LABEL, always_fails, tries=3)

    assert value is None
    assert n_try == 3
    assert exc == "failure-3"
    assert calls == [1, 2, 3]
    # Current behavior sleeps after every exception, including the final one.
    assert sleeps == [1.0, 1.0, 1.0]
    assert LABEL not in pipeline._src_meta


def test_retry_call_success_updates_existing_meta_without_normalizing_it(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)
    pipeline._src_meta[LABEL] = {"status": "existing", "detail": "keep"}

    value, n_try, exc = pipeline._retry_call(LABEL, lambda: 42)

    assert (value, n_try, exc) == (42, 1, None)
    assert pipeline._src_meta[LABEL]["status"] == "existing"
    assert pipeline._src_meta[LABEL]["detail"] == "keep"
    assert isinstance(pipeline._src_meta[LABEL]["ms"], int)
    assert "at" not in pipeline._src_meta[LABEL]


def test_retry_call_timeout_parameter_is_currently_inert_and_not_forwarded(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)
    seen_kwargs = {}

    def fetcher(**kwargs):
        seen_kwargs.update(kwargs)
        return "ok"

    value, n_try, exc = pipeline._retry_call(
        LABEL,
        fetcher,
        timeout=0.01,
        custom="forwarded",
    )

    assert (value, n_try, exc) == ("ok", 1, None)
    assert seen_kwargs == {"custom": "forwarded"}


def test_retry_call_single_failed_try_still_sleeps_once(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fail_once():
        raise RuntimeError("single failure")

    value, n_try, exc = pipeline._retry_call(LABEL, fail_once, tries=1)

    assert value is None
    assert n_try == 1
    assert exc == "single failure"
    assert sleeps == [1.0]
    assert LABEL not in pipeline._src_meta
