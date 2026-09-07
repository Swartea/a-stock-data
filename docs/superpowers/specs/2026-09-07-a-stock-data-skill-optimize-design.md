# A-Stock-Data 技能优化设计稿

| 项 | 值 |
|---|---|
| 日期 | 2026-09-07 |
| 作者 | Mavis (Mavis) |
| 评审 | 老板 (Swartea) |
| 状态 | DRAFT — 待评审 |
| 关联 | `docs/01-策划方案.md` 拍板 3A 质量标准 + `docs/04-模板质量债.md` 债 3 |

---

## 1. 背景与目标

### 1.1 现状

- **数据层**：a-stock-data V3.7.2，11 层 / 54 端点 / 19 数据源，零鉴权
- **报告层**：V3 报告生成器（`analysis/quant_analyzer_v3.py` + `html_report_v3.py`）
- **当前使用**：V3 报告调用 54 端点中的 18 个，单票 80-105s，五件套落档
- **核心痛点**（来自 `analysis/references/report-design-principles.md:3` 用户原话："现在的报告我看不懂"）：
  - 文档层：208KB SKILL.md 难导航
  - 数据层：18 个端点中 4 个持续失败/降级（slist/fflow/5日主力/同业对比）
  - 报告层：债 3 北向口径未修 + 债 5 K线盘中时点逻辑
  - 债 PEG：V2 算法与 ifind PEG(LYR) 差 10.8x（V2=3.87 vs ifind=41.73）

### 1.2 目标（按老板 Q1+Q2 拍板）

| 维度 | 目标 |
|---|---|
| **覆盖度** | V3 报告新增 5 个章节（互动易/股东户数/分红/打板/全市场龙虎榜）|
| **可靠性** | PEG 公式修复（对账 ifind 差距 < 2x）|
| **可用性** | SKILL.md 导航改善（5min 内定位任一端点）|
| **速度** | 单票端到端 < 120s |

### 1.3 不在本设计范围

- ifind 接入（实测发现跨市场+长预测价值，但本期零成本优先）
- 18 已用端点
- Phase 3 回测框架（6A 拍板但未立项）
- V1/V2 历史代码清理（独立工程债）

---

## 2. 方案选择：Section Registry（推荐方案 B）

### 2.1 三个候选对比

| 方案 | 一句话 | 工期 | 维护性 | 6+ 章节成本 |
|---|---|---|---|---|
| A. 内联扩展 | 5 个 fetcher 直接塞 V3 主文件 | 1-2 天 | 主文件涨到 2000+ 行 | 1 天/节 |
| **B. Section Registry** | 5 节各成模块，统一注册表 | 2.5-3 天 | 主文件稳定在 1700 行 | **1 小时/节** |
| C. 折中（yaml 开关） | A + yaml 配置文件 | 2 天 | 同 A，没真拆 | 1 天/节 |

**选 B 理由**：
1. 5 章节是抽象的"刚好"门槛——4 节 inline 还能忍，5+ 该上注册表
2. 老板"日后使用"目标 → 加第 6 节从 1 天降到 1 小时
3. 未来开源：模块边界清晰，外部贡献者容易上手
4. PEG 修复独立（无论 ABC 都要做）

### 2.2 关键 trade-off

- **多 0.5-1 天前置**（写注册表契约 + ABC 基类 + 第一个示范节）
- **换得长期 TCO 优势**（5+ 节后每次加新节快 10x）

---

## 3. 架构

### 3.1 目录变化

```
analysis/
├── quant_analyzer_v3.py     # 主协调器（保持 ~1700 行）
├── html_report_v3.py        # HTML 渲染器（保持 ~1700 行）
├── md_to_docx.py            # DOCX 渲染器
├── fetch_announcements.py   # 已有
├── fetch_finance_summary.py # 已有
├── fetch_news_em.py         # 已有
├── fetch_research_reports.py# 已有
├── sections/                # ⭐ 新增：章节注册表
│   ├── __init__.py          #   SECTIONS 列表 + enabled_sections()
│   ├── _base.py             #   Section ABC（fetch/render/契约）
│   ├── registry.yaml        #   全局开关（按需启用/禁用）
│   ├── irm/                 #   §10.1 互动易
│   │   ├── fetcher.py
│   │   ├── render.py
│   │   ├── meta.json
│   │   └── test_irm.py
│   ├── holders/             #   §4.3 股东户数
│   │   ├── fetcher.py
│   │   ├── render.py
│   │   ├── meta.json
│   │   └── test_holders.py
│   ├── dividend/            #   §4.4 分红
│   │   └── ...
│   ├── board/               #   §8.1-8.3 打板情绪
│   │   └── ...
│   └── dragon_market/       #   §3.9 全市场龙虎榜
│       └── ...
└── ... (V1/V2 暂保留)
```

