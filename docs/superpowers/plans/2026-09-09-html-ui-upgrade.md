# V3 报告 UI 升级 Plan（深色专业版）

| 项 | 值 |
|---|---|
| 日期 | 2026-09-09 |
| 承接 | 报告质量线收官（tag v0.10-report-quality-complete）+ 4-phase 实施 |
| 方向 | 报告质量 > 数据广度（老板 9-8 拍板）|
| 参考 | mingli30119/stock-analysis (深色专业版) |
| 模式 | subagent-driven-development |
| 起点 | V3 HTML 报告 50KB（无 ECharts、无 Hero、无双主题）|
| 终点 | mingli30119 风格：双主题 + ECharts K线 + 4 技术图 + Hero + 5 交易参数 |

---

## 0. 目标

**一句话**：把 mingli30119/stock-analysis 的深色专业版 UI 模板集成到 V3 HTML 渲染器，**不破坏** 报告质量线 6 task 已实现的 4 段逻辑（多空状态机 / 三价位 / 北向口径 / 5 sections / PEG 4 档）。

**验收硬指标**：
- 5 task 全部 commit 落档
- V3 HTML 报告从 50KB 涨到 ~100KB（CSS+JS+Hero+charts）
- 600693 端到端 < 120s（性能预算不变）
- 83 + N tests pass（N 为新增 UI 测试数）
- 暗/浅双主题切换正常
- 4 ECharts 图全部渲染（K线 + MACD + KDJ + RSI + BOLL）
- markLine 自动从 `three_levels` 注入支撑/压力/止损
- 5 sections 卡片化（沿用 `.card` class）

---

## 1. 现状摘要

**V3 HTML 渲染器**：`analysis/html_report_v3.py`（1543 行）
- 当前 6 块 + 5 sections 走 Section Registry 循环
- 数据从 result dict 顶层 keys 读（quote / valuation / blocks / chip_data / ...）
- 输出 50KB HTML，**无 CSS 主题**（继承浏览器默认）、**无 ECharts**、**无 Hero**、**无双主题**

**V3 MD/DOCX 渲染器**：
- `analysis/md_to_docx.py`（483 行）— MD + DOCX 同步
- 输出纯文本，**不涉及本 plan**（保持不变）

**数据格式**（Task 6.3 关键）：
- K 线：`chip_data["kline"]` = list of dict `{date, open, high, low, close, turn}`（**179 条，6 字段，无 volume 是 turn 换手率%**）
- 三价位：`result["three_levels"]` = `{support, resistance, stop_loss, support_candidates, resistance_candidates, method}`
- trading_plan：`result["trading_plan"]` = `{state, template_used, entry_*, stop_loss, tp*, ...}`

**模板来源**（已 fetch）：
- CSS：`https://raw.githubusercontent.com/mingli30119/stock-analysis/main/shared/template_base.css`（~200 行）
- JS：`https://raw.githubusercontent.com/mingli30119/stock-analysis/main/shared/template_base.js`（~190 行）
- HTML 范例：`examples/个股研究-中国长城.html`（参考结构 + 14 锚点）

---

## 2. 5 Task 概览

| Task | 标题 | 涉及 | 工期 |
|---|---|---|---|
| 6.1 | CSS 模板集成 | V3 渲染器 + ECharts CDN | 20-30 min |
| 6.2 | HTML 结构改造 | 顶部导航 + Hero + 结论置顶 + 5 sections 卡片化 | 60-90 min |
| 6.3 | ECharts K 线图 | K 线 + 成交量 + MA5/20/60 + markLine/markPoint | 45-60 min |
| 6.4 | 4 技术指标图 | MACD + KDJ + RSI + BOLL | 30-45 min |
| 6.5 | 主题切换 + 响应式 + 端到端 | 切换按钮 + @media + 600693 冒烟 | 20-30 min |

**总预估**：3-4 小时

**派单策略**（避免 Token Plan 上限）：
- Task 6.1 我自己改（CSS 模板搬入，纯模板工作）
- Task 6.2-6.4 派 worker（每个 1 个 worker，串行避免 V3 渲染器重叠写）
- Task 6.5 我自己改（响应式 + 端到端冒烟）

---

