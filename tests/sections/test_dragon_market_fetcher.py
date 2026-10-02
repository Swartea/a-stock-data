"""§3.9 dragon_market fetcher 单元测试

全部测试通过 monkeypatch 固定时钟与 _raw_fetch，绝不触达线上端点。
"""
import sys
from datetime import datetime as _real_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))

from sections.dragon_market import fetcher


class _FrozenDatetime(_real_datetime):
    """把 now() 钉在固定时刻的 datetime 子类"""

    FROZEN = None  # 测试内设置

    @classmethod
    def now(cls, tz=None):
        return cls.FROZEN


def _payload(n=3):
    return {
        "stocks": [
            {"code": f"60000{i}", "name": f"股票{i}", "net_buy": i}
            for i in range(n)
        ],
        "total_records": n,
    }


def _patch(monkeypatch, frozen_iso):
    """固定时钟 + 拦截 _raw_fetch，返回捕获到的 date 列表"""
    _FrozenDatetime.FROZEN = _real_datetime.fromisoformat(frozen_iso)
    monkeypatch.setattr(fetcher, "datetime", _FrozenDatetime)

    seen = []

    def fake_raw_fetch(date):
        seen.append(date)
        return _payload()

    monkeypatch.setattr(fetcher, "_raw_fetch", fake_raw_fetch)
    return seen


def test_default_date_resolves_today_at_call_time(monkeypatch):
    """不传 date 时，动态解析为调用当日的 YYYYMMDD"""
    seen = _patch(monkeypatch, "2026-10-02T09:30:00")

    result = fetcher.fetch_dragon_market()

    assert seen == ["20261002"], f"应把当日 YYYYMMDD 传给 _raw_fetch，实际 {seen}"
    assert "error" not in result


def test_default_date_tracks_每_call_的当前时刻(monkeypatch):
    """连续两次调用分别解析各自时刻的当日日期（非硬编码）"""
    seen = _patch(monkeypatch, "2026-10-02T09:30:00")
    fetcher.fetch_dragon_market()

    _FrozenDatetime.FROZEN = _real_datetime.fromisoformat("2027-01-15T23:59:00")
    fetcher.fetch_dragon_market()

    assert seen == ["20261002", "20270115"], f"默认日期应随调用时刻变化，实际 {seen}"
    assert "20260904" not in seen, "不得再回落到 brief 示例日期 20260904"


def test_explicit_date_passthrough_is_not_overridden(monkeypatch):
    """显式 date= 原样透传给 _raw_fetch，不被动态默认覆盖"""
    seen = _patch(monkeypatch, "2026-10-02T09:30:00")

    result = fetcher.fetch_dragon_market(date="20250102")

    assert seen == ["20250102"], f"显式 date 应原样透传，实际 {seen}"
    assert "error" not in result


def test_explicit_date_with_top_n_sorts_and_truncates(monkeypatch):
    """显式 date 与 top_n 组合：按 net_buy 降序并截断"""
    _patch(monkeypatch, "2026-10-02T09:30:00")

    result = fetcher.fetch_dragon_market(date="20250102", top_n=2)

    codes = [s["code"] for s in result["stocks"]]
    assert codes == ["600002", "600001"], f"应取 Top 2 降序，实际 {codes}"
    assert result["total_records"] == 3


def test_stale_example_date_absent_from_source():
    """源码中不再硬编码 brief 示例日期 20260904"""
    src = Path(fetcher.__file__).read_text(encoding="utf-8")
    assert "20260904" not in src, "fetcher 源码仍含过期示例日期 20260904"
