"""巨潮 orgId 缓存 24h 刷新策略测试（p2_4_orgid_cache）

覆盖 4 个场景，全部隔离且零网络访问：
1. 新鲜缓存命中 → 不发起任何请求；
2. TTL 到期 → 触发刷新并替换映射与时间戳；
3. 刷新失败（网络异常/非法响应）→ 保留并继续使用旧映射；
4. 首次拉取失败且无任何可用映射 → 回退硬编码 orgId 规则。
"""
import os
import sys
from pathlib import Path

import pytest

WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", str(Path(__file__).resolve().parents[1]))).resolve()
sys.path.insert(0, str(WORKDIR / "analysis"))

import fetch_announcements as fa  # noqa: E402


class _FakeResponse:
    """最小 requests.Response 替身。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _payload(mapping):
    return {"stockList": [{"code": c, "orgId": o} for c, o in mapping.items()]}


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """每个用例从空缓存 + 空时间戳开始，杜绝跨用例污染。"""
    monkeypatch.setattr(fa, "_CNINFO_ORGID_MAP", {}, raising=True)
    monkeypatch.setattr(fa, "_CNINFO_ORGID_FETCHED_AT", None, raising=True)

    def _boom(*_a, **_kw):
        raise AssertionError("测试不得访问网络")

    monkeypatch.setattr(fa.requests, "get", _boom)
    yield


def test_fresh_cache_hit_does_not_refetch(monkeypatch):
    """缓存未过期 → 直接命中，不发起任何请求。"""
    monkeypatch.setattr(fa, "_CNINFO_ORGID_MAP", {"601398": "jjxt0000019"}, raising=True)
    monkeypatch.setattr(fa, "_CNINFO_ORGID_FETCHED_AT", fa.time.monotonic(), raising=True)

    assert fa._cninfo_orgid("601398") == "jjxt0000019"
    assert fa._cninfo_orgid_cache_expired() is False


def test_expired_cache_triggers_refresh(monkeypatch):
    """TTL 到期 → 重新拉取，映射与时间戳一并更新。"""
    now = 1_000_000.0
    monkeypatch.setattr(fa.time, "monotonic", lambda: now, raising=True)
    monkeypatch.setattr(fa, "_CNINFO_ORGID_MAP", {"601398": "stale-org"}, raising=True)
    monkeypatch.setattr(fa, "_CNINFO_ORGID_FETCHED_AT",
                        now - fa.CNINFO_ORGID_TTL_SECONDS - 1, raising=True)
    assert fa._cninfo_orgid_cache_expired() is True

    calls = []

    def _fake_get(url, **_kw):
        calls.append(url)
        return _FakeResponse(_payload({"601398": "fresh-org", "603319": "9900051122"}))

    monkeypatch.setattr(fa.requests, "get", _fake_get)

    assert fa._cninfo_orgid("603319") == "9900051122"
    assert calls == [fa.CNINFO_ORGID_URL]
    assert fa._CNINFO_ORGID_MAP == {"601398": "fresh-org", "603319": "9900051122"}
    assert fa._CNINFO_ORGID_FETCHED_AT == now
    assert fa._cninfo_orgid_cache_expired() is False


def test_failed_refresh_keeps_stale_mapping(monkeypatch):
    """刷新失败（请求异常 / 空表）→ 旧映射与时间戳不变，且继续可用。"""
    now = 2_000_000.0
    monkeypatch.setattr(fa.time, "monotonic", lambda: now, raising=True)
    monkeypatch.setattr(fa, "_CNINFO_ORGID_MAP", {"601398": "stale-org"}, raising=True)
    old_stamp = now - fa.CNINFO_ORGID_TTL_SECONDS - 60
    monkeypatch.setattr(fa, "_CNINFO_ORGID_FETCHED_AT", old_stamp, raising=True)

    def _raise(*_a, **_kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(fa.requests, "get", _raise)
    assert fa._cninfo_orgid("601398") == "stale-org"       # 仍用旧值
    assert fa._CNINFO_ORGID_MAP == {"601398": "stale-org"}
    assert fa._CNINFO_ORGID_FETCHED_AT == old_stamp         # 时间戳未被污染

    # 非法响应（空表 / 缺 orgId）同样不得用空表覆盖旧缓存
    monkeypatch.setattr(fa.requests, "get", lambda *_a, **_kw: _FakeResponse({"stockList": []}))
    assert fa._cninfo_orgid("601398") == "stale-org"
    assert fa._CNINFO_ORGID_MAP == {"601398": "stale-org"}
    assert fa._CNINFO_ORGID_FETCHED_AT == old_stamp


def test_initial_fetch_failure_falls_back_to_hardcoded(monkeypatch):
    """首次拉取失败且无任何缓存 → 回退硬编码 gssx0{code} 规则。"""
    def _raise(*_a, **_kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(fa.requests, "get", _raise)
    assert fa._cninfo_orgid("601398") == "gssh0601398"
    assert fa._CNINFO_ORGID_MAP == {}
    assert fa._CNINFO_ORGID_FETCHED_AT is None

    # 沪指 000300 走白名单前缀 sz→sh 修正（格式 gs{prefix}0{code}，沿用既有规则）
    monkeypatch.setattr(fa.requests, "get", lambda *_a, **_kw: _FakeResponse({"stockList": []}))
    assert fa._cninfo_orgid("000300") == "gssh0000300"
