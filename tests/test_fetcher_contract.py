"""fetcher 数据返回契约测试 (P0-B, 2026-09-11, 规范 §4)

测试 analysis/fetcher_contract.py:
- 4 状态构造器 (ok/empty/error/unsupported)
- 错误对象稳定错误码
- status_of / is_error / is_empty / is_ok / is_unsupported 检测
- from_legacy 适配老 ad-hoc 格式
"""
import os
import sys
import json

sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")

import pytest

from analysis.fetcher_contract import (
    STATUS_OK, STATUS_EMPTY, STATUS_ERROR, STATUS_UNSUPPORTED,
    VALID_STATUSES,
    ERR_NET_TIMEOUT, ERR_NET_SSL, ERR_PARSE, ERR_VALIDATION, ERR_UNSUPPORTED, ERR_UNKNOWN,
    make_error, make_result, make_ok, make_empty, make_error_result, make_unsupported,
    status_of, is_error, is_empty, is_ok, is_unsupported, from_legacy,
)


# ============================================================
# 1. 4 状态枚举 + 错误码常量
# ============================================================
def test_status_constants():
    """§4 4 状态常量"""
    assert STATUS_OK == "ok"
    assert STATUS_EMPTY == "empty"
    assert STATUS_ERROR == "error"
    assert STATUS_UNSUPPORTED == "unsupported"
    assert VALID_STATUSES == {"ok", "empty", "error", "unsupported"}


def test_error_codes_stable():
    """§4 '稳定错误码'"""
    assert ERR_NET_TIMEOUT == "NET_TIMEOUT"
    assert ERR_NET_SSL == "NET_SSL"
    assert ERR_PARSE == "PARSE"
    assert ERR_VALIDATION == "VALIDATION"
    assert ERR_UNSUPPORTED == "UNSUPPORTED"
    assert ERR_UNKNOWN == "UNKNOWN"


# ============================================================
# 2. 构造器
# ============================================================
def test_make_ok_basic():
    """make_ok 构造标准成功返回"""
    r = make_ok({"rows": [1, 2]}, source="eastmoney.datacenter", as_of="2026-09-11")
    assert r["status"] == "ok"
    assert r["data"] == {"rows": [1, 2]}
    assert r["source"] == "eastmoney.datacenter"
    assert r["as_of"] == "2026-09-11"
    assert r["fetched_at"] is not None
    assert r["scope"] == "stock"
    assert r["error"] is None


def test_make_empty_basic():
    """make_empty 业务确认无记录 (status=empty, error code=VALIDATION retryable=False)"""
    r = make_empty(source="sina.news", reason="该期间无新闻")
    assert r["status"] == "empty"
    assert r["data"] is None
    assert r["source"] == "sina.news"
    assert r["error"]["code"] == ERR_VALIDATION
    assert r["error"]["retryable"] is False
    assert "无新闻" in r["error"]["message"]


def test_make_error_basic():
    """make_error_result 网络/解析失败 (status=error, code+message+retryable)"""
    r = make_error_result(ERR_NET_TIMEOUT, "连接 15s 超时", source="push2his", retryable=True)
    assert r["status"] == "error"
    assert r["data"] is None
    assert r["error"]["code"] == "NET_TIMEOUT"
    assert r["error"]["message"] == "连接 15s 超时"
    assert r["error"]["retryable"] is True


def test_make_unsupported_basic():
    """make_unsupported 标的不支持 (e.g. 小盘无融资融券)"""
    r = make_unsupported(source="eastmoney.margin", reason="小盘无融资融券")
    assert r["status"] == "unsupported"
    assert r["error"]["code"] == ERR_UNSUPPORTED
    assert r["error"]["retryable"] is False


def test_make_error_message_truncated():
    """§4 错误消息最大 200 字符 (避免泄露完整响应)"""
    long_msg = "x" * 500
    r = make_error_result(ERR_UNKNOWN, long_msg)
    assert len(r["error"]["message"]) == 200


def test_make_result_rejects_invalid_status():
    """非 4 状态值应抛 ValueError"""
    with pytest.raises(ValueError):
        make_result(status="unknown", data={})


# ============================================================
# 3. 检测函数
# ============================================================
def test_status_of_new_contract():
    """新契约 blob 直接读 status 字段"""
    assert status_of({"status": "ok", "data": {}}) == "ok"
    assert status_of({"status": "error", "error": {"code": "X"}}) == "error"
    assert status_of({"status": "empty"}) == "empty"
    assert status_of({"status": "unsupported"}) == "unsupported"


def test_status_of_legacy():
    """老 ad-hoc 格式推导 status (§4 迁移期兼容)"""
    assert status_of({"error": "timeout", "rows": []}) == "error"
    assert status_of({"error": "no data", "rows": []}) == "error"
    assert status_of({"rows": [{"a": 1}]}) == "ok"
    assert status_of({"rows": []}) == "empty"
    assert status_of({"data": [{"x": 1}]}) == "ok"
    assert status_of({"data": []}) == "empty"
    assert status_of(None) is None
    assert status_of("not a dict") is None


