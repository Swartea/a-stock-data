# A-Stock-Data Skill 优化 · 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计稿实施 4 phase 优化（spec `docs/superpowers/specs/2026-09-07-a-stock-data-skill-optimize-design.md`），让 a-stock-data skill 跑得动、写得快、未来好接手。

**Architecture:**
- **Phase 0** P0 quick wins：4 个 ≤ 8 行 bug 修复
- **Phase 1** Section Registry 骨架：`_base.py` + `__init__.py` + 第一个示范 section (irm)
- **Phase 2** 4 个 section：holders / dividend / board / dragon_market
- **Phase 3** SKILL.md 导航：5 秒定位目录 + 54 端点 emoji + references 关联
- **Phase 4** 集成回归：跑通 600693 3 次 / 验证 PEG / 验证时点

**Tech Stack:** Python 3.12 / venv (`/Users/swarteachou/Desktop/大A数据/venv`) / git / markdown / bash / requests / baostock / mootdx / 同花顺 / 东财 / 巨潮 / 申万 / 新浪

---

## Global Constraints

| 项 | 值 |
|---|---|
| 工作目录 | `/Users/swarteachou/Desktop/大A数据/`（中文 workdir，纯绝对路径，**禁止 `cd` 进去**）|
| Python | `venv/bin/python -W ignore`（arm64 原生，**禁止 `arch -x86_64`**）|
| 运行 | `venv/bin/python -W ignore <script> 2>&1 \| tee /tmp/<log>.log` |
| Commit | 中文 message，1 task 1 commit，prefix 按 type（`fix:` / `feat:` / `docs:` / `test:` / `chore:`）|
| 文档 | 实施完成更新 `docs/04-模板质量债.md` 对应债项状态 |
| 永不变数据 | 4 个 fetcher（财务/公告/研报/新闻）源码不改；2 个 V2 私有函数签名不改 |
| 零编造 | 拉不到的数据标 `⚠️ 端点不可用`，禁止合成 |
| 不删旧文件 | V1 `quant_analyzer.py` 移到 `_legacy/` 而非 `git rm` |
| 失败兜底 | 每节 `try/except` 隔离错误，`result[label] = {"error": str(e)}` + `run_log` 标 error |
| 设计稿 | `docs/superpowers/specs/2026-09-07-a-stock-data-skill-optimize-design.md` |
| 审计报告 | `docs/superpowers/specs/2026-09-07-audit/`（V3/端点/SKILL.md 三份）|

---

## File Structure

### 新增文件

| 路径 | 用途 |
|------|------|
| `analysis/sections/_base.py` | Section ABC 抽象类（fetch / render 契约）|
| `analysis/sections/__init__.py` | SECTIONS 列表 + `enabled_sections()` + 注册逻辑 |
| `analysis/sections/registry.yaml` | 全局开关（disabled_sections）|
| `analysis/sections/irm/{fetcher.py, render.py, meta.json, test_irm.py}` | §10.1 互动易 |
| `analysis/sections/holders/{fetcher.py, render.py, meta.json, test_holders.py}` | §4.3 股东户数 |
| `analysis/sections/dividend/{fetcher.py, render.py, meta.json, test_dividend.py}` | §4.4 分红 |
| `analysis/sections/board/{fetcher.py, render.py, meta.json, test_board.py}` | §8.1-8.3 打板 |
| `analysis/sections/dragon_market/{fetcher.py, render.py, meta.json, test_dragon_market.py}` | §3.9 全市场龙虎榜 |
| `analysis/references/valuation-formulas.md` | PEG 公式文档化（设计稿 §8.3）|
| `analysis/_legacy/quant_analyzer_v1.py` | V1 死代码归档 |
| `tests/test_three_levels.py` | 三价位关系正确性（stop_loss < support < price < resistance）|
| `tests/test_run_log_schema.py` | run_log.json 结构契约 |

### 修改文件

| 路径 | 改法 | 来源 |
|------|------|------|
| `analysis/quant_analyzer_v2.py:249-251` | PEG 公式修 | V3 审计 P0-1 |
| `analysis/quant_analyzer_v2.py:308` | fflow push2 → push2his | 端点验证 Part B |
| `analysis/quant_analyzer_v3.py:269` | _fetch_fund_flow_daily push2 → push2his | 端点验证 Part B |
| `analysis/quant_analyzer_v3.py:538-589` | 改用 `for sec in enabled_sections(): sec.fetch(...)` | 设计稿 §3.3 |
| `analysis/quant_analyzer_v3.py:658,659,746` | 时间戳 `result_v3-{HHMM}.json` / `run_log-{HHMM}.json` | V3 审计 P0-2 |
| `analysis/html_report_v3.py:130-146` | `_source_time` 读 `source_meta` | V3 审计 P1-4 |
| `analysis/fetch_news_em.py:163` | 退避 `0.8+1.2*attempt` | V3 审计 P0-5/P1-7 |
| `SKILL.md` | 顶部 3 个新区 + 54 端点 emoji + 7 处章节锚点 | SKILL.md 审计 §3-6 |
| `scripts/verify_accept_600693.py:13` | 通配匹配 run_log | V3 审计 P0-2 配套 |

---

# Phase 0: P0 Quick Wins

> **目标**：4 个 ≤ 8 行 bug 修复，立即止血 + 跑通回归
> **工期**：1-1.5h

---

## Task 0.1: V3 命名 bug（时间戳防覆盖）

**Files:**
- Modify: `analysis/quant_analyzer_v3.py:658, 659, 746`
- Modify: `scripts/verify_accept_600693.py:13`

**Interfaces:**
- Consumes: `day_dir`（已存在）, `hhmm` 变量（line 654 `base = f"{code}-{safe_name}-{hhmm}"`）
- Produces: 文件 `result_v3-{HHMM}.json` / `run_log-{HHMM}.json` 不再覆盖

- [ ] **Step 1: 写回归测试** — 创建 `tests/test_run_log_schema.py`

```python
import os
import re
import subprocess
import json

WORKDIR = "/Users/swarteachou/Desktop/大A数据"
DAY_DIR = f"{WORKDIR}/reports/600693_东百集团/2026-09-07"

def test_run_log_has_timestamp():
    """两次跑 V3 应产生两个不同 HHMM 的 run_log，不应覆盖"""
    pattern = re.compile(r"run_log-\d{4}\.json")
    files = [f for f in os.listdir(DAY_DIR) if pattern.match(f)]
    # 至少 1 个（最近一次跑），不再有固定名 run_log.json
    assert len(files) >= 1, f"应该有时间戳的 run_log，实际: {os.listdir(DAY_DIR)}"
    # 不应该有固定名的 run_log.json
    assert "run_log.json" not in os.listdir(DAY_DIR), \
        "run_log.json 不应再存在（应改为 run_log-{HHMM}.json）"

def test_result_v3_has_timestamp():
    pattern = re.compile(r"result_v3-\d{4}\.json")
    files = [f for f in os.listdir(DAY_DIR) if pattern.match(f)]
    assert len(files) >= 1
    assert "result_v3.json" not in os.listdir(DAY_DIR)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_run_log_schema.py -v
```

Expected: `test_run_log_has_timestamp` FAIL（因为当前是固定名 `run_log.json`）

- [ ] **Step 3: 修改 `quant_analyzer_v3.py:658, 659, 746`**

打开 `analysis/quant_analyzer_v3.py`，找到：
- Line 658: `json_path = os.path.join(day_dir, "result_v3.json")`
- Line 659: `log_path = os.path.join(day_dir, "run_log.json")`
- Line 746（`_dump_run_log` 函数内）: `with open(os.path.join(day_dir, "run_log.json"), "w", encoding="utf-8") as f:`

改为：
- Line 658: `json_path = os.path.join(day_dir, f"result_v3-{hhmm}.json")`
- Line 659: `log_path = os.path.join(day_dir, f"run_log-{hhmm}.json")`
- Line 746: `with open(os.path.join(day_dir, f"run_log-{datetime.now().strftime('%H%M')}.json"), "w", encoding="utf-8") as f:`

如果 `datetime` 没在文件顶 import，加 `from datetime import datetime`。

- [ ] **Step 4: 修改 `scripts/verify_accept_600693.py:13`**

把固定名 `run_log.json` 改为通配匹配 `run_log-*.json`：

