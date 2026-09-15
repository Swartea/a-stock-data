from analysis.orchestration.source_status import SourceStatusRecorder


def test_retry_style_sparse_metadata_is_preserved():
    recorder = SourceStatusRecorder()

    recorder.setdefault("公告", {})["ms"] = 123

    assert recorder.snapshot() == {"公告": {"ms": 123}}


def test_v2_timer_seed_shape_supports_incremental_updates():
    recorder = SourceStatusRecorder()
    recorder["行情"] = {
        "ms": None,
        "at": None,
        "status": None,
        "detail": None,
    }

    recorder["行情"]["ms"] = 48
    recorder["行情"]["at"] = "12:34:56"

    assert recorder["行情"] == {
        "ms": 48,
        "at": "12:34:56",
        "status": None,
        "detail": None,
    }


def test_source_specific_extra_fields_are_preserved():
    recorder = SourceStatusRecorder()

    meta = recorder.setdefault("申万分类", {"at": "12:34:56"})
    meta["ms"] = 0
    meta["status"] = "error:ssl, 0ms"
    meta["detail"] = "申万行业稳定性"
    meta["tls_recommendation"] = "pip install -U certifi"

    assert recorder["申万分类"]["tls_recommendation"] == "pip install -U certifi"


def test_get_default_does_not_create_an_entry():
    recorder = SourceStatusRecorder()

    assert recorder.get("不存在", {}) == {}
    assert len(recorder) == 0


def test_snapshot_is_detached_from_live_metadata():
    recorder = SourceStatusRecorder()
    recorder["行情"] = {"ms": 10, "status": "ok, 10ms"}

    snapshot = recorder.snapshot()
    snapshot["行情"]["ms"] = 999
    snapshot["新增"] = {"ms": 1}

    assert recorder["行情"]["ms"] == 10
    assert "新增" not in recorder


def test_clear_resets_all_source_metadata():
    recorder = SourceStatusRecorder()
    recorder["行情"] = {"ms": 10}
    recorder["公告"] = {"ms": 20}

    recorder.clear()

    assert recorder.snapshot() == {}
