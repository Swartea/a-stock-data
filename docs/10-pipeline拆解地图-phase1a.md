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

归属：`analysis/orchestration/legacy_bridge.py`（`legacy_bridge.py`）与 `analysis/orchestration/source_status.py`（recorder）。

状态：**Phase 1E / 1F 已完成**。1E 先落地 `SourceStatusRecorder`（`MutableMapping` 兼容层，保留稀疏 metadata 与 `tls_recommendation` 等源特有键，附 `snapshot()` 脱离视图），`_src_meta` 由裸全局 dict 变为有边界的状态对象，V2 monkey-patch 行为未改；1F 把 `_FIELD_OF` / `_TOP_FIELD_OF` / `_V2_FN_TO_SRC` / `_patch_v2_timers` / `_restore_v2` 隔离进 `legacy_bridge.py`，`pipeline.py` 改为 import 并删除原地实现，v3 透传契约（`_TOP_FIELD_OF` / `_V2_FN_TO_SRC`）保持不变。

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

归属：`analysis/orchestration/fetching.py`。

状态：**Phase 1G 已完成**。`_retry_call` / `_call_new` / `_fetch_sections` / `_fetch_margin` / `_fetch_supplements` 已抽到 `fetching.py`，`pipeline.py` 改为 import；`_retry_call` 仍按 v3 透传契约 re-export。取数顺序、灰度策略（spec §3.3：4 旧 fetcher 走老路径、5 新节走新注册表）与失败不致命行为均未改变。

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

### 7. 产物输出
- `_emit`
- `_dump_run_log`
- deliverable_status 计算
- MD / JSON / HTML / DOCX / PDF 写盘

建议归属：`analysis/reporting/artifact_writer.py`。

## 当前拆分顺序

1. **Phase 1A ✅**：建立 `analysis/orchestration/helpers.py`，复制时间/新鲜度逻辑并补单测。
2. **Phase 1B ✅**：`pipeline.py` 接线 helpers，删除原地重复定义；业务行为不变。
3. **Phase 1C ✅**：建立 `analysis/analytics/scope.py`，为北向资金四类口径补契约测试并接线，删除原地 classifier。
4. **Phase 1D ✅**：建立 `analysis/analytics/scoring.py`，迁移 `_build_scoring_breakdown`、`_SCORING_BREAKDOWN_GROUPS`、`_SCORE_DIM_MAX`，新增新旧实现等价测试并完成 `pipeline.py` 接线。
5. **Phase 1E ✅**：引入 `SourceStatusRecorder`，把 `_src_meta` 从裸全局 dict 变成有边界的状态对象；先建立兼容层和测试，不直接改 V2 monkey-patch 行为。
6. **Phase 1F ✅**：抽 V2 legacy bridge，保留行为但隔离 monkey-patch。
7. **Phase 1G ✅**：抽 artifact writer，保持 deliverable contract 不变。
8. **Phase 1H**：最后再拆 `analyze_single_v3` 的 fetch / build / finalize 阶段。

### Phase 1H 进展（有界子步，非整阶段完成）

已完成 **1H-1 result builder 子步**：`analysis/orchestration/result_builder.py` 抽出 `build_result_v3` / `apply_north_scope` / `apply_scoring_breakdown`，`pipeline.py` 已接线，21 个针对性单测（`tests/orchestration/test_result_builder.py`）通过。

保持不变：29 个 result 顶层字段名与顺序、`sections_data` 末尾 splat 覆盖语义、`macro` 原地写入、`scoring_breakdown` 接线、控制台文案与打印顺序；AST 对比确认字段集合与顺序与拆分前逐项一致，仅 2 处为有意参数化（`code6`→`code` 形参、`datetime.now`→`now_fn` 形参）。

尚未拆分：`analyze_single_v3` 的 fetch 编排、freshness guard 收尾、`_emit` 产物输出与控制台摘要仍在主流程内。**Phase 1H 整体未完成。**

## 渐进式验收规则

- 一次只拆一个职责，不做 43KB 文件整体重写。
- 新模块先建立独立测试，再切换 `pipeline.py` 调用。
- 切换时保持函数输入、返回值、展示文案和业务阈值不变。
- 每次接线后必须通过 Critical Ruff、Ubuntu Python 3.10/3.11/3.12、macOS Python 3.12 Pytest，以及 600693 端到端 Smoke。
- MyPy 暂维持渐进式 advisory，单独治理历史类型债务。
- `_retry_call`、V2 monkey-patch、artifact writer 等带共享状态/副作用的职责，在明确边界前不强拆。
