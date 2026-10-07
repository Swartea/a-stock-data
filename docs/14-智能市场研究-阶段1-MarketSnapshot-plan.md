# 智能市场研究 阶段 1 · Market Snapshot plan

> 上一线: `docs/11-智能市场研究系统-项目目标与路线图.md`（6b21a85，2026-10-04）确立新产品目标与 5 阶段主线
> 触发: `docs/11:91`「每一阶段先定义用户可完成的研究任务，再拆分数据、接口和界面工作」；阶段 1 至今**无 plan**（docs/ 下只有 `docs/08-*` / `docs/09-*` / `docs/10-*` / `docs/11` 四条线）
> 范围: 只立**阶段 1（Market Snapshot）**的研究任务、数据/接口/界面拆分与验收门槛
> 状态: 🚧 S0（实测基线）**已实测并回填于「§五之二 S0 实测基线」与 §八**；**S1 已实现并经 PR #4 合并进入 `main`**；
> **S2 已实现、当前在 PR #5 中，仍处 open / 未合并（该 PR head = `270b88d1`）**；
> **当前工作分支只包含 S3 的「A 股核心指数清单」子步**（`analysis/research/market_index_universe.py` + `tests/research/test_market_index_universe.py`）；
> **S3 的可注入 quote transport 尚未开工**（`analysis/research/market_quote_source.py` 与其单测**未创建**），
> S4-S8 仍无代码，**阶段 1（Market Snapshot）尚未完成**。PR #2 与本线分离，本分支**未导入**其任何实现
> 纪律: 全部开发与审查只安排 MiniMax; 不安排 Kimi
> 前置: `docs/08-规范整改-P2D-报告渲染拆分-plan.md` 是**在途未完成**计划（工作区 `M` 状态、未提交），阶段 1 **不得假定**其已完成（见 §六 依赖声明）

---

## 一、阶段 1 的用户可完成研究任务

`docs/11:38` 给的验收方向是「用户能快速了解目标市场当前可确认的状态，并能辨认数据覆盖范围和新鲜度」。
据此，阶段 1 交付后，研究者应当能**独立完成**下面 4 件事。全部是用户行为，不是技术待办：

| # | 用户可完成的研究任务（用户视角） | 怎么算做到了 |
|---|---|---|
| **T1** | 打开一次市场快照，看完 A 股核心指数**最近一个可确认交易状态**（收盘、涨跌、数据所属交易日），不需要点进任何单股报告 | 一次浏览内看完；每个数字旁都有它自己的数据日期 |
| **T2** | 一眼分出哪些指数的数据是**当日的**、哪些是**陈旧的**、哪些**今天缺失或不可用** | 陈旧/缺失/不可用各自有**不同且显式**的标注；系统**不得**用 0 或上一日数值静默顶替 |
| **T3** | 从任一快照数字回溯：这个数字来自**哪个来源**、**什么时候采集**、是否经过**降级或报错** | 每个数字都能走到一条证据记录，含来源、采集时间、质量标记 |
| **T4** | 确认快照停在**哪个交易日**、今天**是不是交易日**，而不是靠系统时钟猜 | 交易日状态来自显式日历证据；**没有证据就是「未知」**，不按周末/节假日启发式推断 |

**明确不属于阶段 1**：不下单建议、不做关联归因、不做信息筛选、不做研究台（`docs/11:42/48/54/60` 分别属于阶段 2/3/4/5）。

> **口径歧义与本计划的取舍（需老板确认）**
> `docs/11:36` 写「统一展示关键指数、**日 K 概览**、市场状态和数据时间」，而 `docs/11:42` 把「K 线展示」独立为阶段 2。
> 本计划取**前者=日 K 的数值概览/摘要，不渲染图表**；交互式 K 线图归阶段 2。若老板认为阶段 1 就要出图，S7 范围要重划。

---

## 二、范围

### 2.1 覆盖与节奏

| 对象 | 阶段 1 范围 | 依据 |
|---|---|---|
| 市场 | **A 股核心指数**。港股 / 美股主要指数**只做契约可容纳**（身份、新鲜度、质量表达与市场无关），**不接数据** | `docs/11:36`「以 A 股为主、并**逐步**纳入」；`docs/11:13` |
| 展示内容 | 关键指数、最近可确认状态、**日 K 数值概览**、市场状态、数据时间 | `docs/11:36` |
| 诚实性 | 缺失 / 延迟 / 不可用**三态分别表达**，不合并成「无数据」 | `docs/11:36`「明确缺失、延迟或不可用的数据」+ `docs/11:75` |
| 终端形态 | 离线可读的快照产物 + 最小可读视图；研究台外壳留给阶段 5 | `docs/11:17/60`；形态歧义见 §九 |

**港股/美股为何不随阶段 1 一起接**（`docs/11:19` 要求说明引入动机而非数量）：阶段 1 要先证明的是
「**A 股核心指数的可信度表达**能不能端到端成立」。在缺失/陈旧/降级三态还没被用户和验收各看一眼之前，
扩市场只会把未验证的表达方式复制到第二个、第三个市场。若 S6 抽样核验通过、且老板认为研究价值成立，
再按同一契约加市场 —— **届时必须单列一片并写清它解决什么问题**。

### 2.2 每个数据入口必须回答的问题（`docs/11:19` + `docs/11:94`）

新增任何数据入口，必须先书面回答这 5 项，缺一不得开工：

1. 它解决阶段 1 哪个**具体**用户任务（T1-T4 的哪一条）？
2. 它的**质量要求**与**新鲜度要求**是什么，按什么策略判定（策略必须显式，不能有全局阈值）？
3. 它的**授权 / 使用条件**是什么？
4. 它的**维护成本**（多久取一次、失败了谁兜底）？
5. 它的**故障降级方式** —— 挂了以后快照长什么样？

> **UNVERIFIED**：本计划**不列任何数据源清单、不列端点数、不列接入数量**。哪些 provider 能稳定提供指数日线、
> 是否需要授权、真实稳定性如何，本次**未联网、未跑任何 live 探针**，一律留到 S3 实测后再写。

---

## 三、现状盘点（仓库实测，2026-10-04）

### 3.1 已具备：阶段 1 可直接复用的能力

**A. `analysis/research/` —— Research Engine 契约层已经建好，而且规模不小**

19 个模块（不含 `__init__.py`）共 **2416 行**，每个模块都有同名单测（`tests/research/` 19 个 `test_*.py`，1:1 无遗漏）：

