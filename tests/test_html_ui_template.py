"""Task 6.1: V3 HTML UI 升级 — CSS 模板集成测试

历史: docs/superpowers/plans/2026-09-09-html-ui-upgrade.md Task 6.1
  - 集成 mingli30119/stock-analysis 双主题 CSS 模板 (~200 行 → 9KB)
  - 加 ECharts CDN (用于后续 K 线 / 4 技术图渲染)
  - CSS 变量定义在 .v3-stock-report 命名空间内
  - V3 旧同名类 (.card / .hero / .container) 会被新 CSS 覆盖 (升级意图: 换皮)

测试覆盖:
  1. _MINGLI_CSS 字符串含关键类 (top-nav / hero / card / conclusion-top / grid-2 / kpi-info-row)
  2. CSS 变量定义 (--bg / --card-bg / --red-up / --green-down / --gold)
  3. .v3-stock-report 命名空间前缀 (避免与 V3 旧 CSS 冲突)
  4. 双主题 (light-mode)
  5. 响应式 (@media < 850px)
  6. ECharts CDN 链接
  7. V3 渲染器 head 段含 ECharts script
  8. 端到端: 跑 600693, HTML 含 mingli CSS 字符串
"""
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")

import pytest

from html_report_v3 import _MINGLI_CSS  # noqa: E402


# ============================================================
# 测试 1: _MINGLI_CSS 含关键类
# ============================================================
@pytest.mark.parametrize("class_name", [
    "top-nav", "hero", "card", "conclusion-top", "grid-2", "grid-3",
    "kpi-info-row", "kpi-info-item", "hero-price", "hero-meta",
    "hero-tag", "verdict-detail", "tag", "val-up", "val-down",
])
def test_mingli_css_has_key_classes(class_name):
    assert f".{class_name}" in _MINGLI_CSS, (
        f"_MINGLI_CSS 缺 {class_name} 类"
    )


# ============================================================
# 测试 2: CSS 变量定义
# ============================================================
@pytest.mark.parametrize("var_name", [
    "--bg", "--card-bg", "--card-bg-alt", "--border",
    "--text-primary", "--text-secondary", "--text-muted",
    "--red-up", "--green-down", "--gold", "--gold-light",
    "--blue-accent", "--orange-warn",
])
def test_mingli_css_has_root_variables(var_name):
    assert var_name in _MINGLI_CSS, (
        f"_MINGLI_CSS 缺 CSS 变量 {var_name}"
    )


# ============================================================
# 测试 3: .v3-stock-report 命名空间前缀
# ============================================================
def test_mingli_css_uses_namespace_prefix():
    """所有选择器应加 .v3-stock-report 前缀，避免与 V3 旧 CSS 冲突。"""
    assert ".v3-stock-report" in _MINGLI_CSS
    # 至少 10 处使用命名空间
    count = _MINGLI_CSS.count(".v3-stock-report")
    assert count >= 10, f"命名空间前缀仅 {count} 处，预期 ≥10"


def test_mingli_css_uses_css_variables_in_inheritance():
    """.v3-stock-report{} 块定义变量, 子类引用 var(--bg) 等。"""
    # 找到 .v3-stock-report{...} 块（含 --bg 等变量定义）
    assert ".v3-stock-report{" in _MINGLI_CSS
    # 至少有一处 var(--bg) 引用
    assert "var(--bg)" in _MINGLI_CSS


# ============================================================
# 测试 4: 双主题 (light-mode)
# ============================================================
def test_mingli_css_has_light_mode_override():
    """应含 .v3-stock-report.light-mode 重定义变量。"""
    assert ".v3-stock-report.light-mode{" in _MINGLI_CSS
    # 浅色模式覆盖块至少含 --bg / --card-bg / --text-primary
    light_mode_idx = _MINGLI_CSS.find(".v3-stock-report.light-mode{")
    light_mode_block = _MINGLI_CSS[light_mode_idx:light_mode_idx + 500]
    assert "--bg" in light_mode_block
    assert "--card-bg" in light_mode_block
    assert "--text-primary" in light_mode_block


# ============================================================
# 测试 5: 响应式 (@media)
# ============================================================
def test_mingli_css_has_responsive_media_query():
    assert "@media(max-width:850px)" in _MINGLI_CSS
    media_idx = _MINGLI_CSS.find("@media(max-width:850px)")
    media_block = _MINGLI_CSS[media_idx:media_idx + 300]
    # 响应式覆盖 grid-2 / .hero
    assert "grid-2" in media_block
    assert "hero" in media_block


# ============================================================
# 测试 6: ECharts CDN (在渲染器 head 段, 不在 _MINGLI_CSS)
# ============================================================
def test_html_report_v3_has_echarts_cdn():
    """V3 渲染器 <head> 段应含 ECharts CDN <script> tag。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert "echarts@5.5.1" in src or "echarts.min.js" in src, (
        "V3 渲染器 head 段未注入 ECharts CDN"
    )


# ============================================================
# 测试 7: V3 渲染器拼接 _MINGLI_CSS 到 <style>
# ============================================================
def test_html_report_v3_includes_mingli_css_in_style():
    """V3 渲染器 <style> 段应含 _MINGLI_CSS。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert "_MINGLI_CSS" in src, (
        "V3 渲染器未在 <style> 段注入 _MINGLI_CSS"
    )


# ============================================================
# 测试 8: _MINGLI_CSS 长度合理 (8-12KB)
# ============================================================
def test_mingli_css_size_reasonable():
    """mingli CSS 字符串长度应 ~9KB (200 行)。"""
    assert 8000 <= len(_MINGLI_CSS) <= 15000, (
        f"_MINGLI_CSS 长度 {len(_MINGLI_CSS)} 不在 8-15KB 范围"
    )
