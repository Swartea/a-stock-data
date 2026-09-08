# 报告质量 + 样本票链路试运行 Plan

| 项 | 值 |
|---|---|
| 日期 | 2026-09-08 |
| 承接 | 4-phase 实施收官（tag v0.9-optimization-complete）|
| 方向 | 报告质量 > 数据广度（老板 9-8 拍板）|
| 样本票 | 杰瑞股份 (002353) |
| 模式 | subagent-driven-development |

---

## 0. 目标

**一句话**：把 `docs/04-模板质量债.md` 4-phase 范围外的债 1/2/3 + D-2/D-3 全部修完，再用杰瑞股份 002353 跑一次端到端验证。

**验收硬指标**：
- 6 task 全部 commit 落档
- 杰瑞股份 002353 五件套落档
- 单票端到端 < 120s
- 5 sections 在 HTML/MD/DOCX 全部正文出现
- 14/14 tests pass（再加新增 task 引入的测试）
- PEG 报告输出与 `report-design-principles.md:73-77` 4 档阈值一致
- 北向资金口径明确标注（全市场 vs 个股）

---

## 1. 现状摘要

**4-phase 已修**（不在本 plan）：
- PEG 公式 `pe_ttm / cagr_pct`（commit b85cee5）→ 600693 PEG 3.85 → 9.56
- V3 命名 bug `result_v3-{HHMM}.json`（commit fb86ac3 + 7422b1f）
- 资金流 push2his（commit 2ccfff6 + 942f952）
- 新闻退避 21s → 6s（commit cc5cba6 + e3e5991）
- Section Registry + 5 sections（Phase 1-2，8 commits）
- SKILL.md 导航（Phase 3，4 commits）
- docs/04 状态更新（commit 8cacc00）

**4-phase 未修**（本 plan 范围）：
- 债 1 结论-操作矛盾（模板层）
- 债 2 支撑/压力字段（模板层）
- 债 3 北向资金口径（数据+模板）
- D-2 MD 报告正文缺 5 节内容（渲染层）
- D-3 PEG talk-text 缺 `> 3 极贵` 第 4 档（`report-design-principles.md:73-77` 是 4 档，V3 只 3 档）
- 任务 5 端到端样本票（杰瑞股份 002353）

**不在本 plan**：
- 债 4 价格快照 screener 部分（V3 时点化 ✅，screener 列未落 `price_snapshot_time`）
- 债 5 K线盘中时点（方案 A 已否决，长期 backlog）
- v2 端点补齐（数据广度线，parked）
- ifind 接入（spec §12 future options，parked）
- 6 项 runtime concerns（fflow 502 / slist fallback / 新闻 14-16s 等，parked）

---

## 2. 6 Task 概览

| Task | 标题 | 涉及 | 工期预估 |
|---|---|---|---|
| 5.1 | 债 1 结论-操作矛盾（多空状态机）| V3 主分析器 + HTML/MD/DOCX 渲染器 | 60-90 min |
| 5.2 | 债 2 支撑/压力字段（三价位表）| V3 主分析器 + 渲染器 | 45-60 min |
| 5.3 | 债 3 北向资金口径 | 验证接口 + 渲染器标注口径 | 30-45 min |
| 5.4 | D-2 MD 报告渲染补 5 节 | md_to_docx.py 同步 Section Registry | 30-45 min |
| 5.5 | D-3 PEG talk-text 补 `> 3 极贵` 档 | quant_analyzer_v3.py:1330 改 4 档 | 15-20 min |
| 5.6 | 任务 5 杰瑞股份 002353 端到端 | 全链路跑 + 对照 6 债项 | 20-30 min |

**总预估**：4-5 小时（含验证 + re-review + commit）

---

## Task 5.1: 债 1 结论-操作矛盾（多空状态机）

**Files**:
- Modify: `analysis/quant_analyzer_v3.py`（V3 主分析器，advice/trading_plan 生成）
- Modify: `analysis/html_report_v3.py`（HTML 渲染器，操作口诀段落）
- Modify: `analysis/md_to_docx.py`（MD/DOCX 渲染器，同上）
- Create: `tests/test_multi_state_trading_plan.py`（5 状态 × 模板断言）

**现状**（`docs/04-模板质量债.md:5-14`）：
- 报告"🔴 看空 43 分｜不建议进场（清仓回避）"，但操作口诀写"现价分两批进场、持有 3-6 个月"
- 模板只套了买入结构，未按多空结论切换操作模板

**Step 1: 查 V3 主分析器生成 trading_plan 的位置**