## Task 6.1: CSS 模板集成

**Files**:
- Modify: `analysis/html_report_v3.py`（V3 HTML 渲染器 `<head>` 段）
- (无需新建文件)

**目标**：把 mingli30119 的 `template_base.css` (~200 行) 完整嵌入 V3 渲染器的 `<style>` 段，并加 ECharts CDN。

**Step 1: 定位 V3 渲染器 HTML 输出位置**

```bash
grep -n "<style>\|<head>\|<body>\|<!DOCTYPE\|render_html" /Users/swarteachou/Desktop/大A数据/analysis/html_report_v3.py | head -10
```

找到 V3 报告 HTML 输出入口（`render_html(res, output_path)` 函数）。

**Step 2: 在 `<head>` 段追加 ECharts CDN**

```python
HEAD_BLOCK = """
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
  <style>
{mingli_css}
  </style>
</head>
"""
```

把 mingli30119 的 `template_base.css` 完整内容（约 200 行）作为字符串注入 `<style>` 段。

**Step 3: 写 1 个最小测试**

创建 `tests/test_html_css_template.py`：
```python
def test_v3_html_has_dark_theme_css():
    """V3 HTML 报告应含 mingli30119 双主题 CSS 变量。"""
    from analysis.html_report_v3 import _HTML_CSS_BLOCK
    assert ":root{" in _HTML_CSS_BLOCK
    assert "--bg:" in _HTML_CSS_BLOCK
    assert "body.light-mode" in _HTML_CSS_BLOCK
    assert ".top-nav" in _HTML_CSS_BLOCK
    assert ".hero" in _HTML_CSS_BLOCK
    assert ".card" in _HTML_CSS_BLOCK
    assert ".conclusion-top" in _HTML_CSS_BLOCK

def test_v3_html_includes_echarts_cdn():
    assert "echarts@5.5.1" in _HTML_CSS_BLOCK or "echarts" in str(_HTML_CSS_BLOCK.lower())
```

**Step 4: 跑 600693 端到端冒烟**

```bash
venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团
```

打开生成的 HTML，用浏览器开发者工具确认：
- 背景是暗色 #0c0f15
- 红涨绿跌 A 股色系生效

**Step 5: commit**

- commit: `feat(ui): V3 HTML 集成 mingli30119 双主题 CSS 模板（暗/浅切换基底层）`

**验收**：
- ✅ V3 HTML 报告嵌入完整 CSS（200 行）
- ✅ 暗色主题默认 #0c0f15 背景生效
- ✅ ECharts CDN 加载
- ✅ 14 + N tests pass

---

## Task 6.2: HTML 结构改造（顶部 + Hero + 结论 + 5 sections 卡片化）

**Files**:
- Modify: `analysis/html_report_v3.py`（V3 渲染器 `<body>` 结构）
- Create: `tests/test_html_structure.py`（结构断言测试）

**目标**：把 V3 6 块平铺改造为：
1. **顶部 sticky 导航**：14 锚点（行情/结论/画像/K线/任务/技术/...）— 适配 V3 的 6 块 + 5 sections
2. **Hero 行情卡片**：5 meta 横向（价格/PE/PB/市值/PEG）
3. **核心结论置顶**：state + 5 交易参数
4. **5 sections 卡片化**：用 `.card` class 包裹

**Step 1: 顶部导航**

```python
TOP_NAV = """
<nav class="top-nav">
  <div class="logo">
    <div class="logo-icon">{name_first}</div>
    <span class="stock-name">{name}</span>
    <span class="stock-code">{code}.{exchange}</span>
  </div>
  <div class="nav-links">
    <a href="#hero" class="active">行情</a>
    <a href="#conclusion-top">结论</a>
    <a href="#section-1">画像</a>
    <a href="#kline-section">K线</a>
    <a href="#section-3">估值</a>
    <a href="#section-4">资金</a>
    <a href="#section-5">技术</a>
    <a href="#section-6">风险</a>
    <a href="#section-7">宏观</a>
    <a href="#section-8">板块</a>
    <a href="#section-9">跟踪</a>
    <a href="#section-10">互动易</a>
    <a href="#section-11">股东</a>
    <a href="#section-12">分红</a>
  </div>
  <button class="theme-toggle" id="themeToggle">☀️ 浅色模式</button>
</nav>
"""
```

