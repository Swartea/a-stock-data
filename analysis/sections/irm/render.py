# analysis/sections/irm/render.py
"""§10.1 互动易 HTML/MD 渲染"""
import html as html_mod


def _esc(s):
    if s is None:
        return ""
    return html_mod.escape(str(s))


def render_html(result: dict, writer: list) -> str:
    """渲染 HTML 片段

    失败兜底：result 含 error → "⚠️ 端点不可用"
    """
    if isinstance(result, dict) and "error" in result:
        return f'<section class="section-irm"><h2>📞 投资者互动问答</h2><p class="warn">⚠️ 互动易端点不可用: {_esc(result["error"])}</p></section>'

    rows = result.get("rows", []) or []
    if not rows:
        return f'<section class="section-irm"><h2>📞 投资者互动问答</h2><p class="warn">⚠️ 互动易无数据</p></section>'

    items = []
    for r in rows[:5]:
        items.append(
            f'<div class="irm-item">'
            f'<p class="irm-q"><b>问</b>({_esc(r.get("date", ""))}): {_esc(r.get("question", ""))}</p>'
            f'<p class="irm-a"><b>答</b>: {_esc(r.get("answer", ""))}</p>'
            f'<p class="irm-asker">— {_esc(r.get("asker", ""))}</p>'
            f'</div>'
        )

    return (
        f'<section class="section-irm">'
        f'<h2>📞 投资者互动问答</h2>'
        f'<div class="irm-list">' + "".join(items) + '</div>'
        f'<p class="source">📡 数据来源: 巨潮 irm.cninfo.com.cn</p>'
        f'</section>'
    )


def render_md(result: dict, writer: list) -> str:
    """渲染 MD 片段"""
    if isinstance(result, dict) and "error" in result:
        return f"## 📞 投资者互动问答\n\n⚠️ 互动易端点不可用: {result['error']}\n"

    rows = result.get("rows", []) or []
    if not rows:
        return f"## 📞 投资者互动问答\n\n⚠️ 互动易无数据\n"

    lines = [f"## 📞 投资者互动问答", ""]
    for r in rows[:5]:
        lines.append(f"**问** ({r.get('date', '')}): {r.get('question', '')}")
        lines.append(f"**答**: {r.get('answer', '')}")
        lines.append(f"— {r.get('asker', '')}")
        lines.append("")

    lines.append("📡 数据来源: 巨潮 irm.cninfo.com.cn")
    return "\n".join(lines)