```bash
grep -n "trading_plan\|buy_signal\|position\|action" /Users/swarteachou/Desktop/大A数据/analysis/quant_analyzer_v3.py | head -30
```

**Step 2: 引入 state 映射函数**

在 V3 主分析器加：

```python
def _score_to_state(score: float) -> str:
    """综合评分 → 状态机映射。阈值与 report-design-principles.md:88-94 一致。"""
    if score >= 65: return "bullish"      # 65+ 看多
    if score >= 55: return "mild_bull"    # 55-65 轻多
    if score >= 45: return "neutral"      # 45-55 中性/震荡
    if score >= 35: return "mild_bear"    # 35-45 轻空
    return "bearish"                      # < 35 看空
```

**Step 3: 5 状态独立模板**

```python
OPERATION_TEMPLATES = {
    "bullish":   "现价分两批进场、持有 3-6 个月",
    "mild_bull": "轻仓试探 10-20%，等 65+ 确认后加仓",
    "neutral":   "区间操作 — 上沿减仓、下沿低吸、严格止损 {stop_loss}",
    "mild_bear": "减仓至轻仓、反弹遇压力位再加仓",
    "bearish":   "清仓回避 — 等待综合评分回升至 45+",
}
```

**Step 4: 修改 trading_plan 生成逻辑**

- 当前：单一模板
- 修后：按 `_score_to_state(score)` 选模板
- 同时模板**必须**包含结论 + 操作 + 风险提示三段（不能只套 buy 模板）

**Step 5: 同步 HTML/MD/DOCX 渲染器**

操作口诀段落（"现价分两批进场"那行）改为读 `result["trading_plan"]["template_used"]` 而非 hardcode。

**Step 6: 测试**

```python
# tests/test_multi_state_trading_plan.py
import pytest
from analysis.quant_analyzer_v3 import _score_to_state, OPERATION_TEMPLATES

@pytest.mark.parametrize("score,expected", [
    (80, "bullish"),
    (65, "bullish"),
    (60, "mild_bull"),
    (55, "mild_bull"),
    (50, "neutral"),
    (45, "neutral"),
    (40, "mild_bear"),
    (35, "mild_bear"),
    (20, "bearish"),
])
def test_score_to_state(score, expected):
    assert _score_to_state(score) == expected

def test_all_states_have_template():
    for state in ["bullish", "mild_bull", "neutral", "mild_bear", "bearish"]:
        assert state in OPERATION_TEMPLATES
        assert "止损" in OPERATION_TEMPLATES[state] or state == "bullish"  # 看多可不写止损
```

**Step 7: re-review + commit**

- subagent 改完 → verifier 复查 → 修 round 1（如有）
- commit: `fix(template): 多空状态机（5 状态独立操作模板，解债 1）`

**验收**：
- ✅ score=45（震荡）→ 操作写"区间操作 + 上下沿 + 止损"
- ✅ score=20（看空）→ "清仓回避 — 等待综合评分回升至 45+"
- ✅ score=70（看多）→ "现价分两批进场、持有 3-6 个月"
- ✅ 600693 实测 score=45 → 输出"区间操作"
- ✅ 杰瑞股份 002353 跑后操作口诀与结论一致

---

## Task 5.2: 债 2 支撑/压力字段（三价位表）

**Files**:
- Modify: `analysis/quant_analyzer_v3.py`（V3 主分析器，technical/chip_data 计算）
- Modify: `analysis/html_report_v3.py`（HTML 渲染器，价位表渲染）
- Modify: `analysis/md_to_docx.py`（MD/DOCX 渲染器，同上）
- Create: `tests/test_three_levels.py`（4 候选价 → 最近者算法测试）

**现状**（`docs/04-模板质量债.md:18-23`）：
- 老板硬要求"结论 + 支撑/压力/止损"缺一不可
- 当前只有止损/止盈（其实是"现价 +X%"反推的），没有真正从技术面算出的支撑/压力

**Step 1: 查 chip_data / valuation_hist 现有字段**

```bash
grep -n "support\|resistance\|stop\|ma60\|boll" /Users/swarteachou/Desktop/大A数据/analysis/quant_analyzer_v3.py | head -30
```

**Step 2: 三价位算法**

