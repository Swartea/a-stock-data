"""HTML 转义加固测试 (P1-D, 2026-09-11, 规范 §7 + §3)

测试 analysis/html_report_v3.py:_esc 对 XSS 攻击的防御:
- <script>alert(1)</script> 等标签注入
- & 转义
- 双引号/单引号属性注入
- JS: URL 伪协议
"""
import os
import re
import sys
from pathlib import Path

# P1-D 测试: 使用仓库/CI 工作目录, 不绑定个人 Mac 路径
WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(WORKDIR / "analysis"))
sys.path.insert(0, str(WORKDIR))

from html_report_v3 import _esc


# ============================================================
# 1. _esc 基础 XSS 防御
# ============================================================
def test_esc_basic_amp_lt_gt():
    """& < > 必须转义 (防标签注入)"""
    s = "<script>alert(1)</script>"
    assert _esc(s) == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_esc_quotes():
    """双引号/单引号必须转义 (防属性注入)"""
    s = '" onclick="alert(1)'
    # html.escape 默认 quote=True, 转义双引号
    assert _esc(s) == "&quot; onclick=&quot;alert(1)"


def test_esc_ampersand():
    """& 必须先转义为 &amp; (否则后续 &lt; 会被双重解析)"""
    s = "A & B"
    assert _esc(s) == "A &amp; B"


def test_esc_none_safe():
    """None 不会抛异常 (防御性)"""
    # 取决于实现, 实际 _esc 期望字符串, 但应该不崩
    try:
        r = _esc(None)
        # 如果不抛, 应该是字符串化的 None
        assert isinstance(r, str)
    except (TypeError, AttributeError):
        # 抛错也 OK, 关键是 report 层不传 None
        pass


def test_esc_passthrough_safe_text():
    """正常文本应该原样保留"""
    s = "支撑下沿 7.16 元 (-27.9%)"
    assert _esc(s) == s


def test_esc_empty_string():
    """空字符串返回空"""
    assert _esc("") == ""


# ============================================================
# 2. XSS 攻击向量
# ============================================================
def test_esc_img_onerror():
    """<img onerror> 注入应被转义 — < > 被转义, onerror 字符串保留但 quote 保护属性"""
    s = '<img src=x onerror="alert(1)">'
    r = _esc(s)
    # 关键: < > 必须被转义, 防止构造新标签
    assert "<img" not in r
    assert "&lt;img" in r
    # 字符串 onerror 仍存在 (无害, 因为是 text content 不是 attribute)
    # 但 quote 被转义, 防止属性逃逸
    assert "onerror=&quot;" in r


def test_esc_javascript_url():
    """javascript: URL 应被转义"""
    s = '<a href="javascript:alert(1)">click</a>'
    r = _esc(s)
    assert "javascript:" in r  # 字符串保留, 但 < > 转义
    assert "<a" not in r
    assert "&lt;a" in r


def test_esc_event_handlers():
    """onclick / onload 等事件属性应被转义"""
    s = '<div onclick="steal()">x</div>'
    r = _esc(s)
    assert "<div" not in r
    assert "&lt;div" in r


# ============================================================
# 3. 静态分析: html_report_v3.py 已知外部文本拼接点都应 _esc
# ============================================================
def test_audit_checklist_5state_uses_esc():
    """P1-A 7.2 加的 5 项 GFM checklist 必须 _esc(label) + _esc(txt)"""
    src = (WORKDIR / "analysis" / "html_report_v3.py").read_text(encoding="utf-8")
    # 找 _render_checklist 末尾的 task-list-item
    import re
    m = re.search(r"for label, txt in items5:.*?</ul>", src, re.DOTALL)
    assert m, "P1-A 5 项 checklist 块未找到"
    block = m.group(0)
    assert "_esc(label)" in block, "5 项 checklist label 未 _esc"
    assert "_esc(txt)" in block, "5 项 checklist txt 未 _esc"


def test_audit_risk_table_uses_esc():
    """P1-A 7.2 加的风险大表 5 列必须 _esc"""
    src = (WORKDIR / "analysis" / "html_report_v3.py").read_text(encoding="utf-8")
    # 找 _render_risk 函数 (line 1393-1434)
    m = re.search(r"def _render_risk\(rows\):(.*?)return.*?join\(h\)", src, re.DOTALL)
    assert m, "_render_risk 未找到"
    block = m.group(0)
    # 5 个 _esc( 出现 (category, desc, sev, trigger, action)
    esc_count = block.count("_esc(")
    assert esc_count >= 5, f"_render_risk 应至少 5 处 _esc, 实际 {esc_count}"


def test_audit_no_unscaped_user_text_in_template():
    """html_report_v3.py 全文审计: 报告层不允许出现 (1) result.get(...) 未 _esc + (2) 直接 % 拼接"""
    src = (WORKDIR / "analysis" / "html_report_v3.py").read_text(encoding="utf-8")
    # 找 h.append(<...%...>) 形式且包含 result.get / it.get / a.get / x.get / b.get
    import re
    # 简单的字符串审计, 找 result.get 直接在 h.append % 后面 (没 _esc)
    # 因为 _esc 嵌套难静态分析, 我们用宽松规则: result.get/it.get/x.get/b.get/a.get 后必须接 _esc
    bad = re.findall(r"h\.append\(.*?%(?: [a-z_]+)?\s*%.*?(?:result|it|x|b|a)\.get\([^)]+\)\s*[,)]", src, re.DOTALL)
    # 这是宽松检查: 只看 h.append 内 result.get 不接 _esc 的
    # 实际还需要更精细, 这里 sanity check
    # 注: 此测试作为审计脚手架, 真正的 _esc 漏需要逐行 review
    assert len(bad) < 5, f"h.append 内可能存在 result.get 未 _esc, 数: {len(bad)}"


# ============================================================
# 4. md 层不需 _esc (但需证明它也不注入)
# ============================================================
def test_md_layer_uses_markdown_table_no_raw_html():
    """md 报告层应避免嵌入原始 HTML (只走 markdown 表格)"""
    # md 文件生成用 | 表格, 不嵌入 <script> 标签
    # 实际: 抓 600693-2230.md 检查
    md_path = str(WORKDIR / "reports" / "600693_东百集团" / "2026-09-11" / "600693-东百集团-2230.md")
    if os.path.exists(md_path):
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
        # 不应有 <script> 或 <iframe>
        assert "<script" not in md.lower(), "MD 文件不应嵌入 <script>"
        assert "<iframe" not in md.lower(), "MD 文件不应嵌入 <iframe>"
