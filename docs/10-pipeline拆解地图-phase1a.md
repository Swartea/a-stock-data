# Phase 1：`pipeline.py` 渐进式拆解地图

目标：对 `analysis/pipeline.py` 做外科式拆分，不改量化公式、不改抓取口径、不改报告业务含义。每次只移动一个职责，并用现有 CI + 针对性单测兜底。

## 当前职责分布

### 1. 评分与结果语义
- `_build_scoring_breakdown`
- `_SCORING_BREAKDOWN_GROUPS`
- `_SCORE_DIM_MAX`

归属：`analysis/analytics/scoring.py`。

状态：**Phase 1D 已完成**。5 维聚合、子维满分、缺失值 50% 中性处理、clamp、中文 label、顶层 total 结构均保持原有契约；新增迁移等价测试后，`pipeline.py` 已改为 import `_build_scoring_breakdown` 并删除原地评分实现。

### 2. 北向资金口径分类
- `_classify_north_scope`

归属：`analysis/analytics/scope.py`。

状态：**Phase 1C 已完成**。分类仍保持 `market / stock / mixed / unknown` 四类以及原有中文 label 契约；主流程调用点不变，只把实现从 `pipeline.py` 移出。

### 3. V2 兼容与计时桥接
- `_V2_FN_TO_SRC`
- `_FIELD_OF`
- `_TOP_FIELD_OF`
- `_src_meta`
- `_patch_v2_timers`
- `_restore_v2`

特点：依赖 `quant_analyzer_v2` monkey-patch 和模块级共享状态，不适合直接搬迁。后续应先引入明确的 recorder，再隔离 legacy bridge。

建议归属：`analysis/orchestration/legacy_bridge.py`。

状态：**Phase 1F 已完成**。先由 `SourceStatusRecorder`（`analysis/orchestration/source_status.py`）接管 `_src_meta` 所有权，再把桥接实现搬进 `analysis/orchestration/legacy_bridge.py`；`pipeline.py` 保留 `_patch_v2_timers` / `_restore_v2` / `_FIELD_OF` / `_TOP_FIELD_OF` / `_V2_FN_TO_SRC` 作为 v3 透传契约。

### 4. 时间与数据新鲜度
- `_latest_trading_day`
- `_kline_freshness`

归属：`analysis/orchestration/helpers.py`。

状态：**Phase 1A / 1B 已完成**。两个 helper 已有独立单测，`pipeline.py` 已改为 import 并删除原地重复实现。

### 5. 重试与取数编排
- `_retry_call`
- 主流程内部 `_call_new`
- Section Registry fetch 循环
- margin fetch 重试
- supplement fetch 循环

特点：当前依赖 `_src_meta` / `run_log`。不能把 `_retry_call` 当普通纯 helper 直接搬走；应先抽 `SourceStatusRecorder`，再统一 fetch orchestration。

建议归属：`analysis/orchestration/fetching.py`。

状态：**Phase 1E 已完成**。`SourceStatusRecorder` 先落地（`analysis/orchestration/source_status.py`），随后 fetch 编排搬进 `analysis/orchestration/fetching.py`（`_retry_call` / `_call_new` / `_fetch_margin` / `_fetch_sections` / `_fetch_supplements`）；`pipeline.py` 改为 import 并透传 `_retry_call`。

### 6. 主流程
- `analyze_single_v3`

当前同时负责：
1. 调 V2 全链路；
2. V2 fallback/SSL 处理；
3. 交易计划和三价位；
4. 追加 fetcher；
5. Section Registry；
6. 两融和 supplements；
7. result 组装；
8. 北向口径接线；
9. scoring breakdown；
10. freshness guard；
11. artifact 输出；
12. 控制台摘要。

最终目标：`analyze_single_v3` 只负责调用阶段函数和组装阶段结果，保留为兼容门面。

状态：**Phase 1H / 1I / 1J 已达成该目标**。12 项职责中，第 1 项（V2 全链路）在 1J
抽到 `v2_stage.run_v2_stage`；第 3/7/8/9/10/11/12 项在 1H 抽到 `result_builder`；
第 4/5/6 项在 1I 抽到 `fetching.fetch_v3_blocks`。主流程现在只剩
**阶段调用 + 阶段结果拆包 + 一段局部量解包**。
仍然内联的只剩第 2 项（申万 TLS 失败处理）——但它本身已是一次
`_record_sw_tls_failure(...)` 调用，留在主流程的是历史背景注释，没有可搬的逻辑。