| 已有契约 | 位置 | 阶段 1 怎么用 |
|---|---|---|
| **指数身份** | `analysis/research/index_registry.py:22` `IndexPublisher`（`csi`/`sse`/`szse`/`cni`）+ `:32` `IndexIdentity`（`index_id` / `publisher` / `local_code`，frozen + 强校验） | 直接作为阶段 1 指数的**统一身份**，**不另发明 id 方案** |
| **指数 → provider 符号映射** | `analysis/research/index_symbols.py:19` `IndexProviderSymbolAlias` | 同一指数在不同 provider 下的符号别名 |
| **能力语义身份** | `analysis/research/capabilities.py:124-142` 内建 `index.registry` / `index.quote` / `index.membership` 等指数能力 id，以及同列的 `market.trading_calendar`、`reference.security_master` | 阶段 1 取数按 capability 表达「要什么」，不按端点表达 |
| **质量元数据** | `analysis/research/quality.py:20/29` `FreshnessStatus`(`fresh`/`stale`/`unknown`) 与 `CompletenessStatus`(`complete`/`partial`/`empty`/`unknown`)、`:38+` `QualityMetadata`（`freshness`/`completeness`/`degraded`/`quality_flags`，frozen + token 校验）、`:75` `contract_fields()` | 阶段 1「缺失/延迟/不可用」的**现成表达**，三态映射到 `freshness` + `completeness` + `degraded` |
| **显式新鲜度策略** | `analysis/research/freshness.py:23` `MaxAgePolicy`、`:66` `evaluate_freshness`；模块 docstring `:1-9` 明确「**由调用方提供策略，不设全局阈值**」 | 「今天的数据」由谁说了算 —— **策略由阶段 1 显式声明**，不硬编码 |
| **多时钟时间语义** | `analysis/research/time_semantics.py:19` `TIME_FIELDS`（`fetched_at`/`data_as_of`/`period_start`/`period_end`/`published_at`/`effective_from`/`effective_to`）、`:41` `TimeMetadata`；docstring `:1-13` 明确「一个时钟不从另一个推断」 | T3 的「什么时候采集」与 T1 的「数据哪一天」必须**分字段**，不能混用 |
| **交易日历（显式证据）** | `analysis/research/trading_calendar.py:20` `TradingDayStatus`(`open`/`closed`/`unknown`)、`:71` `TradingCalendar`、`:95` `status_on`；docstring `:1-11` 明确「**绝不**按周末/节假日/缺行/系统时钟推断」 | T4 的直接来源 |
| **PIT 防护** | `analysis/research/pit_guard.py:31` `PITStatus`(`allow`/`reject`)、`:24-28` 数值档（`full`/`bounded`/`snapshot_only`/`none`/`unknown`）；`analysis/research/derived_pit.py:1-10` 派生值的 `available_at` 约束 | 阶段 1 至少要能说「这个数字**当时**能不能用」 |
| **证券主数据** | `analysis/research/security_registry.py:26` `SecurityMasterRegistry`（`security_master`/`security_symbols`/`security_lifecycle` 合成） | 阶段 2 从指数进个股时已在位 |
| **provider 身份** | `analysis/research/providers.py:24` `ProviderSpec`（`provider_id`/`display_name`/`provider_family`/`aliases`） | T3 的「哪个来源」；且 docstring `:9-11` 明确**老 fetcher 的 `source` 串不许被改写** |
| **可注入传输层范式** | `analysis/research/trading_calendar_szse_fetch.py:1-12`「transport 可注入，契约测试**永不**需要 live 网络」 | 阶段 1 取数层照抄这个范式 |

**B. 既有 V3 侧可复用的契约层**

| 已有能力 | 位置 | 阶段 1 怎么用 |
|---|---|---|
| **fetcher 4 状态契约** | `analysis/fetcher_contract.py:19-22` `STATUS_OK`/`STATUS_EMPTY`/`STATUS_ERROR`/`STATUS_UNSUPPORTED`、`:27-36` 稳定错误码、`:48` `make_result`、`:207` `from_legacy` | 阶段 1 取数**复用同一套状态语义**，不发明第二套 |
| **数据源状态边界** | `analysis/orchestration/source_status.py:12/15` `SourceMeta` / `SourceStatusRecorder`（dict 兼容 + `snapshot` 分离视图） | 「哪些源成功/降级/失败」的现成持有者 |
| **golden 证据基线（离线）** | `tests/fixtures/golden/`：`result_v3-600693-20261003.json`（capture）、`result_v3-002353-20260912.json`（curation）、`golden_fixtures.py`（生成器兼加载器）、`README.md`（出处逐字段登记） | 阶段 1 离线 fixture **沿用同目录、同命名、同出处登记纪律**；`README.md:64-65` 已立「不可重算的快照不能当回归基线」的先例 |
| **薄壳分层范式** | `analysis/quant_analyzer_v3.py`（**189 行**，docstring `:3-31` 明示只做 re-export）、`analysis/pipeline.py`（**307 行**） | 阶段 1 新代码照此保持薄壳 + 实现在子模块 |
| **渐进式验收规则** | `docs/10-pipeline拆解地图-phase1a.md:290-296`（一次只拆一个职责 / 新模块先建独立测试再切换 / 切换时保持输入·返回值·文案·阈值不变） | 阶段 1 切片照此 |

**C. Section 灰度机制（可参考，不复用）**

`analysis/sections/` 有 5 个 Section（`board`/`dividend`/`dragon_market`/`holders`/`irm`），各带 `fetcher.py`/`meta.json`/`meta.py`/`render.py`，
`enabled_sections()`（`analysis/sections/__init__.py:51-56`）按 `registry.yaml` 灰度过滤。
⚠️ **实测事实**：`_REGISTRY_PATH`（`analysis/sections/__init__.py:34`）指向的 `analysis/sections/registry.yaml`
**在磁盘上不存在，也未被 git 跟踪**（`ls -a` 与 `git ls-files` 均无），因此 `_load_disabled()`（`:37-48`）恒走 `:39-40` 的
「文件不存在 → 返回 `[]`」分支，**当前 5 个 Section 全量启用**。阶段 1 若要沿用灰度开关，**必须先决定这个文件归谁、谁生成**。

### 3.2 缺失 / 需新建

