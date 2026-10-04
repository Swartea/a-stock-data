"""analysis/utils.py 契约测试 (P2-A 拆分后的通用工具层)

背景 (为什么补这一份):
    `analysis/utils.py` (297 行) 是 P2-A 从 `quant_analyzer_v3.py` 拆出的**纯工具层**,
    被 6 个生产模块直接 import:

        quant_analyzer_v3.py / report_md.py / pipeline.py /
        three_levels.py / data_fetcher.py / reporting/artifact_writer.py

    **补测前**的静态扫描: 全仓 `tests/` **零引用**该模块 —— 没有任何测试
    import `analysis.utils`, 也没有任何测试提到
    `fpct` / `interpret_yoy` / `finance_talk` / `json_default` …。
    这是本文件落地**之前**的历史状态, 不再是现状: 现在 `analysis.utils` 在 `tests/`
    下**只**被本文件引用 (其余测试仍零引用), 所以这份覆盖是它唯一的防线。

    风险: 这些函数是**报告文案与数值显示的最后一道口径**——
    §3 明令"禁止 default=str 静默序列化", 而 `json_default` 正是那条禁令的**唯一执行点**;
    `interpret_yoy` / `finance_talk` 的分档阈值是 §1 "不修改业务口径" 的硬红线。
    补测前"全部无测试" = 任何人一次"顺手清理"就能改掉报告口径而 CI 全绿。

本文件的定位 (刻意**不**做的事):
    - 不重跑网络/落盘/端到端。全部断言都是**纯函数 → 纯值**, 零 IO、零网络。
    - 不复制 `tests/test_peg_talk_text.py` 的 PEG 阈值断言。那份验的是
      `quant_analyzer_v3._format_peg_talk` 这个**顶层 re-export 通道**;
      本文件验的是 `analysis.utils` 本体的实现 + 全部 12 个 `_` 别名的转发等价性。
      两份不重叠 (见 `test_underscore_alias_delegates_to_public_function`)。

组织方式: 按 utils.py 的分节顺序 (序列化 / 时间 / 数值 / 显示 / 业务口径解读)。
"""
from __future__ import annotations

import ast
import datetime as _dt
import decimal
import enum
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import utils  # noqa: E402


# ============================================================
# §3 序列化契约: json_default  (唯一执行点, 全仓最该有测试的一处)
# ============================================================
class _Color(enum.Enum):
    RED = "red"


class _Opaque:
    """无任何 json 原生表示的自定义类型 —— 必须被显式拒绝。"""