### 3.2 注册表契约（`meta.json`）

每节一个 meta.json，定义：
- `label` — 章节中文名（如"互动易"）
- `title` — 报告中显示标题（如"📞 投资者互动问答"）
- `weight` — 显示权重（用于排序）
- `source_ref` — SKILL.md 章节引用（如"§10.1"）
- `fetcher` — `fetcher.py:fetch` 入口
- `render_html` — `render.py:render_html` 入口
- `render_md` — `render.py:render_md` 入口
- `data_sources` — 依赖的 a-stock-data 函数名（用于回溯）

### 3.3 协调器伪代码

```python
# quant_analyzer_v3.py 核心循环（伪代码）
from sections import enabled_sections

for sec in enabled_sections():
    started = time.time()
    try:
        result[sec.label] = sec.fetch(code, ctx)
        run_log["sources"][sec.label] = f"ok, {int((time.time()-started)*1000)}ms"
    except Exception as e:
        result[sec.label] = {"error": str(e)}
        run_log["sources"][sec.label] = f"error: {e}"
```

```python
# html_report_v3.py 渲染循环（伪代码）
for sec in enabled_sections():
    sec.render_html(result, html_writer)  # 自动注入样式+兜底
```

### 3.4 性能预算

| 段 | 当前 | 目标 | 备注 |
|---|---|---|---|
| 18 原有源 | 80-105s | < 90s | 并行化 fetch（ThreadPoolExecutor）+ 错误早返回 |
| 5 新源 | 0 | < 25s | 5 节并行启动 |
| 渲染（HTML/MD/DOCX） | ~200ms | < 5s | 章节容器 + 内嵌模板 |
| **总** | 82-105s | **< 120s** | 留 10s 余量 |

---

## 4. 五个新章节详细规格

### 4.1 互动易（§10.1 cninfo_irm）

- **数据源**：`cninfo_irm(code)` 拉最近 30 天问答
- **报告位置**：六维新增情报后追加，"📞 投资者互动问答"块
- **展示**：Top 5 Q&A（提问 + 公司回复 + 日期 + 来源）
- **价值**：公司直接回应市场传闻/利空，比新闻更权威
- **失败兜底**：`⚠️ 互动易端点不可用: {err}`

### 4.2 股东户数（§4.3 holder_num_change）

- **数据源**：`holder_num_change(code)` 拉最近 4-8 季
- **报告位置**："👥 股东户数变化"块
- **展示**：4 季趋势表 + 一句话解读（户数↓=集中↑，户数↑=分散）
- **价值**：筹码集中度变化，识别主力吸筹/派发
- **失败兜底**：`⚠️ 股东户数端点不可用`

### 4.3 分红（§4.4 dividend_history）

- **数据源**：`dividend_history(code)` 拉最近 5 年
- **报告位置**："💰 分红送转"块
- **展示**：5 年分红表（每股派息/送股/转增）+ 分红率均值
- **价值**：公司回报股东能力 + 财务健康度
- **失败兜底**：`⚠️ 分红端点不可用`

### 4.4 打板情绪（§8.1-8.3）

- **数据源**：`em_zt_pool`/`em_zb_pool`/`em_dt_pool`/`em_yzt_pool` + `ths_limit_up_pool(date)` + `limit_up_sentiment(date)`
- **报告位置**："🎰 打板情绪背景"块（市场维度，不是单票）
- **展示**：当日涨停 Top 10 + 炸板率 + 连板高度
- **价值**：当日市场情绪背景，影响"该不该追高"的判断
- **失败兜底**：`⚠️ 打板数据不可用`