| # | 缺口 | 实测依据 |
|---|---|---|
| **M1** | **完全没有指数取数实现**。`index.quote`/`index.registry` 只是 `capabilities.py:127/126` 里的能力 id，没有任何 fetcher | 全仓检索 `analysis/` 内无指数 K 线 / 指数行情取数；`analysis/data_fetcher.py:34` 出现的「指数」是**指数退避**的措辞，不是指数数据 |
| **M2** | **没有市场级聚合对象**。`result_v3`（`analysis/quant_analyzer_v3.py:27-30` 键集）逐字是**单股**契约，没有 `MarketSnapshot` 对应物 | `tests/test_result_v3_contract.py` 全部围绕单股 4 个新增/3 个补充字段 |
| **M3** | **没有市场级证据记录**。`analysis/research/` 有身份、质量、时间、PIT，**唯独没有**「一条市场级断言 + 支撑它的证据」这一条记录 | `docs/11:73` 要求「证据内容或引用、来源、发布时间/采集时间、关联对象**及其支持的判断**」—— 最后一项无对应结构 |
| **M4** | **没有任何 Web / 界面层**。全仓 `analysis/`+`tests/` 无 flask/fastapi/uvicorn/http.server 引用；`analysis/templates/` 只有 `prompt-playbooks.md` | 阶段 1 的「界面」= **全新**，不是接线 |
| **M5** | **`analysis/research/` 对生产链路零接线**。全仓检索 `index_registry`/`index_symbols`/`IndexIdentity`，命中**只在** `analysis/research/` 与 `tests/research/` 内部 | 它目前是「有契约、无调用方」状态；阶段 1 是第一个真实使用方 |
| **M6** | **没有离线快照 fixture**。`tests/fixtures/golden/` 只有两份**单股** `result_v3` | 阶段 1 需要自己的 market snapshot 离线基线（`docs/11:75` 质量与边界表达要求可测） |

---

## 四、Research Engine 最小落地（只做阶段 1 够用的部分）

`docs/11:77` 明确「具体字段、存储方式和服务边界在实现设计中确定……避免过早固定不必要的复杂度」。
本节**只**给出阶段 1 端到端必需的最小形状，**不设计整个系统**，不选存储、不定服务边界。

### 4.1 四项职责在阶段 1 的最小落法

| `docs/11` §五 职责 | 阶段 1 最小落法 | 复用 / 新建 |
|---|---|---|
| **统一身份** | 指数一律用 `IndexIdentity`（`index_registry.py:32`），provider 符号一律用 `IndexProviderSymbolAlias`（`index_symbols.py:19`），来源一律用 `ProviderSpec`（`providers.py:24`，`:25` 是其 docstring） | **全部复用，零新建** |
| **统一证据结构** | **新建 1 条** `MarketEvidence`：`(evidence_id, subject: IndexIdentity, metric, observation, provider: ProviderSpec, time: TimeMetadata, quality: QualityMetadata, pit_status: PITStatus, status: STATUS_*)` —— 即「一个数字 + 它的来源 + 两个时钟 + 质量 + 能否用」。`evidence_id` 只标识证据记录；研究对象仍使用既有 `IndexIdentity`。这是 M3 的唯一补丁，**不含**关系、不含结论、不含存储 | **1 个新数据类**；身份、来源、时间、质量和 PIT 状态均复用已有契约；`metric` 与 `observation` 描述单个观测值 |
| **可追溯关联** | 阶段 1 最小 = 「快照里每个数字都能走到一条 `MarketEvidence`」。**关系类型、归因、置信度一律不做**（那是 `docs/11:74` 的完整语义，属阶段 4） | 只做**单向可追溯**一跳 |
| **质量与边界表达** | 直接用 `QualityMetadata` + `MaxAgePolicy` + `TradingDayStatus`。三态映射固定为：`completeness=empty` → 缺失；`freshness=stale` → 延迟；`status=error/unsupported` → 不可用 | **全部复用** |

### 4.2 三条不越界的硬规定

1. **不新建第二套身份**：阶段 1 不得定义自己的指数/来源 id 词法；`index_registry.py:44-54` 的 `index_id` 校验已足够。
2. **不设全局新鲜度阈值**：`freshness.py:1-9` 已把「策略由调用方提供」写成契约，阶段 1 的每个数据类必须**各自声明** `MaxAgePolicy`。
3. **不猜时间**：`time_semantics.py:1-13` 与 `trading_calendar.py:1-11` 都已明令「不从别的时钟推断」「不按日历启发式推断」。阶段 1 违反这两条即判回归。

---

## 五、数据 / 接口 / 界面工作拆分（S0-S8）

排序原则：**先量基线 → 快照与证据纯契约（零取数）→ 指数清单接线 + 取数边界 → 状态与时间 → 诚实性 → 离线产物 → 界面 → 收官**。
其中**指数清单接线**排在取数边界同一片（S3）内、且**必须先于 transport 就位**：取数要有明确的指数对象可取，S4/S5/S6 才不会挂在「没有清单」的空处（见下「S3 前置输入」）。
沿用 `docs/10:290-296` 的渐进式验收形态：**新模块先建独立测试，再切换调用，切换时保持输入/返回值/文案/阈值不变**。

> **验收方向一律不以「接了几个源 / 几个端点 / 多少行」计**（`docs/11:92`）。下表「验收方向」列写的是用户可核对的事实。

