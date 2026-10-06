"""资金流-5日主力 (东财 push2his fflow daykline) 域回归。

模块分层 (见 analysis/data_fetcher.py):
- fetch_fund_flow_daily / _fetch_fund_flow_daily: 真正联网的抓取 (经 v2.em_get);
- 解析/派生 (rows / chg_pct / total_main_yi / start / end) 全部是**纯函数**逻辑, 只吃
  v2.em_get(...).json() 返回的 dict。

所以隔离策略是两段:
1. 那条 live 用例 (test_fund_flow_daily_uses_push2his) 打 @pytest.mark.live +
   integration + 精确 "1" 的 skipif —— 双重 opt-in, 默认不选、不跑、零网络;
2. 其余全部是**离线**回归: monkeypatch 把 data_fetcher 持有的 v2.em_get 换成固定桩,
   直接喂 push2his 响应, 覆盖处理逻辑 / 边界 / 结果。离线用例不打 live 标记。

再加一道**模块级 autouse 网络哨兵** (no_network_tripwire): 本文件**每条**用例 (含那条
live 用例) 运行时都封死 socket 建连与 DNS 解析, 且**不给 live 留豁免分支** —— 门禁只
认"v2.em_get 已被桩接管"这一种安全状态。

F1 假绿整改后, 显式 live 的形态是"**用例体自己把 em_get 打成桩**": `DA_A_RUN_LIVE=1
pytest -m live` 在本模块内**通过** (passed), 因为那条 live 用例第一件事就是自己 monkeypatch
data_fetcher.v2.em_get 并喂确定性 canned 响应, 全程零真实 DNS/建连/HTTP (实测: 独立外层
socket/DNS/HTTP 哨兵命中 0, C 层审计事件 0)。**本文件没有任何一条用例会真打 push2his**,
哨兵也不因 live 标记而开口子; 真联网验收请在本模块之外做。

一个易错点: data_fetcher 用的是 `import analysis.quant_analyzer_v2 as v2` (包路径),
与顶层 `import quant_analyzer_v2` 是**两个不同模块对象**。桩必须打在 data_fetcher
实际持有的那个 v2 (df.v2) 上, 否则桩根本不生效、测试会偷偷真联网 —— 这条 live 用例
同样受这条约束, 它的自打桩也必须落在 df.v2.em_get 上。

live gate 的**全局行为** (选不选 = tests/conftest.py 的 collection 层门禁; 跑不跑 =
DA_A_RUN_LIVE 精确等于 "1" 的 env 门禁) 已由 tests/test_peg_formula.py 完整覆盖, 本文件
**不再重测那套全局子进程矩阵** —— 它验的是同一个 conftest 钩子, 与本文件无关。

本文件只保留 fund-flow 独有的两点 (同进程完成, 不起子进程):
- 本文件那条 live 用例自身的标记契约 (integration + live + skipif = not _live_enabled());
- 它的函数体在**自打桩**下的执行契约 (恰好 1 次调用 + 完整请求契约 + 成功数据), 由那条
  live 用例自己实现; 默认套件再由 test_live_test_body_only_reaches_stubbed_em_get 复用
  **同一个函数体** 跑一遍 stubbed smoke —— 同一个逻辑体、同一套断言, 不是两份实现。

数字口径 —— 下面这四个数**互不等同**, 别混着用 (尤其别把"子进程启动次数"当"用例数"):
- **17** = 被删掉的那套 peg 风格矩阵里的 **pytest 子进程启动次数** (每次 `python -m pytest`
  拉一个解释器, 是运行开销指标, 与用例数无关);
- **19** = 那一轮**移除的旧 test node 总数** (用例节点口径);
- **2**  = 那一轮**新加入的 test node 数** (test_live_test_is_double_opt_in_and_off_by_default、
  test_live_test_body_only_reaches_stubbed_em_get);
- **17** = 本文件 test node 的**净减少** = 19 - 2。
"17" 同时是子进程启动次数和净减少节点数, 纯属同数巧合, 两者无因果关系。
本轮 (tripwire 改 autouse 等) 的节点变化单独记, 不并入上面那组历史数字: 本轮唯一的新增
test node 是 test_kline_helper_blank_close_keeps_nine_fields_offline (夹具 9 段形状回归);
tripwire 改 autouse 本身只加一个 fixture、不加节点。
当前口径 = **共收集 24** (18 个 test_ 函数; 两个 parametrize 分别展开 3 条与 5 条), 默认套件
**23 passed / 1 deselected**, 被 deselect 的那条是 test_fund_flow_daily_uses_push2his。
上面历史里那个 "节点数不变 = 23 (默认 22 跑 + 1 deselect)" 说的是 F1 整改那一轮 (live 用例
自打桩 + smoke 复用同一逻辑体) —— 那一轮确实没动节点, 变的是 live 用例的执行契约与假绿面,
不是覆盖面; 它已被上面 +1 那条推到 24, 别再当现状引用。
"""
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "analysis"))
sys.path.insert(0, str(_REPO_ROOT))

import quant_analyzer_v3 as v3  # noqa: E402  (保持原文件的 v3 引用)

import analysis.data_fetcher as data_fetcher  # noqa: E402  桩打在 df.v2 上