### 4.5 全市场龙虎榜（§3.9 daily_dragon_tiger）

- **数据源**：`daily_dragon_tiger(date)` 拉当日全市场
- **报告位置**："🐉 龙虎榜动向（市场）"块
- **展示**：Top 20 净买额个股 + 总额
- **价值**：主力动向背景 + 题材热度
- **失败兜底**：`⚠️ 龙虎榜全市场端点不可用`

### 4.6 优先级

按"价值/风险"排序：互动易 > 股东户数 > 分红 > 龙虎榜 > 打板情绪
- 互动易/股东户数/分红是**公司维度**，高确定性
- 龙虎榜/打板是**市场维度**，作背景

---

## 5. 数据流

```
[用户] 输入股票代码
   ↓
[quant_analyzer_v3.py] 启动
   ↓
[v2.fetch_*] 18 原有源（部分并行）
   ↓
[sections.*.fetch] 5 新源（5 节并发）
   ↓
[result dict 合并 18+5 = 23 个 key]
   ↓
[html_report_v3.py / md_to_docx.py] 渲染
   ↓
[五件套] MD + HTML + DOCX + result_v3.json + run_log.json
   ↓
[reports/{code}_{name}/{YYYY-MM-DD}/]
```

---

## 6. 错误处理

### 6.1 单节错误隔离（沿用 V3 现有 4-fetcher 模式）

- 每节 `fetcher.py` 包在 try/except
- 失败：`result[sec.label] = {"error": str(e)}` + `run_log["sources"][sec.label] = "error: {e}"`
- 报告展示：`⚠️ {sec.title}端点不可用: {err}`（占位 block，非崩溃）
- **硬约束**：永不编造数据（`report-design-principles.md:63-64`）

### 6.2 全局开关（`registry.yaml`）

```yaml
# 示例
disabled_sections: []    # 空=全启用
# disabled_sections: [board, dragon_market]  # 速度优先时关掉
```

- 老板点票时若想"打板先别拉"，改 yaml 一行
- 跳过 fetch + 跳过 render（报告不显示该 block）

### 6.3 已知脆弱端点提前预案

| 端点 | 风险 | 预案 |
|---|---|---|
| §10.1 互动易 | cninfo 偶发 502 | 失败兜底 + 重试 1 次（间隔 1.5s）|
| §3.9 全市场龙虎榜 | 东财风控 | 同 V3 现有 4 个失败源模式（em_get 限流 + 失败兜底）|
| §8.1-8.3 打板 | 多个端点串联 | 任一失败显示部分数据 + 标注 |

---

## 7. 测试

### 7.1 单节单元测试

每个 section 目录有 `test_<name>.py`：
- Mock `fetch_*` 函数
- 断言 `result` 结构
- 测试错误路径（异常 → error key，pipeline 不崩）
- 测试 render 输出（HTML/MD 含预期 marker）

### 7.2 集成测试（回归）

跑两张历史票作为回归基线：
- **603319 美湖股份**（9-6 V3 五件套）
- **600693 东百集团**（9-7 盘中快照版）

验证：
- [ ] 18 原有源结果与历史一致
- [ ] 5 新源均产生 result key
- [ ] run_log.sources 有 23 个 key
- [ ] run_log.total_sec < 120
- [ ] 五件套全部生成
- [ ] PEG 修复后 600693 PEG 接近 ifind（差距 < 2x）

### 7.3 验收标准（对齐 策划方案 3A 质量标准）

- 结论明确（多空 + 理由 + 风险点）
- 三价位（支撑/压力/止损）— 已有
- 数据全（5 新章节 + 18 原源无缺项）
- 事后可验证（回看 3/5/10 日 — 属 Phase 2 节奏化后启用）

---

## 8. PEG 公式修复（P0 副作用）

### 8.1 Bug

- `quant_analyzer_v2.py` PEG 算 3.87
- ifind PEG(LYR) 算 41.73
- 差 10.8x，对账 600693 同一只票

### 8.2 修法