| # | 片 | 范围 | 计划新增/改动文件（**逐片实际状态见各行**） | 硬约束 | 验收方向 |
|---|---|---|---|---|---|
| **S0** | **实测基线** | **不改源码、不实现功能**。实测并写死当前基线：全量 Pytest `passed`/`skipped` 数、Critical Ruff 现状、`reports/` 现有条目 sha256 清单、Python 矩阵可用性 | 只更新本文件（回填实测数字） | 跑测试前用**独立外层哨兵**阻断非 loopback 出口并报告计数（§六） | 基线数字是**实测值**，不是本文档的估计值；后续每片开工前与收官后各测一次，两次的**基线计数**（`passed`/`skipped`/`deselected`/哨兵计数）必须逐项相同（耗时按各自实测原值记录，不参与判定，口径见 5.2.1） |
| **S1** | 快照容器契约 | 纯数据类：`MarketSnapshot`（只记录快照身份、覆盖市场、指数身份与已知 provider 符号）。零取数、零渲染、无行情数字 | `analysis/research/market_snapshot.py`、`tests/research/test_market_snapshot.py` | 复用 `IndexIdentity` + `IndexProviderSymbolAlias`；frozen + `__post_init__` 校验 | 容器不暴露数字、时间或质量字段；单测全绿 |
| **S2** | 市场证据契约 | 纯数据类：`MarketEvidence`，为单个指数观测显式关联证据身份、指标和值、provider、时间、质量、PIT 与来源状态。零取数、零聚合、零渲染 | `analysis/research/market_evidence.py`、`tests/research/test_market_evidence.py` | 复用 `IndexIdentity`、`ProviderSpec`、`TimeMetadata`、`QualityMetadata`、`PITStatus` 与 `fetcher_contract` 状态；`data_as_of` 与 `fetched_at` 分开，缺失不填 0 | 有值必须关联既有指数身份和来源；无值保留显式状态及质量，不伪装成数字 |
| **S3** | 指数清单接线 + 取数边界 | ① **指数清单（本片前置输入）**：定义 **A 股核心指数清单**，接到 `IndexIdentity` + `IndexProviderSymbolAlias`，证明身份契约**与市场无关**（为港股/美股预留）；② **取数边界**：指数日线取数的**可注入 transport** 边界，复用 `fetcher_contract` 4 状态。**不接任何 live 源**。落法见下「S3 前置输入」 | `analysis/research/market_index_universe.py` ✅**已在当前 S3 分支创建**、`tests/research/test_market_index_universe.py` ✅**已在当前 S3 分支创建**（以上仅「指数清单」子步）；`analysis/research/market_quote_source.py`、`tests/research/test_market_quote_source.py` **仍未创建**（可注入 quote transport 尚未开工） | 清单是 transport 的**显式入参**，无清单构造不出取数调用；不新增 id 词法（`index_registry.py:44-54` 校验已足够）；不预置港股/美股**数据**；transport 可注入（照 `trading_calendar_szse_fetch.py:1-12`）；单测**零网络**；4 状态语义与 `fetcher_contract.py:19-22` 一字不差 | 清单里每个指数都有稳定 `index_id`，且新增一个市场**只加数据、不改编契约**；取数边界**只能在给定清单上运行**；契约测试**在哨兵计数 0 下全绿**；能构造 ok/empty/error/unsupported 四种返回 |
| **S4** | 市场状态与时间 | 组合 `TradingCalendar` + `TimeMetadata` + `MaxAgePolicy` + `QualityMetadata`，产出「可确认状态」 | `analysis/research/market_state.py`、`tests/research/test_market_state.py` | 不按周末/节假日/系统时钟推断交易日（`trading_calendar.py:1-11`）；`data_as_of` 与 `fetched_at` 分字段不混用 | 无日历证据时状态为 `UNKNOWN` 而非 `CLOSED`；策略由调用方传入 |
| **S5** | 缺失/延迟/不可用 | 三态**分别**表达；禁止 0 值 / 上一日值静默顶替 | `analysis/research/market_availability.py`、`tests/research/test_market_availability.py` | 三态不可合并；降级路径必须留 `degraded` / `quality_flags` | 构造「某指数今天没数据」时，产物里是显式缺失，**不是** 0 |
| **S6** | 离线快照产物 | 用**离线 fixture**（M6）端到端产出一份 market snapshot JSON，沿用 golden 目录与出处登记 | `tests/fixtures/golden/market_snapshot-*.json`、`tests/fixtures/golden/README.md`（**追加**，不覆盖既有两份） | 不联网、不用合成行情冒充实盘；归一化口径写进 README；缺键不补 | fixture 能在哨兵计数 0 下重复生成出**同一 sha256**（跨进程自证，方法沿用 P2D §7.1） |
| **S7** | 界面 | 把快照渲染成最小可读视图（T1-T4 可见）。**形态见 §九歧义，需老板先定** | 形态定后再定路径，**不得复用 `analysis/html_report_v3.py`**（见 §六 依赖声明） | 单股 V3 报告的 HTML 资产、CSS token、区块顺序**一个字不改**；`docs/11:85` 三价位与 `docs/11:83-85` 口径零影响 | 界面上 T1-T4 四条**逐条**可被人工核对（截图 + 对照 fixture） |
| **S8** | 收官 | 端到端价值 / 证据可追溯 / 数据质量三面验收 + 抽样核验 + 不改 V3 的证明 | 只更新本文件签字栏 | §六 全部纪律 | §七 验收门槛逐条打勾；**V3 回归**对 S0 基线零变化 |

> **切片形态（每片统一，沿用 `docs/10` Phase 1C/1D 已验证模式）**：① 新建模块写实现；② 建自己的单测；
> ③ 接线；④ 跑 S0 那张门禁表。**禁止新旧两套实现并存**。
> **版本控制纪律**：默认**不执行** `git add` / `commit` / `push` / `merge` / `reset` / `clean` / `stash`；
> 每片是**可审查、可回滚的 checkpoint**，提交与否由老板逐片授权。

### S3 前置输入：A 股核心指数清单

边界修正后 **S2 只剩「市场证据契约」**，「定义指数清单」这项职责已不在 S1/S2 任何一片内。
为免 S4/S5/S6 依赖一份**尚不存在的清单**，本计划把它落回 **S3 内**，作为 transport 的**显式前置输入**（不新增切片号、不重编后续片）：

| 项 | 落法 | 依据 |
|---|---|---|
| **清单落点** | `analysis/research/market_index_universe.py` + 单测 `tests/research/test_market_index_universe.py`（**已在当前 S3 分支创建**，仅指数清单子步；同片的 transport 子步**仍未创建**），与 S3 同片交付 | §五 S3 行「计划新增/改动文件」 |
| **身份来源** | 清单里每个指数 = 一条 `IndexIdentity`（`index_registry.py:32`），`index_id` 必须过 `index_registry.py:44-54` 校验 | §4.2 硬规定 1「不新建第二套身份」 |
| **provider 符号** | 每个指数的已知别名走 `IndexProviderSymbolAlias`（`index_symbols.py:19`），**按 provider 分条**、不合并成一个串 | §3.1-A 表 |
| **市场无关性** | 清单只声明「哪个市场有哪些指数」，**不声明**任何行情数据；加入港股/美股时**只加数据、契约零改动** | §2.1「港股/美股只做契约可容纳」+ §九-1 |
| **验收标准** | ① 每个指数都有**稳定 `index_id`**；② 除 `IndexIdentity` / `IndexProviderSymbolAlias` 外**一个 id 词法都不新增**；③ 清单能参数化到另一市场而**不改契约**；④ 单测**零网络**、哨兵计数 0 | §3.1-A「可注入传输层范式」+ §6.2 O2 |
| **下游消费方** | S4（状态/时间）、S5（缺失/延迟/不可用）、S6（离线产物）**一律只读这份清单**，**禁止各自硬编码指数** | 本节前置约束 |

> **口径提醒**：这份清单是「阶段 1 只交 A 股核心指数、港美只做契约可容纳」（§2.1）的**代码形态**；
> 它**不含**任何 provider 选型结论 —— 哪个 provider 能稳定提供指数日线仍是 U4，**离线阶段一律 stub**。

---

## 五之二、S0 实测基线（2026-10-07 实测回填）

> 本节数字**全部为实测值**，非估计。复现方法、命令、环境见本节各处，可逐条重跑复核。
> 后续每片开工前与收官后各测一次，**两次的基线计数（passed / skipped / deselected / 哨兵计数）必须逐项相同**；耗时按各自实测原值记录，不参与相同性判定（口径同 5.2.1）。

### 5.2.0 实测环境与基线 SHA