# ============================================================
# live gate 第二步: DA_A_RUN_LIVE 精确等于 1 才算开 (与 peg 回归同契约)
# ============================================================
_LIVE_ENV = "DA_A_RUN_LIVE"


def _live_enabled(env=None) -> bool:
    """只有 DA_A_RUN_LIVE **精确为 "1"** 才算开 (0/空/未设置/真值串一律关闭)。"""
    source = os.environ if env is None else env
    return source.get(_LIVE_ENV) == "1"


# ============================================================
# 生产请求契约 —— 逐字取自 analysis/data_fetcher.py:36-46 的实际调用, 不臆造
# ============================================================
_PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_FIELDS1 = "f1,f2,f3,f7"
_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f12"
_REFERER = "https://quote.eastmoney.com/"
_ORIGIN = "https://quote.eastmoney.com"
_TIMEOUT = 15


# ============================================================
# 离线夹具: 桩掉 data_fetcher.v2.em_get, 禁止真实联网
# ============================================================
class _NetworkTripped(AssertionError):
    """autouse 网络哨兵命中时抛的异常。

    继承 AssertionError 只是为了让它在输出/`-x` 流程里读起来仍像断言失败。**自检必须
    用 `pytest.raises(_NetworkTripped)` 而不是 `pytest.raises(AssertionError)`**: 后者
    会被任何无关的 AssertionError 冒充 —— 典型是 CI 外层 socket 哨兵抛的
    "[outer sentinel] ..." 也是 AssertionError, 于是"哨兵到底 arm 了没有"这条证据
    会被外层哨兵顶包, 去掉 autouse 也能照样通过 (已实测过这个漏法)。独立异常类型让
    "内层哨兵已生效"这件事无法被别的 AssertionError 伪造。
    """


class _Resp:
    """最小 response 替身: 只提供 .json(), 让 fetch 只吃数据不碰网络。"""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


# 缺收盘价时占据 p[7] 的**显式空值标记**: 生产解析 (analysis/data_fetcher.py) 判
# `p[7] not in ("", "None", "null")` 才 float(), 选 "" 是与该分支逐字同构的写法。
_BLANK_CLOSE = ""


def _kline(date, main, large, super_large, close):
    """拼一条 push2his fflow daykline 记录 (逗号分隔, 与生产解析同构)。

    **任何输入都固定返回 9 段** (p[0]..p[8]), close=None 也不例外: 那时 p[7] 写成显式
    空值标记 `_BLANK_CLOSE`, p[8] 仍是 f12=600693。

    这条"固定 9 段"是被验收抓出来的夹具陷阱: 早先的写法在 close=None 时**整段省掉
    p[7]**, 于是 parts 只剩 8 项, 尾部 "600693" 滑到 p[7] —— 生产解析的
    `float(p[7])` 会把股票代码当成收盘价 close=600693.0。这类假值不抛异常, 只会安静地
    污染 close/chg_pct 派生, 比直接崩更难归因。保住段位比"少写一段像真实老格式"重要:
    行截断 (len=7) 那条用例另写显式 parts, 不走这个 helper。

    末段固定写 f12=600693 而不是参数化: 生产解析只用 p[0]/p[1]/p[4]/p[5]/p[7], 尾段与
    取值无关, 但保留它才能维持真实响应的 9 段形状 (顺带覆盖"尾部多余段被忽略")。
    """
    parts = [date, str(main), "0", "0", str(large), str(super_large), "0",
             _BLANK_CLOSE if close is None else str(close), "600693"]
    assert len(parts) == 9, "夹具必须恒为 9 段, 否则 f12 会滑进 p[7] 被当成 close"
    return ",".join(parts)


def _new_stub_state():
    return {"mode": "response", "payload": None, "exc": None, "seq": None, "i": 0}


def _install_recording_em_get(monkeypatch, state, calls):
    """把 data_fetcher 实际持有的 v2.em_get 换成记录型桩, 并短路 fetch 的退避 sleep。

    这是本文件**唯一**的桩实现: 离线用例经 stub_em_get fixture 用它, 那条 live 用例经
    _install_canned_em_get 直接用它 —— 同一份记录逻辑 (含 kwargs 原样记录), live 用例
    的请求契约断言才有资格套用同一套口径, 而不是另写一份会漂移的副本。

    桩只能、也必须打在 df.v2 上 (见模块 docstring)。桩不触网 —— autouse 的
    no_network_tripwire 仍封死 socket/DNS 出口, 离线回归靠的是"只喂固定数据",
    不是"容忍真网络"。

    额外 kwarg **原样记录**进 calls[i]["kwargs"]: 请求契约要锁的是"完整调用形态",
    url/params/headers/timeout 之外再冒出任何 kwarg (改 verify / 加重试 / 带代理…)
    都属于悄悄改了生产请求, 必须被契约测试当场抓住, 不能在 **kwargs 里被吃掉。
    """
    def _fake_em_get(url, params=None, headers=None, timeout=15, **kwargs):
        calls.append({"url": url, "params": dict(params or {}),
                      "headers": dict(headers or {}), "timeout": timeout,
                      "kwargs": dict(kwargs)})
        i = len(calls) - 1
        if state["mode"] == "exception":
            raise state["exc"]
        if state["mode"] == "sequence":
            seq = state["seq"]
            payload = seq[min(i, len(seq) - 1)]  # 末位复用
        else:
            payload = state["payload"]
        return _Resp(payload)

    monkeypatch.setattr(data_fetcher.v2, "em_get", _fake_em_get)
    # fetch 里有 0.6/1.2s 退避 sleep; 离线桩不应真等, 直接短路。
    monkeypatch.setattr(data_fetcher.time, "sleep", lambda *_a, **_k: None)
    return calls