class _BrokenIsoFormat:
    """带 isoformat 入口但调用即炸的类型 —— 逼 json_default 走 except 降级。

    真实存在这种形状: date-like 对象的 isoformat 可能因内部状态
    (字段未初始化 / tzinfo 不可用) 抛 ValueError 或 TypeError。
    `calls` 记录是否真的尝试过 isoformat, 让降级路径可被断言, 而非"恰好也报错了"。
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    def isoformat(self) -> str:
        self.calls += 1
        raise self._exc


@pytest.mark.parametrize("obj,expected,label", [
    (_dt.date(2026, 10, 3), "2026-10-03", "date → ISO"),
    (_dt.datetime(2026, 10, 3, 16, 18, 0), "2026-10-03T16:18:00", "datetime → ISO"),
    (decimal.Decimal("1.5"), 1.5, "Decimal → float (金融常见)"),
    (Path("/reports/600693"), "/reports/600693", "Path → str"),
    ({"b", "a"}, ["a", "b"], "set → 排序后 list (确定性 JSON)"),
    (b"\x01\xff", "01ff", "bytes → hex"),
    (ValueError("boom"), "ValueError: boom", "Exception → 类型名+消息"),
    (_Color.RED, "red", "Enum → value"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_json_default_supports_every_documented_type(obj, expected, label):
    """docstring 列出的 7 类支持类型逐类锁死 (规范 §3 显式转换)。"""
    assert utils.json_default(obj) == expected, label


def test_json_default_handles_frozenset_like_set():
    """frozenset 与 set 同口径 —— `json_default` docstring 明写 "set/frozenset → 排序后 list"。

    锁的是"docstring 承诺"与"实现分支"**同时**成立: 实现里是
    `isinstance(obj, (set, frozenset))`, 一旦退化成只判 `set`, frozenset 就一路
    落到函数最后一个兜底分支 `raise TypeError` —— 那是 docstring 承诺过、却唯独
    没实现的容器类型, 也是全套里唯一会"炸"的那类。

    两件事都**就地**断言, 不引用任何外部改动说明: 行为看返回值, 承诺看 docstring 原文。
    """
    assert utils.json_default(frozenset({"b", "a"})) == ["a", "b"]
    assert "frozenset" in (utils.json_default.__doc__ or ""), (
        "docstring 里的 'set/frozenset' 承诺被删了, 与本用例锁定的行为失去对应"
    )


def test_json_default_mixed_type_set_falls_back_to_unsorted_list():
    """元素互不可比较时 `sorted()` 抛 TypeError → 降级走 `return list(obj)`。

    这条分支此前零覆盖, 而它是 set 里混进异构元素 (如 {1, "a"} 或含 date 的集合)
    时唯一的出口。降级后**顺序不确定** (取决于 set 的哈希布局, 跨进程也可能变),
    所以这里只断言两件与顺序无关的事:
      1) 元素集合与输入完全一致 —— 降级只放弃排序, 不能丢元素或凭空多出;
      2) 真实 json.dumps 编码得出来 —— 降级分支仍满足 §3 的可序列化契约。
    """
    import json

    mixed = {1, "a"}
    with pytest.raises(TypeError):
        sorted(mixed)          # 前置确认: 这个集合确实到不了 sorted 分支

    out = utils.json_default(mixed)
    assert isinstance(out, list), "降级分支应返回 list, 而不是回吐 set"
    assert len(out) == 2
    assert set(out) == mixed, "降级只放弃排序, 不能丢元素"

    blob = json.dumps({"mixed": mixed}, ensure_ascii=False, default=utils.json_default)
    assert set(json.loads(blob)["mixed"]) == mixed, "降级结果必须能被 json 真实编码"


def test_json_default_mixed_type_set_fallback_still_runs_elements_through_default():
    """降级 list 里的元素若仍需 json_default, 编码器会逐个再问一次。

    `list(obj)` 只解决"排序失败", 不解决"元素本身不可编码": 集合里混进 `date`
    时, 靠的就是编码器对 list 元素的逐个 default 回问。
    若 list 分支被改成回吐原 set 或整体 str(), 这里就编不出来 (或编成假值)。
    """
    import json

    mixed = {1, _dt.date(2026, 10, 3)}
    with pytest.raises(TypeError):
        sorted(mixed)

    blob = json.dumps({"mixed": mixed}, ensure_ascii=False, default=utils.json_default)
    got = json.loads(blob)["mixed"]
    assert len(got) == 2
    assert set(got) == {1, "2026-10-03"}, "date 元素仍须按 ISO 落, 不得被降级吞掉"


def test_json_default_rejects_unknown_type_instead_of_stringifying():
    """未知类型必须 raise TypeError —— 规范 §3 禁止 `default=str` 静默掩盖。

    这条是本模块**最重要**的断言: 一旦有人把兜底改回 `return str(obj)`,
    报告里未定义类型就会变成一串看着像数据的引号文本, 无人能发现。
    """
    with pytest.raises(TypeError) as ei:
        utils.json_default(_Opaque())
    assert "not JSON serializable" in str(ei.value)
    assert "_Opaque" in str(ei.value), "报错要指名类型, 否则线上无法定位"


@pytest.mark.parametrize("exc_type", [ValueError, TypeError],
                         ids=["isoformat-ValueError", "isoformat-TypeError"])
def test_json_default_broken_isoformat_falls_through_to_unsupported(exc_type):
    """isoformat() 抛错后必须**继续往下走**, 直到最终 unsupported TypeError。

    锁的是 `except (TypeError, ValueError): pass` 之后**没有 return**:
    降级的含义只是"这个入口不可用", 不是"已经处理好了"。
    若有人把 pass 改成 `return str(obj)` / `return None`, 报告里会多出一个
    看着像日期的假值, §3 的显式性被悄悄破坏, 而这类假值在报告里最难被发现。
    `calls` 断言顺带证明确实先尝试过 isoformat —— 否则"降级"可能只是压根没走那一步。
    """
    obj = _BrokenIsoFormat(exc_type("bad iso"))
    with pytest.raises(TypeError) as ei:
        utils.json_default(obj)
    assert obj.calls == 1, "应真的调用过 isoformat, 而不是直接跳到兜底"
    assert "not JSON serializable" in str(ei.value)
    assert "_BrokenIsoFormat" in str(ei.value), "最终报错仍要指名类型"


def test_json_default_is_wired_as_the_real_json_encoder_default():
    """证明 json_default 真的能被 `default=` 用上 (而不是一个没人调用的孤儿函数)。

    `artifact_writer.py` 落盘 result_v3/run_log 走的就是这条路;
    这里用真实 json.dumps 走一遍, 确认 §3 的禁令有实际执行点。
    """
    import json

    blob = json.dumps(
        {"d": _dt.date(2026, 10, 3), "s": {"x", "y"}},
        ensure_ascii=False, default=utils.json_default,
    )
    assert json.loads(blob) == {"d": "2026-10-03", "s": ["x", "y"]}


# ============================================================
# 时间格式化
# ============================================================
def test_short_iso_truncates_to_seconds_and_replaces_t():
    """ISO8601 → 'YYYY-MM-DD HH:MM:SS'：只取前 19 字符并把 T 换成空格。

    边界刻意挑带时区的串 (`+08:00`): 截断到 19 字符正好丢掉时区后缀,
    报告里要的是本地墙上时间, 不是带偏移的完整 ISO。
    """
    assert utils.short_iso("2026-10-03T16:18:00+08:00") == "2026-10-03 16:18:00"
    assert utils.short_iso("2026-10-03T16:18:00") == "2026-10-03 16:18:00"


@pytest.mark.parametrize("bad", [None, ""], ids=["none", "empty"])
def test_short_iso_degrades_to_dash(bad):
    """缺失时间不编造 —— 统一落 '—' (与仓库其余占位符一致)。"""
    assert utils.short_iso(bad) == "—"


def test_fmt_time_formats_epoch_as_hms():
    """时间戳 → HH:MM:SS。用固定时区的 epoch, 避免依赖运行机器本地时区。"""
    import time

    ts = _dt.datetime(2026, 10, 3, 16, 18, 9, tzinfo=_dt.timezone.utc).timestamp()
    localized = time.localtime(ts)
    assert utils.fmt_time(ts) == time.strftime("%H:%M:%S", localized)


# ============================================================
# 数值转换: to_float / num_or_none
# ============================================================
@pytest.mark.parametrize("raw,expected", [
    ("12.5", 12.5),      # 字符串数字 (数据源常态)
    (7, 7.0),            # int
    (True, 1.0),         # bool 是 int 子类, 不特殊处理
    (None, None),
    ("abc", None),
    (float("nan"), None),
    (float("inf"), None),
    (float("-inf"), None),
], ids=["str-num", "int", "bool", "none", "junk", "nan", "inf", "-inf"])
def test_to_float_coerces_or_returns_none(raw, expected):
    """安全转换: 不可转 / NaN / ±inf 一律 None —— 绝不让脏值流进计算与显示。"""
    got = utils.to_float(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_num_or_none_is_to_float_under_another_name():
    """两个名字是同一口径 (data_fetcher 用的就是 num_or_none)。"""
    for raw in ("3.5", None, float("nan"), "x"):
        assert utils.num_or_none(raw) == utils.to_float(raw)


# ============================================================
# 显示格式化: clean / fnum / fpct
# ============================================================
def test_clean_escapes_pipes_and_newlines():
    """竖线/换行会破坏 markdown 表格 —— 必须替换掉。"""
    assert utils.clean("a|b") == "a／b"
    assert utils.clean("a\nb\rc") == "a b c"
    assert utils.clean("  pad  ") == "pad"


def test_clean_truncation_boundary_is_off_by_one_correct():
    """截断边界: 恰好 n 字符**不**加省略号, n+1 字符截成 n-1 + '…' (总长仍为 n)。

    锁的是 `s[:n-1] + "…"` 这个写法: 结果宽度恒等于 n, 报告表格列宽才稳定。
    """
    assert utils.clean("x" * 60) == "x" * 60            # 恰好 n
    out = utils.clean("x" * 61)                        # n+1 → 截断
    assert len(out) == 60 and out.endswith("…")


def test_clean_none_is_dash():
    assert utils.clean(None) == "—"


def test_fnum_thousands_separator_and_precision():
    """千分位 + 固定小数位 (报告金额列的统一格式)。"""
    assert utils.fnum(1234.5) == "1,234.50"
    assert utils.fnum(0) == "0.00"
    assert utils.fnum(1234.5678, nd=3) == "1,234.568"
    assert utils.fnum(-1234.5) == "-1,234.50"


@pytest.mark.parametrize("bad", [None, "abc", float("nan"), float("inf"), float("-inf")],
                         ids=["none", "junk", "nan", "inf", "-inf"])
def test_fnum_degrades_to_dash(bad):
    """显示层与 to_float 同口径: 脏值不出 "nan"/"inf" 字样 —— ±inf **两个方向都要覆盖**。

    只锁 +inf 等于只测了实现里那个二元守卫的一半: `x in (float("inf"), float("-inf"))`
    被改成 `x == float("inf")` 时正无穷那条照样通过, 负无穷却漏进 `f"{x:,.2f}"`
    直出 "-inf" —— 报告金额列里一个看着像数字的脏串, 不抛异常、不报错, CI 全绿。

    `to_float` 与 `fpct` 两侧都把 ±inf 各锁了一条 (见上面 / 下面两条), `fnum`
    只锁 +inf 会与它们的口径不一致: 同一个脏值在两处得到两种显示结果。
    """
    assert utils.fnum(bad) == "—"


@pytest.mark.parametrize("bad", [None, "abc", float("nan"), float("inf"), float("-inf")],
                         ids=["none", "junk", "nan", "inf", "-inf"])
def test_fpct_degrades_to_dash(bad):
    """含 ±inf —— 与 fnum/to_float 同口径: 报告里绝不能冒出 "inf%" 这种脏显示。

    缺 inf 守卫时 `fpct(float("inf"))` 会走 f-string 直出脏串, 且**带默认正号**:
    sign 默认 True, `f"{inf:+.1f}%"` → "+inf%", 负无穷 → "-inf%" (不是无号的 "inf%")。
    两者都落进报告表格且不报错, 属于"脏值静默流进显示层"的典型漏网。
    """
    assert utils.fpct(bad) == "—"


def test_fpct_sign_flag_controls_plus_prefix():
    """sign=True 带 + 号 (同比方向一眼可辨), sign=False 不带。"""
    assert utils.fpct(12.34) == "+12.3%"
    assert utils.fpct(12.34, sign=False) == "12.3%"
    assert utils.fpct(-12.34, sign=False) == "-12.3%"
    assert utils.fpct(0) == "+0.0%", "0% 也要带 + (与 interpret_yoy 的 '+0.0%' 口径一致)"


def test_fpct_honours_precision():
    assert utils.fpct(12.3456, nd=2) == "+12.35%"


# ============================================================
# 业务口径解读 (§1 '不修改业务口径' —— 阈值是红线, 逐个边界锁死)
# ============================================================
@pytest.mark.parametrize("growth,expected_tail", [
    (50,   "高速增长(🔥)"),
    (30,   "高速增长(🔥)"),   # 边界: >= 30
    (29.9, "稳健增长"),
    (10,   "稳健增长"),       # 边界: >= 10
    (9.9,  "微增"),
    (0,    "微增"),          # 边界: >= 0
    (-0.1, "负增长(⚠️ 需排查原因)"),
], ids=["50", "30-上边界", "29.9", "10-上边界", "9.9", "0-上边界", "负"])
def test_interpret_yoy_tier_thresholds(growth, expected_tail):
    """4 档阈值 30 / 10 / 0 的**上边界**归属 (全用 >=, 故 30 属高速而非稳健)。

    这些分档直接决定报告里"高速增长/稳健增长/微增/负增长"的人话措辞,
    改一个数字就是改业务口径, 所以连边界值都写进测试。
    """
    assert utils.interpret_yoy(growth, "营收").endswith(expected_tail)


def test_interpret_yoy_renders_number_and_kind():
    """文案含 kind 与一位小数 —— 报告里 '营收同比 **+30.0%** — ...' 的形状。"""
    assert utils.interpret_yoy(30, "营收") == "营收同比 **+30.0%** — 高速增长(🔥)"
    assert utils.interpret_yoy(30, "净利").startswith("净利同比 ")


def test_interpret_yoy_none_states_missing_base_not_zero():
    """缺上年同期基数时**不能**显示 0.0% —— 必须显式说"数据未披露"。

    这是 §1 的典型踩雷点: 把 None 当 0 会把"没披露"渲染成"零增长"。
    """
    text = utils.interpret_yoy(None, "营收")
    assert text == "营收同比 — (数据未披露/无上年同期基数)"
    assert "0.0%" not in text


def test_interpret_qoq_sign_and_direction():
    """环比: 正数提速 / 非正数转弱。注意 0 归"转弱"(用 > 而非 >=)。"""
    assert utils.interpret_qoq(5.0, "营收") == "单季环比 **+5.0%**(环比提速)"
    assert utils.interpret_qoq(0, "营收") == "单季环比 **+0.0%**(环比转弱)"
    assert utils.interpret_qoq(-3.0, "营收") == "单季环比 **-3.0%**(环比转弱)"


def test_interpret_qoq_none_returns_empty_string():
    """环比缺失返回空串 (调用方据此整行省略), 不是 "—" 也不是 None。"""
    assert utils.interpret_qoq(None, "营收") == ""


# ============================================================
# finance_talk: 财务体检人话
# ============================================================
@pytest.mark.parametrize("bad", [None, {}, "not-a-dict", {"no_latest_key": 1}],
                         ids=["none", "empty", "非dict", "缺 latest 键"])
def test_finance_talk_refuses_to_invent_data(bad):
    """无财务数据时只回一条"不编造"提示, 绝不给出看似真实的点评。

    触发条件是 `not fin or 非 dict or "latest" not in fin` —— 即**结构上就没有** latest。
    """
    out = utils.finance_talk(bad)
    assert out == ["> ⚠️ 财务摘要数据缺失, 无法体检 (不编造)"]


def test_finance_talk_with_empty_latest_degrades_to_placeholders_not_fabrication():
    """`{"latest": None}` 是**另一条**路径: 键在但值为空 -> 渲染全 "—" 占位。

    与上面的"结构缺失"分开断言, 因为两者输出形状不同:
    - 结构缺失 -> 单条"数据缺失, 无法体检"提示 (整段略过)
    - latest 为空 -> 保留体检骨架, 每个字段落 "—" (报告版式不断)

    关键仍是**不编造**: 输出里不得出现任何具体数字, 也不得出现 0.0% 之类
    "把 None 当 0"渲染出来的伪值 (与 interpret_yoy(None) 同一红线)。
    """
    out = utils.finance_talk({"latest": None})
    assert out[0] == "- 最新报告期 **—** 财务体检:"
    joined = "\n".join(out)
    assert "0.0%" not in joined, "None 被当成 0 渲染了"
    assert "数据未披露" in joined          # 同比显式说明缺基数
    assert "同比基数缺失" in joined        # 结论也走"基数缺失"分支而非编造
    assert not any("环比动能" in b for b in out)  # 环比全缺 -> 整行省略


def test_finance_talk_quality_tiers():
    """ROE / 毛利率 / 资产负债率 三档判定 (15/8、40/20、50/70)。"""
    strong = utils.finance_talk({"latest": {
        "report_date": "2026-09-30", "roe": 20, "gross_margin": 50, "debt_ratio": 30,
    }})
    assert any("ROE(加权) 20.00%(≥15% 回报强)" in b for b in strong)
    assert any("毛利率 50.00%(≥40% 高毛利)" in b for b in strong)
    assert any("资产负债率 30.00%(≤50% 稳健)" in b for b in strong)

    mid = utils.finance_talk({"latest": {
        "report_date": "2026-09-30", "roe": 10, "gross_margin": 25, "debt_ratio": 60,
    }})
    assert any("(8~15% 中等)" in b for b in mid)
    assert any("(20~40% 中等)" in b for b in mid)
    assert any("(50~70% 中性)" in b for b in mid)

    weak = utils.finance_talk({"latest": {
        "report_date": "2026-09-30", "roe": 5, "gross_margin": 10, "debt_ratio": 80,
    }})
    assert any("(<8% 偏弱)" in b for b in weak)
    assert any("(<20% 薄利)" in b for b in weak)
    assert any("(>70% 高杠杆🚨)" in b for b in weak)


def test_finance_talk_omits_qoq_line_when_both_absent():
    """环比两项都缺时**不输出**"环比动能"整行 (而不是留一个空的 " | ")。"""
    out = utils.finance_talk({"latest": {"report_date": "2026-09-30"}})
    assert not any("环比动能" in b for b in out)


def test_finance_talk_verdict_picks_loss_over_decline():
    """绝对亏损优先于"同比负增长"作结论 —— 亏损是更强的风险信号。"""
    out = utils.finance_talk({"latest": {
        "report_date": "2026-09-30", "profit_yi": -1.2, "yoy_profit": -30,
    }})
    assert any("仍处亏损状态" in b for b in out)
    assert not any("最大财务风险点" in b for b in out)


# ============================================================
# 转发别名: 12 个 `_` 前缀兼容层
# ============================================================
_ALIAS_PAIRS = [
    ("_json_default", "json_default"),
    ("_fmt_time", "fmt_time"),
    ("_short_iso", "short_iso"),
    ("_to_float", "to_float"),
    ("_num_or_none", "num_or_none"),
    ("_clean", "clean"),
    ("_fnum", "fnum"),
    ("_fpct", "fpct"),
    ("_interpret_yoy", "interpret_yoy"),
    ("_interpret_qoq", "interpret_qoq"),
    ("_finance_talk", "finance_talk"),
    ("_format_peg_talk", "format_peg_talk"),
]


@pytest.mark.parametrize("alias,public", _ALIAS_PAIRS, ids=[a for a, _ in _ALIAS_PAIRS])
def test_underscore_alias_delegates_to_public_function(alias, public):
    """每个 `_x` 别名都必须存在**且真的转发**到 `x` (AST 断言, 非仅 hasattr)。

    为什么用 AST 而不是"跑一下看结果对不对": 生产侧 6 个模块 import 的**正是这些
    下划线名字** (`from analysis.utils import _fnum, _fpct, ...`)。
    若有人把 `def _fnum` 改成独立实现或直接 `return None`, 行为测试未必立刻变红,
    但报告格式会静默走偏。AST 断言锁的是**转发结构**本身。
    """
    tree = ast.parse(Path(utils.__file__).read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert alias in fns, f"utils.py 缺少别名 {alias} —— 生产模块 import 的就是它"

    body = fns[alias].body
    assert len(body) == 1, f"{alias} 应是单行转发, 实际 {len(body)} 条语句"
    stmt = body[0]
    assert isinstance(stmt, ast.Return), f"{alias} 应 return, 实际 {type(stmt).__name__}"
    call = stmt.value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name), (
        f"{alias} 应 return {public}(...)"
    )
    assert call.func.id == public, f"{alias} 应转发到 {public}, 实际 {call.func.id}"


@pytest.mark.parametrize("alias,public", _ALIAS_PAIRS, ids=[a for a, _ in _ALIAS_PAIRS])
def test_underscore_alias_is_importable_and_bound(alias, public):
    """别名不仅要"长得像", 还要真能从模块取到并可调用。"""
    assert callable(getattr(utils, alias)), f"{alias} 不可调用"
    assert callable(getattr(utils, public))


@pytest.mark.parametrize("args,kwargs,expected", [
    ((12.3456,), {}, "+12.3%"),                    # 全默认: nd=1 / sign=True
    ((12.3456, 2), {}, "+12.35%"),                  # 位置传 nd
    ((12.3456, 3), {}, "+12.346%"),                 # nd 与默认档可区分
    ((12.34,), {"sign": False}, "12.3%"),           # 关键字传 sign
    ((-12.34, 0, False), {}, "-12%"),               # 全位置传: nd 与 sign 都不丢
    ((None, 2, False), {}, "—"),                    # 降级分支与参数无关
], ids=["默认", "nd-位置-2位", "nd-位置-3位", "sign-关键字", "nd+sign-全位置", "脏值降级"])
def test_fpct_alias_forwards_nd_and_sign(args, kwargs, expected):
    """`_fpct` 必须把 nd / sign **原样**转给 `fpct` —— 语义转发, 而不只是结构转发。

    AST 断言只锁住 `return fpct(...)` 这个转发**结构**; 它看不出参数有没有被吃掉:
    `def _fpct(x, nd=1, sign=True): return fpct(x)` 形状几乎一样, 却把所有精度与
    正负号请求悄悄丢掉。而生产侧 (report_md / pipeline / three_levels) 正是从
    v3 import `_fpct` 用的, 报告里 "**+12.3%**" 的精度与符号直接由此决定。

    每条同时断言字面期望值与"与 fpct 一致", 避免退化成 a == b 的同义反复。
    """
    got = utils._fpct(*args, **kwargs)
    assert got == expected
    assert got == utils.fpct(*args, **kwargs)


# 带默认值的别名只有 3 个 (其余 9 个全是必填位置参数, 少传一个当场 TypeError,
# 不会静默丢参数), 所以参数级语义用例只锁定这三个: `_fpct` 已在上面覆盖,
# 这里补的是审查点名的 nd / n 两条转发。
@pytest.mark.parametrize("args,kwargs,expected", [
    ((1234.5,), {}, "1,234.50"),                # 全默认 nd=2
    ((1234.5678, 3), {}, "1,234.568"),          # 位置传 nd=3
    ((1234.5678,), {"nd": 3}, "1,234.568"),     # 关键字传 nd (须真叫 nd 且真被用)
    ((1234.5, 0), {}, "1,234"),                  # nd=0: 无小数位, 千分位仍在
    ((-1234.5678, 1), {}, "-1,234.6"),          # 负数 + 非默认精度
    ((None, 4), {}, "—"),                        # 降级分支与 nd 无关
], ids=["默认-nd2", "nd-位置-3位", "nd-关键字-3位", "nd-位置-0位", "负数-nd1", "脏值降级"])
def test_fnum_alias_forwards_nd(args, kwargs, expected):
    """`_fnum` 必须把 nd **原样**转给 `fnum` —— 精度不是可有可无的装饰。

    与 `_fpct` 同一类盲区: AST 断言只锁住 `return fnum(...)` 这个转发**结构**,
    看不出 nd 有没有被吃掉。两种坏改法都能过 AST:
        def _fnum(x, nd=2): return fnum(x)        # 精度参数被静默丢弃
        def _fnum(x, nd=2): return fnum(x, 2)     # 更隐蔽, 写死默认值
    生产侧 (report_md / pipeline / three_levels) 从 v3 import `_fnum` 渲染金额列,
    精度错一位就是报告口径漂移, 而 CI 不会红。

    每条同时断言字面期望值与"与 fnum 一致", 避免退化成同义反复。
    """
    got = utils._fnum(*args, **kwargs)
    assert got == expected
    assert got == utils.fnum(*args, **kwargs)


@pytest.mark.parametrize("args,kwargs,expected", [
    (("x" * 61,), {}, "x" * 59 + "…"),           # 全默认 n=60
    (("abcdefghijk", 10), {}, "abcdefghi…"),     # 位置传 n=10
    (("abcdefgh",), {"n": 5}, "abcd…"),          # 关键字传 n
    (("ab", 1), {}, "…"),                         # n=1: 只剩省略号 (n 真被用, 没被钳到下限)
    (("x" * 10, 10), {}, "x" * 10),               # 恰好等于自定义 n → 不截断
    (("a|b|c", 5), {}, "a／b／c"),                # 先替换竖线再按 n 判长 (5 字恰好不截)
    ((None, 10), {}, "—"),                        # 降级分支与 n 无关
], ids=["默认-n60", "n-位置-10", "n-关键字-5", "n-位置-1", "恰好等于n", "替换后按n判长", "脏值降级"])
def test_clean_alias_forwards_n(args, kwargs, expected):
    """`_clean` 必须把截断长度 n **原样**转给 `clean` —— 报告列宽由此决定。

    `def _clean(s, n=60): return clean(s)` 能过 AST 断言, 却把所有列宽请求
    悄悄按死 60: 报告里只想露 10 字的字段会被截成 60 字, 而截断长度正是
    `s[:n-1] + "…"` 那个 off-by-one 写法要维持的列宽契约。
    关键字形式 (n=5) 同时锁住"形参真叫 n" —— 改名或删掉都会当场 TypeError。

    每条同时断言字面期望值与"与 clean 一致", 避免退化成同义反复。
    """
    got = utils._clean(*args, **kwargs)
    assert got == expected
    assert got == utils.clean(*args, **kwargs)


@pytest.mark.parametrize("alias,public", _ALIAS_PAIRS, ids=[a for a, _ in _ALIAS_PAIRS])
def test_alias_signature_matches_public_function(alias, public):
    """12 个别名的形参 (名字/顺序/默认值/注解) 必须与公开函数**逐项相同**。

    补 AST 断言的第三处盲区: AST 只看函数体 `return public(...)`, 看不见
    `def _fnum(x)` 少写一个 nd 这类改法 —— 那种改法要等生产侧
    `_fnum(roe, 3)` / `_fnum(x, nd=3)` 真正调用时才炸, 测试期一片绿。
    行为用例只覆盖带默认值的 nd / n / sign 三个别名 (其余 9 个全是一串必填
    位置参数, 少传一个当场 TypeError, 不构成静默丢参数), 这里把 12 个的形参
    契约一次性锁死, 顺带保证别名不会被偷偷加参数而生产侧无从察觉。
    """
    import inspect

    alias_sig = inspect.signature(getattr(utils, alias))
    public_sig = inspect.signature(getattr(utils, public))
    assert alias_sig == public_sig, (
        f"{alias} 形参与 {public} 不一致: {alias_sig} != {public_sig}"
    )


# ============================================================
# 顶层 re-export 通道: v3 透传 (静态断言, 不 import v3)
# ============================================================
_V3_PATH = Path(__file__).resolve().parents[1] / "analysis" / "quant_analyzer_v3.py"


def _read_v3_source() -> str:
    """直接读仓库内 analysis/quant_analyzer_v3.py —— 文件缺失就**测试失败**, 不静默 skip。

    刻意不用 conftest.quant_analyzer_v3_source: 那个 fixture 在 analysis/ 目录或
    v3 文件缺失时走 pytest.skip, 于是下面这 24 条 (12 import + 12 __all__) 会在
    "通道宿主文件不见了" 这种最该报警的场景下集体变绿 —— 正是本仓库
    test_fund_flow_domain.py 注释里点名的假绿 (断言被跳过所以照样绿)。
    改成测试自己读: 路径按本文件顶部 sys.path 注入的同一口径从 __file__ 推导
    (不依赖 DA_A_DATA_DIR 覆盖, 免得环境变量把断言指到别的树去), 找不到就 assert 失败。
    """
    assert _V3_PATH.exists(), (
        f"v3 源文件不存在: {_V3_PATH} —— 通道断言必须失败, 不能跳过后假装通过"
    )
    return _V3_PATH.read_text(encoding="utf-8")


def _v3_utils_import_names(source: str) -> set[str]:
    """从 v3 源码里取出 `from analysis.utils import (...)` 实际导入的名字集合。"""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and node.module == "analysis.utils":
            names.update(alias.name for alias in node.names)
    return names


def _v3_all_names(source: str) -> set[str]:
    """取出 v3 的 __all__ 字面量列表。"""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return set()


@pytest.mark.parametrize("name", [a for a, _ in _ALIAS_PAIRS], ids=lambda n: n)
def test_v3_imports_utils_aliases_from_utils_module(name):
    """v3 必须**真的从 analysis.utils 导入**这 12 个名字。

    刻意用 AST 静态断言而不是 `importorskip` 后 `hasattr`:
    importorskip 会在 v3 导入链出问题时**静默跳过**——而 v3 顶层 import 很重
    (连带 v2 / sections / fetcher_contract), 在 CI 矩阵的任一 Python 版本上
    依赖不齐就可能整体跳过, 于是这 12 条变成"永远绿的空断言"。
    那正是本仓库 test_fund_flow_domain.py 注释里点名的"假绿"(断言被跳过所以照样绿)。
    静态读源码与运行环境无关, 矩阵里也照跑; 源码缺失则 assert 失败 (见 _read_v3_source)。
    """
    assert name in _v3_utils_import_names(_read_v3_source()), (
        f"v3 未从 analysis.utils 导入 {name}"
    )


@pytest.mark.parametrize("name", [a for a, _ in _ALIAS_PAIRS], ids=lambda n: n)
def test_v3_declares_utils_aliases_in_dunder_all(name):
    """这 12 个名字还必须留在 v3 的 `__all__` 里。

    只 import 不进 __all__ 时, `from analysis.quant_analyzer_v3 import *` 的老写法
    拿不到它们——通道看似在, 实际已断。
    """
    assert name in _v3_all_names(_read_v3_source()), (
        f"v3 的 __all__ 丢失 {name} (星号导入的老调用方会拿不到)"
    )