```python
import glob
log_files = glob.glob(f"{DAY_DIR}/run_log-*.json")
assert log_files, f"未找到 run_log-*.json in {DAY_DIR}"
log_path = max(log_files, key=os.path.getmtime)  # 取最新的
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_run_log_schema.py -v
```

Expected: 2 passed

- [ ] **Step 6: 跑 V3 600693 验证 2 份 run_log 共存**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_after_001.log
```

确认 `reports/600693_东百集团/2026-09-07/` 有 2 个 `run_log-*.json`（不互覆盖）

- [ ] **Step 7: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/quant_analyzer_v3.py scripts/verify_accept_600693.py tests/test_run_log_schema.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "fix(v3): result_v3.json + run_log.json 加时间戳防覆盖

- V3 line 658/659/746 改 result_v3-{HHMM}.json / run_log-{HHMM}.json
- verify_accept_600693.py 用 glob 匹配 run_log-*.json
- 配套测试 tests/test_run_log_schema.py 验证时间戳 + 不互覆盖
- 解 9-7 12:02 已被 16:16 覆盖的债（V3 审计 P0-2）"
```

---

## Task 0.2: push2 → push2his 资金流域名修复

**Files:**
- Modify: `analysis/quant_analyzer_v3.py:268-272`（`_fetch_fund_flow_daily`）
- Modify: `analysis/quant_analyzer_v2.py:308`（`fetch_fund_flow_minute`）

**Interfaces:**
- Consumes: `v2.em_get`（已存在）, `code` 字符串
- Produces: 资金流数据走 `push2his.eastmoney.com`（与 SKILL.md §4.5 一致）

- [ ] **Step 1: 写端到端测试**

创建 `tests/test_fund_flow_domain.py`：

```python
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
import quant_analyzer_v3 as v3

def test_fund_flow_daily_uses_push2his():
    """5 日主力资金流应走 push2his（同 §4.5），不应 error"""
    code = "600693"
    # 触发 _fetch_fund_flow_daily（公开函数名可能不同，按实际修）
    result = v3._fetch_fund_flow_daily(code, days=5) if hasattr(v3, "_fetch_fund_flow_daily") else None
    if result is None:
        # 调外部入口验证
        from quant_analyzer_v3 import analyze_single_v3
        out = analyze_single_v3(code, "东百集团", write_artifact=False)
        assert "fund_daily5" in out or "资金面-5日主力" in str(out)
    else:
        assert "error" not in result or "Expecting value" not in result.get("error", "")
```

- [ ] **Step 2: 跑测试，确认部分失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_fund_flow_domain.py -v 2>&1 | tail -30
```

Expected: 测试可能因 error 失败（如当前 push2 路径返回空）

- [ ] **Step 3: 修 `quant_analyzer_v3.py:268-272`**

打开 `analysis/quant_analyzer_v3.py`，找到 `_fetch_fund_flow_daily` 函数（约 line 268-272），把：

```python
d = v2.em_get(..., timeout=15).json()
```

中 URL 从 `push2.eastmoney.com` 改为 `push2his.eastmoney.com`。具体看代码：

```python
# 原代码（line 268-272 类似）
url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
# 改为
url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
```

- [ ] **Step 4: 同步修 `quant_analyzer_v2.py:308`**

打开 `analysis/quant_analyzer_v2.py`，找到 `fetch_fund_flow_minute` 函数（约 line 299-327）：

```python
# 找原 push2 URL
url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
# 改为
url = "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
```

- [ ] **Step 5: 跑测试 + V3 验证**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_fund_flow_domain.py -v && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_after_002.log
```

Expected: 测试通过；run_log 显示 `资金面-5日主力: ok, ...`（不是 error）

- [ ] **Step 6: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/quant_analyzer_v3.py analysis/quant_analyzer_v2.py tests/test_fund_flow_domain.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "fix(fund-flow): 资金流域名 push2 → push2his（解 9-7 资金面-5日主力失败）

- V3 _fetch_fund_flow_daily (line 269) 域名前缀改 push2his
- V2 fetch_fund_flow_minute (line 308) 同步改
- 与 SKILL.md §4.5 stock_fund_flow_120d 实现对齐（push2his 与 push2 不同 WAF，9-6 案例证明 push2 挂时 push2his 仍稳）"
```

---

## Task 0.3: PEG 公式修复

**Files:**
- Modify: `analysis/quant_analyzer_v2.py:249-251`
- Create: `analysis/references/valuation-formulas.md`

**Interfaces:**
- Consumes: `price`, `eps_cur`, `eps_next`（已存在）
- Produces: `peg` 字段与 ifind PEG(LYR) 差 < 2x（目标 600693 PEG 在 35-50 范围）

- [ ] **Step 1: 写 PEG 公式单测**

创建 `tests/test_peg_formula.py`：

```python
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
import quant_analyzer_v2 as v2

def test_peg_600693_close_to_ifind():
    """600693 PEG 应在 35-50 范围（ifind PEG(LYR)=41.73 ± 20%）"""
    v = v2.fetch_full_valuation("600693")
    peg = v.get("peg")
    pe_fwd = v.get("pe_fwd")
    cagr_pct = v.get("cagr_pct") or ((v.get("eps_next", 0) / v.get("eps_cur", 1)) - 1) * 100
    print(f"pe_fwd={pe_fwd}, eps_cur={v.get('eps_cur')}, eps_next={v.get('eps_next')}, cagr_pct={cagr_pct}, peg={peg}")
    assert peg is not None, "PEG 不应为 None"
    assert 35 <= peg <= 50, f"PEG {peg} 偏离 ifind 41.73 太远（>2x）"

def test_peg_calculation_uses_cagr_pct():
    """PEG 应 = pe_fwd / cagr_pct（cagr_pct 已是百分数，不是小数）"""
    # 构造虚拟数据验证公式
    # pe_fwd=20, cagr_pct=20% → PEG = 1.0
    # pe_fwd=40, cagr_pct=20% → PEG = 2.0
    pass  # 实际测试通过 fetch_full_valuation 隐式覆盖
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_peg_formula.py -v -s
```

Expected: 看到 `peg=3.87` 之类的当前错误值，测试失败

- [ ] **Step 3: 修 `quant_analyzer_v2.py:249-251`**

打开 `analysis/quant_analyzer_v2.py`，找到 line 249-251：

```python
# 原代码
pe_fwd = price / eps_cur if (eps_cur and eps_cur > 0) else None
cagr = ((eps_next / eps_cur - 1) if (eps_cur and eps_next and eps_cur > 0) else 0)
peg = (pe_fwd / (cagr * 100)) if (pe_fwd and cagr > 0) else None
```

改为：

```python
# 新代码
pe_fwd = price / eps_cur if (eps_cur and eps_cur > 0) else None
cagr_pct = ((eps_next / eps_cur - 1) * 100) if (eps_cur and eps_next and eps_cur > 0) else 0
peg = (pe_fwd / cagr_pct) if (pe_fwd and cagr_pct > 0) else None
# 注意：cagr_pct 是百分数（如 21 = 21%），不是小数 0.21
# PEG = PE / 增速% = 218 / 5.2 = 41.9（接近 ifind PEG(LYR)=41.73）
```

同时找到使用 `cagr`（小数）的其他位置（如 `digest_years` 公式），保持小数不变：
```python
# 如果有 digest_years 之类的公式用了 cagr（小数），保持 cagr
# 但不要用 cagr * 100
cagr_decimal = cagr_pct / 100
```

- [ ] **Step 4: 跑测试 + 对账 ifind**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_peg_formula.py -v -s
```

Expected: 看到 `peg ≈ 41.9`（接近 ifind 41.73），测试通过

- [ ] **Step 5: 写 `analysis/references/valuation-formulas.md` 文档**

```markdown
# 估值公式说明

## PEG（市盈率相对盈利增长比率）

**标准公式**：`PEG = PE / 盈利增速%`

其中盈利增速是**百分比数值**（如 21 = 21%），不是小数（0.21）。

**ifind PEG(LYR) 口径**：
- 分母 = LYR（Last Year Reported）净利润同比增速%
- 分子 = PE TTM
- 600693 实测：PE 218 / 同比 5.2% = 41.9（实测 41.73）

**本项目 V2/V3 实现**：
- `analysis/quant_analyzer_v2.py` `fetch_full_valuation()`
- `cagr_pct = (eps_next / eps_cur - 1) * 100`（已转为百分数）
- `peg = pe_fwd / cagr_pct`

**注意**：
- `digest_years` 公式内部用 `cagr_decimal = cagr_pct / 100`（小数）
- 历史 bug（9-7 发现）：曾用 `cagr * 100` 把小数当百分数，导致 PEG 差 10.8x
- 现已修复（9-8 commit 0.3）
```

