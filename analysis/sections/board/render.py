# analysis/sections/board/render.py
"""§8.1-8.3 打板情绪 HTML/MD 渲染

市场维度（非单票）：
- 当日涨停 Top 10（按连板数/封板资金排序）
- 跌停池样本（最多 5 条）
- 涨停原因归因（同花顺 Top 5）
- §8.3 情绪温度计：炸板率/连板高度/连板梯队
"""
import html as html_mod


def _esc(s):
    if s is None:
        return ""
    return html_mod.escape(str(s))


def _interp_sentiment(sent: dict) -> str:
    """根据情绪字典生成一句话解读

    - 涨停 ≥ 50 + 炸板率 < 30% → 情绪活跃，追高胜率较高
    - 涨停 ≥ 20 + 炸板率 < 50% → 情绪中性偏暖
    - 涨停 < 20 或 炸板率 > 50% → 情绪低迷，谨慎追高
    - 最高连板 ≥ 5 → 有空间高度
    """
    if not sent:
        return "数据不足，无法判断打板情绪"

    zt_n = sent.get("zt_count", 0) or 0
    br = sent.get("break_rate", 0) or 0
    max_h = sent.get("max_height", 0) or 0

    if zt_n >= 50 and br < 30:
        mood = "情绪活跃，追高胜率较高"
    elif zt_n >= 20 and br < 50:
        mood = "情绪中性偏暖"
    else:
        mood = "情绪低迷，谨慎追高"

    height_hint = ""
    if max_h >= 5:
        height_hint = f"，最高 {max_h} 连板（空间高度）"
    elif max_h >= 3:
        height_hint = f"，最高 {max_h} 连板"

    return f"{mood}（涨停 {zt_n} 只，炸板率 {br}%{height_hint}）"


def _top_zt(zt: list, top_n: int = 10) -> list:
    """Top N 涨停：按连板数 desc → 封板资金 desc → 封板时间 asc"""
    def sort_key(s):
        try:
            return (-int(s.get("limit_days", 0) or 0),
                    -float(s.get("seal_fund", 0) or 0),
                    str(s.get("first_seal", "99:99:99") or "99:99:99"))
        except Exception:
            return (0, 0, "99:99:99")
    return sorted(zt, key=sort_key)[:top_n]


def _top_dt(dt: list, top_n: int = 5) -> list:
    """Top N 跌停：按封单资金 desc"""
    def sort_key(s):
        try:
            return -float(s.get("seal_fund", 0) or 0)
        except Exception:
            return 0
    return sorted(dt, key=sort_key)[:top_n]


def _top_reasons(reasons: list, top_n: int = 5) -> list:
    """Top N 涨停原因：按封板成功率 desc → 封单额 desc"""
    def sort_key(s):
        try:
            return (-float(s.get("seal_rate", 0) or 0),
                    -float(s.get("seal_amount", 0) or 0))
        except Exception:
            return (0, 0)
    return sorted(reasons, key=sort_key)[:top_n]


def _fmt_yi(yuan):
    """元 → 亿元字符串"""
    try:
        v = float(yuan) / 1e8
        return f"{v:.2f}亿"
    except Exception:
        return "—"