def test_is_error_combines_new_and_legacy():
    """is_error 同时识别新契约 status=error + 老 ad-hoc {'error': str}"""
    assert is_error({"status": "error", "error": {"code": "X"}}) is True
    assert is_error({"error": "fail", "rows": []}) is True
    assert is_error({"status": "ok", "data": {}}) is False
    assert is_error({"rows": [1]}) is False
    assert is_error({"rows": []}) is False  # empty 不是 error
    assert is_error(None) is True  # None 视为错误


def test_is_empty_distinguishes_from_error():
    """§4 '空记录集通常应标为 empty' — 跟 error 区分"""
    assert is_empty({"status": "empty"}) is True
    assert is_empty({"rows": []}) is True
    assert is_empty({"data": []}) is True
    assert is_empty({"status": "error"}) is False
    assert is_empty({"error": "x"}) is False  # 老 ad-hoc + rows=[] 是 empty 还是 error?
    # 文档: 老 ad-hoc {"error": str} 视作 error (有 error 字段), 即便 rows=[]
    assert is_empty({"error": "x", "rows": []}) is False


def test_is_ok_and_unsupported():
    """is_ok / is_unsupported 基础"""
    assert is_ok({"status": "ok", "data": []}) is True
    assert is_ok({"rows": [1]}) is True
    assert is_unsupported({"status": "unsupported"}) is True
    assert is_unsupported({"status": "ok"}) is False


# ============================================================
# 4. from_legacy adapter (§4 迁移期兼容)
# ============================================================
def test_from_legacy_passthrough_new_contract():
    """已经是新契约的 blob 直接返回 (不重复包装)"""
    new = {"status": "ok", "data": [1, 2], "source": "x", "as_of": None}
    assert from_legacy(new) is new


def test_from_legacy_error_format():
    """老 {'error': 'msg'} 格式 → 新 status=error"""
    legacy = {"error": "推送超时", "rows": []}
    r = from_legacy(legacy, source="eastmoney.fflow")
    assert r["status"] == "error"
    assert r["error"]["code"] == ERR_UNKNOWN
    assert "推送超时" in r["error"]["message"]
    assert r["source"] == "eastmoney.fflow"


def test_from_legacy_rows_with_data():
    """老 {'rows': [...]} 有数据 → status=ok, data={rows: [...]}"""
    legacy = {"rows": [{"a": 1}, {"a": 2}]}
    r = from_legacy(legacy, source="ths")
    assert r["status"] == "ok"
    assert r["data"]["rows"] == [{"a": 1}, {"a": 2}]


def test_from_legacy_rows_empty():
    """老 {'rows': []} 但无 error 字段 → 视为 empty"""
    legacy = {"rows": []}
    r = from_legacy(legacy, source="sina")
    assert r["status"] == "empty"
    assert r["error"]["code"] == ERR_VALIDATION


def test_from_legacy_none():
    """None → error (UNKNOWN, retryable=False)"""
    r = from_legacy(None)
    assert r["status"] == "error"
    assert r["error"]["code"] == ERR_UNKNOWN
    assert r["error"]["retryable"] is False


def test_from_legacy_string_blob():
    """非 dict 类型 → error (VALIDATION)"""
    r = from_legacy("not a dict")
    assert r["status"] == "error"
    assert r["error"]["code"] == ERR_VALIDATION


# ============================================================
# 5. 跟 quant_analyzer_v3 实测 fetcher 端到端 (4 fetcher 入仓后)
# ============================================================
def test_v3_fetcher_import_compat_with_contract():
    """v3 import 4 fetcher 后, 包 from_legacy 仍能正确分类"""
    # 模拟老 fetcher 返回
    legacy_error = {"error": "东财超时", "rows": []}
    legacy_ok = {"rows": [{"title": "公告1"}]}

    assert from_legacy(legacy_error)["status"] == "error"
    assert from_legacy(legacy_ok)["status"] == "ok"


def test_four_fetchers_status_zh():
    """4 fetcher (announcements/finance/research/news_em) 走 from_legacy 应正常分类"""
    # 模拟 4 fetcher 在 V3 中的典型返回
    samples = {
        "公告":   {"announcements": [{"title": "公告1", "date": "2026-09-10"}], "as_of": "2026-09-10"},
        "财务":   {"finance": {"latest": {"report_date": "2026-06-30"}}, "as_of": "2026-09-10"},
        "研报":   {"reports": [{"机构": "中信", "评级": "买入"}], "as_of": "2026-09-10"},
        "新闻":   {"news": [{"title": "新闻1", "date": "2026-09-10"}], "as_of": "2026-09-10"},
    }
    for name, sample in samples.items():
        # 这些是 ad-hoc (有 data 但无 status), 走 from_legacy
        r = from_legacy(sample, source=f"test.{name}")
        # 视为 ok (有数据)
        assert r["status"] == "ok", f"{name} should be ok, got {r['status']}"
        assert r["source"] == f"test.{name}"