**Step 2: Hero 行情卡片**

```python
HERO_BLOCK = """
<div class="hero" id="hero">
  <div class="hero-price-block">
    <span class="hero-price">{price}</span>
    <span class="hero-change" style="color: {change_color};">{change_pct}</span>
  </div>
  <div class="hero-meta">
    <div class="hero-meta-item">
      <div class="val">{pe_ttm}</div>
      <div class="label">PE(TTM)</div>
    </div>
    <div class="hero-meta-item">
      <div class="val">{pb}</div>
      <div class="label">PB</div>
    </div>
    <div class="hero-meta-item">
      <div class="val">{mcap}亿</div>
      <div class="label">市值</div>
    </div>
    <div class="hero-meta-item">
      <div class="val">{peg}</div>
      <div class="label">PEG</div>
    </div>
    <div class="hero-meta-item">
      <div class="val">{score}</div>
      <div class="label">综合评分</div>
    </div>
  </div>
  <div class="hero-tags">
    <span class="hero-tag">{state_emoji} {state_label}</span>
    <span class="hero-tag">PEG {peg_label}</span>
    <span class="hero-tag">{industry}</span>
  </div>
</div>
"""
```

**Step 3: 核心结论置顶**

```python
CONCLUSION_TOP = """
<div class="conclusion-top" id="conclusion-top">
  <div class="big-verdict">{state_emoji} 综合评分 {score} · {advice}</div>
  <div class="verdict-detail">{template_used}</div>
  <div class="verdict-tags">
    <span class="tag">买入 {entry_low}-{entry_high}</span>
    <span class="tag">止损 {stop_loss}</span>
    <span class="tag">目标 {tp1}</span>
  </div>
  <div style="display:flex;gap:20px;margin-top:14px;padding-top:12px;border-top:1px dashed var(--border);">
    <div style="text-align:center;"><div style="font-size:11px;color:var(--text-muted);">支撑</div><div style="font-weight:700;color:var(--green-down);">{three_levels.support}</div></div>
    <div style="text-align:center;"><div style="font-size:11px;color:var(--text-muted);">压力</div><div style="font-weight:700;color:var(--red-up);">{three_levels.resistance}</div></div>
    <div style="text-align:center;"><div style="font-size:11px;color:var(--text-muted);">止损</div><div style="font-weight:700;color:var(--green-down);">{three_levels.stop_loss}</div></div>
  </div>
</div>
"""
```

**Step 4: 5 sections 卡片化**

现有 Section Registry 渲染循环（`html_report_v3.py:1370-1383`）已经输出 `sec.render_html(sec_data)`，**只是没有用 `.card` class 包裹**。改造：
- 给每个 section 套 `<div class="card" id="section-{N}">`
- 头部加 `<div class="card-header"><span class="icon">{emoji}</span><h2>{title}</h2></div>`

```python
def render_section_card(sec_id, sec_title, sec_emoji, sec_html):
    return f'<div class="card" id="section-{sec_id}"><div class="card-header"><span class="icon">{sec_emoji}</span><h2>{sec_title}</h2></div>{sec_html}</div>'
```

5 sections 各自 emoji 映射：
- irm → 📞 互动易
- holders → 📊 股东户数
- dividend → 💰 分红
- board → 🎰 打板情绪
- dragon_market → 🐉 龙虎榜

**Step 5: 测试**