def render_html(result: dict, writer: list) -> str:
    """渲染 HTML 片段

    失败兜底：result 含 error → "⚠️ 端点不可用"
    无数据 → "⚠️ 无打板数据"
    """
    if isinstance(result, dict) and "error" in result:
        return (
            f'<section class="section-board">'
            f'<h2>🎰 打板情绪</h2>'
            f'<p class="warn">⚠️ 打板端点不可用: {_esc(result["error"])}</p>'
            f'</section>'
        )

    zt = result.get("zt", []) or []
    dt = result.get("dt", []) or []
    reasons = result.get("limit_up_reasons", []) or []
    sent = result.get("sentiment", {}) or {}

    if not zt and not sent:
        return (
            f'<section class="section-board">'
            f'<h2>🎰 打板情绪</h2>'
            f'<p class="warn">⚠️ 暂无打板数据（v2 端点 em_zt_pool 等未实现）</p>'
            f'</section>'
        )

    # 情绪摘要
    parts = []
    parts.append('<section class="section-board">')
    parts.append('<h2>🎰 打板情绪</h2>')

    # §8.3 情绪温度计
    if sent:
        zt_n = sent.get("zt_count", 0) or 0
        dt_n = sent.get("dt_count", 0) or 0
        br = sent.get("break_rate", 0) or 0
        max_h = sent.get("max_height", 0) or 0
        parts.append(
            f'<p class="summary">📊 涨停 <strong>{zt_n}</strong> 只，'
            f'跌停 <strong>{dt_n}</strong> 只，'
            f'炸板率 <strong>{br}%</strong>，'
            f'最高 <strong>{max_h}</strong> 连板</p>'
        )
    parts.append(f'<p class="interpretation">💡 {_esc(_interp_sentiment(sent))}</p>')

    # 当日涨停 Top 10
    top_zt = _top_zt(zt, 10)
    if top_zt:
        parts.append('<h3>当日涨停 Top 10</h3>')
        parts.append('<table class="board-table">')
        parts.append('<thead><tr><th>名称</th><th>连板</th><th>封板时间</th><th>封板资金</th><th>行业</th></tr></thead>')
        parts.append('<tbody>')
        for s in top_zt:
            parts.append(
                f'<tr>'
                f'<td>{_esc(s.get("name", ""))} {_esc(s.get("code", ""))}</td>'
                f'<td>{_esc(s.get("limit_days", ""))}</td>'
                f'<td>{_esc(s.get("first_seal", ""))}</td>'
                f'<td>{_esc(_fmt_yi(s.get("seal_fund", 0)))}</td>'
                f'<td>{_esc(s.get("industry", ""))}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    # 涨停原因归因 Top 5（同花顺）
    top_reasons = _top_reasons(reasons, 5)
    if top_reasons:
        parts.append('<h3>涨停原因归因（Top 5）</h3>')
        parts.append('<table class="board-table">')
        parts.append('<thead><tr><th>名称</th><th>涨停原因</th><th>封板率</th><th>几板</th></tr></thead>')
        parts.append('<tbody>')
        for s in top_reasons:
            parts.append(
                f'<tr>'
                f'<td>{_esc(s.get("name", ""))}</td>'
                f'<td>{_esc(s.get("reason", ""))}</td>'
                f'<td>{_esc(s.get("seal_rate", ""))}</td>'
                f'<td>{_esc(s.get("high_days", ""))}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    # 跌停池样本 Top 5
    top_dt = _top_dt(dt, 5)
    if top_dt:
        parts.append('<h3>跌停池样本（Top 5 封单额）</h3>')
        parts.append('<table class="board-table">')
        parts.append('<thead><tr><th>名称</th><th>跌幅%</th><th>连跌</th><th>封单资金</th></tr></thead>')
        parts.append('<tbody>')
        for s in top_dt:
            parts.append(
                f'<tr>'
                f'<td>{_esc(s.get("name", ""))} {_esc(s.get("code", ""))}</td>'
                f'<td>{_esc(s.get("pct", ""))}</td>'
                f'<td>{_esc(s.get("dt_days", ""))}</td>'
                f'<td>{_esc(_fmt_yi(s.get("seal_fund", 0)))}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    # 连板梯队
    ladder = sent.get("ladder", {}) if sent else {}
    if ladder:
        ladder_str = " / ".join(f"{k}板:{v}家" for k, v in sorted(ladder.items(), key=lambda x: int(x[0])))
        parts.append(f'<p class="ladder">🏆 连板梯队: {_esc(ladder_str)}</p>')

    parts.append('<p class="source">📡 数据来源: 东方财富 push2ex 四池 + 同花顺涨停揭秘（§8.1-8.3）</p>')
    parts.append('</section>')

    return "".join(parts)


def render_md(result: dict, writer: list) -> str:
    """渲染 MD 片段"""
    if isinstance(result, dict) and "error" in result:
        return f"## 🎰 打板情绪\n\n⚠️ 打板端点不可用: {result['error']}\n"

    zt = result.get("zt", []) or []
    dt = result.get("dt", []) or []
    reasons = result.get("limit_up_reasons", []) or []
    sent = result.get("sentiment", {}) or {}

    if not zt and not sent:
        return "## 🎰 打板情绪\n\n⚠️ 暂无打板数据（v2 端点 em_zt_pool 等未实现）\n"

    lines = ["## 🎰 打板情绪", ""]

    # §8.3 情绪温度计
    if sent:
        zt_n = sent.get("zt_count", 0) or 0
        dt_n = sent.get("dt_count", 0) or 0
        br = sent.get("break_rate", 0) or 0
        max_h = sent.get("max_height", 0) or 0
        lines.append(
            f"📊 涨停 **{zt_n}** 只，跌停 **{dt_n}** 只，"
            f"炸板率 **{br}%**，最高 **{max_h}** 连板"
        )
        lines.append("")
    lines.append(f"💡 {_interp_sentiment(sent)}")
    lines.append("")

    # 当日涨停 Top 10
    top_zt = _top_zt(zt, 10)
    if top_zt:
        lines.append("### 当日涨停 Top 10")
        lines.append("")
        lines.append("| 名称 | 连板 | 封板时间 | 封板资金 | 行业 |")
        lines.append("|---|---|---|---|---|")
        for s in top_zt:
            lines.append(
                f"| {s.get('name', '')} {s.get('code', '')} | "
                f"{s.get('limit_days', '')} | {s.get('first_seal', '')} | "
                f"{_fmt_yi(s.get('seal_fund', 0))} | {s.get('industry', '')} |"
            )
        lines.append("")

    # 涨停原因 Top 5
    top_reasons = _top_reasons(reasons, 5)
    if top_reasons:
        lines.append("### 涨停原因归因（Top 5）")
        lines.append("")
        lines.append("| 名称 | 涨停原因 | 封板率 | 几板 |")
        lines.append("|---|---|---|---|")
        for s in top_reasons:
            lines.append(
                f"| {s.get('name', '')} | {s.get('reason', '')} | "
                f"{s.get('seal_rate', '')} | {s.get('high_days', '')} |"
            )
        lines.append("")

    # 跌停池样本
    top_dt = _top_dt(dt, 5)
    if top_dt:
        lines.append("### 跌停池样本（Top 5 封单额）")
        lines.append("")
        lines.append("| 名称 | 跌幅% | 连跌 | 封单资金 |")
        lines.append("|---|---|---|---|")
        for s in top_dt:
            lines.append(
                f"| {s.get('name', '')} {s.get('code', '')} | "
                f"{s.get('pct', '')} | {s.get('dt_days', '')} | "
                f"{_fmt_yi(s.get('seal_fund', 0))} |"
            )
        lines.append("")

    # 连板梯队
    ladder = sent.get("ladder", {}) if sent else {}
    if ladder:
        ladder_str = " / ".join(f"{k}板:{v}家" for k, v in sorted(ladder.items(), key=lambda x: int(x[0])))
        lines.append(f"🏆 连板梯队: {ladder_str}")
        lines.append("")

    lines.append("📡 数据来源: 东方财富 push2ex 四池 + 同花顺涨停揭秘（§8.1-8.3）")
    return "\n".join(lines)