| # | 项 | 实测值 |
|---|---|---|
| E1 | 实测日期 | 2026-10-07 02:31 CST |
| E2 | 平台 | macOS 26.5.2（Darwin arm64，MacBookPro） |
| E3 | 解释器 | `/opt/homebrew/opt/python@3.13/bin/python3.13` = **Python 3.13.5** |
| E4 | 测试运行器 | pytest **9.1.1**（项目 venv） |
| E5 | Lint | ruff **0.16.10** |
| E6 | 基线 commit | `1e5bdcf377ee1c6352645c5ec7136ef66daeb090`（「docs: 增加智能市场研究系统总体进度与阶段验收」） |
| E7 | 基线与 `origin/main` | 实测时**逐字相同**（fetch 后确认），故本基线为 origin/main 基线 |
| E8 | 实测分支 | `codex/market-snapshot-s0-isolated`（独立 worktree，基于 origin/main） |

**⚠️ 基线适用性说明（重要，后续各片必读）**
- 本基线在**独立隔离 worktree** 内实测：`/Users/swartea/agent-orchestrator/runs/codex-market-snapshot-s0-isolated/worktree`。
- 该 worktree 的 `reports/` **只有 `.gitkeep`**（`reports/` 产物不进版本库）。因此**若在别处复测**，
  `skipped` 数会因报告目录是否存在而变化 —— 见 5.2.2 逐条 skip 归因。**跨 worktree 复测 `skipped` 不可直接比对**。

### 5.2.1 全量 Pytest 基线（U1 回填）

命令（外层哨兵包裹，见 §6.2 O2）：

```bash
/Users/swartea/Desktop/大A数据/venv/bin/python /tmp/s0_net_sentinel.py -p no:cacheprovider -q
```

**实测结果（连跑两轮）**：

| 轮次 | passed | skipped | deselected | 耗时 | 哨兵拦截计数 | 返回码 |
|---|---:|---:|---:|---:|---:|---:|
| 第 1 轮 | **987** | **11** | **2** | 22.15s | **0** | 0 |
| 第 2 轮 | **987** | **11** | **2** | 21.90s | **0** | 0 |

> **「逐项相同」的准确口径**：两轮**基线计数**（`passed` / `skipped` / `deselected` / 哨兵拦截计数 / 返回码）**逐项相同**。
> **耗时不相同**（22.15s vs 21.90s），耗时本就受机器负载影响，**不作为「相同/不一致」的判据**，故上表按实测原值各自保留。
> 本文件另有两处沿用同一口径：§五之二开篇与 §十签字栏均只对**基线计数**要求「逐项相同」。

> **轮次口径（本文件统一按两轮）**：本节可复核的运行记录为**两轮**，故 §5.2.1、§八 U1 与 §十签字栏**三处一律写「两轮 / 两次一致」**。
> 父提交 `abad230` 的提交说明曾写「连跑三次一致」，但**本文件未留存第三轮的独立明细**，按「无明细即不计入」的口径不予采信，故统一为两轮。

> `docs/10:284` 记录的 779 passed / 9 skipped 为**历史基线，已失效**，不得再沿用（本节数字为准）。

**哨兵（外层，独立于 pytest）**：在 pytest 之前安装 socket 守卫，阻断一切非 loopback 出口
（`connect` / `connect_ex` / `create_connection` / `getaddrinfo` / `gethostbyname`）并计数。
守卫自检：loopback（`127.0.0.1`/`::1`/`localhost`/`0.0.0.0`）放行；`example.com`/`8.8.8.8`/`qt.gtimg.cn` 判定为出网并阻断。
哨兵脚本位于 `/tmp/s0_net_sentinel.py`（**仓外临时脚本，不进版本库**，故不在下方证据路径内）。

**11 个 skipped 的逐条归因（实测原文）**：

| # | 用例 | 原因 | 是否依赖 worktree |
|---|---|---|---|
| 1 | `tests/reporting/test_artifact_delivery_contract.py:471` | LibreOffice/soffice 未安装 | 否（本机环境） |
| 2-4 | `tests/test_html_ui_template.py:205 / :340 / :394` | 600693 报告目录不存在 | **是** |
| 5-7 | `tests/test_scoring_breakdown.py:286`（3 例） | 605162_新中港 报告目录不存在（且无 golden fixture） | **是** |
| 8-10 | `tests/test_three_levels.py:47`（3 例） | 未提供历史 `result_v3` fixture（002353_杰瑞股份 / 600693_东百集团 / 605162_新中港） | **是** |

⇒ 归因合计 = 1 + 3 + 3 + 3 = **10**，与实测 `skipped = 11` **差 1**，本文件**不为其余 1 条指定归因**，标 **UNVERIFIED**。
（`1（本机环境）+ 9（本 worktree `reports/` 无跑批产物）= 10` 是上述逐条可归因的部分，**不可写成 11 = 1 + 10**。）
在装有这些报告目录的环境复测，`skipped` 会低于 11。

> **只读复核补充（本次更正，未运行测试）**：静态检索显示 `tests/test_three_levels.py` 内 `_load_historical_result`（`:44-49`）
> 实际有 **4 处**调用点（`:585` / `:600` / `:615` / `:671`，各属一个独立 `def test_`，均无 parametrize），而非上表所写的 3 处；
> 若这 4 条在本 worktree 全部 skip，则合计为 11。本文件**未运行测试核实**，故此说明只作为归因线索，
> **上表数字与 `skipped = 11` 的实测值均维持原样**，差异归因仍为 UNVERIFIED，留待下次可运行时以 `-rs` 输出核对。

### 5.2.2 Critical Ruff 基线（U2 回填）

```bash
/Users/swartea/Desktop/大A数据/venv/bin/python -m ruff check . --output-format=concise
```

**实测：4 errors（3 条可 `--fix` 自动修，1 条需手改），全部位于 `scripts/`，`analysis/` 与 `tests/` 零告警。**

| 文件:行 | 规则 | 说明 |
|---|---|---|
| `scripts/add_emoji_to_skill.py:187:17` | SIM102 | 嵌套 if 可合并（**唯一不可自动修的一条**） |
| `scripts/verify_accept_600693.py:4:1` | E401 + I001 | 单行多 import；import 块未排序 |
| `scripts/verify_north_scope.py:13:1` | I001 | import 块未排序 |

**解读**：这 4 条是**基线既存**问题，与阶段 1 无关。后续各片**不得新增** Ruff 错误；若需要，可另行申请修这 4 条（不在阶段 1 范围）。

### 5.2.3 `reports/` 现有条目 sha256 清单（U3 回填）

```bash
find reports -type f -exec shasum -a 256 {} \; | sort -k2
```

| 条目 | sha256 | 说明 |
|---|---|---|
| `reports/.gitkeep` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 空文件（`e3b0c442…` 即 sha256 of empty string） |