### 7. 产物输出
- `_emit`
- `_dump_run_log`
- deliverable_status 计算
- MD / JSON / HTML / DOCX / PDF 写盘

建议归属：`analysis/reporting/artifact_writer.py`。

状态：**Phase 1G 已完成**。落盘与 deliverable contract 搬进 `analysis/reporting/artifact_writer.py`；`pipeline.py` import `_emit` / `_dump_run_log` 并作为 v3 透传契约保留。

## 当前拆分顺序

1. **Phase 1A ✅**：建立 `analysis/orchestration/helpers.py`，复制时间/新鲜度逻辑并补单测。
2. **Phase 1B ✅**：`pipeline.py` 接线 helpers，删除原地重复定义；业务行为不变。
3. **Phase 1C ✅**：建立 `analysis/analytics/scope.py`，为北向资金四类口径补契约测试并接线，删除原地 classifier。
4. **Phase 1D ✅**：建立 `analysis/analytics/scoring.py`，迁移 `_build_scoring_breakdown`、`_SCORING_BREAKDOWN_GROUPS`、`_SCORE_DIM_MAX`，新增新旧实现等价测试并完成 `pipeline.py` 接线。
5. **Phase 1E ✅**：引入 `SourceStatusRecorder`，把 `_src_meta` 从裸全局 dict 变成有边界的状态对象（`analysis/orchestration/source_status.py`）。
6. **Phase 1F ✅**：抽 V2 legacy bridge（`analysis/orchestration/legacy_bridge.py`），保留行为但隔离 monkey-patch。
7. **Phase 1G ✅**：抽 artifact writer（`analysis/reporting/artifact_writer.py`），保持 deliverable contract 不变。
8. **Phase 1H ✅**：拆 `analyze_single_v3` 的 build / finalize 阶段到 `analysis/orchestration/result_builder.py`。
9. **Phase 1I ✅**：拆 `analyze_single_v3` 的 fetch 阶段到 `analysis/orchestration/fetching.py` 的 `fetch_v3_blocks`。
10. **Phase 1J ✅**：拆 `analyze_single_v3` 的 V2 全链路阶段到 `analysis/orchestration/v2_stage.py` 的 `run_v2_stage`（主流程已无任何重试/中止编排）。

## Phase 1H 落地说明（2026-10-03）

`analyze_single_v3` 的 12 项职责里，纯计算部分（3 / 7 / 8 / 9 / 10 / 11 / 12）抽到
`analysis/orchestration/result_builder.py`，主流程收敛为 **fetch / build / finalize** 三段：

- **build**：`build_trade_levels`（三价位 + 状态机注入）、`build_signals`、
  `assemble_result`（result_v3 契约键集）、`enrich_result`（北向口径 + 评分构成）。
- **finalize**：`finalize_run`（freshness guard → 时点收尾 → `_emit` → 控制台摘要）。

未动的部分（有意保留）：V2 全链路重试与 `_patch_v2_timers` / `_restore_v2` 仍留在主流程——
它们依赖 monkey-patch 的模块级状态，拆开风险高于收益。

⚠️ **注入口不能内联绑定**：`compute_three_levels` / `inject_state_to_plan` /
`_classify_north_scope` / `_build_scoring_breakdown` / `_kline_freshness` /
`_record_kline_freshness_guard` / `_finalize_run_log_timing` 必须由 `pipeline.py`
显式传入。若 `result_builder` 直接绑定自身 import，端到端契约测试
（`monkeypatch.setattr(pipeline, ...)`）会失效并退化成真实抓取 + 真实落盘。
`tests/orchestration/test_result_builder_wiring.py::test_pipeline_passes_injection_seams_into_result_builder`
锁定该约束。

### Phase 1H 验收缺口：golden fixture（2026-10-03）

上面「渐进式验收规则」要求矩阵 Pytest 全绿，但矩阵 job 里 `reports/` 只有 `.gitkeep`
（smoke 是**另一个 job**，在 test 之后才跑），而 `tests/test_scoring_breakdown.py`
与 `tests/test_three_levels.py` 的 golden 端到端用例是按
`reports/<code>_<name>/<date>/result_v3-<HHMM>.json` 找历史跑批产物的 ——
**矩阵里 result_v3 契约覆盖等于 0，全部 skip**。