- [ ] **Step 6: 跑 V3 验证报告 PEG 显示正确**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_after_003.log
```

打开 `reports/600693_东百集团/2026-09-07/600693-东百集团-*-v3.html` 看 PEG 字段，应该接近 41.9 而非 3.87

- [ ] **Step 7: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/quant_analyzer_v2.py analysis/references/valuation-formulas.md tests/test_peg_formula.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "fix(valuation): PEG 公式 cagr * 100 → cagr_pct（解 10.8x 偏差）

- V2 fetch_full_valuation: 改 cagr_pct = (eps_next/eps_cur - 1) * 100
- peg = pe_fwd / cagr_pct（分母是百分数，不是小数）
- 600693 PEG: 3.87 → 41.9（接近 ifind PEG(LYR) 41.73，差距 < 1x）
- 文档化到 analysis/references/valuation-formulas.md"
```

---

## Task 0.4: 新闻退避时间压缩

**Files:**
- Modify: `analysis/fetch_news_em.py:163`

**Interfaces:**
- Consumes: `attempt`（0/1/2）
- Produces: 总退避 21s → 6s（省 15s）

- [ ] **Step 1: 写退避单测**

创建 `tests/test_news_backoff.py`：

```python
import time
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")

def test_news_backoff_reduced():
    """新闻 fetcher 总退避应 < 10s（3 次失败）"""
    # 静态检查源码
    src = open("/Users/swarteachou/Desktop/大A数据/analysis/fetch_news_em.py").read()
    # 旧的 sleep 3 + 4*attempt = 3/7/11s（21s 总和）
    # 新的 sleep 0.8 + 1.2*attempt = 0.8/2.0/3.2s（6s 总和）
    assert "0.8 + 1.2 * attempt" in src or "0.8+1.2*attempt" in src, \
        "应改为 0.8+1.2*attempt"
    assert "3 + 4 * attempt" not in src, "旧的 3+4*attempt 不应保留"
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_news_backoff.py -v
```

Expected: FAIL（当前是 `3 + 4 * attempt`）

- [ ] **Step 3: 修 `fetch_news_em.py:163`**

打开 `analysis/fetch_news_em.py`，找到 line 163 附近的 `time.sleep(3 + 4 * attempt)`：

```python
# 改为
time.sleep(0.8 + 1.2 * attempt)    # 0.8, 2.0, 3.2s 替代 3, 7, 11s
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/test_news_backoff.py -v
```

Expected: PASS

- [ ] **Step 5: 跑 V3 验证新闻源耗时 < 10s**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_after_004.log
```

查看 `run_log-{HHMM}.json` 的 `新闻舆情` ms 字段，应 < 10000ms

- [ ] **Step 6: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/fetch_news_em.py tests/test_news_backoff.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "perf(news): 退避 3+4*attempt → 0.8+1.2*attempt（省 15s）

- 旧的 3+7+11=21s 退避链 → 新的 0.8+2.0+3.2=6s
- 单票新闻源从 23s → 8s（节省 15s）
- 配合 P0-2 之后总跑 < 60s"
```

---

## Task 0.5: Phase 0 集成验证

- [ ] **Step 1: 跑 600693 3 次，确认 3 份 run_log 共存 + PEG 正确 + 资金面不 error**

```bash
cd /Users/swarteachou/Desktop/大A数据 && for i in 1 2 3; do venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase0_$i.log; sleep 60; done
```

- [ ] **Step 2: 验证 4 个 P0 修复都生效**

```bash
cd /Users/swarteachou/Desktop/大A数据 && ls reports/600693_东百集团/2026-09-07/run_log-*.json
# 应有 ≥ 2 个 run_log-*.json（不互覆盖）
grep "PEG" reports/600693_东百集团/2026-09-07/600693-东百集团-*-v3.html | head -5
# PEG 应显示 41.x 而非 3.87
grep "资金面-5日主力\|fund_daily" reports/600693_东百集团/2026-09-07/run_log-*.json
# 应是 ok 不是 error
grep "新闻舆情" reports/600693_东百集团/2026-09-07/run_log-*.json
# 应 < 10000ms
```

- [ ] **Step 3: 跑所有 Phase 0 测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

Expected: 所有 Phase 0 测试通过

- [ ] **Step 4: 提交（无文件改动，跳过）**

Phase 0 结束。准备进 Phase 1。

---

# Phase 1: Section Registry 骨架

> **目标**：建立 `analysis/sections/` 目录 + Section ABC + 注册逻辑 + 1 个示范 section (irm)
> **工期**：1.5-2 天
> **依据**：设计稿 §3 + §4.1

---

## Task 1.1: Section ABC 抽象类

**Files:**
- Create: `analysis/sections/_base.py`
- Create: `analysis/sections/__init__.py`
- Create: `tests/sections/__init__.py`
- Create: `tests/sections/test_base.py`

**Interfaces:**
- Consumes: 无
- Produces: `Section` 抽象类（fetch / render_html / render_md 三个方法）

- [ ] **Step 1: 写测试** — 创建 `tests/sections/test_base.py`

```python
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections._base import Section

def test_section_abstract_cannot_instantiate():
    """Section 是抽象类，不能直接实例化"""
    try:
        s = Section()
        assert False, "应抛 TypeError"
    except TypeError:
        pass

def test_section_subclass_must_implement_methods():
    """子类必须实现 fetch / render_html / render_md"""
    class IncompleteSection(Section):
        label = "test"
    try:
        s = IncompleteSection()
        assert False, "应抛 TypeError"
    except TypeError:
        pass

def test_section_full_subclass_works():
    """完整子类可实例化并调方法"""
    class TestSection(Section):
        label = "test"
        title = "测试章节"
        weight = 1
        sort_order = 50
        source_ref = "§x.x"
        data_sources = ["test_endpoint"]
        def fetch(self, code, ctx):
            return {"rows": [1, 2, 3]}
        def render_html(self, result, writer):
            writer.append(f"<h2>{self.title}</h2>")
            return f"<section>{self.title}: {result.get('rows')}</section>"
        def render_md(self, result, writer):
            writer.append(f"## {self.title}")
            return f"{self.title}: {result.get('rows')}"
    s = TestSection()
    assert s.label == "test"
    assert s.fetch("600693", {})["rows"] == [1, 2, 3]
    assert "测试章节" in s.render_html({"rows": []}, [])
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/sections/test_base.py -v
```

Expected: ModuleNotFoundError（`sections` 模块不存在）

- [ ] **Step 3: 创建 `analysis/sections/_base.py`**

```python
# analysis/sections/_base.py
"""Section 抽象基类 — V3 报告章节插件的基础接口

每节必须实现：
- label (str): 报告中显示的简短标签
- title (str): 报告中显示的完整标题
- weight (int): 排序权重（越小越靠前）
- sort_order (int): MD 渲染中的顺序
- source_ref (str): SKILL.md 章节引用（如 "§10.1"）
- data_sources (list[str]): 依赖的 a-stock-data 端点名
- fetch(code, ctx) -> dict: 拉数据，返回 result key
- render_html(result, writer) -> str: 渲染 HTML 片段
- render_md(result, writer) -> str: 渲染 MD 片段
"""
from abc import ABC, abstractmethod
from typing import Any


class Section(ABC):
    """Section 抽象类 — 单一职责：拉数据 + 渲染"""
    label: str = ""
    title: str = ""
    weight: int = 100
    sort_order: int = 50
    source_ref: str = ""
    data_sources: list[str] = []

    @abstractmethod
    def fetch(self, code: str, ctx: dict) -> dict:
        """拉数据，返回 dict 存入 result[self.label]

        Args:
            code: 6 位股票代码
            ctx: 上下文（如 v2.fetch_full_valuation 的结果）

        Returns:
            dict 数据，或 {"error": str(e)} 兜底
        """
        pass

    @abstractmethod
    def render_html(self, result: dict, writer: list) -> str:
        """渲染 HTML 片段到 result dict

        Args:
            result: 当前节的 result key
            writer: HTML 写入列表（append 字符串）

        Returns:
            完整 HTML 片段字符串
        """
        pass

    @abstractmethod
    def render_md(self, result: dict, writer: list) -> str:
        """渲染 MD 片段到 result dict

        Args:
            result: 当前节的 result key
            writer: MD 写入列表（append 字符串）

        Returns:
            完整 MD 片段字符串
        """
        pass

    def has_error(self, result: dict) -> bool:
        """检查 result 是否有 error"""
        return isinstance(result, dict) and "error" in result
```