⇒ 本 worktree 的 `reports/` **仅有 1 个条目**（`.gitkeep`）。这是 `reports/` 不入版本库 + 隔离 worktree 的必然结果，
**不是**「报告被删」——`docs/14 §6.2 O5` 要核对的是「跑测试不得新增/改动 `reports/` 产物」，实测前后两次 sha256 一致。
**S6 之后本清单会变**（新增 market snapshot 离线基线），届时须更新本节。

### 5.2.4 Python 矩阵可用性（U2 附项）

CI 矩阵（`.github/workflows/ci.yml:84-97` 实测）：`ubuntu-latest × py3.10 / py3.11 / py3.12` + `macos-latest × py3.12`。
`pyproject.toml:6` `requires-python = ">=3.10"`。

| 版本 | 本机可用 | 说明 |
|---|---|---|
| 3.10 | ✅ `/opt/homebrew/bin/python3.10`（3.10.20） | CI 矩阵最低版本，本机有 |
| 3.11 | ⚠️ `/usr/local/bin/python3.11`（3.11.3） | 存在但**非 homebrew**，疑似非本次环境自建，不建议作为复测基准 |
| 3.12 | ❌ 未找到 | **CI 矩阵的主版本之一本机缺失** |
| 3.13 | ✅ `/opt/homebrew/bin/python3.13`（3.13.5，= 本次实测解释器） | **超出 `requires-python >=3.10` 上限，且不在 CI 矩阵内** |

**结论（局限，重要）**：本基线只在 **Python 3.13.5 单版本**实测。**CI 矩阵的 py3.10 / py3.11 / py3.12 未在本机复现**，
其中 py3.12 本机不可用。因此本基线**不能替代 CI 跨版本结论**；跨版本兼容性仍以 CI 为准（U2 保留）。

### 5.2.5 live 门禁三层（O3）逐条实测确认

三层的**门禁生效（默认关闭）**均实测确认，非仅读代码推断；其中第 ③ 层「显式 opt-in 放行后」的用例执行结果**未实测**，单列于表下：

| 层 | 机制 | 实测证据 |
|---|---|---|
| ① | `pyproject.toml:71` addopts `-m "not live"` | 默认收集即 **998 collected / 2 deselected**；`-m live` 可正向点名回 2 个 |
| ② | 收集期 fail-closed（`tests/conftest.py:475` `pytest_collection_modifyitems`，`_LIVE_MARK` 定义于 `:415`） | `-m "not slow"` 实测**仍是 2 deselected**，未把 live 用例选回来（防「命令行 `-m` 覆盖 addopts」坑） |
| ③ | 用例级 skipif 要求 `DA_A_RUN_LIVE` **精确等于 `"1"`** | 默认（未设 env）`-m live` → **2 skipped**。**放行后的执行结果 UNVERIFIED**：本次遵守 O1 纪律未设 `DA_A_RUN_LIVE=1`、未运行 live 用例，且两条 live 用例的隔离形态**并不相同**，见下方逐条区分 |

被 deselect 的 2 个 live 用例及其**逐条区分**（`DA_A_RUN_LIVE=1` 显式 opt-in 后各会发生什么）：

| live 用例 | 是否自打桩 | 显式 opt-in 后的真实行为 | 依据 |
|---|---|---|---|
| `tests/test_fund_flow_domain.py::test_fund_flow_daily_uses_push2his` | **是**。用例体第一件事就 `monkeypatch` 掉 `data_fetcher.v2.em_get` 并喂 canned 响应；且本模块有 **autouse 级 `no_network_tripwire`**（`tests/test_fund_flow_domain.py:504`），封死 socket 建连与 DNS 解析，**不给 live 留豁免分支** | 走桩，**不访问真实 push2his** | 用例 skipif reason 与模块 docstring `:18-22`；tripwire 定义 `:504-555` |
| `tests/test_peg_formula.py::test_peg_600693_live_in_spec_range` | **否**。用例体直接调 `v2.fetch_full_valuation("600693")`，**全仓检索该用例无任何桩** | **会访问真实 provider**：该函数经 `requests.get` 打 `https://qt.gtimg.cn/q=...`（`analysis/quant_analyzer_v2.py:240-242`），并取同花顺一致预期 | 用例 docstring `:673`「显式 integration 用例, 会打 qt.gtimg.cn + 同花顺」 |

⚠️ **哨兵计数的适用范围（不得外推）**：5.2.1 的哨兵计数 0 覆盖的是**默认全量运行**——该运行里这两条 live 用例被
①/② 层 **deselect**、在 ③ 层又被 **skip**，**从未执行**。它**不构成**「opt-in 放行后仍零外网」的证据。

⚠️ **门禁没有全局网络守卫**：`no_network_tripwire` 是 `tests/test_fund_flow_domain.py` 的**模块级 autouse fixture**，
作用域仅限该模块（pytest fixture 不跨模块生效）；`tests/conftest.py` 只有选择层门禁
（`pytest_collection_modifyitems`，`:475`）与一个 session 级 `_inject_analysis_path`（`:372`），
**不含任何全局 socket/DNS 守卫**。因此 peg 那条 live 用例一旦放行，仓内无第二道兜底。

**修正记录**：本节早前版本写「`DA_A_RUN_LIVE=1` 时 `-m live` → 2 passed 且哨兵计数仍为 0（用例自打桩，执行期零真实网络）」。
该表述把两条用例一并当作自打桩，与 peg 用例的实际代码形态（无桩、真联网）不符，故撤回；
放行后的实测结果本次**未执行、不予补测**（遵守 O1），标 **UNVERIFIED**。
按 O1「live 场景一律 stub / 打桩」，阶段 1 若需 live 覆盖，应在**注入 transport 的边界内**做（对照 S3），不得靠放行这两条真实联网用例。

### 5.2.6 离线纪律与产物洁净度实测

| # | 纪律 | 实测结果 |
|---|---|---|
| O1 | 测试离线、无真实 DNS/socket/HTTP | ✅ **默认全量运行**哨兵计数 **0**；默认 `-m live` 时 2 条 live 用例被 deselect/skip、**从未执行**，零外网。⚠️ **opt-in 放行后的零外网不成立**：peg 那条无桩、会真联网（见 5.2.5 ③），本次未运行、标 UNVERIFIED |
| O2 | 独立外层哨兵 + 计数为 0 | ✅ 见 5.2.1 |
| O5 | `reports/` 逐字节未变、**不产生新跑批产物** | ✅ 跑批前后 sha256 一致；跑测后 `git status` 仅新增本文件 |
| — | 未改源码/测试/配置 | ✅ 本次唯一改动 = 本文件（`git status` 核对） |

