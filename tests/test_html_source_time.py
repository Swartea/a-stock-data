"""_source_time 取时点逻辑回归测试 (P1-4, 2026-09-07 audit 01-v3-codebase-audit.md)

背景: V3 主流程把来源元数据写进 `run_log["source_meta"][label]` (dict, 含 at/fetched_at),
而 `run_log["sources"][label]` 只是状态字符串 ("ok, 1772ms")。旧实现只读 `sources` 且要求
值是 dict, 时点标注因此永远退化成报告日期。

覆盖 (纯本地、无网络):
- source_meta 精确匹配 / 关键字子串匹配
- source_meta 优先于老格式 sources
- 老 run_log 的 dict 型 sources 兜底
- sources 里的字符串状态值不当时点
- 时点字段优先级 + 16 字符截断
- 无可用时点时返回调用方传入的 default
"""
import os
import sys
from pathlib import Path

WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(WORKDIR / "analysis"))
sys.path.insert(0, str(WORKDIR))

from html_report_v3 import _source_time  # noqa: E402

HINTS = ["margin", "融资", "两融"]
DEFAULT = "2026-09-07"


def _run_log(source_meta=None, sources=None):
    log = {}
    if source_meta is not None:
        log["source_meta"] = source_meta
    if sources is not None:
        log["sources"] = sources
    return log


# ============================================================
# 1. source_meta: 精确匹配 + 子串模糊匹配
# ============================================================
def test_source_meta_exact_key_match():
    """key_hint 精确命中 source_meta 的 label"""
    log = _run_log(source_meta={"融资融券": {"at": "2026-09-05 10:31:00"}})
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-05 10:31"


def test_source_meta_fuzzy_key_match():
    """label 不完全等于 key_hint 时按子串命中"""
    log = _run_log(source_meta={"两融历史-30日": {"at": "2026-09-04 08:00:00"}})
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-04 08:00"


def test_hint_order_wins_over_substring_scan():
    """精确匹配优先于子串扫描 (先精确、后模糊)"""
    log = _run_log(source_meta={
        "两融历史-30日": {"at": "2026-09-04 08:00:00"},   # 模糊命中
        "margin": {"at": "2026-09-06 09:00:00"},         # 精确命中
    })
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-06 09:00"


# ============================================================
# 2. source_meta 优先 + 老格式 sources 兜底
# ============================================================
def test_source_meta_primary_over_legacy_sources():
    """两边都有 dict 型时点时, source_meta 优先"""
    log = _run_log(
        source_meta={"融资融券": {"at": "2026-09-06 09:00:00"}},
        sources={"融资融券": {"at": "2026-01-01 00:00:00"}},
    )
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-06 09:00"


def test_legacy_dict_sources_used_as_fallback():
    """没有 source_meta 时, 老 run_log 的 dict 型 sources 仍可用"""
    log = _run_log(sources={"两融历史-30日": {"fetched_at": "2026-09-03 07:00:00"}})
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-03 07:00"


def test_string_status_in_sources_is_not_a_timestamp():
    """当前契约的字符串状态值不得被当成时点"""
    log = _run_log(sources={"融资融券": "ok, 1772ms", "两融历史": "error:超时, 0ms"})
    assert _source_time(log, HINTS, DEFAULT) == DEFAULT


def test_source_meta_miss_falls_through_to_legacy_dict():
    """source_meta 无匹配时, 继续查老格式 dict 型 sources"""
    log = _run_log(
        source_meta={"行情-K线": {"at": "2026-09-05 15:00:00"}},   # 与 key_hints 无关
        sources={"融资融券": {"as_of": "2026-09-02 06:00:00"}},
    )
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-02 06:00"


# ============================================================
# 3. 字段优先级 + 截断
# ============================================================
def test_timestamp_field_precedence():
    """as_of > at > fetched_at > ts > date > data_end > time (第一个非空)"""
    order = ("as_of", "at", "fetched_at", "ts", "date", "data_end", "time")
    values = dict(zip(order, "ABCDEFG"))
    # 逐个摘掉优先级更高的字段, 期望落到下一个
    for idx, expected in enumerate("ABCDEF"):
        blob = {k: v for k, v in values.items() if k not in order[:idx]}
        assert _source_time(_run_log(source_meta={"margin": blob}), HINTS, DEFAULT) == expected
    # 只剩优先级最低的 time
    assert _source_time(
        _run_log(source_meta={"margin": {"time": "2026-09-01 08:00"}}), HINTS, DEFAULT
    ) == "2026-09-01 08:00"


def test_empty_field_value_is_skipped():
    """空串/None 不算时点, 继续往后找"""
    log = _run_log(source_meta={"margin": {"as_of": "", "at": None, "ts": "2026-09-01 12:00"}})
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-01 12:00"


def test_timestamp_truncated_to_16_chars():
    """秒级时间戳截断到分钟 (16 字符)"""
    log = _run_log(source_meta={"融资融券": {"at": "2026-09-05 10:31:45.123456+08:00"}})
    assert _source_time(log, HINTS, DEFAULT) == "2026-09-05 10:31"


# ============================================================
# 4. default 兜底
# ============================================================
def test_default_when_no_timestamp_available():
    """无任何可用时点时返回调用方传入的 default"""
    assert _source_time(_run_log(), HINTS, DEFAULT) == DEFAULT
    assert _source_time(_run_log(source_meta={}, sources={}), HINTS, DEFAULT) == DEFAULT
    assert _source_time(_run_log(source_meta={"行情": {"ms": 12}}), HINTS, DEFAULT) == DEFAULT
    # 非 dict 输入 / 字段类型异常都不崩
    assert _source_time(None, HINTS, DEFAULT) == DEFAULT
    assert _source_time("not-a-log", HINTS, DEFAULT) == DEFAULT
    assert _source_time(_run_log(source_meta="bad", sources=["bad"]), HINTS, DEFAULT) == DEFAULT


def test_default_none_is_preserved():
    """调用方传 None (用于 `or chip_t or report_date` 链式兜底) 时保持 None"""
    log = _run_log(source_meta={"行情": {"at": "2026-09-05 15:00:00"}})
    assert _source_time(log, HINTS, None) is None
