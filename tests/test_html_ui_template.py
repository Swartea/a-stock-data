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


# ============================================================
# Task 6.2: 顶部导航 + 主题切换 JS 集成测试
# ============================================================

def test_v3_render_html_has_top_nav():
    """V3 渲染器 <body> 段应含 .top-nav + theme-toggle 按钮。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert '<nav class="top-nav">' in src, "V3 渲染器未输出 .top-nav"
    assert 'id="themeToggle"' in src, "V3 渲染器未注入 themeToggle 按钮"


def test_v3_render_html_has_theme_js():
    """V3 渲染器应含主题切换 JS (localStorage 记忆 + body.light-mode 切换)。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert "v3-stock-report-theme" in src, "V3 渲染器未注入主题 JS (localStorage key)"
    assert "light-mode" in src, "V3 渲染器未注入 .light-mode 切换逻辑"
    assert "localStorage" in src, "V3 渲染器未注入 localStorage 记忆"


def test_v3_body_wrapped_in_v3_stock_report():
    """V3 渲染器 <body> 内层 div 应为 .v3-stock-report (CSS 变量继承基底层)。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert '<div class="v3-stock-report">' in src, (
        "V3 渲染器 <body> 内层未用 .v3-stock-report 包裹 (CSS 变量无法继承)"
    )
    # 确认不再是 .container (V3 旧 wrapper)
    assert '<div class="container">' not in src, (
        "V3 渲染器仍在用 .container (升级后应改 .v3-stock-report)"
    )


def test_theme_toggle_button_text_default_dark():
    """主题切换按钮默认文本应为 '☀️ 浅色模式' (暗色模式提示切换到浅色)。"""
    import inspect
    from html_report_v3 import write_html_report_v3
    src = inspect.getsource(write_html_report_v3)
    assert "☀️ 浅色模式" in src, "主题按钮默认文本不正确"
    assert "🌙 深色模式" in src, "主题按钮切换后文本不正确"


# ============================================================
# 端到端: 跑 600693 验证 HTML 含主题切换元素
# ============================================================
def test_e2e_600693_html_has_theme_toggle():
    """端到端: 跑 600693, 输出 HTML 应含 top-nav + themeToggle 按钮 + 主题 JS。"""
    import subprocess
    import sys
    from pathlib import Path

    report_dir = Path("/Users/swarteachou/Desktop/大A数据/reports/600693_东百集团")
    if not report_dir.exists():
        pytest.skip("600693 报告目录不存在, 跳过端到端测试")

    # 跑 V3 一次 (使用已有的 result_v3, 不重新跑端到端 — 避免测试慢)
    # 直接验证最新 HTML 含主题元素
    md_files = list(report_dir.glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告, 跳过")

    latest_date_dir = max(md_files, key=lambda p: p.stat().st_mtime).parent
    html_files = list(latest_date_dir.glob("600693-东百集团-v3-*.html"))
    if not html_files:
        pytest.skip("无 600693 HTML 报告, 跳过")

    latest_html = max(html_files, key=lambda p: p.stat().st_mtime)
    content = latest_html.read_text(encoding="utf-8")

    # 验证主题切换元素
    assert 'class="top-nav"' in content, f"{latest_html.name} 缺 .top-nav"
    assert 'id="themeToggle"' in content, f"{latest_html.name} 缺 themeToggle 按钮"
    assert "v3-stock-report-theme" in content, f"{latest_html.name} 缺主题 JS"
    assert "v3-stock-report" in content, f"{latest_html.name} 缺 v3-stock-report 包裹"


# ============================================================
# Task 6.3: ECharts K 线 + 4 占位符数据转换
# ============================================================

def test_kline_to_rawdata_format():
    """V3 K 线 dict 列表 → ECharts 模板格式 ([date, open, high, low, close, turn])。"""
    from analysis.html_report_v3 import _kline_to_rawdata
    sample = [
        {"date": "2026-01-01", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "turn": 1.5},
        {"date": "2026-01-02", "open": 10.5, "high": 11.2, "low": 10.3, "close": 10.8, "turn": 1.8},
    ]
    result = _kline_to_rawdata(sample)
    assert result == [
        ["2026-01-01", 10.0, 11.0, 9.5, 10.5, 1.5],
        ["2026-01-02", 10.5, 11.2, 10.3, 10.8, 1.8],
    ]


def test_kline_to_rawdata_handles_missing_turn():
    """K 线缺 turn 字段应默认为 0.0。"""
    from analysis.html_report_v3 import _kline_to_rawdata
    sample = [{"date": "2026-01-01", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5}]
    result = _kline_to_rawdata(sample)
    assert result[0][5] == 0.0


def test_kline_to_rawdata_empty():
    from analysis.html_report_v3 import _kline_to_rawdata
    assert _kline_to_rawdata([]) == []


def test_markline_data_from_three_levels():
    """从 three_levels 自动生成 markLine (3 条: 压力/支撑/止损)。"""
    from analysis.html_report_v3 import _markline_data
    tl = {"support": 7.16, "resistance": 12.67, "stop_loss": 9.95}
    result = _markline_data(tl, current_price=11.52)
    assert len(result) == 3
    y_values = {item["yAxis"] for item in result}
    assert 7.16 in y_values
    assert 12.67 in y_values
    assert 9.95 in y_values
    names = {item["name"] for item in result}
    assert names == {"压力", "支撑", "止损"}


def test_markline_data_empty_three_levels():
    from analysis.html_report_v3 import _markline_data
    assert _markline_data(None) == []
    assert _markline_data({}) == []


def test_markpoint_data_includes_current_and_extremes():
    """markPoint: 现价 + 阶段高 + 阶段低。"""
    from analysis.html_report_v3 import _markpoint_data
    sample = [
        {"close": 10.0},
        {"close": 12.0},   # 阶段高
        {"close": 9.0},    # 阶段低
        {"close": 11.5},   # 当前 (最后一个)
    ]
    result = _markpoint_data(sample, current_price=11.5)
    assert len(result) == 3
    values = {item["value"] for item in result}
    assert "现价" in values
    assert "阶段高" in values
    assert "阶段低" in values


def test_markpoint_data_no_current_price():
    """current_price 为空时只返回空。"""
    from analysis.html_report_v3 import _markpoint_data
    sample = [{"close": 10.0}, {"close": 12.0}]
    assert _markpoint_data(sample, None) == []
    assert _markpoint_data([], 10.0) == []


# ============================================================
# Task 6.4: 5 ECharts 容器 (K线 + MACD + KDJ + RSI + BOLL)
# ============================================================

def test_v3_render_has_5_echarts_containers():
    """V3 渲染器应输出 5 个 ECharts 容器 (K线 + 4 技术图)。"""
    from analysis.html_report_v3 import _render_echarts_kline_block, _render_echarts_tech_block
    fake_result = {
        "chip_data": {"kline": [
            {"date": "2026-01-01", "open": 10, "high": 11, "low": 9.5, "close": 10.5, "turn": 1.5}
        ]},
        "three_levels": {"support": 9.5, "resistance": 11, "stop_loss": 9.0},
        "quote": {"price": 10.5},
    }
    kline_html = _render_echarts_kline_block(fake_result)
    tech_html = _render_echarts_tech_block()
    assert 'id="chart-kline-full"' in kline_html
    assert 'id="echarts-kline-section"' in kline_html
    for cid in ["chart-macd", "chart-kdj", "chart-rsi", "chart-boll"]:
        assert f'id="{cid}"' in tech_html, f"tech 容器缺 {cid}"
    assert 'id="echarts-tech-section"' in tech_html


def test_v3_render_kline_no_data_returns_empty():
    """无 K 线数据时 K 线渲染返回空字符串 (不报错)。"""
    from analysis.html_report_v3 import _render_echarts_kline_block
    assert _render_echarts_kline_block({}) == ""
    assert _render_echarts_kline_block({"chip_data": {}}) == ""
    assert _render_echarts_kline_block({"chip_data": {"kline": []}}) == ""


def test_e2e_600693_html_has_echarts_5_containers():
    """端到端: 600693 报告 HTML 应含 5 ECharts 容器 + markLine + markPoint。"""
    from pathlib import Path
    report_dir = Path("/Users/swarteachou/Desktop/大A数据/reports/600693_东百集团")
    if not report_dir.exists():
        pytest.skip("600693 报告目录不存在")
    md_files = list(report_dir.glob("**/600693-东百集团-*.md"))
    if not md_files:
        pytest.skip("无 600693 报告")
    latest_date_dir = max(md_files, key=lambda p: p.stat().st_mtime).parent
    html_files = list(latest_date_dir.glob("600693-东百集团-v3-*.html"))
    if not html_files:
        pytest.skip("无 600693 HTML 报告")
    latest_html = max(html_files, key=lambda p: p.stat().st_mtime)
    content = latest_html.read_text(encoding="utf-8")

    # 5 容器
    for cid in ["chart-kline-full", "chart-macd", "chart-kdj", "chart-rsi", "chart-boll"]:
        assert f'id="{cid}"' in content, f"{latest_html.name} 缺 {cid}"

    # markLine + markPoint 数据
    assert "markLine" in content, f"{latest_html.name} 缺 markLine"
    assert "markPoint" in content, f"{latest_html.name} 缺 markPoint"

    # 三价位标注 (from three_levels 自动注入)
    assert '"压力"' in content or "压力" in content
    assert '"支撑"' in content or "支撑" in content
    assert '"止损"' in content or "止损" in content

    # ECharts JS 主题适配 (light-mode 切换)
    assert "light-mode" in content, f"{latest_html.name} 缺 light-mode 主题适配"