```python
def compute_three_levels(quote, technical, chip_data):
    """支撑/压力/止损，从 4 候选价取最近者（当前价 ±5% 范围内）。
    
    支撑候选（取价格最低的、且 ≤ 当前价）：
        1. MA60 (technical.get("ma60"))
        2. 前低 (technical.get("recent_low"))  # 60 日最低
        3. 筹码峰 (chip_data.get("cost_concentration").get("peak_price"))
        4. 布林下轨 (technical.get("boll_lower"))
    
    压力候选（取价格最高的、且 ≥ 当前价）：
        1. 年线 (technical.get("ma250"))  # 若 N<250 则用 MA120
        2. 前高 (technical.get("recent_high"))  # 60 日最高
        3. 布林上轨 (technical.get("boll_upper"))
    
    止损：支撑位 × 0.95（支撑下方 5%）
    """
    price = quote["price"]
    support = _pick_closest(price, [c for c in support_candidates if c and c <= price * 1.05], prefer="low")
    resistance = _pick_closest(price, [c for c in resistance_candidates if c and c >= price * 0.95], prefer="high")
    stop_loss = round(support * 0.95, 2) if support else None
    return {"support": support, "resistance": resistance, "stop_loss": stop_loss}
```

**Step 3: 渲染器加显式三价位表**

操作口诀上方加：

```
三价位(同源): 支撑=11.17 压力=12.67 止损=9.95
```

**Step 4: 测试**

```python
# tests/test_three_levels.py
def test_three_levels_picks_closest_support():
    quote = {"price": 11.52}
    technical = {"ma60": 11.20, "recent_low": 10.80, "boll_lower": 11.00}
    chip_data = {"cost_concentration": {"peak_price": 11.40}}
    result = compute_three_levels(quote, technical, chip_data)
    # 4 候选：11.20 / 10.80 / 11.40 / 11.00，取最低且 ≤ 当前价 = 10.80
    assert result["support"] == 10.80

def test_stop_loss_is_5pct_below_support():
    quote = {"price": 11.52}
    technical = {"ma60": 11.20}
    chip_data = {"cost_concentration": {"peak_price": 10.50}}
    result = compute_three_levels(quote, technical, chip_data)
    assert result["stop_loss"] == round(10.50 * 0.95, 2) == 9.97
```

**Step 5: re-review + commit**

- commit: `feat(template): 三价位表（4 候选取最近者，解债 2）`

**验收**：
- ✅ 600693 report 含 `三价位(同源): 支撑=X 压力=Y 止损=Z`
- ✅ 杰瑞股份 002353 三价位数字与 K 线 MA60/前低/布林下轨/筹码峰对得上
- ✅ 止损 = 支撑 × 0.95（5% 安全垫）

---

## Task 5.3: 债 3 北向资金口径

**Files**:
- Modify: `analysis/quant_analyzer_v3.py`（V3 主分析器，macro.north 数据源）
- Modify: `analysis/html_report_v3.py`（HTML 渲染器，北向显示）
- Modify: `analysis/md_to_docx.py`（MD/DOCX 渲染器，同上）
- Create: `tests/test_north_fund_scope.py`（接口返回值 scope 字段测试）

**现状**（`docs/04-模板质量债.md:25-33`）：
- 报告"✅ 北向净流入 370.5亿"
- 美湖股份流通市值 102 亿，全市场当日北向净流入 370 亿才算合理
- 怀疑：数据源把"全市场北向净流入"当个股口径填入了

**Step 1: 查北向数据源**

```bash
grep -rn "north\|北向\|hsgt" /Users/swarteachou/Desktop/大A数据/analysis/ | head -20
```

**Step 2: 验证接口返回值**

跑 600693，看 `result["macro"]["north"]` 实际结构：

```python
# scripts/verify_north_scope.py
import sys
sys.path.insert(0, "analysis")
from quant_analyzer_v3 import run_v3
res = run_v3("600693", "东百集团")
import json
print(json.dumps(res.get("macro", {}).get("north", {}), ensure_ascii=False, indent=2))
```

**Step 3: 标注口径**

接口返 `{"total": 370.5, "sh": 200.3, "sz": 170.2}`（全市场）→ 模板改：

```
- ✅ 北向资金（**全市场**净流入）：沪 200.3 亿 + 深 170.2 亿 = 370.5 亿
```

接口返 `{"stock_change_pct": 0.5, "stock_holding_ratio": 2.3}`（个股持股变化）→ 模板改：

```
- ✅ 个股北向持股变化：+0.5%（持股比例 2.3%）
```

接口返混合 → 模板分两段显示，明确各自口径。

**Step 4: 渲染器加 scope 标签**

```python
north = res.get("macro", {}).get("north", {})
scope = north.get("scope", "unknown")  # "market" / "stock" / "mixed"
if scope == "market":
    label = f"全市场北向净流入 {north.get('total', 0):.1f} 亿（沪 {north.get('sh', 0):.1f} + 深 {north.get('sz', 0):.1f}）"
elif scope == "stock":
    label = f"个股北向持股变化 {north.get('stock_change_pct', 0):+.2f}%"
else:
    label = "北向数据口径未明"
L.append(f"- {label}")
```

