# 智能市场研究 阶段 1 · Market Snapshot plan

> 上一线: `docs/11-智能市场研究系统-项目目标与路线图.md`（6b21a85，2026-10-04）确立新产品目标与 5 阶段主线
> 触发: `docs/11:91`「每一阶段先定义用户可完成的研究任务，再拆分数据、接口和界面工作」；阶段 1 至今**无 plan**（docs/ 下只有 `docs/08-*` / `docs/09-*` / `docs/10-*` / `docs/11` 四条线）
> 范围: 只立**阶段 1（Market Snapshot）**的研究任务、数据/接口/界面拆分与验收门槛
> 状态: 📋 待老板拍板开干（**本文件只立计划，未实现任何代码 / 测试 / 接口 / 界面；未改动任何既有文件**）
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
| **统一证据结构** | **新建 1 条** `MarketEvidence`：`(subject: IndexIdentity, observation, provider_id, time: TimeMetadata, quality: QualityMetadata, pit_status: PITStatus, status: STATUS_*)` —— 即「一个数字 + 它的来源 + 两个时钟 + 质量 + 能否用」。这是 M3 的唯一补丁，**不含**关系、不含结论、不含存储 | **1 个新数据类**；字段全部引用已有契约，**不新增字段语义** |
| **可追溯关联** | 阶段 1 最小 = 「快照里每个数字都能走到一条 `MarketEvidence`」。**关系类型、归因、置信度一律不做**（那是 `docs/11:74` 的完整语义，属阶段 4） | 只做**单向可追溯**一跳 |
| **质量与边界表达** | 直接用 `QualityMetadata` + `MaxAgePolicy` + `TradingDayStatus`。三态映射固定为：`completeness=empty` → 缺失；`freshness=stale` → 延迟；`status=error/unsupported` → 不可用 | **全部复用** |

### 4.2 三条不越界的硬规定

1. **不新建第二套身份**：阶段 1 不得定义自己的指数/来源 id 词法；`index_registry.py:44-54` 的 `index_id` 校验已足够。
2. **不设全局新鲜度阈值**：`freshness.py:1-9` 已把「策略由调用方提供」写成契约，阶段 1 的每个数据类必须**各自声明** `MaxAgePolicy`。
3. **不猜时间**：`time_semantics.py:1-13` 与 `trading_calendar.py:1-11` 都已明令「不从别的时钟推断」「不按日历启发式推断」。阶段 1 违反这两条即判回归。

---

## 五、数据 / 接口 / 界面工作拆分（S0-S8）

排序原则：**先量基线 → 纯契约（零取数）→ 身份接线 → 取数边界 → 状态与时间 → 诚实性 → 离线产物 → 界面 → 收官**。
沿用 `docs/10:290-296` 的渐进式验收形态：**新模块先建独立测试，再切换调用，切换时保持输入/返回值/文案/阈值不变**。

> **验收方向一律不以「接了几个源 / 几个端点 / 多少行」计**（`docs/11:92`）。下表「验收方向」列写的是用户可核对的事实。

| # | 片 | 范围 | 计划新增/改动文件（**尚未创建**） | 硬约束 | 验收方向 |
|---|---|---|---|---|---|
| **S0** | **实测基线** | **不改源码、不实现功能**。实测并写死当前基线：全量 Pytest `passed`/`skipped` 数、Critical Ruff 现状、`reports/` 现有条目 sha256 清单、Python 矩阵可用性 | 只更新本文件（回填实测数字） | 跑测试前用**独立外层哨兵**阻断非 loopback 出口并报告计数（§六） | 基线数字是**实测值**，不是本文档的估计值；后续每片开工前与收官后各测一次，两次数字必须逐项相同 |
| **S1** | 快照契约 | 纯数据类：`MarketSnapshot`（快照容器）+ `MarketEvidence`（M3 唯一补丁）。零取数、零渲染 | `analysis/research/market_snapshot.py`、`tests/research/test_market_snapshot.py` | 字段只引用 §4.1 已有契约；frozen + `__post_init__` 校验，照抄 `quality.py:38-80` / `index_registry.py:43-58` 的写法 | 缺证据的数字**无法构造**（类型层面挡住）；单测全绿 |
| **S2** | 指数身份接线 | 定义 A 股核心指数清单，接到 `IndexIdentity` + `IndexProviderSymbolAlias`；证明契约与市场无关（为港股/美股预留） | `analysis/research/market_index_universe.py`、`tests/research/test_market_index_universe.py` | 不新增 id 词法；不预置港股/美股**数据** | 清单里每个指数都有稳定 `index_id`；新增一个市场只加数据不改编契约 |
| **S3** | 取数边界 | 指数日线取数的**可注入 transport** 边界，复用 `fetcher_contract` 4 状态。**不接任何 live 源** | `analysis/research/market_quote_source.py`、`tests/research/test_market_quote_source.py` | transport 可注入（照 `trading_calendar_szse_fetch.py:1-12`）；单测**零网络**；4 状态语义与 `fetcher_contract.py:19-22` 一字不差 | 契约测试**在哨兵计数 0 下全绿**；能构造 ok/empty/error/unsupported 四种返回 |
| **S4** | 市场状态与时间 | 组合 `TradingCalendar` + `TimeMetadata` + `MaxAgePolicy` + `QualityMetadata`，产出「可确认状态」 | `analysis/research/market_state.py`、`tests/research/test_market_state.py` | 不按周末/节假日/系统时钟推断交易日（`trading_calendar.py:1-11`）；`data_as_of` 与 `fetched_at` 分字段不混用 | 无日历证据时状态为 `UNKNOWN` 而非 `CLOSED`；策略由调用方传入 |
| **S5** | 缺失/延迟/不可用 | 三态**分别**表达；禁止 0 值 / 上一日值静默顶替 | `analysis/research/market_availability.py`、`tests/research/test_market_availability.py` | 三态不可合并；降级路径必须留 `degraded` / `quality_flags` | 构造「某指数今天没数据」时，产物里是显式缺失，**不是** 0 |
| **S6** | 离线快照产物 | 用**离线 fixture**（M6）端到端产出一份 market snapshot JSON，沿用 golden 目录与出处登记 | `tests/fixtures/golden/market_snapshot-*.json`、`tests/fixtures/golden/README.md`（**追加**，不覆盖既有两份） | 不联网、不用合成行情冒充实盘；归一化口径写进 README；缺键不补 | fixture 能在哨兵计数 0 下重复生成出**同一 sha256**（跨进程自证，方法沿用 P2D §7.1） |
| **S7** | 界面 | 把快照渲染成最小可读视图（T1-T4 可见）。**形态见 §九歧义，需老板先定** | 形态定后再定路径，**不得复用 `analysis/html_report_v3.py`**（见 §六 依赖声明） | 单股 V3 报告的 HTML 资产、CSS token、区块顺序**一个字不改**；`docs/11:85` 三价位与 `docs/11:83-85` 口径零影响 | 界面上 T1-T4 四条**逐条**可被人工核对（截图 + 对照 fixture） |
| **S8** | 收官 | 端到端价值 / 证据可追溯 / 数据质量三面验收 + 抽样核验 + 不改 V3 的证明 | 只更新本文件签字栏 | §六 全部纪律 | §七 验收门槛逐条打勾；**V3 回归**对 S0 基线零变化 |