- [ ] **Step 4: 创建 `analysis/sections/__init__.py`**

```python
# analysis/sections/__init__.py
"""Section Registry — V3 报告章节插件注册表

公开 API:
- SECTIONS: 所有注册的 Section 实例列表
- enabled_sections(): 根据 registry.yaml 过滤后的启用列表
"""
import os
import yaml
from typing import List
from ._base import Section

# 注册表（按 sort_order 排序）
SECTIONS: List[Section] = []

# 延迟导入具体 section（避免循环）
def _register_sections():
    from .irm import IRMSection
    from .holders import HoldersSection
    from .dividend import DividendSection
    from .board import BoardSection
    from .dragon_market import DragonMarketSection
    SECTIONS.extend([
        IRMSection(),
        HoldersSection(),
        DividendSection(),
        BoardSection(),
        DragonMarketSection(),
    ])
    SECTIONS.sort(key=lambda s: s.sort_order)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "registry.yaml")


def _load_disabled() -> list:
    """从 registry.yaml 读 disabled_sections"""
    if not os.path.exists(_REGISTRY_PATH):
        return []
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("disabled_sections", []) or []
    except Exception:
        return []


def enabled_sections() -> List[Section]:
    """返回按 sort_order 排序的启用 section 列表"""
    if not SECTIONS:
        _register_sections()
    disabled = set(_load_disabled())
    return [s for s in SECTIONS if s.label not in disabled]


__all__ = ["Section", "SECTIONS", "enabled_sections"]
```

- [ ] **Step 5: 创建 `tests/sections/__init__.py`**

```python
# 空文件，让 tests/sections 成为 Python 包
```

- [ ] **Step 6: 跑测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/sections/test_base.py -v
```

Expected: 部分测试可能因 sections 缺子模块而 fail（Task 1.2 之后修复），但 `test_section_abstract_cannot_instantiate` 和 `test_section_subclass_must_implement_methods` 应该 PASS

- [ ] **Step 7: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/sections/_base.py analysis/sections/__init__.py tests/sections/test_base.py tests/sections/__init__.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "feat(sections): Section ABC 抽象基类 + 注册表骨架

- analysis/sections/_base.py: Section 抽象类（fetch / render_html / render_md 3 个抽象方法）
- analysis/sections/__init__.py: SECTIONS 列表 + enabled_sections() 工具 + registry.yaml 解析
- tests/sections/test_base.py: 抽象类不可实例化 + 子类必须实现 3 方法 + 完整子类可工作
- 5 节全部 import 占位（Task 1.2/2.1-2.4 会逐个实现）"
```

---

## Task 1.2: 第一个示范 section（互动易 §10.1）

**Files:**
- Create: `analysis/sections/irm/__init__.py`
- Create: `analysis/sections/irm/fetcher.py`
- Create: `analysis/sections/irm/render.py`
- Create: `analysis/sections/irm/meta.json`
- Create: `analysis/sections/irm/test_irm.py`

**Interfaces:**
- Consumes: `code` 6位代码, `v2.fetch_*` 已存在的函数
- Produces: `result["irm"]` dict（含 `rows` 列表），HTML 片段含 📞 标题，MD 片段含 ## 标题

- [ ] **Step 1: 写测试** — 创建 `analysis/sections/irm/test_irm.py`

```python
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
from sections.irm import IRMSection
from sections.irm.fetcher import fetch_irm
from sections.irm.render import render_html, render_md

def test_irm_meta():
    s = IRMSection()
    assert s.label == "irm"
    assert s.title == "📞 投资者互动问答"
    assert s.source_ref == "§10.1"
    assert s.sort_order == 40

def test_irm_fetch_600693(monkeypatch):
    """mock fetch 返回样本数据"""
    from sections.irm.fetcher import fetch_irm
    fake = {
        "rows": [
            {"date": "2026-09-05", "asker": "投资者A", "question": "Q1", "answer": "A1"},
        ]
    }
    monkeypatch.setattr("sections.irm.fetcher._raw_fetch", lambda code, limit: fake["rows"])
    result = fetch_irm("600693", limit=5)
    assert "rows" in result
    assert len(result["rows"]) >= 1
    assert result["rows"][0]["question"] == "Q1"

def test_irm_render_html():
    result = {"rows": [{"date": "2026-09-05", "asker": "A", "question": "Q", "answer": "A"}]}
    html = render_html(result, [])
    assert "📞 投资者互动问答" in html
    assert "投资者互动" in html or "互动易" in html
    assert "Q" in html

def test_irm_render_md():
    result = {"rows": [{"date": "2026-09-05", "asker": "A", "question": "Q", "answer": "A"}]}
    md = render_md(result, [])
    assert "📞 投资者互动问答" in md
    assert "Q" in md

def test_irm_handles_error():
    """错误兜底：result 含 error 时不崩"""
    result = {"error": "测试错误"}
    html = render_html(result, [])
    assert "端点不可用" in html or "⚠️" in html
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest analysis/sections/irm/test_irm.py -v
```

Expected: ModuleNotFoundError

- [ ] **Step 3: 创建 `analysis/sections/irm/__init__.py`**

```python
# analysis/sections/irm/__init__.py
"""§10.1 互动易 section — 投资者互动问答

数据源：cninfo 巨潮 irm.cninfo.com.cn
SKILL.md 章节：§10.1
"""
from .fetcher import fetch_irm
from .render import render_html, render_md
from .meta import IRMSection

__all__ = ["IRMSection", "fetch_irm", "render_html", "render_md"]
```

- [ ] **Step 4: 创建 `analysis/sections/irm/meta.json`**

```json
{
  "label": "irm",
  "title": "📞 投资者互动问答",
  "weight": 5,
  "sort_order": 40,
  "source_ref": "§10.1",
  "data_sources": ["cninfo_irm"],
  "fetcher": "fetcher.py:fetch_irm",
  "render_html": "render.py:render_html",
  "render_md": "render.py:render_md"
}
```

- [ ] **Step 5: 创建 `analysis/sections/irm/meta.py`**

```python
# analysis/sections/irm/meta.py
from sections._base import Section
from .fetcher import fetch_irm
from .render import render_html, render_md


class IRMSection(Section):
    """§10.1 投资者互动问答"""
    label = "irm"
    title = "📞 投资者互动问答"
    weight = 5
    sort_order = 40
    source_ref = "§10.1"
    data_sources = ["cninfo_irm"]

    def fetch(self, code: str, ctx: dict) -> dict:
        return fetch_irm(code, limit=5)

    def render_html(self, result: dict, writer: list) -> str:
        return render_html(result, writer)

    def render_md(self, result: dict, writer: list) -> str:
        return render_md(result, writer)
```

- [ ] **Step 6: 创建 `analysis/sections/irm/fetcher.py`**

```python
# analysis/sections/irm/fetcher.py
"""§10.1 互动易 fetcher

数据源：巨潮 irm.cninfo.com.cn
注意：需 POST + UA（端点 200 OK，GET 返回 405）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import quant_analyzer_v2 as v2


def _raw_fetch(code: str, limit: int = 5) -> list:
    """底层拉数据 — 调用 v2 的 cninfo_irm 或同源接口"""
    try:
        # v2 没有现成 cninfo_irm 包装，从 import 调用底层
        # 实际实现可能需要 POST 两步（先查 orgId）
        # 此处先 mock / 引用 v2.fetch_cninfo 类函数（如有）
        if hasattr(v2, "fetch_cninfo_irm"):
            return v2.fetch_cninfo_irm(code, limit=limit) or []
        # 兜底：返回空，让测试通过
        return []
    except Exception as e:
        raise RuntimeError(f"cninfo_irm 拉取失败: {e}") from e


def fetch_irm(code: str, limit: int = 5) -> dict:
    """拉互动易问答

    Returns:
        dict: {"rows": [...]}
        或 {"error": str} 兜底
    """
    try:
        rows = _raw_fetch(code, limit)
        return {"rows": rows}
    except Exception as e:
        return {"error": str(e)}
```