**Step 5: 测试 + commit**

- commit: `fix(data): 北向资金口径标注（全市场/个股分流，解债 3）`

**验收**：
- ✅ 600693 报告北向一行含 `（全市场）` 或 `（个股）` scope 标签
- ✅ 不再出现"美湖股份 102 亿市值但北向 370 亿"的明显口径混淆
- ✅ 杰瑞股份 002353 报告北向口径明确

---

## Task 5.4: D-2 MD 报告渲染补 5 节

**Files**:
- Modify: `analysis/md_to_docx.py`（MD 渲染器，section 渲染循环）
- (HTML/DOCX 已含 5 节，本 task 只补 MD)

**现状**（docs/04 D-2）：
- HTML/DOCX 报告含 5 sections 完整内容
- MD 报告正文缺 5 节内容（只 run_log 表格提及 sections）

**Step 1: 查 MD 渲染器 section 循环**

```bash
grep -n "section\|irm\|holders\|dividend\|board\|dragon_market" /Users/swarteachou/Desktop/大A数据/analysis/md_to_docx.py | head -30
```

**Step 2: 对比 HTML 渲染器实现**

`html_report_v3.py:1304-1320` 有 Section Registry 渲染循环。MD 应该没抄过去。

**Step 3: 抄过去**

把 HTML 的 Section Registry 循环 pattern 复制到 MD 渲染器：

```python
# md_to_docx.py
from analysis.sections import SECTIONS

def render_md(res, writer=None):
    # ... 现有 6 块 ...
    
    # --- Section Registry 循环（与 html_report_v3.py 一致）---
    for sec_id, sec_cls in SECTIONS.items():
        if not sec_cls.enabled():
            continue
        sec_data = sec_cls.collect(res)
        if sec_data:
            L.append(f"## {sec_cls.title()}")
            for k, v in sec_data.items():
                L.append(f"- **{k}**: {v}")
            L.append("")
    
    return "\n".join(L)
```

**Step 4: 测试 + commit**

- commit: `feat(md): 5 sections 渲染循环（与 HTML/DOCX 对齐，解 D-2）`

**验收**：
- ✅ 600693 MD 报告含 5 sections 完整内容（irm/holders/dividend/board/dragon_market）
- ✅ 杰瑞股份 002353 MD 报告 5 sections 全部就位

---

## Task 5.5: D-3 PEG talk-text 补 `> 3 极贵` 档

**Files**:
- Modify: `analysis/quant_analyzer_v3.py:1330`（PEG talk-text 改 4 档）
- Create: `tests/test_peg_talk_text.py`（4 档阈值断言）

**现状**：
- `report-design-principles.md:73-77` 定义 4 档：`< 1 / 1-1.5 / > 1.5 / > 3 极贵（成长股例外）`
- V3 `quant_analyzer_v3.py:1330` 只实装 3 档，缺 `> 3 极贵`

**Step 1: 修改 line 1330**

```python
# 旧（line 1330）：
peg_talk = "PEG < 1, 便宜区" if peg < 1 else ("PEG 1~1.5, 合理" if peg < 1.5 else "PEG > 1.5, 偏贵")

# 新（4 档，对齐 report-design-principles.md:73-77）：
if peg < 1:
    peg_talk = "PEG < 1, 便宜区"
elif peg < 1.5:
    peg_talk = "PEG 1~1.5, 合理"
elif peg < 3:
    peg_talk = "PEG 1.5~3, 偏贵"
else:
    peg_talk = "PEG > 3, 极贵（成长股例外：壁垒深可能合理）"
```

**Step 2: 测试**

```python
# tests/test_peg_talk_text.py
import pytest

@pytest.mark.parametrize("peg,expected_substr", [
    (0.5, "便宜区"),
    (1.0, "合理"),
    (1.4, "合理"),
    (1.5, "偏贵"),
    (2.5, "偏贵"),
    (3.0, "极贵"),
    (5.0, "极贵"),
    (9.56, "极贵"),  # 600693 实测
])
def test_peg_talk_text_4_tiers(peg, expected_substr):
    text = _format_peg_talk(peg)
    assert expected_substr in text
```

**Step 3: commit**

- commit: `fix(template): PEG talk-text 补 > 3 极贵档（对齐 report-design-principles.md:73-77）`

