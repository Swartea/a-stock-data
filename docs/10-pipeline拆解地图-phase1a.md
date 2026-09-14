# Phase 1A：`pipeline.py` 拆解地图

目标：对 `analysis/pipeline.py` 做外科式拆分，不改量化公式、不改抓取口径、不改报告业务含义。每次只移动一个职责，并用现有 CI + 新增单测兜底。

## 当前职责分布

### 1. 评分与结果语义
- `_build_scoring_breakdown`
- `_SCORING_BREAKDOWN_GROUPS`
- `_SCORE_DIM_MAX`

建议归属：`analysis/analytics/scoring.py`。

### 2. V2 兼容与计时桥接
- `_V2_FN_TO_SRC`
- `_FIELD_OF`
- `_TOP_FIELD_OF`
- `_src_meta`
- `_patch_v2_timers`
- `_restore_v2`

特点：依赖 `quant_analyzer_v2` monkey-patch 和模块级共享状态，不适合第一刀。后续应先引入明确的 recorder，再移除全局 monkey-patch。

建议归属：`analysis/orchestration/legacy_bridge.py`。

### 3. 时间与数据新鲜度
- `_latest_trading_day`
- `_kline_freshness`

特点：低耦合、无网络、无 V2 依赖，是首批最适合迁移的逻辑。

Phase 1A 目标归属：`analysis/orchestration/helpers.py`。

### 4. 重试与取数编排
- `_retry_call`
- 主流程内部 `_call_new`
- Section Registry fetch 循环
- margin fetch 重试
- supplement fetch 循环

特点：当前依赖 `_src_meta` / `run_log`，下一步应先抽 `SourceStatusRecorder`，再统一为可测试的 fetch orchestration。

建议归属：`analysis/orchestration/fetching.py`。

### 5. 主流程
- `analyze_single_v3`

当前同时负责：
1. 调 V2 全链路；
2. V2 fallback/SSL 处理；
3. 交易计划和三价位；
4. 追加 fetcher；
5. Section Registry；
6. 两融和 supplements；
7. result 组装；
8. 北向口径；
9. scoring breakdown；
10. freshness guard；
11. artifact 输出；
12. 控制台摘要。

最终目标：`analyze_single_v3` 只负责调用阶段函数和组装阶段结果，保留为兼容门面。

### 6. 产物输出
- `_emit`
- `_dump_run_log`
- deliverable_status 计算
- MD / JSON / HTML / DOCX / PDF 写盘

建议归属：`analysis/reporting/artifact_writer.py`。

## 建议拆分顺序

1. **Phase 1A**：时间/新鲜度 helper + 单测。
2. **Phase 1B**：让 `pipeline.py` 改为 import helper，删除原地重复定义；只做等价迁移。
3. **Phase 1C**：抽 `SourceStatusRecorder`，把 `_src_meta` 从裸全局 dict 变成有边界的对象。
4. **Phase 1D**：抽 V2 legacy bridge，保留行为但隔离 monkey-patch。
5. **Phase 1E**：抽 artifact writer，保持 deliverable contract 不变。
6. **Phase 1F**：最后再拆 `analyze_single_v3` 的 fetch / build / finalize 阶段。

## Phase 1A 验收标准

- 新建 `analysis/orchestration/helpers.py`。
- `_latest_trading_day` 和 `_kline_freshness` 行为与 `pipeline.py` 现状一致。
- 新增独立单测覆盖：周末、开盘前、开盘后、K 线新鲜、K 线过期、`window_end` fallback、数据源错误。
- 本阶段不改 `pipeline.py` 的调用关系，因此业务运行路径零变化。
- CI 必须继续通过后，才进入 Phase 1B。