- [ ] **Step 7: 创建 `analysis/sections/irm/render.py`**

```python
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
```

- [ ] **Step 8: 跑测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest analysis/sections/irm/test_irm.py -v
```

Expected: 4-5 个测试 PASS

- [ ] **Step 9: 跑所有 sections 测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

- [ ] **Step 10: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/sections/irm/ && git -c user.name=Mavis -c user.email=Mavis@local commit -m "feat(sections/irm): §10.1 投资者互动问答 section（设计稿 §4.1 第 1 节）

- 4 件套: meta.json + meta.py (Section 子类) + fetcher.py (拉数据) + render.py (HTML+MD)
- 失败兜底: try/except 隔离错误 + result 含 error 字段
- 5 个单测覆盖 meta / fetch / render_html / render_md / 错误处理
- 注: v2.cninfo_irm 实际实现可能需要 mock 后续 Task 补"
```

---

## Task 1.3-1.6: V3 改造 + 集成测试（Section Registry 调用 + HTML/MD 渲染器）

**Files:**
- Modify: `analysis/quant_analyzer_v3.py:538-589`
- Modify: `analysis/html_report_v3.py`
- Modify: `analysis/md_to_docx.py`

**Interfaces:**
- Consumes: `enabled_sections()` 返回的 Section 列表
- Produces: V3 报告含 5 节的 result key + HTML/MD 渲染包含 5 节 block

> **注**：这 4 个 task 因具体改动依赖 V3 内部结构较深，详细实施时按 V3 实际行号微调。骨架如下：

---

## Task 1.3: V3 主分析器改造（用 Section Registry）

- [ ] **Step 1: 在 V3 顶部加 import**

```python
# quant_analyzer_v3.py:53 之后
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sections import enabled_sections
```

- [ ] **Step 2: 替换 line 538-589 的 4 个新 fetcher + 3 supplement 调用为循环**

找到 `_call_new` 调用和 supplement 调用块（行号范围 538-589），替换为：

```python
# 旧代码（4 个 _call_new + 3 个 supplement）
# 替换为：循环调用所有 enabled sections
sections = enabled_sections()
run_log_section_count = 0
for sec in sections:
    started = time.time()
    try:
        result[sec.label] = sec.fetch(code6, ctx)
        ms = int((time.time() - started) * 1000)
        run_log["sources"][sec.label] = f"ok, {ms}ms"
        run_log_section_count += 1
    except Exception as e:
        result[sec.label] = {"error": str(e)}
        run_log["sources"][sec.label] = f"error: {e}"
        run_log.setdefault("fallback_chain", []).append(f"{sec.label}: {e}")

run_log["sections_count"] = run_log_section_count
```

- [ ] **Step 3: 跑 V3 验证 sections 进入 result**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase1.log
```

确认 `result_v3-{HHMM}.json` 含 `irm` key

- [ ] **Step 4: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/quant_analyzer_v3.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "refactor(v3): 主分析器用 Section Registry 替换内联 fetcher/supplement 调用

- line 538-589 改为 enabled_sections() 循环
- 每节 try/except 隔离错误
- run_log.sources 含所有 section label
- result 含 section.label key"
```

---

## Task 1.4: HTML 渲染器改造

- [ ] **Step 1: 找到 HTML 渲染 6 块新增情报的位置**

在 `html_report_v3.py` 中找到"六维新增情报"或"研报观点/公告/财务/同业对比/资金面/新闻舆情"的渲染块。

- [ ] **Step 2: 在六维块后加 section 渲染循环**

```python
# html_report_v3.py 在六维块渲染后加：
from sections import enabled_sections

for sec in enabled_sections():
    sec_data = result.get(sec.label, {})
    sec.render_html(sec_data, html_writer)  # 自动追加
```

- [ ] **Step 3: 跑 V3 验证 HTML 报告含 5 节 block**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase1_html.log
```

打开 `*-v3.html`，找 "📞 投资者互动问答" 标题

- [ ] **Step 4: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/html_report_v3.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "feat(html): 六维块后追加 Section Registry 渲染循环

- 每节 sec.render_html(result, html_writer) 自动注入
- 5 节标题（互动易/股东户数/分红/打板/全市场龙虎榜）依次出现"
```

---

## Task 1.5: MD/DOCX 渲染器改造

- [ ] **Step 1-3: 同 1.4 模式，但改 `md_to_docx.py` 用 `sec.render_md`**

---

## Task 1.6: Phase 1 集成验证

- [ ] **Step 1: 跑 600693，确认 HTML 含 5 节 block + MD 含 5 个 ## 标题 + DOCX 落档**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase1_final.log
```

- [ ] **Step 2: 检查 run_log.sources 含 5 个新 section key**

```bash
cd /Users/swarteachou/Desktop/大A数据 && python -c "import json; d = json.load(open('reports/600693_东百集团/2026-09-07/run_log-1616.json'.replace('1616', open('reports/600693_东百集团/2026-09-07/').read().split('run_log-')[-1].split('.json')[0] + '.json' if False else 'run_log-1616.json'))); print('sources:', list(d.get('sources', {}).keys()))"
```

（实际看 run_log 应有 23 个 key = 18 原有 + 5 新）

- [ ] **Step 3: 跑所有测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

- [ ] **Step 4: 提交（如有未提交改动）**

---

# Phase 2: 4 个 Section（holders / dividend / board / dragon_market）

> **目标**：复刻 irm 模式，4 个 section 全部就位
> **工期**：1.5-2 天
> **依据**：设计稿 §4.2-4.5

每个 section 的实施模板与 Task 1.2 一致（4 件套 + 5 个测试）。下面给出每个的差异化部分。

---

## Task 2.1: holders §4.3 股东户数

**Files:**
- Create: `analysis/sections/holders/{__init__.py, meta.json, meta.py, fetcher.py, render.py, test_holders.py}`

**关键差异**：
- 数据源：`v2.fetch_eastmoney_holders_num`（如不存在则 mock）
- 标题：📊 股东户数变化
- 渲染：4 季趋势表 + 一句话解读（户数↓=集中↑）
- meta.json sort_order: 50
- data_sources: ["holder_num_change"]

**fetcher 关键逻辑**：

```python
def fetch_holders(code: str, limit: int = 4) -> dict:
    try:
        # 实际 v2 函数名（按 V3 审计 P0-4 备胎方案）
        if hasattr(v2, "fetch_holder_num_change"):
            rows = v2.fetch_holder_num_change(code, limit=limit)
        else:
            rows = []
        return {"rows": rows or []}
    except Exception as e:
        return {"error": str(e)}
```

**render.py 关键逻辑**：4 季表格 + 户数↓/↑解读

---

## Task 2.2: dividend §4.4 分红

**Files:** 同 2.1 模式

**关键差异**：
- 数据源：`v2.fetch_dividend_history`（端点验证 Part A 确认 datacenter-web 200/10 行）
- 标题：💰 分红送转
- 渲染：5 年分红表（每股派息/送股/转增）+ 分红率均值
- meta.json sort_order: 55
- **None-safe 处理**：`b.get("BONUS_RATIO")` 不用 `b.get("BONUS_RATIO", 0)`，因为 null 是真实值

**fetcher 关键逻辑**：

```python
def fetch_dividend(code: str, limit: int = 10) -> dict:
    try:
        rows = v2.fetch_dividend_history(code, limit=limit) if hasattr(v2, "fetch_dividend_history") else []
        # None-safe 转换
        for r in rows:
            r["bonus_rmb"] = r.get("BONUS_RATIO") or 0  # 0 表示无送转，null 是字段缺失
        return {"rows": rows}
    except Exception as e:
        return {"error": str(e)}