```python
# tests/test_html_structure.py
def test_v3_html_has_top_nav():
    """V3 HTML 应含顶部 sticky 导航 + 14 锚点。"""
    from analysis.html_report_v3 import _TOP_NAV
    assert 'class="top-nav"' in _TOP_NAV
    assert '#hero' in _TOP_NAV
    assert '#conclusion-top' in _TOP_NAV
    assert _TOP_NAV.count('<a href=') >= 10

def test_v3_html_has_hero_block():
    from analysis.html_report_v3 import _HERO_BLOCK
    assert 'class="hero"' in _HERO_BLOCK
    assert 'hero-price' in _HERO_BLOCK
    assert 'hero-meta-item' in _HERO_BLOCK
    assert '{pe_ttm}' in _HERO_BLOCK or 'pe_ttm' in _HERO_BLOCK.lower()

def test_v3_html_has_conclusion_top():
    from analysis.html_report_v3 import _CONCLUSION_TOP
    assert 'class="conclusion-top"' in _CONCLUSION_TOP
    assert 'big-verdict' in _CONCLUSION_TOP
    assert '{state_emoji}' in _CONCLUSION_TOP

def test_v3_html_has_section_card_wrapper():
    """5 sections 应用 .card class 包裹。"""
    from analysis.html_report_v3 import render_section_card
    html = render_section_card('irm', '投资者互动', '📞', '<p>content</p>')
    assert 'class="card"' in html
    assert 'id="section-irm"' in html
    assert '投资者互动' in html
```

**Step 6: 跑 600693 端到端冒烟**

```bash
venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团
```

打开 HTML 验证：
- 顶部导航可见（深色 sticky）
- Hero 卡片显示价格/PE/PB/市值/PEG/综合评分
- 核心结论置顶在 Hero 下方
- 5 sections 用 `.card` 包裹（含 icon + h2）

**Step 7: commit**

- commit: `feat(ui): V3 HTML 结构改造（顶部导航 + Hero + 结论置顶 + 5 sections 卡片化）`

**验收**：
- ✅ 14 锚点导航可见
- ✅ Hero 5 meta 全部正确显示（PE 204.8 / PB 2.78 / 市值 100亿 / PEG 9.56 / 综合 44）
- ✅ 结论置顶含 state + 5 交易参数
- ✅ 5 sections 卡片化
- ✅ 14 + N tests pass

---

## Task 6.3: ECharts K 线图

**Files**:
- Modify: `analysis/html_report_v3.py`（V3 渲染器，K 线 + JS 注入）
- Create: `tests/test_kline_chart.py`（K 线 + 标注测试）

**目标**：在 HTML 报告加 ECharts K 线图，含 MA5/20/60 + 成交量 + markLine/markPoint 标注（自动从 `three_levels` 注入）。

**Step 1: K 线字段映射（V3 → JS 模板格式）**

V3 `chip_data["kline"]` 是 dict 列表，mingli30119 JS 模板要 `[date, open, high, low, close, vol]` 列表。

V3 端做映射：
```python
def _kline_to_rawdata(kline_dicts: list) -> list:
    """V3 chip_data['kline'] dict 列表 → [date, open, high, low, close, turn] 列表
    
    V3 字段: {date, open, high, low, close, turn}  (turn=换手率%)
    JS 模板字段: [date, open, high, low, close, vol]  (vol=成交量, 我们用 turn 替)
    """
    return [
        [d["date"], d["open"], d["high"], d["low"], d["close"], d.get("turn", 0)]
        for d in kline_dicts
    ]
```

**Step 2: markLine 数据自动从 three_levels 生成**

```python
def _markline_data(three_levels: dict, current_price: float) -> list:
    """从 three_levels 自动生成 markLine 标注。"""
    return [
        {"yAxis": three_levels["resistance"], "name": "压力"},
        {"yAxis": three_levels["support"], "name": "支撑"},
        {"yAxis": three_levels["stop_loss"], "name": "止损"},
    ]
```

**Step 3: markPoint 数据**

```python
def _markpoint_data(kline_dicts: list, current_price: float) -> list:
    """markPoint：当前价 + 关键历史价。"""
    if not kline_dicts:
        return []
    closes = [d["close"] for d in kline_dicts]
    max_idx = closes.index(max(closes))
    min_idx = closes.index(min(closes))
    return [
        {"coord": [len(kline_dicts) - 1, current_price], "value": "现价", "itemStyle": {"color": "#d4a853"}},
        {"coord": [max_idx, max(closes)], "value": "阶段高", "itemStyle": {"color": "#f55656"}},
        {"coord": [min_idx, min(closes)], "value": "阶段低", "itemStyle": {"color": "#28c75b"}},
    ]
```

**Step 4: JS 模板注入到 V3**

把 mingli30119 的 `template_base.js` 完整内容（~190 行）作为字符串注入到 V3 HTML 底部 `<script>` 段，4 个占位符替换：

