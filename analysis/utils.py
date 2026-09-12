"""analysis/ 通用工具函数 (P2-A 拆分, 2026-09-12)

按规范 §2 模块边界, 把 v3 主文件的纯工具函数集中到 utils.py:
- 序列化 / 时间格式化 / 数值转换 / 显示格式化 / 字符串清理
- 增速/环比解释 (YOY/QOQ 业务口径)
- 财务/股票日志/龙虎榜解读 (人话)

向后兼容: v3 顶层 `from analysis.utils import *` 全部重导出, 老 import 路径仍工作。

§1 '不修改业务口径' — 所有函数体照搬 v3, 仅搬位置。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


# ============================================================
# 序列化 (§3 '禁止 default=str 静默序列化')
# ============================================================
def json_default(obj: Any) -> Any:
    """P1-C 规范整改 (2026-09-11, §3): 显式 JSON 序列化默认处理。

    替代禁用的 default=str 静默序列化 (规范 §3 '禁止静默使用 default=str 掩盖未定义
    的序列化类型; 应显式转换日期、数值和模型')。

    支持类型:
      - datetime/date:  → ISO 8601 字符串 (含时区)
      - Decimal:        → 浮点 (金融场景常见)
      - Path:           → 字符串
      - set/frozenset:  → 排序后的 list (确定性 JSON)
      - bytes:          → hex 编码
      - Exception:      → type 名称 + 消息
      - Enum:           → value

    未知类型: raise TypeError (强制显式声明, 不静默字符串化)
    """
    if hasattr(obj, "isoformat"):
        # datetime / date / time
        try:
            return obj.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(obj, set):
        try:
            return sorted(list(obj))
        except TypeError:
            return list(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, Exception):
        return f"{type(obj).__name__}: {obj}"
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    # 兜底: 强制显式, 不静默
    raise TypeError(
        f"object of type {type(obj).__name__} is not JSON serializable; "
        f"显式转换或加进 json_default 列表 (规范 §3)"
    )


# 别名 (兼容老调用 `_json_default`)
def _json_default(obj: Any) -> Any:
    return json_default(obj)


# ============================================================
# 时间格式化
# ============================================================
def fmt_time(ts: float) -> str:
    """时间戳 → HH:MM:SS 字符串"""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


# 别名
def _fmt_time(ts: float) -> str:
    return fmt_time(ts)


# ============================================================
# 数值转换 / 显示
# ============================================================
def to_float(v: Any) -> float | None:
    """安全 float 转换, None/不可转 → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


# 别名
def _to_float(v: Any) -> float | None:
    return to_float(v)


def num_or_none(x: Any) -> float | None:
    """值 → float 或 None (与 to_float 一致, 命名兼容)"""
    return to_float(x)


# 别名
def _num_or_none(x: Any) -> float | None:
    return num_or_none(x)


def clean(s: str, n: int = 60) -> str:
    """去竖线/换行, 防 markdown 表格破坏; 截断。"""
    if s is None:
        return "—"
    s = str(s).replace("|", "／").replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# 别名
def _clean(s: str, n: int = 60) -> str:
    return clean(s, n)


def fnum(x: Any, nd: int = 2) -> str:
    """数值 → 显示串; None/NaN/inf → '—'。"""
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x or x in (float("inf"), float("-inf")):
        return "—"
    return f"{x:,.{nd}f}"


# 别名
def _fnum(x: Any, nd: int = 2) -> str:
    return fnum(x, nd)


def fpct(x: Any, nd: int = 1, sign: bool = True) -> str:
    """百分比显示; None → '—'"""
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x or x in (float("inf"), float("-inf")):
        return "—"
    if sign:
        return f"{x:+.{nd}f}%"
    return f"{x:.{nd}f}%"


# 别名
def _fpct(x: Any, nd: int = 1, sign: bool = True) -> str:
    return fpct(x, nd, sign)


# ============================================================
# 业务口径解读 (§1 '不修改业务口径')
# ============================================================
def interpret_yoy(growth: Any, kind: str) -> str:
    """增速 → 人话。kind: '营收'/'净利' (§1 业务口径照搬)"""
    if growth is None:
        return f"{kind}同比 — (数据未披露/无上年同期基数)"
    g = float(growth)
    if g >= 30:
        return f"{kind}同比 **+{g:.1f}%** — 高速增长(🔥)"
    if g >= 10:
        return f"{kind}同比 **+{g:.1f}%** — 稳健增长"
    if g >= 0:
        return f"{kind}同比 **+{g:.1f}%** — 微增"
    return f"{kind}同比 **{g:.1f}%** — 负增长(⚠️ 需排查原因)"


# 别名
def _interpret_yoy(growth: Any, kind: str) -> str:
    return interpret_yoy(growth, kind)


def interpret_qoq(growth: Any, kind: str) -> str:
    """环比 → 人话"""
    if growth is None:
        return ""
    g = float(growth)
    return f"单季环比 **{g:+.1f}%**" + ("(环比提速)" if g > 0 else "(环比转弱)")


# 别名
def _interpret_qoq(growth: Any, kind: str) -> str:
    return interpret_qoq(growth, kind)


def finance_talk(fin: dict) -> list:
    """财务体检一句人话点评 → 若干 bullet (数据从 fetcher 实取, 无则 '—')。"""
    if not fin or not isinstance(fin, dict) or "latest" not in fin:
        return ["> ⚠️ 财务摘要数据缺失, 无法体检 (不编造)"]
    lt = fin.get("latest") or {}
    out = [f"- 最新报告期 **{lt.get('report_date','—')}** 财务体检:"]
    out.append(f"- {interpret_yoy(lt.get('yoy_revenue'), '营收')} | "
               f"{interpret_yoy(lt.get('yoy_profit'), '净利')}")
    qr, qp = lt.get("qoq_revenue"), lt.get("qoq_profit")
    if qr is not None or qp is not None:
        parts = []
        if qr is not None:
            parts.append(f"营收单季环比 **{qr:+.1f}%**")
        if qp is not None:
            parts.append(f"净利单季环比 **{qp:+.1f}%**")
        out.append("- 环比动能: " + " / ".join(parts))
    # 盈利质量
    roe, gm, debt = lt.get("roe"), lt.get("gross_margin"), lt.get("debt_ratio")
    bits = []
    if roe is not None:
        bits.append(f"ROE(加权) {fnum(roe)}%" +
                    ("(≥15% 回报强)" if roe >= 15 else ("(8~15% 中等)" if roe >= 8 else "(<8% 偏弱)")))
    if gm is not None:
        bits.append(f"毛利率 {fnum(gm)}%" +
                    ("(≥40% 高毛利)" if gm >= 40 else ("(20~40% 中等)" if gm >= 20 else "(<20% 薄利)")))
    if debt is not None:
        bits.append(f"资产负债率 {fnum(debt)}%" +
                    ("(≤50% 稳健)" if debt <= 50 else ("(50~70% 中性)" if debt <= 70 else "(>70% 高杠杆🚨)")))
    if bits:
        out.append("- " + " | ".join(bits))
    # 一句人话总结
    profit_yi = lt.get("profit_yi")
    yoy_p = lt.get("yoy_profit")
    if profit_yi is not None and profit_yi < 0:
        verdict = "最新一期仍处亏损状态, 首要看点是扭亏进度与现金流"
    elif yoy_p is not None and yoy_p < 0:
        verdict = "净利同比负增长是当前最大财务风险点, 需盯紧后续季报能否收窄"
    elif yoy_p is not None:
        verdict = "盈利同比正增长, 当前主业经营数据未见明显恶化"
    else:
        verdict = "同比基数缺失(披露窗口外), 以绝对额与环比为准"
    out.append(f"> 📝 人话点评: 最新一期**净利同比 {fpct(yoy_p)}**、营收同比 "
               f"{fpct(lt.get('yoy_revenue'))}, {verdict}")
    return out


# 别名
def _finance_talk(fin: dict) -> list:
    return finance_talk(fin)
