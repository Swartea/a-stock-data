# Phase 1：`pipeline.py` 渐进式拆解地图

目标：对 `analysis/pipeline.py` 做外科式拆分，不改量化公式、不改抓取口径、不改报告业务含义。每次只移动一个职责，并用现有 CI + 针对性单测兜底。

## 当前职责分布

### 1. 评分与结果语义
- `_build_scoring_breakdown`
- `_SCORING_BREAKDOWN_GROUPS`
- `_SCORE_DIM_MAX`

建议归属：`analysis/analytics/scoring.py`。

特点：逻辑相对纯，但属于评分业务语义。迁移时必须保留现有维度、满分、缺失值中性处理和输出结构，并复用现有 scoring tests 做契约保护。

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
4. **Phase 1D（建议下一步）**：把 `_build_scoring_breakdown` 及其常量迁入 `analysis/analytics/scoring.py`；只移动，不调整评分口径。
5. **Phase 1E**：引入 `SourceStatusRecorder`，把 `_src_meta` 从裸全局 dict 变成有边界的状态对象。
6. **Phase 1F**：抽 V2 legacy bridge，保留行为但隔离 monkey-patch。
7. **Phase 1G**：抽 artifact writer，保持 deliverable contract 不变。
8. **Phase 1H**：最后再拆 `analyze_single_v3` 的 fetch / build / finalize 阶段。

## 渐进式验收规则

- 一次只拆一个职责，不做 43KB 文件整体重写。
- 新模块先建立独立测试，再切换 `pipeline.py` 调用。
- 切换时保持函数输入、返回值、展示文案和业务阈值不变。
- 每次接线后必须通过 Critical Ruff、Ubuntu Python 3.10/3.11/3.12、macOS Python 3.12 Pytest，以及 600693 端到端 Smoke。
- MyPy 暂维持渐进式 advisory，单独治理历史类型债务。
- `_retry_call`、V2 monkey-patch、artifact writer 等带共享状态/副作用的职责，在明确边界前不强拆。