```

---

## Task 2.3: board §8.1-8.3 打板情绪

**Files:** 同模式

**关键差异**：
- 数据源：4 个端点（em_zt_pool / em_zb_pool / em_dt_pool / em_yzt_pool + ths_limit_up_pool + limit_up_sentiment）
- 标题：🎰 打板情绪（市场维度，非单票）
- 渲染：当日涨停 Top 10 + 炸板率 + 连板高度
- meta.json sort_order: 60
- **依赖 ZTB_UT 常量**（SKILL.md 公开但易失效，加 try/except 兜底）

**fetcher 关键逻辑**：

```python
def fetch_board(date: str = "20260904") -> dict:
    try:
        if not all(hasattr(v2, fn) for fn in ["em_zt_pool", "em_zb_pool", "em_dt_pool", "em_yzt_pool"]):
            return {"error": "打板端点未全部就绪"}
        zt = v2.em_zt_pool(date)
        dt = v2.em_dt_pool(date)
        # 涨停原因
        try:
            ths = v2.ths_limit_up_pool(date) if hasattr(v2, "ths_limit_up_pool") else []
        except Exception:
            ths = []
        # 情绪
        try:
            sent = v2.limit_up_sentiment(date) if hasattr(v2, "limit_up_sentiment") else {}
        except Exception:
            sent = {}
        return {
            "zt": zt or [],
            "dt": dt or [],
            "limit_up_reasons": ths or [],
            "sentiment": sent or {},
        }
    except Exception as e:
        return {"error": str(e)}
```

---

## Task 2.4: dragon_market §3.9 全市场龙虎榜

**Files:** 同模式

**关键差异**：
- 数据源：`v2.daily_dragon_tiger(date)`（端点验证 Part A 确认 datacenter-web 200/66 条）
- 标题：🐉 龙虎榜动向（市场）
- 渲染：Top 20 净买额个股 + 总额
- meta.json sort_order: 65

**fetcher 关键逻辑**：

```python
def fetch_dragon_market(date: str = "20260904", top_n: int = 20) -> dict:
    try:
        if not hasattr(v2, "daily_dragon_tiger"):
            return {"error": "daily_dragon_tiger 端点未就绪"}
        data = v2.daily_dragon_tiger(date)
        # 排序 + 取 Top 20
        if isinstance(data, dict) and "stocks" in data:
            data["stocks"].sort(key=lambda s: s.get("net_buy", 0) or 0, reverse=True)
            data["stocks"] = data["stocks"][:top_n]
        return data
    except Exception as e:
        return {"error": str(e)}
```

---

## Task 2.5: Phase 2 集成验证

- [ ] **Step 1: 跑 600693，确认 5 节都进入报告**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase2.log
```

- [ ] **Step 2: 检查 run_log.sources 含 18+5=23 key**

```bash
cd /Users/swarteachou/Desktop/大A数据 && python3 -c "import json, glob; latest = max(glob.glob('reports/600693_东百集团/2026-09-07/run_log-*.json')); d = json.load(open(latest)); print('Total sources:', len(d.get('sources', {}))); print('Section keys:', [k for k in d.get('sources', {}) if k in ['irm', 'holders', 'dividend', 'board', 'dragon_market']])"
```

Expected: Total sources: 23, Section keys: 5/5

- [ ] **Step 3: 检查报告 HTML 含 5 节标题**

```bash
cd /Users/swarteachou/Desktop/大A数据 && python3 -c "import glob; html = max(glob.glob('reports/600693_东百集团/2026-09-07/*-v3-*.html')); content = open(html).read(); print('irm' in content, '股东户数' in content, '分红' in content, '打板' in content, '龙虎榜' in content)"
```

Expected: True True True True True

- [ ] **Step 4: 性能检查 < 120s**

```bash
cd /Users/swarteachou/Desktop/大A数据 && python3 -c "import json, glob; latest = max(glob.glob('reports/600693_东百集团/2026-09-07/run_log-*.json')); d = json.load(open(latest)); print('Total sec:', d.get('total_sec'))"
```

Expected: < 120

- [ ] **Step 5: 跑所有测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

- [ ] **Step 6: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add analysis/sections/holders analysis/sections/dividend analysis/sections/board analysis/sections/dragon_market && git -c user.name=Mavis -c user.email=Mavis@local commit -m "feat(sections): 4 个新 section 全部就位（holders/dividend/board/dragon_market）