> **切片形态（每片统一，沿用 `docs/10` Phase 1C/1D 已验证模式）**：① 新建模块写实现；② 建自己的单测；
> ③ 接线；④ 跑 S0 那张门禁表。**禁止新旧两套实现并存**。
> **版本控制纪律**：默认**不执行** `git add` / `commit` / `push` / `merge` / `reset` / `clean` / `stash`；
> 每片是**可审查、可回滚的 checkpoint**，提交与否由老板逐片授权。

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

本计划**未运行任何测试、未联网、未取任何 live 数据**。以下一律为 `UNVERIFIED`，**不作为已证事实**：

| # | 未核实项 | 何时必须实测 |
|---|---|---|
| **U1** | 当前全量 Pytest 的 `passed` / `skipped` 具体数字 | **S0**。`docs/10:284` 记录的 779 passed / 9 skipped 是**历史基线**，其后 `1c053e1` 等提交已增改大量测试文件，**不可沿用** |
| **U2** | Critical Ruff 与 Python 矩阵的当前实际状态 | **S0** |
| **U3** | `reports/` 现有条目的 sha256 清单 | **S0** |
| **U4** | 哪个 provider 能稳定提供指数日线、是否需要授权、真实失败率 | **S3**（需网络授权后单独做 live 探针；离线阶段一律 stub） |
| **U5** | 港股 / 美股主要指数的 provider 符号映射是否存在 | **S3 之后**；阶段 1 不做，故不影响本阶段 |
| **U6** | P2-D 何时收官、是否会被老板批准 | 持续在途；S7 启动前必须重新确认（§6.3） |
| **U7** | 阶段 1 界面的技术形态（静态 HTML / 本地服务 / 其它） | **需老板拍板**（§九） |
| **U8** | `tests/fixtures/golden/README.md:22-23` 记录的 fixture 字节数（40,307 B / 1,644 B）是 **README 的记载值**，本次**未复测** | 需要时以 `wc -c` 复测 |

---

## 九、需要老板拍板的歧义点（本计划已各取一种解释，请复核）

1. **港股/美股是否随阶段 1 交付？** 本计划取**否** —— 阶段 1 只交 A 股核心指数，港美只保证**契约可容纳**（§2.1）。依据 `docs/11:36`「逐步纳入」+ `docs/11:19` 不以数量推进。若老板要阶段 1 就含港美，S2 范围要重划并先回答 §2.2 五问。
2. **「日 K 概览」是否出图？** 本计划取**不出图**（数值摘要），图表归阶段 2（§一 口径歧义）。若要出图，S7 提前且必然撞上 §6.3 的 P2-D 依赖。
3. **阶段 1 界面的技术形态？** 仓库**零** Web 层（M4），本计划未定形态，只要求「最小可读视图」。建议老板在拍板时一并定形态，否则 S7 无法开工。
4. **`analysis/sections/registry.yaml` 缺失归谁？** 实测该文件不存在且未被跟踪，5 个 Section 现全量启用（§3.1-C）。阶段 1 若要灰度开关，需老板指定归属。
5. **是否允许阶段 1 顺带把 `analysis/research/` 接进 V3 主链路？** 本计划取**否**（§6.4 末条）—— 阶段 1 是新增消费方。接进主链路是独立议题。

---

## 十、签字栏

- 立项: Mavis 2026-10-04（补 `docs/11:91` 要求的阶段 1 专属 plan；此前只有 `docs/11` 路线图，无阶段 plan）
- 拍板: 老板（**待批**）
- 状态: 📋 **待老板拍板**；**本文件未实现任何代码 / 测试 / 接口 / 界面**，未改动任何既有源码、测试、配置或既有文档
- 开工条件: 老板「开干」+ §九 五条歧义**至少就 1/2/3 条给出结论**，然后**从 S0（实测基线）开始** —— S0 不做，后续每片都失去对比基准
- 提交授权: **无**。本计划不因写进文档就自动获得 stage / commit / push 授权；每片为可审查 checkpoint，逐片拍板
- 审查安排: 全部由 MiniMax 独立只读验收; **不安排 Kimi**