修法落在 `tests/fixtures/golden/`（生成器 + 版本化 fixture + 出处 README）：

- **600693**：`capture`——从本仓库真实跑批产物
  `reports/600693_东百集团/2026-10-03/result_v3-1618.json` 裁剪，源 sha256 钉死；
- **002353**：`curation`——仓库内没有任何 002353 result 产物，按文档与测试中**已记录的
  标量**拼装，每个值都有出处，缺的一律缺键不补；
- 归一化只做 5 件事（剥落盘产物元数据 / 剥本机路径 / 刮耗时尾巴但保留
  `ok`/`fallback`/`error` 语义 / 丢可重算序列 / 丢派生 `scoring_breakdown`），
  **不落盘生成的 PDF 与报告**。

净效果：`tests/test_scoring_breakdown.py` 从 17 passed / 11 skipped 变为
25 passed / 3 skipped，8 个原本在矩阵里死掉的 golden 用例真正在跑；
`tests/test_result_v3_contract.py` 的 4 个 result_v3 键集契约用例同样改为读
golden，不再依赖"当日跑过 V3"。CI 模拟（`reports/` 只有 `.gitkeep`）实测
**707 passed / 26 skipped → 722 passed / 11 skipped**。

**未解决的部分（有意留 skip）**：`tests/test_three_levels.py` 4 个按**精确数值**断言的
用例（002353@2026-09-12、600693@2026-09-12、605162@2026-09-11）需要那几天真实的
baostock 前复权日 K 序列 + 筹码峰 + V2 交易计划，仓库里没有。已实测：用唯一的真实
600693 产物重算 `compute_three_levels` 得 `8.31 / 7.13 / 8.67`，与期望的
`8.99 / 7.16 / 9.23` 三个值全不同（日期不同行情本就不同）。补齐口径与「不要用合成行情
把它们跑绿」的纪律见 `tests/fixtures/golden/README.md` 的「缺失源数据」一节。

## Phase 1I 落地说明（2026-10-03）

§6 的最终目标是「`analyze_single_v3` 只负责调用阶段函数和组装阶段结果」。1H 抽走
build / finalize 后，主流程里**最后一段内联编排**是第 4 步「V3 追加数据块」
（4 个 `_call_new` + Section Registry + 两融 + 3 个 supplements，约 48 行），
现已抽到 `analysis/orchestration/fetching.py` 的 `fetch_v3_blocks`，
返回 `V3FetchedBlocks(fetched, margin, sections_data)`。

口径不变的部分（逐字保持）：

- 调用顺序：**公告 → 财务 → 研报 → 新闻 → Section Registry → 两融 → supplements**；
- 研报仍传 `days=200`（小票近 90 日常无覆盖）；
- `fetched` 仍是 8 键，**初始化值全 `None`**，由各自 primitive 回填；
- `peers` 仍收 `base_result.get("blocks", [])`；
- 控制台提示串与 `_call_new` 的 4 组 `(src_label, mod_key)` 标签不变。

⚠️ **注入口同样不能内联绑定**（与 1H 同一纪律）：**17 个 seam 全部由 `pipeline.py`
显式传入**，其中 **8 个位置参数 + 9 个关键字参数**（不是"全部以关键字传入"——
位置参数同样是对签名形参的显式绑定，少传一个照样会让下面的打桩失效）：

| 位置参数（8） | 形参 ← pipeline 符号 | 关键字参数（9） | 形参 ← pipeline 符号 |
|---|---|---|---|
| `code` | `code6` | `call_new` | `_call_new` |
| `base_result` | `base_result` | `enabled_sections` | `enabled_sections` |
| `run_log` | `run_log` | `fetch_sections` | `_fetch_sections` |
| `recorder` | `_src_meta` | `fetch_margin` | `_fetch_margin` |
| `new_imports` | `_NEW_IMPORTS` | `fetch_supplements` | `_fetch_supplements` |
| `src_desc` | `_SRC_DESC` | `fund_flow_fetcher` | `_fetch_fund_flow_daily` |
| `status_of` | `status_of` | `margin_history_fetcher` | `_fetch_margin_history` |
| `fmt_time` | `_fmt_time` | `peers_fetcher` | `_fetch_concept_peers` |
| | | `margin_fetcher` | `v2.fetch_margin_trading` |

若 `fetching` 自行绑定，上表打桩全部失效，端到端契约测试会退化成真实抓取 +
真实落盘。若 `pipeline` 少传任一 seam，`test_fetch_stage_wiring.py` 立即报出是哪一个。