1. 查 V2 PEG 公式（在 `compute_quant_score_v2` 或 `_make_trading_plan`）
2. 对齐行业标准：`PEG = PE / 年化增长率(%)`
3. 基准用同花顺一致预期次年增速（已是 V3 现源）
4. 回归：600693 PEG 应在 8-12 区间（ifind 41.73 因其基准含长期低增长，与 V2 选的"次年 21%"基准不一致属正常）

### 8.3 交付

- 1 commit
- 0.5 天
- 文档化到 `analysis/references/valuation-formulas.md`

---

## 9. SKILL.md 导航改善（Q1 区域 a）

### 9.1 现状

- 208KB SKILL.md，章节"端点路由速查"埋在 line 155
- 4 个 references 文档在 `analysis/references/` 但 SKILL.md 无关联

### 9.2 改法

1. SKILL.md 顶部新增"📑 5 秒定位"目录
2. 章节锚点 + 跳转到 11 层
3. 关联 `analysis/references/`（report-delivery / pitfalls / design-principles）
4. 关键端点用 emoji 标识（🔥 主力 / ⚠️ 易封 / 💎 备胎）

### 9.3 交付

- 0.5 天
- 文档改动，不动 V3 代码

---

## 10. 实施阶段（高层）

| 阶段 | 内容 | 工期 |
|---|---|---|
| **Phase 1** | PEG 修复 + Section Registry 骨架（`_base.py` + `__init__.py` + 第 1 节 irm 作模板）+ V3 协调器改造 | 1.5 天 |
| **Phase 2** | 剩余 4 节（holders/dividend/board/dragon_market）| 1.5-2 天 |
| **Phase 3** | SKILL.md 导航 + references 关联 | 0.5 天 |
| **Phase 4** | 集成测试 + 回归（603319 + 600693）+ 文档 | 0.5 天 |
| **总计** | | **4-4.5 天** |

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 5 新源串联拉超 120s | fetch 并行化（ThreadPoolExecutor，max_workers=4）|
| 互动易 cninfo 502 | 单节 try/except + 重试 1 次（间隔 1.5s）|
| 注册表契约被绕过（V3 老调用残留）| 灰度：先保留 4 旧 fetcher 走老路径，5 新节走新注册表；下版本统一 |
| PEG 修复发现其他估值债 | 限定本次只修 PEG；其他标记为下次债项 |
| 老板后续提"想加第 6 节" | registry 设计已留口，直接加目录即可 |

---

## 12. 未来选项（Out of Scope）

| 项 | 触发条件 |
|---|---|
| ifind 接入 | 5 内部端点用完仍缺维度 / 跨市场需求出现 / 老板想看 3 年预测 |
| iwencai 接入 | 老板需要自然语言语义搜索（"找 ROE>15% PE<20 的票"）|
| Phase 3 回测框架 | Phase 1 三票齐 + 回看 3/5/10 日机制落地 |
| V4 重构（接口稳定化）| 注册表跑 6+ 节后回头定 abstract interface |
| 自动化 cron（盘后日报）| Phase 2 节奏化时再立 |

---

## 13. 成功标准（可量化）

| 项 | 当前 | 目标 |
|---|---|---|
| V3 报告章节数 | 13 | **18+**（+5 新章节）|
| 端到端耗时 | 82-105s | **< 120s** |
| PEG 对账 | V2=3.87 vs ifind=41.73（差 10.8x）| 差 **< 2x** |
| SKILL.md 定位 | 全文 grep | 5 min 内定位任一端点 |
| 回归一致性 | N/A | 603319/600693 旧报告可重现 |

---

## 14. 决策记录

| # | 决策 | 老板拍板 |
|---|---|---|
| 1 | 优化方向 = a 导航 + c 错误文档 + e 报告/数据完整 | ✅ |
| 2 | "完整信息"= 补 a-stock-data 内部 36 端点（选 B）| ✅ |
| 3 | 成功标准 = 覆盖度优先（5+ 章节，< 120s）| ✅ |
| 4 | 架构 = Section Registry（Approach B）| ✅（授权 Mavis 拍板）|
| 5 | ifind 暂不接入 | ✅（Mavis 推荐）|
| 6 | PEG 修复独立子任务 | ✅ |

---

_下一步：老板评审 → 通过后进入 superpowers:writing-plans 写实施计划_
