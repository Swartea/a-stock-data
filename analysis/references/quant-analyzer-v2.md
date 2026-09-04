# quant_analyzer_v2.py — 10 因子量化打分框架

本地脚本：`~/.hermes/skills/finance/a-stock-data/quant_analyzer_v2.py`
（V1 `quant_analyzer.py` 保留不动；V2 与之并存）

## 何时调用

用户说以下任何一种时：
- "跑一下这只票的量化打分"
- "001696 估值分析"
- "对比这几只票"
- "出 Markdown 报告"
- 任何"多因子打分/量化分析"请求

直接命令：
```bash
~/.hermes/skills/finance/a-stock-data/./run_in_venv.sh \
  ~/.hermes/skills/finance/a-stock-data/quant_analyzer_v2.py \
  001696 宗申动力
```

## 10 因子 / 100 分 权重

| 因子 | 满分 | 数据来源 | 核心字段 |
|------|------|----------|----------|
| 趋势 | 12 | 腾讯实时 | 涨跌% + 低开高走 |
| 估值 | 15 | 腾讯实时 + 同花顺一致预期 | PE-TTM / PB / PE消化年数 / PEG |
| **估值分位** | 8 | baostock 估值历史 | PE/PB 在过去 3 年的分位 |
| 资金 | 15 | 东财 push2 | 当日分钟级主力/大单 |
| 动量 | 8 | 腾讯实时 | 换手/量比/振幅 |
| 情绪 | 8 | 东财 slist + 同花顺北向 | 板块热度 + 北向累计 |
| 风险 | 10 | 腾讯 + 东财解禁 | 市值/PE/解禁/股价 |
| **筹码** | 8 | mootdx K 线 + 本地算法 | 获利比例 + 集中度 (V3.7 mock) |
| **申万稳定** | 6 | sw_industry_history | 行业变迁次数 (V3.7 mock) |
| 龙虎榜 | 10 | 东财 datacenter-web | 近 30 日上榜次数 + 净买入 |

加粗的两个是 V3.7 新增，但当前 V2 mock（基础分 +0/-1），需要后续接入 K 线 + sw_industry_history。

## 输出

### 控制台
- 综合评分 + 5 档建议（强烈看多/看多/中性偏多/中性偏空/看空/强烈看空）
- 10 因子分项
- 加分/扣分明细（每条 1-3 行可解释）

### Markdown
写到 `~/Documents/a-stock-reports/YYYY-MM-DD/CODE-NAME-HHMM.md`
包含 9 个章节：行情 / 一致预期 / 估值分位 / 板块 / 资金流 / 解禁 / 龙虎榜 / 因子明细 / 建议。

## 设计原则

### 1. 错误隔离
**任何单个端点失败不能让整张报告崩**。每个 fetch 包 try/except，返回 `{"error": "..."}` 让上游识别。这点跟 V3.7 SKILL.md 里反复提到的「东财被风控时换手机热点」配套 — 数据可能缺，但不能挂。

### 2. 限流
`em_get()` 走串行限流（间隔 ≥ 1.2s + 随机抖动）+ session 复用。批量 5 票实测 2.5 分钟。**不要并发**调东财，必被封。

### 3. 估值分位 = 严格小于
`(pe_series < cur_pe).sum() / len(pe_series) * 100` — 这是研报圈标准口径。别用 `scipy.stats.percentileofscore`（它默认 ≤）。

### 4. 单票 CLI vs 批量模式分入口
- 有 `sys.argv[1]` → 单票（写 Markdown）
- 没有 → 批量（控制台表格）

单票优先级更高 —— 用户问"001696 怎么样"时跑 5 票批量是浪费。

## 已知 mock 项（待补）

- **筹码分布**：需要先拉日 K（建议 mootdx，比腾讯/百度稳），再调 `chip_distribution(df)`。当前 V2 不接，筹码因子给基础 4 分。
- **申万行业变迁**：需要下载 `sw_industry_history()` 12,893 行 XLSX，session 内缓存。当前 V2 mock。
- **ETF 期权**：不在量化打分范围内，但 full_valuation 应支持 ETF 代码（当前 `get_prefix` 已经处理 `5x` ETF → `sh`）。
- **ST 退市股**：腾讯实时对部分 ST 股仍返回数据，但估值历史会全 NaN。V2 已经处理（返回 `{"error": ...}`），但综合评分会偏低，**这是设计意图**——ST 票就是要被打低分。

## 复用建议

V2 是**数据采集 + 打分模板**，不是**最终结论**。用户拿到 62 分中性偏多 ≠ 真就买。建议在 prompt 里明示："评分是量化模型给的，结合你自己的研究再决策"。

## V1 → V2 迁移

旧 V1 函数签名保留（`fetch_tencent_quote` / `fetch_eastmoney_concept_blocks` 等），但**字段名变了**：
- `quote["pe"]` → `quote["pe_ttm"]`
- `quote["market_cap"]` → `quote["float_mcap"]`
- `quote["pb"]` 不变
- `fund_flow_minute` 返回结构从 `dict{"total_main", "trend"}` 改为 `dict{"klines": [...], "summary": {"total_main_yi", ...}}`

任何依赖 V1 的代码升级前先 grep 这些字段名。

## 跑完一次输出参考（001696 2026-09-03 21:29）

```
综合 62分 🟡 中性偏多
  价格: 17.04  涨跌: +5.19%
  PE(TTM)=33.7  PB=3.52  市值=195亿
  一致预期: 当年EPS=0.77 次年EPS=1.00 覆盖2家
  前向PE=22.1x  PEG=0.74  消化到30x=0.0年
  估值分位(3年): PE 50.5% / PB 45.4%
  → 观望为主，轻仓试探
```

38 秒出结果。批量 5 票 2.5 分钟。