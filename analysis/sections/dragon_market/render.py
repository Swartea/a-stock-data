# analysis/sections/dragon_market/render.py
"""§3.9 全市场龙虎榜 HTML/MD 渲染

市场维度（非单票）：
- Top 20 净买额个股（按 net_buy desc）
- 净买总额
- 解读：主力资金动向（净买为正→主力介入，净买为负→主力派发）
"""
import html as html_mod


def _esc(s):
    if s is None:
        return ""
    return html_mod.escape(str(s))


def _fmt_yi(yuan):
    """元 → 亿元字符串"""
    try:
        v = float(yuan) / 1e8
        return f"{v:.2f}亿"
    except Exception:
        return "—"


def _interp(stocks: list) -> str:
    """根据 Top 20 净买额生成一句话解读

    - 净买总额 ≥ 10 亿 → 主力大幅介入，市场情绪偏多
    - 净买总额 ≥ 0 → 主力温和介入
    - 净买总额 < 0 → 主力净流出，谨慎
    - 数量 < top_n → 数据不全，提示
    """
    if not stocks:
        return "数据不足，无法判断主力动向"

    try:
        nets = [float(s.get("net_buy", 0) or 0) for s in stocks]
        total = sum(nets)
    except (TypeError, ValueError):
        return "净买数据异常，无法解读"

    n = len(stocks)
    if total >= 1e9:
        mood = "主力大幅介入，市场情绪偏多"
    elif total >= 0:
        mood = "主力温和介入"
    else:
        mood = "主力净流出，谨慎"

    hint = ""
    if n < 20:
        hint = f"（仅 {n} 条上榜）"

    return f"Top {n} 净买总额 {_fmt_yi(total)}，{mood}{hint}"


def render_html(result: dict, writer: list) -> str:
    """渲染 HTML 片段

    失败兜底：result 含 error → "⚠️ 端点不可用"
    无数据 → "⚠️ 无龙虎榜数据"
    """
    if isinstance(result, dict) and "error" in result:
        return (
            f'<section class="section-dragon-market">'
            f'<h2>🐉 龙虎榜动向（市场）</h2>'
            f'<p class="warn">⚠️ 龙虎榜全市场端点不可用: {_esc(result["error"])}</p>'
            f'</section>'
        )

    stocks = result.get("stocks", []) or []
    total_records = result.get("total_records", 0) or 0

    if not stocks:
        return (
            f'<section class="section-dragon-market">'
            f'<h2>🐉 龙虎榜动向（市场）</h2>'
            f'<p class="warn">⚠️ 暂无全市场龙虎榜数据（v2 端点 daily_dragon_tiger 未实现）</p>'
            f'</section>'
        )

    # 净买总额
    try:
        total = sum(float(s.get("net_buy", 0) or 0) for s in stocks)
    except (TypeError, ValueError):
        total = 0

    parts = []
    parts.append('<section class="section-dragon-market">')
    parts.append('<h2>🐉 龙虎榜动向（市场）</h2>')
    parts.append(
        f'<p class="summary">📊 当日全市场共 <strong>{total_records}</strong> 条龙虎榜记录，'
        f'Top {len(stocks)} 净买总额: <strong>{_esc(_fmt_yi(total))}</strong></p>'
    )
    parts.append(f'<p class="interpretation">💡 {_esc(_interp(stocks))}</p>')

    # Top 20 净买额个股
    parts.append('<h3>Top 20 净买额个股</h3>')
    parts.append('<table class="dragon-market-table">')
    parts.append('<thead><tr><th>名称</th><th>净买额</th><th>上榜原因</th><th>涨跌幅%</th></tr></thead>')
    parts.append('<tbody>')
    for s in stocks[:20]:
        parts.append(
            f'<tr>'
            f'<td>{_esc(s.get("name", ""))} {_esc(s.get("code", ""))}</td>'
            f'<td>{_esc(_fmt_yi(s.get("net_buy", 0)))}</td>'
            f'<td>{_esc(s.get("reason", ""))}</td>'
            f'<td>{_esc(s.get("pct_chg", ""))}</td>'
            f'</tr>'
        )
    parts.append('</tbody></table>')

    parts.append('<p class="source">📡 数据来源: 东方财富 datacenter-web RPT_DAILYBILLBOARD_DETAILSNEW（§3.9）</p>')
    parts.append('</section>')

    return "".join(parts)


def render_md(result: dict, writer: list) -> str:
    """渲染 MD 片段"""
    if isinstance(result, dict) and "error" in result:
        return f"## 🐉 龙虎榜动向（市场）\n\n⚠️ 龙虎榜全市场端点不可用: {result['error']}\n"

    stocks = result.get("stocks", []) or []
    total_records = result.get("total_records", 0) or 0

    if not stocks:
        return "## 🐉 龙虎榜动向（市场）\n\n⚠️ 暂无全市场龙虎榜数据（v2 端点 daily_dragon_tiger 未实现）\n"

    try:
        total = sum(float(s.get("net_buy", 0) or 0) for s in stocks)
    except (TypeError, ValueError):
        total = 0

    lines = ["## 🐉 龙虎榜动向（市场）", ""]
    lines.append(
        f"📊 当日全市场共 **{total_records}** 条龙虎榜记录，"
        f"Top {len(stocks)} 净买总额: **{_fmt_yi(total)}**"
    )
    lines.append("")
    lines.append(f"💡 {_interp(stocks)}")
    lines.append("")

    # Top 20 净买额个股
    lines.append("### Top 20 净买额个股")
    lines.append("")
    lines.append("| 名称 | 净买额 | 上榜原因 | 涨跌幅% |")
    lines.append("|---|---|---|---|")
    for s in stocks[:20]:
        lines.append(
            f"| {s.get('name', '')} {s.get('code', '')} | "
            f"{_fmt_yi(s.get('net_buy', 0))} | {s.get('reason', '')} | "
            f"{s.get('pct_chg', '')} |"
        )
    lines.append("")

    lines.append("📡 数据来源: 东方财富 datacenter-web RPT_DAILYBILLBOARD_DETAILSNEW（§3.9）")
    return "\n".join(lines)