这 17 个 seam 由两类测试分工把守，**"9 个注入点"指 9 个 seam 符号，不是 9 个测试**：

| 类别 | 覆盖什么 | 范围 |
|---|---|---|
| 行为契约测试 | 真正跑 `analyze_single_v3`，靠打桩隔离网络/落盘 | 5 个测试模块（`test_call_new_contract` / `test_margin_contract` / `test_supplements_contract` / `test_section_registry_contract` / `test_kline_guard_contract`）覆盖 **9 个注入点**：`_NEW_IMPORTS`、`_call_new`、`enabled_sections`、`_fetch_margin`、`_fetch_supplements`、`_fetch_fund_flow_daily`、`_fetch_margin_history`、`_fetch_concept_peers`、`v2.fetch_margin_trading` |
| 接线测试 | 静态锁定形参 ← pipeline 符号的映射 | `test_fetch_stage_wiring.py` 额外锁住**行为测试未 monkeypatch** 的 4 个 seam：`_fetch_sections`、`_SRC_DESC`、`status_of`、`_fmt_time` |

即：4 + 9 = 13 个 seam 由行为测试或接线测试覆盖；其余 4 个（`code6` /
`base_result` / `run_log` / `_src_meta`）是主流程自有局部量，不构成注入点。

净效果：`analyze_single_v3` 168 → **144 行**，`pipeline.py` 323 → 300 行。
全量 Pytest **753 passed / 9 skipped**（较 Phase 1I 首轮的 745 passed 新增 8 个测试——
接线测试改写为 AST 断言后由 4 个增至 12 个；9 个 skip 与改动前完全一致，无新增）；
`reports/` 6 份产物 sha256 **逐字节未变**（口径：5 份跑批产物 + `reports/.gitkeep`
占位文件，合计 6 个目录条目——`.gitkeep` 是 0 字节空文件，不含任何报告内容）。

> **基线 168 的可复算口径**（别再靠记忆改这个数）：计数一律取
> `ast` 的 `end_lineno - lineno + 1`（含 `def` 行与末行）。两条交叉验证互相锁死：
>
> 1. **函数口径**：第 4 步区域实测由 50 行（旧内联块 49 行 + 1 行分隔空行）缩到
>    26 行，净减 **24**；144 + 24 = **168**。
> 2. **文件口径**：`pipeline.py` 323 → 300 共减 23 行 = 函数减 24 − 新增 import 1 行
>    （`fetch_v3_blocks,`），反推函数净减必须是 24。
>
> 若基线写成 167（函数只减 23），文件口径会算出 301 而非 300，两条验证当场互相矛盾。
> 复核命令（**必须用 venv 解释器**——本机没有裸 `python`，`python3` 也不在 venv 里、
> 装不上 `analysis` 的依赖，会直接 ImportError）：
> ```
> venv/bin/python3 -c "import ast,inspect,analysis.pipeline as p;
> f=next(n for n in ast.parse(inspect.getsource(p)).body if isinstance(n,ast.FunctionDef)
> and n.name=='analyze_single_v3'); print(f.end_lineno-f.lineno+1)"
> ```
> 期望输出：`144`（1I 收官口径；Phase 1J 之后该值变为 147，见下节）。

## Phase 1J 落地说明（2026-10-03）

1H 抽走 build / finalize、1I 抽走 fetch 之后，1H 记为「有意保留」的那段
——**V2 全链路的 3 次重试时间盒 + fatal 中止收尾 + `try/finally` 恢复计时器**
——就是主流程里最后一段内联编排，现已抽到
`analysis/orchestration/v2_stage.py` 的 `run_v2_stage`，
返回 `V2StageResult(base_result, abort)`（`abort` 非 `None` 时主流程原样返回）。

逐字保留的历史行为（**都不要"顺手修"**）：

- 重试固定 **3 次**（`V2_ATTEMPTS`），每次调 V2 前 `recorder.clear()` 一次；
- **最后一次失败后仍然 sleep**——`test_fatal_run_log_timing_contract` 断言
  `sleeps == [3, 3, 3]`，收窄会改变端到端耗时；
- fatal 文案 `V2 行情链路失败(腾讯为终点, 禁止陈旧价兜底): {fatal}` 与
  返回 dict 形状不变；收尾顺序仍是 **fatal 写 run_log → 收时点 → 落 run_log → 打印中止**；