```python
def _js_block(raw_data_json, markline_json, markpoint_json) -> str:
    js_template = """..."""
    js_template = js_template.replace("__RAW_DATA_ARRAY__", raw_data_json)
    js_template = js_template.replace("__PIE_DATA_ARRAY__", "[]")  # 暂不渲染饼图
    js_template = js_template.replace("__MARKLINE_DATA__", markline_json)
    js_template = js_template.replace("__MARKPOINT_DATA__", markpoint_json)
    return js_template
```

**Step 5: HTML 中加 K 线容器**

在 5 sections 卡片化之间（或结论置顶之后、5 sections 之前）插入 K 线 card：

```python
KLINE_CARD = """
<div class="card" id="kline-section">
  <div class="card-header">
    <span class="icon">📈</span>
    <h2>K线图 · 近 {kline_count} 个交易日</h2>
    <span class="sub">前复权日K · MA5/MA20/MA60</span>
  </div>
  <div id="chart-kline-full" style="width:100%;height:480px;"></div>
  <div class="kpi-info-row">
    <div class="kpi-info-item"><div class="label">支撑</div><div class="value" style="color:var(--green-down);">{three_levels.support}</div></div>
    <div class="kpi-info-item"><div class="label">压力</div><div class="value" style="color:var(--red-up);">{three_levels.resistance}</div></div>
    <div class="kpi-info-item"><div class="label">止损</div><div class="value" style="color:var(--green-down);">{three_levels.stop_loss}</div></div>
  </div>
</div>
"""
```

**Step 6: 测试**

```python
# tests/test_kline_chart.py
def test_kline_to_rawdata_format():
    """V3 K 线 dict 列表 → JS 模板格式（[date, open, high, low, close, turn]）。"""
    from analysis.quant_analyzer_v3 import _kline_to_rawdata
    sample = [
        {"date": "2026-01-01", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "turn": 1.5},
        {"date": "2026-01-02", "open": 10.5, "high": 11.2, "low": 10.3, "close": 10.8, "turn": 1.8},
    ]
    result = _kline_to_rawdata(sample)
    assert result == [
        ["2026-01-01", 10.0, 11.0, 9.5, 10.5, 1.5],
        ["2026-01-02", 10.5, 11.2, 10.3, 10.8, 1.8],
    ]

def test_markline_data_from_three_levels():
    from analysis.quant_analyzer_v3 import _markline_data
    tl = {"support": 7.16, "resistance": 12.67, "stop_loss": 9.95}
    result = _markline_data(tl, current_price=11.52)
    assert len(result) == 3
    assert any(item["yAxis"] == 7.16 for item in result)  # 支撑
    assert any(item["yAxis"] == 12.67 for item in result)  # 压力
    assert any(item["yAxis"] == 9.95 for item in result)  # 止损
    assert any(item["name"] == "支撑" for item in result)
    assert any(item["name"] == "压力" for item in result)
    assert any(item["name"] == "止损" for item in result)

def test_markpoint_data_includes_current_and_extremes():
    from analysis.quant_analyzer_v3 import _markpoint_data
    sample = [
        {"date": "2026-01-01", "close": 10.0},
        {"date": "2026-01-02", "close": 12.0},  # 阶段高
        {"date": "2026-01-03", "close": 9.0},   # 阶段低
        {"date": "2026-01-04", "close": 11.5},  # 当前
    ]
    result = _markpoint_data(sample, current_price=11.5)
    assert len(result) == 3  # 现价 + 阶段高 + 阶段低
    assert any(item["value"] == "现价" for item in result)
    assert any(item["value"] == "阶段高" for item in result)
    assert any(item["value"] == "阶段低" for item in result)
```

**Step 7: 跑 600693 端到端冒烟**

```bash
venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团
```

打开 HTML 验证：
- K 线图渲染（蜡烛图 + 3 条均线 + 成交量柱）
- markLine 看到"支撑/压力/止损"3 条虚线
- markPoint 看到"现价/阶段高/阶段低"3 个 pin
- 红涨绿跌 A 股色

**Step 8: commit**

- commit: `feat(ui): ECharts K 线图 + markLine/markPoint（自动从 three_levels 注入）`

