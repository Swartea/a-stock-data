# analysis/sections/holders/render.py
"""§4.3 股东户数 HTML/MD 渲染

4 季趋势表 + 一句话解读（户数↓=集中↑，户数↑=分散↑）
"""
import html as html_mod


def _esc(s):
    if s is None:
        return ""
    return html_mod.escape(str(s))


def _interp(rows: list) -> str:
    """根据最近 2 季户数变化生成一句话解读

    - 户数↓ → 筹码集中度上升（潜在主力吸筹）
    - 户数↑ → 筹码分散度上升（潜在派发/散户接盘）
    - 数据不足 → 提示数据缺失
    """
    if not rows or len(rows) < 2:
        return "数据不足，需 ≥2 季才能判断集中度趋势"
    # 端点默认按报告期倒序，最新在前
    latest = rows[0]
    prev = rows[1]
    try:
        latest_num = float(latest.get("holder_num", 0) or 0)
        prev_num = float(prev.get("holder_num", 0) or 0)
    except (TypeError, ValueError):
        return "户数数据异常，无法解读"
    if prev_num <= 0:
        return "户数数据异常（前期为 0）"
    delta_pct = (latest_num - prev_num) / prev_num * 100
    if delta_pct < -1.0:
        return f"户数环比 ↓{delta_pct:.2f}%，筹码集中度上升（潜在主力吸筹）"
    elif delta_pct > 1.0:
        return f"户数环比 ↑+{delta_pct:.2f}%，筹码分散度上升（潜在派发）"
    else:
        return f"户数环比 {delta_pct:+.2f}%，基本持平"


def render_html(result: dict, writer: list) -> str:
    """渲染 HTML 片段

    失败兜底：result 含 error → "⚠️ 端点不可用"
    无数据 → "⚠️ 无股东户数数据"
    """
    if isinstance(result, dict) and "error" in result:
        return (
            f'<section class="section-holders">'
            f'<h2>📊 股东户数变化</h2>'
            f'<p class="warn">⚠️ 股东户数端点不可用: {_esc(result["error"])}</p>'
            f'</section>'
        )

    rows = result.get("rows", []) or []
    if not rows:
        return (
            f'<section class="section-holders">'
            f'<h2>📊 股东户数变化</h2>'
            f'<p class="warn">⚠️ 暂无股东户数数据（v2 端点 fetch_holder_num_change 未实现）</p>'
            f'</section>'
        )

    # 4 季趋势表
    items = ['<table class="holders-table">']
    items.append('<thead><tr><th>报告期</th><th>股东户数</th><th>环比</th><th>户均持股</th></tr></thead>')
    items.append('<tbody>')
    for r in rows[:4]:
        items.append(
            f'<tr>'
            f'<td>{_esc(r.get("date", ""))}</td>'
            f'<td>{_esc(r.get("holder_num", ""))}</td>'
            f'<td>{_esc(r.get("change_ratio", ""))}%</td>'
            f'<td>{_esc(r.get("avg_shares_per_holder", ""))}</td>'
            f'</tr>'
        )
    items.append('</tbody></table>')

    interp = _interp(rows)

    return (
        f'<section class="section-holders">'
        f'<h2>📊 股东户数变化</h2>'
        f'{"".join(items)}'
        f'<p class="interpretation">💡 { _esc(interp) }</p>'
        f'<p class="source">📡 数据来源: 东方财富 datacenter-web RPT_HOLDERNUMLATEST</p>'
        f'</section>'
    )


def render_md(result: dict, writer: list) -> str:
    """渲染 MD 片段"""
    if isinstance(result, dict) and "error" in result:
        return f"## 📊 股东户数变化\n\n⚠️ 股东户数端点不可用: {result['error']}\n"

    rows = result.get("rows", []) or []
    if not rows:
        return "## 📊 股东户数变化\n\n⚠️ 暂无股东户数数据（v2 端点 fetch_holder_num_change 未实现）\n"

    lines = ["## 📊 股东户数变化", ""]
    lines.append("| 报告期 | 股东户数 | 环比 | 户均持股 |")
    lines.append("|---|---|---|---|")
    for r in rows[:4]:
        lines.append(
            f"| {r.get('date', '')} | {r.get('holder_num', '')} | "
            f"{r.get('change_ratio', '')}% | {r.get('avg_shares_per_holder', '')} |"
        )
    lines.append("")
    lines.append(f"💡 {_interp(rows)}")
    lines.append("")
    lines.append("📡 数据来源: 东方财富 datacenter-web RPT_HOLDERNUMLATEST")
    return "\n".join(lines)
