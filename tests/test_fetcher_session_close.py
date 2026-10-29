"""fetcher requests.Session 关闭契约测试 (行为级, 2026-10-05)

背景: analysis/fetch_announcements.py 与 analysis/fetch_research_reports.py 的私有
_fetch_eastmoney() 各自新建 requests.Session() 却不 close() → 连接池泄漏, 只能靠
GC 回收; 修法是改用 `with requests.Session() as sess:`, 让正常返回和异常退出都关池。

覆盖 4 个用例 = 2 模块 × {正常完成, HTTP 错误}:
  - 正常完成: stub Session 返回健康响应 → 断言 close() 被调用 (且只调一次)
  - HTTP 错误: stub 的 raise_for_status() 抛 requests.exceptions.HTTPError →
    断言异常照原样向上传播 **且** close() 仍被调用

异常路径直调模块私有 _fetch_eastmoney(), 不经公共入口:
fetch_announcements() / fetch_research_reports() 在上层把异常吞掉降级
(东财→巨潮 / 东财→同花顺), 从公共入口测根本看不到异常, 也就验不到 with 的
异常分支。

stub 按源码真实次序搭建: Session() → headers.update() → get() → raise_for_status()
→ json() → (with 退出) close()。纯行为断言, 不做源码文本断言, 不联网。
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 绝对 import: 仓库根加入 sys.path, 让 `import analysis.xxx` 生效 (同 conftest 注入)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import analysis.fetch_announcements as ann_mod
import analysis.fetch_research_reports as res_mod


# ============================================================
# stub: 记录调用次序的假 Session / Response
# ============================================================
class _Recorder:
    """跨一个用例的调用记录 (events 次序 + sessions 实例列表)。"""

    def __init__(self):
        self.events = []
        self.sessions = []

    def mark(self, what):
        self.events.append(what)


class _RecordingHeaders(dict):
    """代理 requests.Session.headers.update() 的调用次序。"""

    def __init__(self, recorder):
        super().__init__()
        self._recorder = recorder

    def update(self, *args, **kwargs):
        self._recorder.mark("headers.update()")
        return super().update(*args, **kwargs)


class _FakeResponse:
    """只实现源码真正用到的方法: raise_for_status() / json()。

    次序同真实 requests: 先 raise_for_status(), 通过了才 json();
    HTTP 错误时 json() 不会被调用 (与真实行为一致)。
    """

    def __init__(self, recorder, payload, http_error):
        self._recorder = recorder
        self._payload = payload
        self._http_error = http_error

    def raise_for_status(self):
        self._recorder.mark("raise_for_status()")
        if self._http_error is not None:
            raise self._http_error

    def json(self):
        self._recorder.mark("json()")
        return self._payload


class _FakeSession:
    """上下文管理器化的假 Session: with 退出必 close, 且不吞异常。"""

    def __init__(self, recorder, payload, http_error):
        self._recorder = recorder
        self._payload = payload
        self._http_error = http_error
        self.headers = _RecordingHeaders(recorder)
        self.closed = False
        self.close_calls = 0
        self.get_calls = []
        recorder.sessions.append(self)
        recorder.mark("Session()")

    def __enter__(self):
        self._recorder.mark("__enter__()")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False                    # 异常照原样传播, 不在会话层吞

    def close(self):
        self.close_calls += 1
        self.closed = True
        self._recorder.mark("close()")

    def get(self, url, params=None, headers=None, timeout=None):
        self._recorder.mark("get()")
        self.get_calls.append({
            "url": url, "params": params, "headers": headers, "timeout": timeout,
        })
        return _FakeResponse(self._recorder, self._payload, self._http_error)


def _install_session(monkeypatch, payload, http_error=None):
    """把目标模块的 requests.Session 换成 stub; 返回 recorder。"""
    recorder = _Recorder()

    def _factory(*args, **kwargs):
        return _FakeSession(recorder, payload, http_error)

    # 模块内是 `import requests` + `requests.Session()`, 故打在这里的绑定点
    monkeypatch.setattr(ann_mod.requests, "Session", _factory)
    return recorder


# ============================================================
# 健康响应 fixture (按源码读的字段搭, 不做源码文本断言)
# ============================================================
def _ann_payload():
    """东财公告: data.list[]; 第一条在窗口内, 第二条远早于窗口 → 翻页提前停。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return {"data": {"list": [
        {
            "art_code": "AN20261005001",
            "title": "关于股份回购进展的公告",
            "notice_date": today + " 09:30:00",
            "columns": [{"column_code": "s_szsh", "column_name": "公司公告"}],
            "codes": [{"stock_code": "603319"}],
        },
        {
            "art_code": "AN20190102001",
            "title": "很久以前的公告",
            "notice_date": "2019-01-02 10:00:00",
            "columns": [],
            "codes": [{"stock_code": "603319"}],
        },
    ]}}