### 5.2.7 U8 复测（fixture 字节数，原标 UNVERIFIED）

`wc -c tests/fixtures/golden/*.json` 实测：`result_v3-600693-20261003.json` = **40,307 B**、
`result_v3-002353-20260912.json` = **1,644 B** —— 与 `tests/fixtures/golden/README.md:22-23` 记载值**逐项一致**。
（`README.md` 自身 8,061 B。）**U8 由 UNVERIFIED 转为已核实。**


---

## 六、硬约束

### 6.1 V3 业务口径（`docs/11:81-87`，逐条不得违反）

- **不调整量化公式。**
- **不改变评分定义或计算方式。**
- **不改变三价位的定义、计算口径或表达含义。**

> 如未来确需调整上述口径，应作为**单独、明确的产品决策和变更评审**处理，**不能**作为架构拆分或新系统接入的顺带改动。
> （`docs/11:87` 原文口径）

补充到本计划的执行口径：

- 阶段 1 **只读不写** V3 产物：不得改 `result_v3` 键集（`analysis/quant_analyzer_v3.py:27-30`）、`three_levels` 结构
  （`analysis/three_levels.py`）、5 状态机与 `trading_plan.template_used`（`analysis/trading_plan.py`）、10 因子与 5 维评分
  （`analysis/analytics/scoring.py`）。
- 阶段 1 引用 V3 结果时**只引用、不重算**；任何「顺手统一一下口径」的念头按上条走变更评审。

### 6.2 离线测试纪律（沿用本仓既有门禁）

| # | 纪律 | 依据 |
|---|---|---|
| **O1** | 测试**必须离线**：不得发起真实 DNS / socket / HTTP。live 场景一律 stub / 打桩 | `docs/11:66`（实时行情属后续扩展，阶段 1 不做）+ 本仓既有纪律 |
| **O2** | 跑测试前用**独立于 pytest 的外层哨兵**阻断非 loopback 出口，并在汇报里给出**计数，必须为 0** | 沿用 P2D §九 第 3 条（同一纪律） |
| **O3** | live 门禁是**三层**，都要确认生效：① `pyproject.toml:71` addopts `-m "not live"` —— **只是可被命令行 `-m` 整体覆盖的默认值**（`pyproject.toml:62` 注释已写明这个坑）；② 收集期选择层 `tests/conftest.py:475` `pytest_collection_modifyitems`（`_LIVE_MARK` 定义在 `:415`），fail-closed 整表达式 opt-in；③ 用例级 `skipif`，要求 `DA_A_RUN_LIVE` **精确等于 `"1"`**（`tests/conftest.py:413` 口径） | 三层缺一即视为门禁未生效 |
| **O4** | **不得新增**任何「不带 `live` 标记却实际出网」的用例 | O1-O3 的推论 |
| **O5** | 收官要核对 `reports/` 现有条目 **sha256 逐字节未变**；本计划全程**不产生新的 `reports/` 跑批产物** | 沿用 P2D §九 第 6 条 |

### 6.3 在途依赖声明（P2-D **未完成**）

- `docs/08-规范整改-P2D-报告渲染拆分-plan.md` 是**在途计划**，状态 `📋 待老板拍板`（其 §十三 签字栏：拍板「待批」），
  工作区该文件为 `M`（已修改未提交）。**阶段 1 不得假定其已完成。**
- **因此**：S7（界面）**禁止**复用或依赖 `analysis/html_report_v3.py` 的渲染结构。若老板要求阶段 1 出图，
  则该片**必须显式标注对 P2-D 的依赖**，并等 P2-D 收官后再启动 —— 这一条需老板拍板（§九）。
- 同理，S7 不得改单股 V3 报告的任何 HTML 资产 / CSS token / 区块顺序（`docs/11:83-85`）。

### 6.4 其他不得越界项

- 不改 `pyproject.toml`、`.github/workflows/ci.yml` 的 lint / marker / addopts 配置（门禁本身不得被阶段 1 改动）。
- 不改 `analysis/sections/**` 的 5 个 Section 与其 `enabled_sections()` 灰度机制。
- 不动 `analysis/quant_analyzer_v2.py`（V2 兼容线）。
- 不做实时行情（`docs/11:66` 明确属后续扩展，且要先定义延迟/覆盖/降级/成本要求）。
- 不把 `analysis/research/` 的 19 个模块重构进 V3 主链路；阶段 1 是**新增消费方**，不是迁移方（`docs/11:28` 模块渐进演进）。

---

## 七、验收门槛（`docs/11:91-95`）

**不设**「N 个数据源」「N 个端点」「N 行代码」类指标（`docs/11:92` 明确不以这些代替验收）。

### 7.1 端到端使用价值

- [ ] T1-T4 四条用户任务**逐条**可被人工走通（打开产物 → 看完 → 认出新鲜度 → 回溯到证据 → 确认交易日）。
- [ ] 快照在**不接 V3 单股报告**的前提下独立成立。
- [ ] 研究者**不需要**读日志、不需要跑脚本，就能判断「这个数字能不能用」。

### 7.2 证据可追溯

- [ ] 快照中**每一个**数字都能走到一条 `MarketEvidence`，含 `provider_id` + `TimeMetadata` + `QualityMetadata`。
- [ ] `data_as_of` 与 `fetched_at` **分字段**存在且未被互相推断。
- [ ] 抽样核验（`docs/11:93`）：至少对**一个**真实 provider 逐条核对来源、时效、对象映射、表述准确性，**核验记录写进本文件**。
- [ ] 离线 fixture 的每个标量都有**出处登记**（沿用 `tests/fixtures/golden/README.md` 的逐字段出处表纪律）。
- [ ] 不完整的数据**没有**被呈现为确定事实（`docs/11:75`）。

### 7.3 数据质量

- [ ] 缺失 / 延迟 / 不可用**三态分别**可观测，且**无一处**用 0 或上一日值静默顶替。
- [ ] 无日历证据时交易日状态为 `UNKNOWN`；实测**零**「按周末/节假日启发式判定」的代码路径。
- [ ] 新鲜度策略**逐数据类显式声明**（`MaxAgePolicy`），全仓**无**全局默认阈值。
- [ ] V3 回归：全量 Pytest `passed` 不减、**`skipped` 数与 S0 实测完全一致**（基线以 S0 为准）。
- [ ] 离线哨兵计数 **0**；live 门禁三层（O3）逐条确认生效。
- [ ] `reports/` 现有条目 sha256 逐字节未变。

---

## 八、UNVERIFIED 标注

本节开篇的**历史口径（2026-10-04 立项时）**：当时本计划**未运行任何测试、未联网、未取任何 live 数据**，以下一律为 `UNVERIFIED`，**不作为已证事实**。