def _install_canned_em_get(monkeypatch, payload):
    """自打桩入口: 只需一份确定性 payload, 返回记录型桩的 calls 列表。

    live 用例靠它就地封掉唯一网络出口 (df.v2.em_get), 且**不依赖任何 fixture** ——
    桩装在用例自己体内, "忘了打桩还能看起来通过"这条路被从结构上堵死 (那正是 F1)。
    """
    state = _new_stub_state()
    state["payload"] = payload
    return _install_recording_em_get(monkeypatch, state, [])


@pytest.fixture
def stub_em_get(monkeypatch):
    """离线用例的桩入口: 返回一个 (response | exception | sequence) 注册器 + calls 列表。"""
    calls = []
    state = _new_stub_state()
    _install_recording_em_get(monkeypatch, state, calls)

    class _Reg:
        def __init__(self):
            self.calls = calls  # 在方法作用域里取闭包变量, 类体里裸取会 NameError

        def response(self, payload):
            state.update(mode="response", payload=payload)
            return self

        def exception(self, exc):
            state.update(mode="exception", exc=exc)
            return self

        def sequence(self, seq):
            state.update(mode="sequence", seq=seq)
            return self

    return _Reg()


def _payload(klines):
    return {"data": {"klines": klines}}


# ============================================================
# 离线: 请求形状 / 端点契约 (SKILL.md §4.5 走 push2his)
# ============================================================
def test_push2his_endpoint_and_params_offline(stub_em_get):
    """请求契约整体锁死: 端点 / params 全量 / UA+Referer+Origin / timeout。

    值全部取自 analysis/data_fetcher.py:36-46 生产实际传给 v2.em_get 的东西, 不臆造:
    - params 用**整字典相等**而非逐键断言, 增删任一字段都会失败 (增字段是接口漂移的先兆);
    - User-Agent 与 v2.UA 动态比对, UA 升级时这条回归不会误报;
    - Referer/Origin 是东财的准入条件, 删掉会 4xx / 风控, 故锁成字面量;
    - timeout 锁 15, 避免有人调大把退避重试乘出不可预期的墙钟;
    - 额外 kwarg 锁为空: 桩把 **kwargs 原样记录, 任何"顺手多加一个参数"都会在这里
      失败 —— 完整调用契约 (不只是那四个显式参数) 一起锁死。
    """
    stub_em_get.response(_payload([_kline("2026-10-01", 0, 0, 0, 9.0)]))
    data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert len(stub_em_get.calls) == 1
    call = stub_em_get.calls[0]
    assert call["url"] == _PUSH2HIS_URL
    assert call["params"] == {
        "secid": "1.600693",   # 沪市前缀, 来自 v2.em_market_code
        "klt": 101,            # 日线
        "lmt": 5,              # days 透传
        "fields1": _FIELDS1,
        "fields2": _FIELDS2,
    }
    assert call["headers"] == {
        "User-Agent": data_fetcher.v2.UA,
        "Referer": _REFERER,
        "Origin": _ORIGIN,
    }
    assert call["timeout"] == _TIMEOUT
    # 完整调用参数契约: 显式四参之外不允许再有额外 kwarg (桩会原样记进 "kwargs")
    assert call["kwargs"] == {}, f"生产调用多传了 kwargs: {call['kwargs']}"


def test_secid_market_prefix_covers_sh_sz_bj(stub_em_get):
    """secid 市场前缀: 沪=1, 深/京=0 (与生产 get_prefix/em_market_code 同源)。"""
    cases = {"600693": "1.600693", "000001": "0.000001", "833171": "0.833171"}
    for code, expected in cases.items():
        stub_em_get.response(_payload([_kline("2026-10-01", 0, 0, 0, 9.0)]))
        data_fetcher._fetch_fund_flow_daily(code, days=5)
        assert stub_em_get.calls[-1]["params"]["secid"] == expected, code