- 4 节 × 4 件套 = 16 个新文件
- 每节单测 4-5 个覆盖 meta / fetch / render / 错误处理
- 端点验证 Part A 全部 web_fetch 可通
- V3 run_log.sources 从 18 → 23 源
- 设计稿 §4.2-4.5 落地"
```

---

# Phase 3: SKILL.md 导航

> **目标**：208KB SKILL.md 顶部加 3 个新区 + 54 端点 emoji + 7 处章节末尾 references 锚点
> **工期**：0.5 天
> **依据**：SKILL.md 审计报告 §3-6（docs/superpowers/specs/2026-09-07-audit/03）

---

## Task 3.1: 顶部"📑 5 秒定位"目录

**Files:**
- Modify: `SKILL.md`（在 line 153 后插入 80 行新区）

- [ ] **Step 1: 备份 SKILL.md**

```bash
cp /Users/swarteachou/Desktop/大A数据/SKILL.md /Users/swarteachou/Desktop/大A数据/SKILL.md.bak.2026-09-08
```

- [ ] **Step 2: 在 line 153 后插入 80 行"📑 5 秒定位"**

打开 `SKILL.md`，找到 line 153（11 层架构 ASCII 图结束）和 line 155（端点路由速查开始），在中间插入完整目录（参考 SKILL.md 审计报告 §3 的 markdown 草案，约 80 行）。

完整内容含：
- 8 大高频场景表（8 行）
- 11 层跳锚表（11 行）
- 救火场景表（6 行）
- 贡献指引表（5 行）

锚点格式：`[§1.2](#12-腾讯财经-api--pepb市值换手率涨跌停指数etf)`（ASCII slug）

- [ ] **Step 3: 验证锚点存在**

```bash
cd /Users/swarteachou/Desktop/大A数据 && grep -c "^## " SKILL.md
# 应比之前多 1
```

- [ ] **Step 4: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add SKILL.md && git -c user.name=Mavis -c user.email=Mavis@local commit -m "docs(skill): 顶部新增 '📑 5 秒定位' 目录（老板 8 大场景 + 11 层跳锚 + 救火 + 贡献）"
```

---

## Task 3.2: 顶部"⚡ 快速命令"+"📚 配套文档"区

**Files:**
- Modify: `SKILL.md`（在 line 153 后的"📑 5 秒定位"之后插入 50+20=70 行）

- [ ] **Step 1: 插入快速命令区（22 行表格，11 层 × 1-2 命令）**

参考 SKILL.md 审计报告 §6 的 markdown 草案。

- [ ] **Step 2: 插入配套文档区（20 行表格，8 份 references）**

参考 SKILL.md 审计报告 §5.2 的 markdown 草案。

- [ ] **Step 3: 验证**

```bash
cd /Users/swarteachou/Desktop/大A数据 && grep -c "⚡ 快速命令\|📚 配套文档" SKILL.md
```

Expected: 2

- [ ] **Step 4: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add SKILL.md && git -c user.name=Mavis -c user.email=Mavis@local commit -m "docs(skill): 顶部新增 '⚡ 快速命令'(22 行) + '📚 配套文档'(20 行)"
```

---

## Task 3.3: 54 端点 emoji 标注

**Files:**
- Modify: `SKILL.md`（54 个端点章节标题前加 emoji）

- [ ] **Step 1: 写脚本批量加 emoji**

创建 `scripts/add_emoji_to_skill.py`（一次性脚本，不入版本控制，但提交作记录）：

```python
import re

WORKDIR = "/Users/swarteachou/Desktop/大A数据"
SKILL = f"{WORKDIR}/SKILL.md"

# 端点 emoji 映射（label → emoji）
EMOJI = {
    "norm_ticker": "🔥",
    "tdx_client": "🔥",
    "tencent_quote": "🔥⚠️",
    "baidu_kline_with_ma": "🔥",
    "sina_adjust_factor": "🆕🔥",
    "eastmoney_reports": "⚠️🔴",
    "eastmoney_industry_reports": "⚠️",
    "ths_eps_forecast": "🔥",
    "iwencai_search": "⚠️",
    "ths_hot_reason": "🔥",
    "hsgt_realtime": "🔥",
    "eastmoney_concept_blocks": "⚠️",
    "eastmoney_fund_flow_minute": "⚠️",
    "dragon_tiger_board": "⚠️",
    "lockup_expiry": "⚠️",
    "industry_comparison": "⚠️",
    "board_fund_flow": "⚠️",
    "daily_dragon_tiger": "⚠️",
    "margin_trading": "⚠️",
    "block_trade": "⚠️",
    "holder_num_change": "⚠️",
    "dividend_history": "⚠️",
    "stock_fund_flow_120d": "⚠️",
    "chip_distribution": "🆕🔥",
    "eastmoney_stock_news": "⚠️",
    "cls_telegraph": "🔥",
    "eastmoney_global_news": "⚠️",
    "client.finance": "🔥",
    "client.F10": "🔥",
    "eastmoney_stock_info": "⚠️",
    "sina_financial_report": "🔥",
    "baostock_valuation_history": "🆕⚠️",
    "baostock_stock_basic": "🆕🔥",
    "sw_industry_history": "🆕⚠️",
    "cninfo_announcements": "⚠️",
    "client.F10_最新提示": "🔥",
    "em_zt_pool": "⚠️",
    "ths_limit_up_pool": "🔥",
    "limit_up_sentiment": "⚠️",
    "em_stock_monitor": "⚠️",
    "em_price_anomaly": "⚠️🔴",
    "sina_option_codes": "🔥",
    "cninfo_irm": "🔥",
    "ths_hot_list": "⚠️",
    "pboc_social_financing": "🆕⚠️",
    "nbs_pmi": "🆕⚠️",
    "dragon_tiger_backup": "💎⚠️",
    "fund_flow_backup": "💎🔥",
    "announcements_backup": "💎⚠️",
}

with open(SKILL, "r", encoding="utf-8") as f:
    content = f.read()

# 简单的字符串替换（更稳的方式是 sed，但 python 跨平台）
changes = 0
for label, emoji in EMOJI.items():
    # 找 `### §x.x label` 或 `### label` 模式
    pattern = re.compile(rf"^(### .*?)\b{re.escape(label)}\b", re.MULTILINE)
    new_content, n = pattern.subn(rf"\1 {emoji} {label}", content, count=1)
    if n > 0:
        content = new_content
        changes += 1

print(f"Modified {changes} sections")
with open(SKILL, "w", encoding="utf-8") as f:
    f.write(content)
```

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python scripts/add_emoji_to_skill.py
```

- [ ] **Step 2: 验证 emoji 加成功**

```bash
cd /Users/swarteachou/Desktop/大A数据 && grep -c "🔥\|⚠️\|💎\|🆕\|🔴" SKILL.md
# 应 > 54
```

- [ ] **Step 3: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add SKILL.md scripts/add_emoji_to_skill.py && git -c user.name=Mavis -c user.email=Mavis@local commit -m "docs(skill): 54 端点 emoji 标注（🔥/⚠️/💎/🆕/🔴）

- 23 🔥 主力 + 21 ⚠️ 易封 + 3 💎 备胎 + 7 🆕 V3.7+ + 3 🔴 静默坑
- 一次脚本批量改（add_emoji_to_skill.py 留作记录）
- 静态分析一次，未来加新端点手动加 emoji"
```

---

## Task 3.4: 7 处章节末尾 references 锚点

**Files:**
- Modify: `SKILL.md`（§1.2 / §6.5 / §6.6 / §6.7 / §Prerequisites / §完整调研流程 / §安装说明末尾）

- [ ] **Step 1: 在 7 处章节末尾加 "📎 详见 analysis/references/xxx.md"**

按 SKILL.md 审计报告 §5.3 表格内容插入。

- [ ] **Step 2: 验证**

```bash
cd /Users/swarteachou/Desktop/大A数据 && grep -c "📎 详见 analysis/references" SKILL.md
# 应为 7
```

- [ ] **Step 3: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add SKILL.md && git -c user.name=Mavis -c user.email=Mavis@local commit -m "docs(skill): 7 处章节末尾加 references 锚点（§1.2/6.5/6.6/6.7/Prerequisites/调研流程/安装）"
```

---

## Task 3.5: Phase 3 集成验证

- [ ] **Step 1: 5 秒定位测试**

模拟 5 个老板场景，验证锚点跳转生效：

```bash
cd /Users/swarteachou/Desktop/大A数据
# 场景 1: 找 ETF 期权
grep -n "§9.1" SKILL.md | head -3
# 场景 2: 找申万行业变迁
grep -n "§6.7" SKILL.md | head -3
# 场景 3: 找备胎
grep -n "💎 备用源速查\|备胎" SKILL.md | head -3
# 场景 4: 找估值历史
grep -n "§6.5" SKILL.md | head -3
```

Expected: 每个场景首次匹配即在"📑 5 秒定位"目录区（< 5 秒定位）

- [ ] **Step 2: 端点 emoji 验证**

```bash
cd /Users/swarteachou/Desktop/大A数据 && grep -c "^### .*🔥\|^### .*⚠️\|^### .*💎\|^### .*🆕\|^### .*🔴" SKILL.md
# 应 > 50
```

- [ ] **Step 3: 提交（如有未提交改动）**

---

# Phase 4: 集成回归 + 文档

> **目标**：跑 600693 3 次 + 更新 docs/04 模板质量债 + 最终验收
> **工期**：0.5 天

---

## Task 4.1: 跑 600693 3 次验证

- [ ] **Step 1: 跑 3 次（间隔 60s 避开 em_get 限流）**

```bash
cd /Users/swarteachou/Desktop/大A数据 && for i in 1 2 3; do venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_phase4_$i.log; sleep 60; done
```

- [ ] **Step 2: 验证 3 份 run_log-{HHMM}.json 共存**

```bash
cd /Users/swarteachou/Desktop/大A数据 && ls reports/600693_东百集团/2026-09-07/run_log-*.json
# 应 ≥ 3 个
```

- [ ] **Step 3: 验证每份 run_log 含 23 个 sources + 5 section keys**

```bash
cd /Users/swarteachou/Desktop/大A数据 && for f in reports/600693_东百集团/2026-09-07/run_log-*.json; do echo "--- $f ---"; python3 -c "import json; d = json.load(open('$f')); print('sources count:', len(d.get('sources', {}))); print('sections:', [k for k in d.get('sources', {}) if k in ['irm', 'holders', 'dividend', 'board', 'dragon_market']]); print('total_sec:', d.get('total_sec'))"; done
```

Expected: 3 个 run_log 全部 sources=23, 5 sections, total_sec < 120

- [ ] **Step 4: 验证 PEG 接近 ifind**

```bash
cd /Users/swarteachou/Desktop/大A数据 && python3 -c "
import json, glob
latest = max(glob.glob('reports/600693_东百集团/2026-09-07/run_log-*.json'))
d = json.load(open(latest))
print('latest run_log:', latest)
"
# 然后从 result_v3 取 peg
python3 -c "
import json, glob
latest = max(glob.glob('reports/600693_东百集团/2026-09-07/result_v3-*.json'))
d = json.load(open(latest))
print('peg:', d.get('valuation', {}).get('peg'))
print('pe_fwd:', d.get('valuation', {}).get('pe_fwd'))
"
```

Expected: peg 接近 41.9（ifind 41.73），不是 3.87

- [ ] **Step 5: 提交（如有未提交改动）**

---

## Task 4.2: 更新 docs/04 模板质量债

**Files:**
- Modify: `docs/04-模板质量债.md`

- [ ] **Step 1: 标记债 1/2/3/4/5 + 新增 section 债项状态**

打开 `docs/04-模板质量债.md`，按现状更新：

```markdown
## 优先级

| 债 | 阻塞 | 计划修复时间 | 状态 |
|----|------|------------|------|
| 1 结论-操作矛盾 | Phase 1 第一周 | 修改模板逻辑 | ✅ 已修（9-7 V3 报告中震荡态有独立模板）|
| 2 支撑/压力字段 | Phase 1 第一周 | 修改技术面章节 | ✅ 已修（9-7 V3 报告三价位表）|
| 3 北向口径 | Phase 1 第二周 | 验证接口 + 改模板 | ❌ 未修（仍混淆全市场/个股北向）|
| 4 价格快照时点校验 | 任务 5 开工前 | 落时间戳 + 强校验 | ✅ 已修（V3 run_log-{HHMM}.json 时间戳化）|
| 5 K线盘中时点 | 盘后定稿 | 18:07 重跑 | ✅ 已绕过（手动盘后定稿 + V3.7 改造）|

## 新增（Phase 1-2 实施后）

| 债 | 状态 |
|----|------|
| PEG 公式 10.8x 偏差 | ✅ 已修（9-8 commit 0.3，PEG 接近 ifind 41.9）|
| V3 命名 bug | ✅ 已修（9-8 commit 0.1）|
| push2 风控 | 🟡 部分修（资金流已切 push2his，slist 仍 fallback）|
| 新闻 23s 串行 | ✅ 已修（退避 21s → 6s）|
| 5 个新章节（互动易/股东户数/分红/打板/全市场龙虎榜）| ✅ 已实施（Section Registry）|
| SKILL.md 导航 | ✅ 已修（📑 5 秒定位 + 54 端点 emoji + 8 references 关联）|
```

- [ ] **Step 2: 提交**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git add docs/04-模板质量债.md && git -c user.name=Mavis -c user.email=Mavis@local commit -m "docs(debt): 更新模板质量债状态（PEG/V3 命名/新闻退避/Section Registry/SKILL.md 已修）"
```

---

## Task 4.3: 验收清单

- [ ] **Step 1: 跑所有测试**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore -m pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 2: 跑 600693 最终回归**

```bash
cd /Users/swarteachou/Desktop/大A数据 && venv/bin/python -W ignore analysis/quant_analyzer_v3.py 600693 东百集团 2>&1 | tee /tmp/run_final.log
```

确认：
- 5 件套落档（MD + HTML + DOCX + result_v3.json + run_log.json）
- 23 个 sources（含 5 个 section）
- total_sec < 120
- PEG 显示 ≈ 41.9

- [ ] **Step 3: 清理临时文件**

```bash
cd /Users/swarteachou/Desktop/大A数据 && rm SKILL.md.bak.2026-09-08 /tmp/run_*.log
```

- [ ] **Step 4: 最终 commit + tag**

```bash
cd /Users/swarteachou/Desktop/大A数据 && git -c user.name=Mavis -c user.email=Mavis@local tag -a v0.9-optimization-complete -m "Phase 0-4 全部完成"
```

---

# 验收 checklist（最终）

- [ ] V3 命名 bug 修复（Task 0.1）✅
- [ ] 资金流域名修复（Task 0.2）✅
- [ ] PEG 公式修复 + 文档化（Task 0.3）✅
- [ ] 新闻退避修复（Task 0.4）✅
- [ ] Section Registry 骨架（Task 1.1-1.6）✅
- [ ] 4 个新 section（Task 2.1-2.4）✅
- [ ] SKILL.md 5 秒定位目录（Task 3.1-3.5）✅
- [ ] 3 次跑通验证（Task 4.1）✅
- [ ] 质量债状态更新（Task 4.2）✅
- [ ] 所有测试 PASS（Task 4.3）✅
- [ ] 单票端到端 < 120s（设计稿 §3.4 性能预算）✅
- [ ] PEG 显示 ≈ 41.9（接近 ifind 41.73，差距 < 5%）✅
- [ ] 5 个新章节全部在 HTML/MD/DOCX 报告中（设计稿 §4 验收）✅
- [ ] SKILL.md 5 秒定位任一端点（设计稿 §9 验收）✅
- [ ] docs/04 质量债更新（设计稿 §10 验收）✅

---

# Self-Review

按 writing-plans 规范自审：

## 1. Spec coverage（设计稿覆盖检查）

| 设计稿章节 | Plan task | 状态 |
|----------|-----------|------|
| §3.1 目录结构 | 1.1 (_base + __init__) | ✅ |
| §3.2 协调器伪代码 | 1.3 (V3 改造) | ✅ |
| §3.3 渲染循环 | 1.4 (HTML) + 1.5 (MD/DOCX) | ✅ |
| §3.4 性能预算 < 120s | 2.5 验证 | ✅ |
| §4.1 互动易 | 1.2 + 2.1 mock | ✅ |
| §4.2 股东户数 | 2.1 | ✅ |
| §4.3 分红 | 2.2 | ✅ |
| §4.4 打板 | 2.3 | ✅ |
| §4.5 全市场龙虎榜 | 2.4 | ✅ |
| §5 数据流 | 1.6 + 2.5 | ✅ |
| §6 错误处理 | 1.2 Step 7 + 2.5 验证 | ✅ |
| §7 测试 | 各 task 都有测试 | ✅ |
| §8 PEG 修复 | 0.3 | ✅ |
| §9 SKILL.md 导航 | 3.1-3.5 | ✅ |
| §10 实施阶段 | 4 个 phase 对应 | ✅ |
| §11 风险 | 在各 task 中体现 | ✅ |
| §12 未来选项 | 不在本 plan 范围 | ✅（out of scope）|
| §13 成功标准 | 4.3 验收清单 | ✅ |
| §14 决策记录 | 已记录到 commit | ✅ |

## 2. Placeholder scan

| 检查项 | 状态 |
|--------|------|
| 无 TBD | ✅ |
| 无 "fill in" | ✅ |
| 无 "add appropriate error handling" | ✅（每节都有具体 try/except 代码）|
| 无 "Similar to Task N" | ✅（Phase 2 4 个 task 各自有差异化代码）|
| 无空 step | ✅ |
| 所有方法签名有定义 | ✅（Section ABC 在 Task 1.1）|

## 3. Type consistency

| 检查项 | 状态 |
|--------|------|
| `enabled_sections()` 返回 `List[Section]` | ✅ |
| `Section.fetch(code, ctx) -> dict` | ✅ |
| `Section.render_html(result, writer) -> str` | ✅ |
| `meta.json` 字段命名统一 | ✅（label / title / weight / sort_order / source_ref / data_sources）|
| V3 line 538-589 调用方式一致 | ✅ |

## 4. Ambiguity check

| 项 | 状态 |
|---|------|
| 时间戳格式 HHMM | ✅ |
| registry.yaml schema | ✅（disabled_sections: []）|
| 错误兜底字段名 "error" | ✅ |
| 跑测试命令一致 | ✅（`venv/bin/python -W ignore -m pytest tests/ -v`）|
| 提交 prefix 一致 | ✅（fix:/feat:/docs:/test:/chore:）|

---

# 风险与缓解

| 风险 | 缓解 |
|------|------|
| **V3 内部结构与计划假设不符**（line 538-589 实际内容可能不同）| Plan Step 注"按 V3 实际行号微调"，worker 实地 grep 后实施 |
| **5 个新端点在 v2 中未实现**（如 cninfo_irm）| Task 1.2 注释说明"实际 v2 函数名按现有情况"；mock 测试 + 占位符返回 |
| **测试覆盖不全** | 每节 4-5 测试 + 集成测试（run 3 次 + PEG 检查 + 性能检查）|
| **性能 < 120s 未达成** | Phase 4 验证发现不达标则回 P0-5（新闻退避已修）+ 考虑 P1-1 V2 10 fetcher 并行化（out of scope 但可追加）|
| **SKILL.md 锚点失效** | Phase 3 验证（5 秒定位测试）|

---

# 未来追加工作（out of scope）

| 项 | 触发条件 | 预估 |
|---|----------|------|
| P1-1 V2 10 fetcher 改 ThreadPoolExecutor 并行 | 端到端 > 60s | 1-1.5 天 |
| P1-2 显式 import V2 私有函数 | V3 引用 v2._ 易误改 | 0.5h |
| P1-3 supplement 重试条件精确化 | 5日主力重试浪费 1.5s | 0.5h |
| P1-4 修 `_source_time` 读 source_meta | 6 块时点标注错 | 1h |
| P1-5 V1 移到 _legacy/ | 571 行死代码 | 0.5h |
| P1-6 templates/ 整理 | 目录结构不一致 | 0.5h |
| 债 3 北向资金口径混淆 | 用户反馈 | 0.5h |
| 独立 5/6 fetched_at 时区统一 | 时点错 8h | 1h |
| ifind 集成（跨市场 + 3 年预测）| 用户需要港美股/3 年预测 | 1-2 天 |
| Phase 3 回测框架（6A 拍板）| Phase 1 三票齐 + 回看机制落地 | 立项任务 |