**验收**：
- ✅ PEG=0.5 → "便宜区"
- ✅ PEG=1.4 → "合理"
- ✅ PEG=2.5 → "偏贵"
- ✅ PEG=9.56 → "极贵（成长股例外：壁垒深可能合理）"
- ✅ 杰瑞股份 002353 报告 PEG 输出符合 4 档

---

## Task 5.6: 任务 5 杰瑞股份 002353 端到端

**Files**:
- 无代码修改
- Create: `.superpowers/sdd/2026-09-08-report-quality-and-sample-run/task-5.6-report.md`（验证报告）

**Step 1: 跑 002353**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 002353 杰瑞股份 2>&1 | tee /tmp/run_002353.log
```

**Step 2: 对照 6 债项人工验收**

| 验收项 | 期望 | 实测 |
|---|---|---|
| 5 件套落档 | MD + HTML + DOCX + result_v3 + run_log | ___ |
| 单票端到端 | < 120s | ___ |
| 债 1 多空状态机 | 操作口诀与 score 一致 | ___ |
| 债 2 三价位表 | 含 support/resistance/stop_loss | ___ |
| 债 3 北向口径 | 含（全市场）或（个股）scope 标签 | ___ |
| D-2 MD 5 节 | MD 报告含 5 sections 完整内容 | ___ |
| D-3 PEG 4 档 | PEG 落在 4 档之一 | ___ |

**Step 3: 跑所有 tests**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

Expected: 14 + 新增 4-6 个 = 18-20 tests pass

**Step 4: 写验收报告 + 更新 docs/04**

- `task-5.6-report.md` 记录 6 债项对照
- docs/04 债 1/2/3 + D-2/D-3 状态全部改 ✅

**Step 5: commit + tag**

- commit: `docs(debt): 报告质量线 6 task 全部完成`
- tag: `v0.10-report-quality-complete`

**验收**：
- ✅ 杰瑞股份 002353 报告 6 债项全部对账通过
- ✅ 14+N tests pass
- ✅ 单票 < 120s
- ✅ 5 sections 全活
- ✅ docs/04 状态更新
- ✅ tag v0.10-report-quality-complete 落档

---

## 3. Self-Review

### 3.1 6 债项覆盖

| 债/项 | 计划 task | 状态 |
|---|---|---|
| 债 1 结论-操作矛盾 | 5.1 多空状态机 | ✅ |
| 债 2 支撑/压力字段 | 5.2 三价位表 | ✅ |
| 债 3 北向口径 | 5.3 scope 标注 | ✅ |
| D-2 MD 5 节 | 5.4 MD 渲染循环 | ✅ |
| D-3 PEG 4 档 | 5.5 补 > 3 极贵档 | ✅ |
| 任务 5 端到端 | 5.6 002353 杰瑞股份 | ✅ |

### 3.2 风险

- **5.1 多空状态机**：score → state 阈值需与 `report-design-principles.md:88-94` 一致（仓位 5 档），不能拍脑袋。**已对齐**
- **5.2 三价位算法**：4 候选价取最近者，可能有边界 case（如 MA60 > 当前价 5%，应不纳入支撑候选）。**已加 ±5% 过滤**
- **5.3 北向口径**：若接口返 `{"scope": "unknown"}` 需 fallback 到"数据口径未明"提示，**已加**
- **5.4 MD 渲染**：抄 HTML 循环时需保证 `SECTIONS` import 路径一致（绝对 import）。**已用 `from analysis.sections import SECTIONS`**
- **5.5 PEG 4 档**：注意 `peg == 1.5` / `peg == 3` 边界用 `<` 不是 `<=`。**已对齐**
- **5.6 杰瑞股份 002353**：PE 通常较高（10-30x），PEG 可能落在"极贵"档，需确认 talk-text 正确

### 3.3 范围外

- 债 4 PARTIAL：V3 时点化 ✅，screener 列 `price_snapshot_time` 仍未落 → 留 parked
- 债 5 K线盘中时点：方案 A 否决，长期 backlog
- v2 端点 5 个未实现：parked（数据广度线，下次 plan）
- ifind 接入：parked（spec §12 future options）

### 3.4 subagent 派单策略

- Task 5.1-5.5：派 `worker` 实施，每个 task 1 个 subagent
- Task 5.6：自己跑（端到端验证，人工对照）
- 涉及公式/算法改动（5.2 三价位、5.5 PEG 阈值、5.1 状态机）：实施后派 `verifier` 复查
- 不阻塞并行：5.1 完成后 5.2/5.3/5.4/5.5 可并行派（不同 subagent 各自读不同文件，无重叠写）