# ============================================================
# 离线: 解析/派生 (处理逻辑 + 结果)
# ============================================================
def test_parses_rows_fields_and_derived_totals_offline(stub_em_get):
    """成功路径: 逐行解析 main/large_super/close, 派生 chg_pct/total/start/end。"""
    stub_em_get.response(_payload([
        _kline("2026-10-01", 123456789, 80000000, 4356789, 9.85),
        _kline("2026-10-02", -50000000, -30000000, -20000000, 9.90),
        _kline("2026-10-03", 0, 0, 0, 10.00),
    ]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert "error" not in result
    assert result["start"] == "2026-10-01"
    assert result["end"] == "2026-10-03"
    assert result["total_main_yi"] == pytest.approx(0.735, abs=1e-6)

    rows = result["rows"]
    assert [r["date"] for r in rows] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    # 单位换算: 原始"元" → "亿", 保留 3 位
    assert rows[0]["main_net_yi"] == pytest.approx(1.235, abs=1e-6)
    assert rows[0]["large_super_yi"] == pytest.approx(0.844, abs=1e-6)
    assert rows[1]["main_net_yi"] == pytest.approx(-0.5, abs=1e-6)
    # close / 派生涨跌幅: 实现用 closes[i+1] (下一行收盘) 做分母, 是**向后错位**;
    # 末行 i+1 越界 → chg_pct=None。这里锁的是当前实现的实际行为, 不替生产侧判断
    # 这个错位方向的业务口径对不对。
    assert rows[0]["close"] == pytest.approx(9.85)
    assert rows[0]["chg_pct"] == pytest.approx(-0.51, abs=0.01)
    assert rows[-1]["chg_pct"] is None


def test_legacy_seven_field_line_has_no_close_offline(stub_em_get):
    """兼容老格式 (len=7, 无收盘价列): 不写 close, chg_pct 全 None, 不崩。

    这是**行截断** (整行只有 7 段) 而不是"字段存在但为空", 所以**不用 _kline 走空值
    分支**: 直接写显式 parts, 让"少一段"与"_kline(close=None) 但仍是 9 段"两种形状
    在测试里各自独立、不互相冒充。生产侧的区分点是 len(p)>=8 才写 close 键。
    """
    # 老格式: date,main,small,medium,large,super,? —— 只有 7 段
    line = "2026-10-01,123456789,0,0,80000000,4356789,0"
    assert len(line.split(",")) == 7
    stub_em_get.response(_payload([line]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    row = result["rows"][0]
    assert "close" not in row
    assert row["chg_pct"] is None
    assert row["main_net_yi"] == pytest.approx(1.235, abs=1e-6)


@pytest.mark.parametrize("raw_close", ["", "None", "null"])
def test_blank_close_markers_become_none_offline(stub_em_get, raw_close):
    """f57 收盘价为 空串/None/null → close=None (不抛, 不误算 chg_pct)。"""
    # 刻意手写、不复用 _kline helper: 本条锁的是**生产解析对三种空值标记的处理**,
    # 而 test_kline_helper_blank_close_keeps_nine_fields_offline 锁的是 **helper 自己恒 9 段
    # 的形状**。各写各的行, helper 日后改形状也不会顺带改掉这里的输入形状, 覆盖边界独立。
    line = ",".join([
        "2026-10-01", "123456789", "0", "0", "80000000", "4356789", "0", raw_close, "600693",
    ])
    stub_em_get.response(_payload([line]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    row = result["rows"][0]
    assert row["close"] is None
    assert row["chg_pct"] is None  # 无 close → 无法派生涨跌幅


def test_kline_helper_blank_close_keeps_nine_fields_offline(stub_em_get):
    """夹具层回归: _kline(close=None) 仍是 9 段, p[7] 为空值, **不会**把 f12 滑成 close。

    背景: 早先的 _kline 在 close=None 时整段省掉 p[7], parts 缩成 8 项, 尾部
    "600693" 落到 p[7] —— 生产解析 float(p[7]) 于是得到 close=600693.0。这种假值不
    抛异常, 只是安静地污染 close 与依赖它的 chg_pct, 所以只断言"不抛"是抓不到的。

    本条断三件事: (a) helper 输出恒为 9 段且 p[7]==""、p[8]=="600693"; (b) 经生产解析
    后 close 必须是 None 而不是 600693.0; (c) 缺 close → chg_pct 也是 None。
    与 test_legacy_seven_field_line_has_no_close_offline (行截断, 显式 7 段) 是两种
    不同形状, 不互相替代。
    """
    line = _kline("2026-10-01", 123456789, 80000000, 4356789, None)
    parts = line.split(",")
    assert len(parts) == 9, f"close=None 不得缩短行: {parts!r}"
    assert parts[7] == _BLANK_CLOSE, f"p[7] 应为显式空值标记, 实际 {parts[7]!r}"
    assert parts[8] == "600693", f"p[8] 应保持 f12, 实际 {parts[8]!r}"

    stub_em_get.response(_payload([line]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    row = result["rows"][0]
    assert row["close"] is None, f"空 close 不得被 f12 顶成 {row.get('close')!r}"
    assert row["close"] != 600693.0
    assert row["chg_pct"] is None
    assert row["main_net_yi"] == pytest.approx(1.235, abs=1e-6)


def test_last_row_without_next_close_yields_chg_pct_none_offline(stub_em_get):
    """末行**没有下一行收盘价** → chg_pct 必为 None (边界: i+1 越界)。

    名字要说清是"无后值"而不是"缺字段": 这里两行的 f57 收盘价**都在** (9.0 / 9.5),
    末行为 None 只因 closes[i+1] 取不到下一根, 与 f57 缺失那条
    (test_blank_close_markers_become_none_offline) 是两回事。
    同样只锁实现现状 (向后错位), 不对该口径的业务正确性表态。
    """
    stub_em_get.response(_payload([
        _kline("2026-10-01", 100000000, 0, 0, 9.0),
        _kline("2026-10-02", -20000000, 0, 0, 9.5),
    ]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert result["rows"][-1]["chg_pct"] is None
    assert result["rows"][0]["chg_pct"] == pytest.approx(-5.26, abs=0.01)


# ============================================================
# 离线: 空数据 / 异常边界
# ============================================================
def test_empty_klines_exhausts_retries_offline(stub_em_get):
    """data 存在但 klines 为空 → 判定为"没拿到数据", 退避重试 3 次后报 fetch 失败。

    边界要点: 空 klines 让 `d.data and klines` 判定为假, 循环不 break, 走 for-else
    返回 "push2his fetch failed after 3 retries" —— 与下面"有 klines 但行全畸形"的
    无数据分支是**两条不同**的错误路径。
    """
    stub_em_get.response(_payload([]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert result["error"] == "push2his fetch failed after 3 retries"
    assert result["rows"] == []
    assert len(stub_em_get.calls) == 3  # 退避重试耗尽


def test_malformed_lines_return_no_data_error_offline(stub_em_get):
    """klines 非空但每行都 <7 段 → 一次取回即 break, rows 为空 → "无数据"。

    与 test_empty_klines_* 的区别: 这里**没有**重试 (第 1 次就 break), 错误文案也不同。
    守住 for/else + 空 rows 两条路径不被合并。
    """
    stub_em_get.response(_payload(["bad", "also,bad"]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert result["error"] == "近5日主力资金无数据"
    assert result["rows"] == []
    assert len(stub_em_get.calls) == 1  # klines 非空 → 首轮就 break, 不重试


def test_missing_data_recovers_on_next_retry_offline(stub_em_get):
    """响应缺 data 键 (风控/结构异常) → 下一次重试拿到数据就**成功返回**, 恰好 2 次调用。

    为什么不能只断言"报了错 + 退避 3 次": 那与 test_empty_klines_exhausts_retries_offline
    完全同形, 换掉触发条件也测不出新的分支。所以本条改锁**恢复**路径, 三件事一起断:
    (a) 成功结果 —— 无 error, rows 逐行内容、total_main_yi / start / end 全部派生出来;
    (b) 恰好 2 次调用 —— 第 2 轮就 break, 不该再退避;
    (c) 重试发的是**同一个请求** (url 与 params 完全一致) —— 证明是靠重试循环恢复,
        而不是第二次调用了别的东西。
    与 test_recovers_on_second_attempt_offline 的分工: 那条首轮是**整字典为空** {} 且
    断言较松; 这里首轮是"信封字段在、唯独 data 键不在"的风控形状, 并锁完整成功契约。
    """
    stub_em_get.sequence([
        {"rc": 0, "result": None, "msg": "无数据"},  # data 键缺失
        _payload([
            _kline("2026-10-01", 100000000, 60000000, 40000000, 9.0),
            _kline("2026-10-02", -20000000, -10000000, -10000000, 9.5),
        ]),
    ])
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert "error" not in result
    assert [r["date"] for r in result["rows"]] == ["2026-10-01", "2026-10-02"]
    assert result["rows"][0]["main_net_yi"] == pytest.approx(1.0, abs=1e-6)
    assert result["rows"][0]["close"] == pytest.approx(9.0)
    assert result["rows"][0]["chg_pct"] == pytest.approx(-5.26, abs=0.01)
    assert result["rows"][-1]["chg_pct"] is None  # 末行无 closes[i+1]
    assert result["total_main_yi"] == pytest.approx(0.8, abs=1e-6)
    assert (result["start"], result["end"]) == ("2026-10-01", "2026-10-02")

    assert len(stub_em_get.calls) == 2  # 第 2 轮拿到 klines 即 break
    assert stub_em_get.calls[0]["url"] == stub_em_get.calls[1]["url"] == _PUSH2HIS_URL
    assert stub_em_get.calls[0]["params"] == stub_em_get.calls[1]["params"]


def test_network_exception_is_captured_offline(stub_em_get):
    """抓取抛异常 → 3 次重试后 error 带原始信息, 不向上抛。"""
    stub_em_get.exception(RuntimeError("connect timeout"))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert "connect timeout" in result["error"]
    assert result["rows"] == []
    assert len(stub_em_get.calls) == 3


def test_recovers_on_second_attempt_offline(stub_em_get):
    """首轮**整字典为空** {}、第二轮有数据 → 成功返回 rows (最小重试回归)。

    这里只求"空信封能恢复"这一条最小事实; 首轮是风控形状 (信封字段都在、data 为
    None) 且要锁完整成功契约的, 见 test_missing_data_recovers_on_next_retry_offline。
    """
    good = _payload([_kline("2026-10-01", 100000000, 0, 0, 9.0)])
    stub_em_get.sequence([{}, good])
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)

    assert "error" not in result
    assert result["rows"]
    assert len(stub_em_get.calls) == 2


def test_days_param_forwarded_offline(stub_em_get):
    """days 参数透传到 lmt (取近 N 日), 口径回归。"""
    stub_em_get.response(_payload([_kline("2026-10-01", 0, 0, 0, 9.0)]))
    data_fetcher._fetch_fund_flow_daily("600693", days=20)
    assert stub_em_get.calls[-1]["params"]["lmt"] == 20


# ============================================================
# live gate 第二步自身 (纯逻辑, 离线)
# ============================================================
# 这一条不是 peg 全局门禁的重复: peg 验的是它自己那份 _live_enabled, 而本文件 skipif
# 调的是**本模块这份** _live_enabled —— 两份是各自独立的函数对象, peg 覆盖不到这里。
# 所以保留最小集: 开/关各一, 外加 "0" 这条早期 `not os.environ.get()` 判反的真实事故回归。
@pytest.mark.parametrize("raw,expected", [
    ("1", True),
    ("0", False),   # "0" 是真值字符串 —— 早期 `not os.environ.get()` 判反的坑
    ("", False),
    ("2", False),   # 任何非 "1" 的真值串都关
    ("true", False),
])
def test_live_env_requires_exactly_one(raw, expected):
    """只有 DA_A_RUN_LIVE=1 开; 0/空/未设置/其它真值串一律关。"""
    assert _live_enabled({_LIVE_ENV: raw}) is expected
    assert _live_enabled({}) is False


# ============================================================
# live 用例自身的标记与隔离 (fund-flow 独有, 不重测 peg 的全局门禁矩阵)
# ============================================================
@pytest.fixture(autouse=True)
def no_network_tripwire(monkeypatch):
    """把 socket/DNS 入口封死, **本模块每条用例都生效** (autouse, 无任何豁免分支):
    任何**绕过** v2.em_get 桩的真实建连或解析都当场失败。

    为什么是 autouse 而不是逐条声明: 之前只有那条"直接执行 live 用例体"的用例请求了
    它, 于是**其余所有离线用例都没有兜底** —— 某个用例哪天忘了打桩, 就会在 CI 里
    真连 push2his, 表现为随机超时/风控, 极难归因。哨兵变成模块级默认后, 忘记打桩的
    后果是当场 AssertionError, 而不是一次真实请求。socket 层的 connect/解析是 HTTP 的
    必经之路, 所以"禁 socket/DNS 出口"即等价于"禁 HTTP 出口"。

    为什么不给 live 用例留豁免: 那条 live 用例**自己**就把 v2.em_get 打成桩, 所以无论它是
    被 `DA_A_RUN_LIVE=1 pytest -m live` 显式选中, 还是被默认套件的 smoke 直接调用同一个
    函数体, 唯一的 em_get 出口都已被桩接管 —— 哨兵照封不误, 它要的正是"桩接管后没有第二个
    出口"。

    这里曾经有一个 F1 假绿 (已修): 那条 live 用例体**没有**打桩就直接跑, 真发请求被哨兵
    拦下, 异常又被 data_fetcher 的 `except Exception` 吞掉并重试 3 次, 于是用例内
    `"Expecting value" not in err` 成立、失败分支又被 `if not err` 整段跳过 → **passed**,
    而外层独立哨兵实测记到 3 次 DNS 尝试。现在用例体第一步就是自打桩 + 断言"恰好 1 次
    调用", 哨兵若真被触到, 那一次调用数就已经不是 1, 用例当场红 —— 假绿在结构上不可达。

    因此显式 live 在桩下**通过**, 而它通过的唯一理由是"桩接管", 不是"网络开了": 门禁只认
    桩, 不认"标记 + 环境变量"这种自证式放行; 真联网验收请在本模块之外做, 不靠 fixture
    开口子。

    只封 connect/connect_ex/create_connection/getaddrinfo/gethostbyname/gethostbyname_ex
    这几个**函数**, 不替换 socket.socket 这个**类对象** —— 替换类会让 requests 依赖的
    `class SSLSocket(socket)` 在 import 期直接炸掉。requests/ssl 随 data_fetcher 导入时
    就已装好, 这里只封"建连 + 解析"两个动作, 不影响任何模块导入。

    与 stub_em_get 的共存: 两者共用同一个 function-scope monkeypatch, 但改的目标互不
    重叠 (这里只碰 socket 模块的属性, 桩只碰 df.v2.em_get 与 df.time.sleep), teardown
    各自回滚, 不存在谁覆盖谁。

    命中时抛 _NetworkTripped (AssertionError 子类), 自检也只认这个类型 —— 详见该类
    docstring: 用宽泛的 AssertionError 断言, "已 armed" 这条证据会被外层哨兵顶包。
    """
    import socket

    def _blocked(name):
        def _f(*_a, **_k):
            raise _NetworkTripped(f"触达真实网络入口 {name} —— 期望零网络")
        return _f

    monkeypatch.setattr(socket.socket, "connect", _blocked("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _blocked("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _blocked("socket.getaddrinfo"))
    monkeypatch.setattr(socket, "gethostbyname", _blocked("socket.gethostbyname"))
    monkeypatch.setattr(socket, "gethostbyname_ex", _blocked("socket.gethostbyname_ex"))


def test_tripwire_is_armed_for_plain_offline_tests(stub_em_get):
    """autouse 生效性回归: 不显式请求 fixture, 离线用例也已经在封网状态下运行。

    这条同时断三件事, 少一件这条回归就名不副实:
    (a) no_network_tripwire 是 autouse —— 本用例没请求它, DNS 与 TCP 入口仍已封死;
    (b) 只封**方法/函数**不换**类** —— socket.socket 仍是原类对象, ssl 的
        `class SSLSocket(socket)` 依旧能成立 (换成桩类会在 import 期炸);
    (c) 与 stub_em_get 共存 —— 数据通道由桩接管照常走通, 网络通道照封。
    """
    import socket
    import ssl

    with pytest.raises(_NetworkTripped, match="getaddrinfo"):
        socket.getaddrinfo("push2his.eastmoney.com", 443)
    with socket.socket() as sock, pytest.raises(_NetworkTripped, match="socket.connect"):
        sock.connect(("push2his.eastmoney.com", 443))
    # 类对象未被替换 → ssl 的继承关系仍成立
    assert issubclass(ssl.SSLSocket, socket.socket)

    stub_em_get.response(_payload([_kline("2026-10-01", 100000000, 0, 0, 9.0)]))
    result = data_fetcher._fetch_fund_flow_daily("600693", days=5)
    assert "error" not in result
    assert [r["date"] for r in result["rows"]] == ["2026-10-01"]
    assert len(stub_em_get.calls) == 1


def test_live_test_is_double_opt_in_and_off_by_default():
    """本文件那条 live 用例自身的标记契约: live + integration + env skipif。

    与 peg 的全局门禁矩阵**不重叠**: 那套验的是 conftest 钩子怎么按生效 -m 选用例; 这里
    验的是**本文件的 live 用例带对了标记**。漏掉 @live 是最危险的退化 —— 默认 addopts 的
    `-m "not live"` 就不再排除它, 用例会混进默认 pytest; 配合 skipif 一起丢, 才会演变成
    默认跑就去抓数据, 所以这两条断言一起护住它。

    skipif 条件与 `not _live_enabled()` **动态比对**而非写死 True: 这样本用例在
    DA_A_RUN_LIVE=1 的显式集成环境下同样成立, 不依赖外层环境变量取值。
    """
    marks = list(test_fund_flow_daily_uses_push2his.pytestmark)
    names = {m.name for m in marks}
    assert "live" in names, (
        "live 用例必须打 @pytest.mark.live, 否则默认 -m 'not live' 拦不住它"
    )
    assert "integration" in names, "live 用例必须同时打 integration (常用的显式 opt-in 出口)"

    skipifs = [m for m in marks if m.name == "skipif"]
    assert skipifs, "live 用例必须有 env skipif, 否则 DA_A_RUN_LIVE 未设时默认 pytest 会执行它"
    assert all(m.args[0] == (not _live_enabled()) for m in skipifs)
    # 关闭理由要指名开关, 这样 -ra 摘要里被 skip 时能自解释
    assert all(_LIVE_ENV in (m.kwargs.get("reason") or "") for m in skipifs)


def test_live_test_body_only_reaches_stubbed_em_get(monkeypatch):
    """默认套件里的 stubbed smoke: 执行**同一个** live 用例体, 零真实 DNS/建连。

    与那条 live 用例是"同一份实现"而不是两份拷贝: 这里直接把
    test_fund_flow_daily_uses_push2his(monkeypatch) 调起来, 于是它内部那套断言
    (恰好 1 次调用 + 完整请求契约 + 必须拿到成功数据) 原样生效, 本文件**不再复制第二遍**
    —— 副本会漂移, 而 F1 那种"断言被 if 跳过所以照样绿"的假绿正是从副本里长出来的。
    skipif 是 collection 期行为, 直接调用函数体不受影响, 所以默认套件 (live 被 deselect)
    下这条照样跑: 这就是"live 逻辑体在默认套件里也有一项 stubbed smoke"的落点。

    本条自己的**增量**价值只有一件事 —— 哨兵在这次执行的前后都 armed:
    (a) 调用前自检 getaddrinfo 已被封 → autouse 对这条 stubbed 用例同样生效
        (这里**不**显式请求 tripwire fixture, 免得自证);
    (b) 调用后再自检一次 → 调用期间没有第二个网络出口被打开过 (桩接管即封死);
    (c) 断 _NetworkTripped 而非 AssertionError —— 外层哨兵/别的 AssertionError 不能顶包
        (理由见该类 docstring)。
    替身先抛错, 不会真的发起 DNS 解析。
    """
    import socket

    def _probe_armed():
        with pytest.raises(_NetworkTripped, match="getaddrinfo"):
            socket.getaddrinfo("push2his.eastmoney.com", 443)

    _probe_armed()  # (a)

    test_fund_flow_daily_uses_push2his(monkeypatch)  # 不抛 = 该用例体全部断言均成立

    _probe_armed()  # (b)


# ============================================================
# live 用例 (双重 opt-in: 选不选 = -m live/integration, 跑不跑 = DA_A_RUN_LIVE=1)
# ============================================================
# 确定性 canned 响应: 3 根日线, 日期/数值全部写死。live 用例要断言"成功数据", 就不能
# 依赖当天行情; 字段位置对齐生产解析 (p[1]=主力净额, p[4]/p[5]=大单/超大单, p[7]=收盘价,
# p[8]=代码), 与 _kline 的 9 段形状一致。
_LIVE_CANNED_KLINES = [
    _kline("2026-10-01", 123456789, 80000000, 4356789, 9.85),
    _kline("2026-10-02", -50000000, -30000000, -20000000, 9.90),
    _kline("2026-10-03", 0, 0, 0, 10.00),
]


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    not _live_enabled(),
    reason=(f"实时资金流检查: 需显式加 -m live/integration 且 {_LIVE_ENV}=1 才会执行本用例"
            f"({_LIVE_ENV}=0/空/未设置 均视为关闭); 它自打桩, 执行期零真实网络"),
)
def test_fund_flow_daily_uses_push2his(monkeypatch):
    """5 日主力资金流应走 push2his（同 SKILL.md §4.5），不应再有 'Expecting value' 错误

    双重 opt-in: 选不选 = -m live/integration (conftest collection 层门禁), 跑不跑 =
    DA_A_RUN_LIVE 精确等于 "1" (下面 skipif)。原判定逻辑逐字保留, 只是从"默认跑"挪到
    "双重 opt-in 跑", 默认 pytest 不再因此抖动。对应的离线回归见本文件上方
    test_push2his_endpoint_and_params_offline / test_parses_rows_fields_and_derived_totals_offline 等。

        DA_A_RUN_LIVE=1 pytest tests/test_fund_flow_domain.py -m live

    关键 (F1 整改): 用例体**自己**先把唯一网络出口 data_fetcher.v2.em_get 换成确定性
    canned 响应的桩, 然后才去执行抓取 —— 不靠任何外部 fixture, 所以"漏打桩"不可能悄悄
    变成一次真请求再被 data_fetcher 的 `except Exception` 吞掉重试 (那正是原来的假绿:
    用例内 "Expecting value" not in err 成立、失败分支被 `if not err` 跳过 → passed,
    而实际已发生 3 次真实 DNS 尝试)。autouse no_network_tripwire 对本用例**同样生效且
    不豁免**, 于是上面这条命令在本文件内是 **passed 且零真实 DNS/建连/HTTP** (外层独立
    sentinel 实测命中 0), 既不是 fail-closed 报错, 也不是真打 push2his。

    契约: 恰好 1 次调用 (被退避重试成 3 次就说明桩没接管), url / params / headers /
    timeout / 额外 kwargs 全量锁死, 且必须拿到**成功**数据 —— 不再靠 "error 不含某串"
    这种失败即可糊过去的弱断言。
    """
    calls = _install_canned_em_get(monkeypatch, _payload(_LIVE_CANNED_KLINES))

    # fail-closed 而非 fallback: re-export 一旦消失, 这里必须当场红。原先那条
    # analyze_single_v3 fallback 会连发多次 em_get 并跑整条 pipeline, 与"恰好 1 次调用 +
    # 零真实网络"的契约正面冲突 —— 留着它等于给 F1 假绿留后门。
    assert hasattr(v3, "_fetch_fund_flow_daily"), (
        "v3 不再 re-export _fetch_fund_flow_daily: 本用例只认单次抓取路径, "
        "不再 fallback 到 analyze_single_v3 (它会发多次请求, 违背零网络契约)"
    )
    result = v3._fetch_fund_flow_daily("600693", days=5)

    # 1. 旧 push2 JSON 解析错误不应再现 (原判定逐字保留)
    err = result.get("error", "")
    assert "Expecting value" not in err, f"应消除旧 push2 JSON 解析错误: {err}"

    # 2. 自打桩必须真的接管了唯一出口: 恰好 1 次调用。
    #    若桩没打或打在错误的模块对象上, 这里会是 3 次 (真请求被哨兵拦下后被重试吞掉)。
    assert len(calls) == 1, f"live 用例体必须经 df.v2.em_get 抓取且恰好 1 次, 实际 {len(calls)}: {calls}"
    call = calls[0]
    assert call["url"] == _PUSH2HIS_URL
    assert call["params"] == {
        "secid": "1.600693",   # 沪市前缀, 来自 v2.em_market_code
        "klt": 101,            # 日线
        "lmt": 5,              # days 透传
        "fields1": _FIELDS1,
        "fields2": _FIELDS2,
    }
    assert call["headers"] == {
        "User-Agent": data_fetcher.v2.UA,
        "Referer": _REFERER,
        "Origin": _ORIGIN,
    }
    assert call["timeout"] == _TIMEOUT
    assert call["kwargs"] == {}, f"生产调用多传了 kwargs: {call['kwargs']}"

    # 3. 成功数据必须是成功: 有 error 就直接红, 不再让失败分支从 `if not err` 里溜过去。
    assert not err, f"自打桩下应取到 canned 成功数据, 实际 error={err!r}"
    assert result.get("rows") or result.get("data"), f"成功路径应返回 rows/data，实际: {list(result.keys())}"
    assert [r["date"] for r in result["rows"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert result["rows"][0]["main_net_yi"] == pytest.approx(1.235, abs=1e-6)
    assert result["rows"][0]["large_super_yi"] == pytest.approx(0.844, abs=1e-6)
    assert result["rows"][-1]["chg_pct"] is None  # 末行无 closes[i+1]
    assert (result["start"], result["end"]) == ("2026-10-01", "2026-10-03")
    assert result["total_main_yi"] == pytest.approx(0.735, abs=1e-6)
