"""Phase 1I fetch 阶段契约: fetch_v3_blocks 的顺序/键集/参数逐字锁定。

这些断言锁的是**原内联实现的行为**, 不是新实现自己的行为 —— 抽离只搬边界,
不改口径。若将来有人调整 fetch 顺序或补删 fetched 槽位, 这里必须先被改。
"""

from analysis.orchestration import fetching
from analysis.orchestration.source_status import SourceStatusRecorder


def _seams(calls):
    """Build a full seam set that records invocations into ``calls``."""
    return {
        "call_new": lambda *a, **kw: calls.append(("call_new", a[5], a[6], a[7:])) or f"v-{a[5]}",
        "enabled_sections": lambda: calls.append(("enabled_sections",)) or [],
        "fetch_sections": lambda run_log, sections, code, base: calls.append(
            ("fetch_sections", code)
        ) or {"irm": {"ok": True}},
        "fetch_margin": lambda run_log, src_desc, fmt_time, fetcher, code: calls.append(
            ("fetch_margin", code, fetcher("600693"))
        ) or {"margin": 1},
        "fetch_supplements": lambda recorder, run_log, fetched, *rest: calls.append(
            ("fetch_supplements", tuple(fetched))
        ) or fetched.update({"fund_daily5": 1, "margin_hist": 2, "peers": 3}),
        "fund_flow_fetcher": object(),
        "margin_history_fetcher": object(),
        "peers_fetcher": object(),
        "margin_fetcher": lambda code: {"margin_payload": code},
    }


def _run(monkeypatch, base_result=None):
    calls: list = []
    seams = _seams(calls)
    run_log = {"sources": {}, "source_meta": {}, "fallback_chain": []}
    return (
        fetching.fetch_v3_blocks(
            "600693",
            base_result if base_result is not None else {"blocks": [{"n": 1}]},
            run_log,
            SourceStatusRecorder(),
            {"公告": {"ok": True, "fn": object(), "err": ""}},
            {"公告": "desc"},
            lambda blob: "ok",
            lambda ts: "12:00:00",
            **seams,
        ),
        calls,
    )


def test_fetch_stage_preserves_historical_call_order(monkeypatch):
    """公告 → 财务 → 研报 → 新闻 → Section Registry → 两融 → supplements"""
    _, calls = _run(monkeypatch)

    assert [c[0] for c in calls] == [
        "call_new",
        "call_new",
        "call_new",
        "call_new",
        "enabled_sections",
        "fetch_sections",
        "fetch_margin",
        "fetch_supplements",
    ]
    # 4 个 _call_new 的 (src_label, mod_key) 标签契约
    assert [(c[1], c[2]) for c in calls[:4]] == [
        ("公告", "公告"),
        ("财务摘要", "财务"),
        ("研报观点", "研报"),
        ("新闻舆情", "新闻"),
    ]


def test_research_fetch_keeps_days_200(monkeypatch):
    """研报 days=200: 小票近 90 日常无覆盖, 收窄会打回空结果。"""
    _, calls = _run(monkeypatch)

    # call_new 记的是 (src_label, mod_key, 其后位置参数)
    research = next(c for c in calls if c[1] == "研报观点")
    assert research[3] == ("600693", 200), "研报 _call_new 必须仍传 days=200"
    for label in ("公告", "财务摘要", "新闻舆情"):
        other = next(c for c in calls if c[1] == label)
        assert other[3] == ("600693",), f"{label} 不应额外传参"


def test_fetched_keeps_exact_eight_key_shape(monkeypatch):
    """fetched 必须仍是 8 键 —— result_v3 契约按名字索引它们。"""
    blocks, _ = _run(monkeypatch)

    assert list(blocks.fetched) == [
        "announcements",
        "finance",
        "news",
        "research",
        "margin",
        "fund_daily5",
        "margin_hist",
        "peers",
    ]
    assert blocks.fetched["margin"] == {"margin": 1}
    assert blocks.margin == {"margin": 1}
    assert blocks.sections_data == {"irm": {"ok": True}}


def test_fetched_slots_start_as_none_before_population(monkeypatch):
    """supplements 之前 5 个槽位由各自 primitive 填, 不得预置占位值。"""
    calls: list = []
    seams = _seams(calls)
    # 让所有写入源返回 None, 观察初始化形状
    seams["call_new"] = lambda *a, **kw: None
    seams["fetch_margin"] = lambda *a, **kw: None
    seams["fetch_supplements"] = lambda recorder, run_log, fetched, *rest: (
        calls.append(("supp_at_entry", tuple(fetched.values())))
    )

    blocks = fetching.fetch_v3_blocks(
        "600693",
        {"blocks": []},
        {"sources": {}, "source_meta": {}, "fallback_chain": []},
        SourceStatusRecorder(),
        {},
        {},
        lambda blob: "ok",
        lambda ts: "00:00:00",
        **seams,
    )

    at_entry = next(c[1] for c in calls if c[0] == "supp_at_entry")
    assert at_entry == (None, None, None, None, None, None, None, None)
    assert blocks.fetched == dict.fromkeys(blocks.fetched, None)


def test_supplements_receives_base_result_blocks(monkeypatch):
    """peers 需要 base_result['blocks'] 做概念口径, 缺失时传空列表。"""
    seen = {}
    calls: list = []
    seams = _seams(calls)

    def spy(recorder, run_log, fetched, src_desc, fmt_time, code, blocks, *rest):
        seen["blocks"] = blocks
        seen["code"] = code

    seams["fetch_supplements"] = spy

    fetching.fetch_v3_blocks(
        "600693",
        {"blocks": [{"name": "东百"}]},
        {"sources": {}, "source_meta": {}, "fallback_chain": []},
        SourceStatusRecorder(),
        {},
        {},
        lambda blob: "ok",
        lambda ts: "00:00:00",
        **seams,
    )

    assert seen == {"blocks": [{"name": "东百"}], "code": "600693"}


def test_fetch_stage_returns_named_tuple_fields():
    """返回形状固定为 (fetched, margin, sections_data)。"""
    assert fetching.V3FetchedBlocks._fields == (
        "fetched",
        "margin",
        "sections_data",
    )