- V2 抛异常**不吞**（原实现无 `except`），但 `finally` 仍恢复计时器；
- `v2.analyze_single` 仍传 `output_md=False`。

⚠️ **注入口纪律第三次沿用**（1H result_builder / 1I fetching 之后）：
**15 个 seam 全部由 `pipeline.py` 显式传入**，其中 **6 个位置参数 + 9 个关键字参数**
（数据量在前、注入口在后，便于阅读与防错位）：

| 位置参数（6） | 形参 ← pipeline 符号 | 关键字参数（9） | 形参 ← pipeline 符号 |
|---|---|---|---|
| `code` | `code` | `patch_timers` | `_patch_v2_timers` |
| `name` | `name` | `restore_v2` | `_restore_v2` |
| `run_log` | `run_log` | `finalize_timing` | `_finalize_run_log_timing` |
| `started` | `started` | `dump_run_log` | `_dump_run_log` |
| `recorder` | `_src_meta` | `sleep` | `time.sleep` |
| `v2` | `v2` | `time_fn` | `time.time` |
| | | `now_fn` | `datetime.now` |
| | | `analyze_single` | `v2.analyze_single` |
| | | `fmt_time` | `_fmt_time` |

两个不能省的细节：

1. **`v2` 模块对象本身也是 seam**——既有测试在 `pipeline.v2` 上打桩
   `analyze_single`，所以必须把 `v2` 与 `v2.analyze_single` 一起显式传下去；
   阶段若自己去 `import quant_analyzer_v2`，打桩失效，端到端测试会退化成真实抓取。
2. **`time.sleep` / `time.time` / `datetime.now` 必须写成属性查找**——
   `test_fatal_run_log_timing_contract` 是整体替换 `pipeline.time` /
   `pipeline.datetime` 的；写成 `from time import sleep` 这类绑定会让假时钟失效。

分工：行为契约 `test_v2_stage_contract.py`（11 个用例，锁重试/中止/异常/恢复语义）+
接线测试 `test_v2_stage_wiring.py`（15 个用例，AST 断言 + 15 个 seam 变异测试 +
内联残留反证），与 `test_fatal_run_log_timing_contract.py` 的端到端侧互为交叉。

**本次刻意没有再降行数（如实记录）**：`analyze_single_v3` 144 → **147 行**，
`pipeline.py` 300 → 307 行，函数口径反而 **+3**。原因是该段 `pipeline.py` diff
实测 **20 行删除 / 23 行新增**（hunk `@@ -152,20 +166,23 @@`），23 行新增拆解为
**15 行显式 seam 传参 + 3 行注释 + 2 行调用定界（`run_v2_stage(` 与 `)`）+ 3 行 abort 拆包**，
净 +3；文件口径 307 = 300 + 3
（函数）+ 3（import 块）+ 1（文件头依赖清单），两条口径仍互相锁死。1H / 1I 是
"搬走一大段、接一次调用"，1J 搬走的是**短但 seam 密集**的一段，所以行数不降——
**本阶段的价值是边界与可测性，不是行数**。若为凑行数合并 seam（例如让阶段自己去取
`v2.analyze_single`），会直接破坏上面两个测试锁住的契约，不做。

净效果：全量 Pytest **779 passed / 9 skipped**（较 1I 的 753 passed 新增 26 个测试；
**9 个 skip 与改动前完全一致，无新增**——4 个依赖 2026-09-11/12 缺失 K 线 fixture 的
用例原样保留，本次未触碰 `compute_three_levels` / chip_data 任何逻辑）；
Critical Ruff `--select=E9,F63,F7,F82` 全绿，3 个新文件在完整 advisory 规则下亦无新告警；
`reports/` 6 份条目 sha256 **逐字节未变**。

## 渐进式验收规则

- 一次只拆一个职责，不做 43KB 文件整体重写。
- 新模块先建立独立测试，再切换 `pipeline.py` 调用。
- 切换时保持函数输入、返回值、展示文案和业务阈值不变。
- 每次接线后必须通过 Critical Ruff、Ubuntu Python 3.10/3.11/3.12、macOS Python 3.12 Pytest，以及 600693 端到端 Smoke。
- MyPy 暂维持渐进式 advisory，单独治理历史类型债务。
- `_retry_call`、V2 monkey-patch、artifact writer 等带共享状态/副作用的职责，在明确边界前不强拆。