def _res_payload():
    """东财研报: data[] + TotalPage=1 → 一页即止, 不触发限流 sleep。"""
    return {
        "TotalPage": 1,
        "data": [{
            "publishDate": (date.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
            "orgSName": "山西证券",
            "title": "603319 深度报告",
            "emRatingName": "增持",
            "predictNextYearEps": "1.23",
        }],
    }


def _assert_closed_once(recorder, module_label):
    """close() 恰好调一次, 且在 Session()/get() 之后。"""
    assert len(recorder.sessions) == 1, f"{module_label}: 每次拉取应只建一个 Session"
    sess = recorder.sessions[0]
    assert sess.closed is True, f"{module_label}: with 退出后 session 未关闭"
    assert sess.close_calls == 1, f"{module_label}: close() 应恰好 1 次, 实际 {sess.close_calls}"
    ev = recorder.events
    assert ev[0] == "Session()" and ev[1] == "__enter__()", f"{module_label}: 次序 {ev}"
    assert ev[-1] == "close()", f"{module_label}: close() 应是最后一个事件, 实际 {ev}"
    assert "get()" in ev, f"{module_label}: 未发生请求, 事件 {ev}"


# ============================================================
# 1) 公告 fetcher —— 正常完成
# ============================================================
def test_announcements_eastmoney_closes_session_on_success(monkeypatch):
    """东财正常返回: with 退出关池; URL/timeout/params/UA 保持原样。"""
    recorder = _install_session(monkeypatch, _ann_payload())

    out = ann_mod._fetch_eastmoney("603319", 30)

    _assert_closed_once(recorder, "fetch_announcements")
    assert len(out) == 1, f"窗口内应只剩 1 条, 实际 {len(out)}"
    assert out[0]["date"] == datetime.now().strftime("%Y-%m-%d")
    assert "AN20261005001" in out[0]["url"]
    # 请求参数未被顺手改动
    call = recorder.sessions[0].get_calls[0]
    assert call["url"] == ann_mod.EM_URL
    assert call["timeout"] == 20
    assert call["headers"] == {"User-Agent": ann_mod.UA}
    assert call["params"]["stock_list"] == "603319"
    assert call["params"]["page_index"] == 1
    # 公告源走每请求 headers, 不碰 session 级 headers
    assert "headers.update()" not in recorder.events


# ============================================================
# 2) 公告 fetcher —— HTTP 异常
# ============================================================
def test_announcements_eastmoney_closes_session_on_http_error(monkeypatch):
    """HTTP 错误: 异常向上传播 (直调私有函数), 且仍关池。"""
    err = ann_mod.requests.exceptions.HTTPError("503 Server Error")
    recorder = _install_session(monkeypatch, _ann_payload(), http_error=err)

    with pytest.raises(ann_mod.requests.exceptions.HTTPError):
        ann_mod._fetch_eastmoney("603319", 30)

    _assert_closed_once(recorder, "fetch_announcements(err)")
    # 与真实 requests 一致: raise_for_status 抛了, json() 不会被调用
    assert "json()" not in recorder.events
    assert recorder.events[-2] == "raise_for_status()", recorder.events


# ============================================================
# 3) 研报 fetcher —— 正常完成
# ============================================================
def test_research_reports_eastmoney_closes_session_on_success(monkeypatch):
    """东财研报正常返回: with 退出关池; headers.update 在 with 内、get 之前。"""
    recorder = _install_session(monkeypatch, _res_payload())
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")

    result = res_mod._fetch_eastmoney("603319", 90, fetched_at)

    _assert_closed_once(recorder, "fetch_research_reports")
    assert result["source"] == "eastmoney"
    assert result["count"] == 1
    assert result["reports"][0]["rating"] == "增持"
    assert result["reports"][0]["target_price"] == 1.23
    # session 级 UA 必须在会话存活期内写入 (with 之内)
    ev = recorder.events
    assert ev.index("headers.update()") < ev.index("get()"), f"次序 {ev}"
    assert recorder.sessions[0].headers.get("User-Agent") == res_mod.UA
    # 请求参数未被顺手改动
    call = recorder.sessions[0].get_calls[0]
    assert call["url"] == res_mod.REPORT_API
    assert call["timeout"] == 30
    assert call["headers"] == {"Referer": "https://data.eastmoney.com/"}
    assert call["params"]["code"] == "603319"
    assert call["params"]["qType"] == "0"
    assert call["params"]["pageNo"] == "1"


# ============================================================
# 4) 研报 fetcher —— HTTP 异常
# ============================================================
def test_research_reports_eastmoney_closes_session_on_http_error(monkeypatch):
    """HTTP 错误: 异常向上传播 (直调私有函数), 且仍关池。"""
    err = res_mod.requests.exceptions.HTTPError("502 Bad Gateway")
    recorder = _install_session(monkeypatch, _res_payload(), http_error=err)
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")

    with pytest.raises(res_mod.requests.exceptions.HTTPError):
        res_mod._fetch_eastmoney("603319", 90, fetched_at)

    _assert_closed_once(recorder, "fetch_research_reports(err)")
    assert "json()" not in recorder.events
    assert recorder.events[-2] == "raise_for_status()", recorder.events


# ============================================================
# 5) 公共入口不回归: 异常仍被上层吞掉并降级 (不因 with 改动而冒出异常)
# ============================================================
def test_public_entry_still_swallows_and_falls_back(monkeypatch):
    """回归护栏: 公共入口行为不变 —— 主源 HTTP 错误被上层吞掉并降级, 不向外抛。

    公共入口的 except 兜底本来就在 (本次只动缩进), 这里钉住它没被 with 改坏。
    """
    # 预置 orgId 映射, 让巨潮路径不触发任何 requests.get
    monkeypatch.setattr(ann_mod, "_CNINFO_ORGID_MAP", {"603319": "gssh0603319"})

    def _em_boom(*a, **k):
        return _FakeSession(_Recorder(), None,
                            ann_mod.requests.exceptions.HTTPError("500"))

    # 公告 part A: 东财抛 → 吞掉 → 降级巨潮健康但窗口内无公告 (count=0, 非 error)
    monkeypatch.setattr(ann_mod.requests, "Session", _em_boom)
    monkeypatch.setattr(ann_mod.requests, "post",
                        lambda url, data=None, headers=None, timeout=None:
                        _FakeResponse(_Recorder(), {"announcements": []}, None))
    ann_res = ann_mod.fetch_announcements("603319", days=30)
    assert ann_res.get("source") == "cninfo", f"应降级到巨潮: {ann_res}"
    assert ann_res.get("count") == 0 and "error" not in ann_res

    # 公告 part B: 东财 + 巨潮都抛 → 返回 error dict, 两个源名都留痕
    def _cninfo_boom(url, data=None, headers=None, timeout=None):
        raise ann_mod.requests.exceptions.ConnectionError("cninfo down")

    monkeypatch.setattr(ann_mod.requests, "post", _cninfo_boom)
    ann_res = ann_mod.fetch_announcements("603319", days=30)
    assert "error" in ann_res
    assert "eastmoney" in ann_res["error"] and "cninfo" in ann_res["error"]

    # 研报: 东财抛 → 吞掉 → 同花顺也抛 → 仍返回 error dict 而非向外抛
    monkeypatch.setattr(res_mod.requests, "Session",
                        lambda *a, **k: _FakeSession(
                            _Recorder(), None,
                            res_mod.requests.exceptions.HTTPError("500")))

    def _ths_boom(url, headers=None, timeout=None):
        raise res_mod.requests.exceptions.ConnectionError("ths down")

    monkeypatch.setattr(res_mod.requests, "get", _ths_boom)
    res = res_mod.fetch_research_reports("603319", days=90)
    assert "error" in res
    assert "东财主源失败" in res["error"]