**验收**：
- ✅ K 线图渲染（蜡烛 + MA5/20/60 + 成交量）
- ✅ markLine 3 条标注（支撑/压力/止损）— 自动从 three_levels
- ✅ markPoint 3 个 pin（现价/阶段高/阶段低）
- ✅ V3 K 线 dict 列表 → JS 模板列表映射正确
- ✅ 14 + N tests pass

---

## Task 6.4: 4 技术指标图（MACD/KDJ/RSI/BOLL）

**Files**:
- Modify: `analysis/html_report_v3.py`（V3 渲染器，技术图 4 card）
- Create: `tests/test_tech_indicators_chart.py`（4 图测试）

**目标**：在 K 线图下方加 4 个 ECharts 技术指标图（MACD/KDJ/RSI/BOLL），数据源同 K 线（`chip_data["kline"]`）。

**Step 1: HTML 加 4 card 容器**

```python
TECH_CARD = """
<div class="card" id="section-5">
  <div class="card-header">
    <span class="icon">📊</span>
    <h2>技术指标</h2>
    <span class="sub">MACD / KDJ / RSI / BOLL</span>
  </div>
  <div class="grid-2">
    <div id="chart-macd" style="height:280px;"></div>
    <div id="chart-kdj" style="height:280px;"></div>
  </div>
  <div class="grid-2" style="margin-top:16px;">
    <div id="chart-rsi" style="height:260px;"></div>
    <div id="chart-boll" style="height:260px;"></div>
  </div>
</div>
"""
```

**Step 2: JS 模板已含 4 渲染函数**

mingli30119 的 `template_base.js` 已经包含 `renderMACD` / `renderKDJ` / `renderRSI` / `renderBOLL` 4 个函数（~80 行）。

**注意**：JS 模板计算函数 `calcKDJData` / `calcRSI` / `calcBOLL` 等需要 high/low/close 三列。V3 K 线 dict 列表含 open/high/low/close/turn，**high/low 都齐全**。直接用。

**Step 3: 测试**

```python
# tests/test_tech_indicators_chart.py
def test_v3_html_has_4_tech_chart_containers():
    """V3 HTML 应含 4 个 ECharts 容器（macd/kdj/rsi/boll）。"""
    from analysis.html_report_v3 import _TECH_CARD
    assert 'id="chart-macd"' in _TECH_CARD
    assert 'id="chart-kdj"' in _TECH_CARD
    assert 'id="chart-rsi"' in _TECH_CARD
    assert 'id="chart-boll"' in _TECH_CARD

def test_v3_html_has_grid2_layout_for_tech():
    """技术图应 grid-2 双列布局。"""
    from analysis.html_report_v3 import _TECH_CARD
    assert 'class="grid-2"' in _TECH_CARD
```

**Step 4: 跑 600693 端到端冒烟**

打开 HTML 验证：
- 4 图全部渲染
- MACD：DIF/DEA 双线 + 红绿柱
- KDJ：K/D/J 三线（0-100）
- RSI：RSI6/12/24 三线（0-100）
- BOLL：上/中/下三轨 + 收盘价

**Step 5: commit**

- commit: `feat(ui): 4 技术指标图（MACD/KDJ/RSI/BOLL）ECharts 集成`

**验收**：
- ✅ 4 图全部渲染
- ✅ K 线 + 4 技术图 共 5 个 ECharts 实例
- ✅ 14 + N tests pass

---

## Task 6.5: 主题切换 + 响应式 + 端到端

**Files**:
- Modify: `analysis/html_report_v3.py`（V3 渲染器，主题切换 + 响应式）
- 无新建文件

**目标**：
1. 主题切换按钮（已含在 Task 6.2 顶部导航）
2. 主题切换 JS（已含在 mingli30119 JS 模板）
3. @media 响应式（已含在 mingli30119 CSS 模板）
4. 端到端冒烟：600693 完整跑一次，5 件套对比升级前后

**Step 1: 验证主题切换**

打开 HTML，点击"☀️ 浅色模式"按钮，验证：
- 背景变浅色 #fdf8f0
- 文字变深色 #2a1f12
- Hero 背景变浅色渐变
- 卡片变浅色背景
- K 线 + 4 技术图 自动重渲染（颜色随主题变）

