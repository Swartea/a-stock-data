# analysis/sections/dividend/render.py
"""§4.4 分红送转 HTML/MD 渲染

5 年分红表（每股派息/送股/转增）+ 分红率均值
"""
import html as html_mod


def _esc(s):
    if s is None:
        return ""
    return html_mod.escape(str(s))


def _interp(rows: list) -> str:
    """根据分红记录生成一句话解读

    - 平均派息 ≥ 0.3 元 → 持续回报能力强
    - 平均派息 < 0.1 元 → 分红率低，回报股东能力弱
    - 含转增 → 股本扩张
    - 数据不足 → 提示数据缺失
    """
    if not rows or len(rows) < 1:
        return "数据不足，无法判断分红能力"

    # 计算平均派息（brief 字段名：bonus_rmb = 每股派息）
    try:
        bonuses = [float(r.get("bonus_rmb", 0) or 0) for r in rows]
        avg_bonus = sum(bonuses) / len(bonuses) if bonuses else 0
    except (TypeError, ValueError):
        return "分红数据异常，无法解读"

    has_transfer = any(
        float(r.get("transfer_ratio", 0) or 0) > 0 for r in rows
    )

    if avg_bonus >= 0.3:
        rating = "持续回报能力强"
    elif avg_bonus >= 0.1:
        rating = "分红水平中等"
    else:
        rating = "分红率低，回报股东能力弱"

    if has_transfer:
        return f"{len(rows)} 条平均每股派息 {avg_bonus:.2f} 元（{rating}）；含转增，股本扩张"
    return f"{len(rows)} 条平均每股派息 {avg_bonus:.2f} 元（{rating}）"


def _avg_bonus_rmb(rows: list) -> str:
    """计算平均派息（bonus_rmb 字段，元/股）"""
    if not rows:
        return "—"
    try:
        bonuses = [float(r.get("bonus_rmb", 0) or 0) for r in rows]
        avg = sum(bonuses) / len(bonuses) if bonuses else 0
        return f"{avg:.2f}"
    except (TypeError, ValueError):
        return "—"


def render_html(result: dict, writer: list) -> str:
    """渲染 HTML 片段

    失败兜底：result 含 error → "⚠️ 端点不可用"
    无数据 → "⚠️ 无分红数据"
    """
    if isinstance(result, dict) and "error" in result:
        return (
            f'<section class="section-dividend">'
            f'<h2>💰 分红送转</h2>'
            f'<p class="warn">⚠️ 分红端点不可用: {_esc(result["error"])}</p>'
            f'</section>'
        )

    rows = result.get("rows", []) or []
    if not rows:
        return (
            f'<section class="section-dividend">'
            f'<h2>💰 分红送转</h2>'
            f'<p class="warn">⚠️ 暂无分红数据（v2 端点 fetch_dividend_history 未实现）</p>'
            f'</section>'
        )

    # 5 年分红表（最多 10 条 ≈ 5 年）
    items = ['<table class="dividend-table">']
    items.append('<thead><tr><th>报告期</th><th>方案</th><th>每股派息(元)</th><th>每股送股</th><th>每股转增</th></tr></thead>')
    items.append('<tbody>')
    for r in rows[:10]:
        items.append(
            f'<tr>'
            f'<td>{_esc(r.get("report_date", ""))}</td>'
            f'<td>{_esc(r.get("plan", ""))}</td>'
            f'<td>{_esc(r.get("bonus_rmb", ""))}</td>'
            f'<td>{_esc(r.get("bonus_ratio", ""))}</td>'
            f'<td>{_esc(r.get("transfer_ratio", ""))}</td>'
            f'</tr>'
        )
    items.append('</tbody></table>')

    avg = _avg_bonus_rmb(rows)
    interp = _interp(rows)

    return (
        f'<section class="section-dividend">'
        f'<h2>💰 分红送转</h2>'
        f'<p class="summary">📊 {len(rows)} 条平均每股派息: <strong>{_esc(avg)}</strong> 元</p>'
        f'{"".join(items)}'
        f'<p class="interpretation">💡 {_esc(interp)}</p>'
        f'<p class="source">📡 数据来源: 东方财富 datacenter-web RPT_SHAREBONUS_DET</p>'
        f'</section>'
    )


def render_md(result: dict, writer: list) -> str:
    """渲染 MD 片段"""
    if isinstance(result, dict) and "error" in result:
        return f"## 💰 分红送转\n\n⚠️ 分红端点不可用: {result['error']}\n"

    rows = result.get("rows", []) or []
    if not rows:
        return "## 💰 分红送转\n\n⚠️ 暂无分红数据（v2 端点 fetch_dividend_history 未实现）\n"

    lines = ["## 💰 分红送转", ""]
    avg = _avg_bonus_rmb(rows)
    lines.append(f"📊 {len(rows)} 条平均每股派息: **{avg}** 元")
    lines.append("")
    lines.append("| 报告期 | 方案 | 每股派息(元) | 每股送股 | 每股转增 |")
    lines.append("|---|---|---|---|---|")
    for r in rows[:10]:
        lines.append(
            f"| {r.get('report_date', '')} | {r.get('plan', '')} | "
            f"{r.get('bonus_rmb', '')} | {r.get('bonus_ratio', '')} | "
            f"{r.get('transfer_ratio', '')} |"
        )
    lines.append("")
    lines.append(f"💡 {_interp(rows)}")
    lines.append("")
    lines.append("📡 数据来源: 东方财富 datacenter-web RPT_SHAREBONUS_DET")
    return "\n".join(lines)