> **当前状态（2026-10-07 更新）**：该历史口径**已被 S0 的离线实测部分取代**，须按项区分，不得整体沿用。
> - **已于 2026-10-07 离线实测的项**：U1（全量 Pytest 计数）、U3（`reports/` sha256 清单）、U8（fixture 字节数）→ 已核实；U2 部分核实（Ruff 已实测，Python 矩阵跨版本仍未复现）。
> - **本次实测全程离线**：S0 未设置 `DA_A_RUN_LIVE=1`、未运行任何 live 用例，哨兵计数 0 覆盖的是**默认全量运行**。
> - **仍为 UNVERIFIED 的项**：U4-U7（维持原状）；**新增**：`DA_A_RUN_LIVE=1` 放行后两条 live 用例的实际执行结果 —— 其中
>   `test_peg_600693_live_in_spec_range` **无桩、opt-in 后会真实访问 qt.gtimg.cn 与同花顺**，本次按 O1 未运行、不补测（详见 5.2.5 ③）；
>   另 `skipped = 11` 的**逐条归因尚差 1 条**未落实（见 5.2.1 归因表下方说明）。

| # | 未核实项 | 何时必须实测 | 当前状态 |
|---|---|---|---|
| **U1** | 当前全量 Pytest 的 `passed` / `skipped` 具体数字 | **S0** | ✅ **已实测**：987 passed / 11 skipped / 2 deselected（**两轮**基线计数一致，见 5.2.1；`skipped` 的逐条归因尚差 1 条未落实，见该节说明）。`docs/10:284` 的 779/9 为失效历史值，不得沿用 |
| **U2** | Critical Ruff 与 Python 矩阵的当前实际状态 | **S0** | ⚠️ **部分实测**：Ruff = 4 errors（均在 `scripts/`，见 5.2.2）；**Python 矩阵未在本机复现**（py3.12 本机缺失，仅在 py3.13.5 实测，见 5.2.4） |
| **U3** | `reports/` 现有条目的 sha256 清单 | **S0** | ✅ **已实测**：仅 `reports/.gitkeep` = `e3b0c442…b855`（空文件）。见 5.2.3 |
| **U4** | 哪个 provider 能稳定提供指数日线、是否需要授权、真实失败率 | **S3**（需网络授权后单独做 live 探针；离线阶段一律 stub） | ❌ UNVERIFIED（S0 未联网，符合预期） |
| **U5** | 港股 / 美股主要指数的 provider 符号映射是否存在 | **S3 之后**；阶段 1 不做，故不影响本阶段 | ❌ UNVERIFIED |
| **U6** | P2-D 何时收官、是否会被老板批准 | 持续在途；S7 启动前必须重新确认（§6.3） | ❌ UNVERIFIED |
| **U7** | 阶段 1 界面的技术形态（静态 HTML / 本地服务 / 其它） | **需老板拍板**（§九） | ❌ UNVERIFIED |
| **U8** | `tests/fixtures/golden/README.md:22-23` 记录的 fixture 字节数 | 需要时以 `wc -c` 复测 | ✅ **已复测**：40,307 B / 1,644 B，与 README 记载**逐项一致**。见 5.2.7 |

---

## 九、需要老板拍板的歧义点（本计划已各取一种解释，请复核）

1. **港股/美股是否随阶段 1 交付？** 本计划取**否** —— 阶段 1 只交 A 股核心指数，港美只保证**契约可容纳**（§2.1）。依据 `docs/11:36`「逐步纳入」+ `docs/11:19` 不以数量推进。若老板要阶段 1 就含港美，**§五 的阶段 1 切片范围要重划**并先回答 §2.2 五问（注意：**不是**改「S2」—— S2 现为市场证据契约片，港美扩展落点见 S3 指数清单与「S3 前置输入」的市场无关性验收）。
2. **「日 K 概览」是否出图？** 本计划取**不出图**（数值摘要），图表归阶段 2（§一 口径歧义）。若要出图，S7 提前且必然撞上 §6.3 的 P2-D 依赖。
3. **阶段 1 界面的技术形态？** 仓库**零** Web 层（M4），本计划未定形态，只要求「最小可读视图」。建议老板在拍板时一并定形态，否则 S7 无法开工。
4. **`analysis/sections/registry.yaml` 缺失归谁？** 实测该文件不存在且未被跟踪，5 个 Section 现全量启用（§3.1-C）。阶段 1 若要灰度开关，需老板指定归属。
5. **是否允许阶段 1 顺带把 `analysis/research/` 接进 V3 主链路？** 本计划取**否**（§6.4 末条）—— 阶段 1 是新增消费方。接进主链路是独立议题。

---

## 十、签字栏

- 立项: Mavis 2026-10-04（补 `docs/11:91` 要求的阶段 1 专属 plan；此前只有 `docs/11` 路线图，无阶段 plan）
- 拍板: 老板（**待批**）
- 状态: 🚧 **S0（实测基线）已实测回填**（2026-10-07，见 §五之二）；**S1 已实现并经 PR #4 合并进入 `main`**；
  **S2 已实现、当前在 PR #5 中，仍 open / 未合并（该 PR head = `270b88d1`）**；
  **当前分支只包含 S3 的「A 股核心指数清单」子步**（模块 + 其直接单测已创建），**S3 的可注入 quote transport 尚未开工**；
  **S4-S8 仍无代码，阶段 1（Market Snapshot）尚未完成**。PR #2 与本线分离，本分支未导入其任何实现
- S0 实测: 987 passed / 11 skipped / 2 deselected（**两轮**基线计数一致，耗时不同不参与判定）、哨兵计数 0（**默认全量运行**）、Ruff 4 errors（既存，在 `scripts/`）、
  `reports/` 仅 `.gitkeep`、live 门禁三层在**默认关闭**下逐条实测生效；
  **局限**：仅 py3.13.5 单版本实测，CI 矩阵 py3.10-3.12 未复现；`DA_A_RUN_LIVE=1` 放行后的 live 执行结果 **UNVERIFIED**
  （peg 那条 live 用例无桩、会真实联网，本次按 O1 未运行）；`skipped = 11` 的逐条归因尚差 1 条未落实
- 开工条件: 老板「开干」+ §九 五条歧义**至少就 1/2/3 条给出结论**，然后**从 S0（实测基线）开始** —— S0 不做，后续每片都失去对比基准
  （S0 已完成；S1 已合并、S2 在 PR #5 未合并；当前进行中为 **S3 的指数清单子步**，其后为 **S3 的可注入 quote transport**）
- 提交授权: **本任务已获授权做「小而聚焦的本地提交」**（不含 push / PR / merge）；其余各片提交仍逐片拍板
- 审查安排: 全部由 MiniMax 独立只读验收; **不安排 Kimi**