**Step 2: 验证响应式**

浏览器开发者工具切换到手机视图（< 850px 宽），验证：
- .grid-2 变 .grid-1（2 列变 1 列）
- Hero 变 flex-direction: column
- 导航链接换行

**Step 3: 端到端 600693 完整冒烟**

```bash
venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团
```

读 `result_v3-{HHMM}.json` 验证：
- 5 sections 顶层 keys 仍齐（irm/holders/dividend/board/dragon_market）
- trading_plan 字段仍齐（state / template_used / entry_*, stop_loss, tp*）
- three_levels 字段仍齐
- north_label 字段仍齐
- PEG talk-text 4 档仍齐

**Step 4: 跑全部测试**

```bash
venv/bin/python -W ignore -m pytest tests/ -v
```

期望：83 + N tests pass（N = Task 6.1-6.4 新增测试）

**Step 5: 跑 002353 杰瑞股份对比**

```bash
venv/bin/python -W ignore analysis/quant_analyzer_v3.py 002353 杰瑞股份
```

验证升级对另一只票同样有效（002353 PEG 0.51 便宜区，升级后 Hero + 三价位 + 5 sections 都正常）。

**Step 6: docs/04 状态更新**

- 报告质量线 + UI 升级线 都实施完
- docs/04 新增"E. UI 升级线"区块，记录 5 task 状态

**Step 7: commit + tag**

- commit: `docs(debt): V3 UI 升级 5 task 全部完成 + tag v0.11-ui-upgrade-complete`
- tag: `v0.11-ui-upgrade-complete`

**验收**：
- ✅ 主题切换按钮工作（深/浅）
- ✅ 响应式（< 850px 移动布局）
- ✅ 600693 + 002353 端到端全通过
- ✅ 83 + N tests pass
- ✅ 5 sections / 6 债项逻辑无回归
- ✅ tag v0.11-ui-upgrade-complete 落档

---

## 3. Self-Review

### 3.1 5 task 覆盖

| Task | 标题 | 状态 |
|---|---|---|
| 6.1 | CSS 模板集成 | ✅ |
| 6.2 | HTML 结构改造 | ✅ |
| 6.3 | ECharts K 线图 | ✅ |
| 6.4 | 4 技术指标图 | ✅ |
| 6.5 | 主题切换 + 响应式 + 端到端 | ✅ |

### 3.2 风险

- **CSS 字符太长**（200 行）— V3 HTML 报告从 50KB 涨到 ~100KB（+50KB），单文件渲染可能略慢（< 1s）
- **K 线字段差异**（V3 用 turn，mingli30119 用 vol）— V3 端做映射，JS 模板不动
- **5 sections 在新结构下顺序** — 5 sections 走 Section Registry 循环输出，**id 需要唯一**（section-10/11/12 给 3 sections 用，或用 sec.label）
- **DOCX 同步** — DOCX 是静态不能 ECharts，**保持原文字版本**（不升级）
- **MD 同步** — MD 也不能 ECharts，**保持原文字版本**

### 3.3 范围外（parked）

- 饼图（业务构成）— mingli30119 有 `chart-business-pie`，但 V3 没拉业务构成（不在 54 端点内），**暂不实现**
- MathJax — V3 报告不用数学公式，**不加**
- 7 day K 线 vs 30 day K 线切换 — **不实现**（V3 只跑 179 天 K 线）
- 板块轮动 TOP5 表格 — mingli30119 有，V3 板块数据在 macro.industry，**可在 6.5 阶段补充**

### 3.4 subagent 派单策略

- Task 6.1 我自己改（CSS 搬入，纯模板，10 分钟）
- Task 6.2 派 worker（HTML 结构改造，最复杂）
- Task 6.3 派 worker（K 线 + markLine 注入）
- Task 6.4 派 worker（4 技术图，独立模块）
- Task 6.5 我自己改（响应式 + 端到端 + tag）

**串行派单**（避免 V3 渲染器重叠写），worker 报告 + spot check + commit 验证。

Token Plan 上限风险：worker 实施长任务可能被截断（Task 5.4 教训），**2-3 个 worker 派单 + 2 个自己改**是稳的。
