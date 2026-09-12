# v0.17 P2-A 渐进模块拆分 plan

> 上一线: v0.16 规范整改 P0+P1 (8 task) 收官, P2-B (CI) + P2-C (docs 同步) 落地
> 范围: 渐进拆分 analysis/quant_analyzer_v3.py (2341 行) 按规范 §2 模块边界
> 状态: 📋 待老板拍板开干

## 一、上下文

v0.16 P0+P1 收官后, quant_analyzer_v3.py 单文件 2341 行违反规范 §2 模块边界:

| 职责 | 当前行数 | 期望模块 |
|---|---|---|
| CLI 入口 (main, sys.argv) | ~30 | cli.py |
| 数据采集 (8 fetcher) | ~250 | data_fetcher.py |
| 三价位计算 (compute_three_levels + 候选) | ~150 | three_levels.py |
| 交易计划 (_make_trading_plan + 5 状态机) | ~100 | trading_plan.py |
| 报告渲染 (write_markdown_report_v3, 43 节) | ~1100 | report_md.py |
| 编排 (analyze_single_v3 + _emit) | ~600 | pipeline.py |
| 工具/常量 | ~200 | utils.py |

## 二、目标

按 §2 拆 6-7 个模块, 每个 300-500 行; v3 主文件降为 200-400 行薄壳 (re-export 给向后兼容)。

## 三、9 task 概览 (渐进 5 phase)

### Phase 1: 工具/常量抽取 (本周先做, 工作量小)

| # | Task | 文件 | 预计 |
|---|---|---|---|
| 1 | 提取 _fmt_time / _json_default / _interpret_yoy / _interpret_qoq / _finance_talk / _stock_log_talk / _dragon_talk / 等工具函数 | analysis/utils.py | 1h |
| 2 | 提取 _SRC_DESC / _SRC_DETAIL / fetch 端点元数据常量 | analysis/constants.py | 0.5h |

### Phase 2: 5 状态机 + 交易计划

| # | Task | 文件 | 预计 |
|---|---|---|---|
| 3 | 提取 _score_to_state / _make_trading_plan / _patch_v2_timers | analysis/trading_plan.py | 1h |

### Phase 3: 三价位 (P0-A 已有 rules.md, 拆分)

| # | Task | 文件 | 预计 |
|---|---|---|---|
| 4 | 提取 compute_three_levels + _to_float / _series_ma / _series_recent_low / _series_boll / _klines_to_series 辅助 | analysis/three_levels.py | 1h |

### Phase 4: 8 fetcher 集中 (P0-B 已有 contract.py, 集中入口)

| # | Task | 文件 | 预计 |
|---|---|---|---|
| 5 | 提取 8 fetcher wrapper (_fetch_fund_flow_daily / _fetch_margin_history / _fetch_concept_peers / _fetch_news_em 等) | analysis/data_fetcher.py | 1h |
| 6 | 引入 fetcher_contract 入口, 适配 v2 旧 fetcher | analysis/fetcher_dispatcher.py | 0.5h |

### Phase 5: 报告渲染 + 编排

| # | Task | 文件 | 预计 |
|---|---|---|---|
| 7 | 提取 write_markdown_report_v3 (43 节) | analysis/report_md.py | 2h |
| 8 | 提取 analyze_single_v3 + _emit → analysis/pipeline.py | analysis/pipeline.py | 1.5h |
| 9 | v3 薄壳 (re-export + 入口) + 端到端回归 | analysis/quant_analyzer_v3.py | 1h |

## 四、不破坏向后兼容

老板习惯: `python quant_analyzer_v3.py <code> <name>` 入口 + 5 commits 入仓 + 1 task 1 commit。

策略:
- 拆完的模块以 `from analysis.xxx import yyy` 互导
- v3 顶层文件: 留 main() + 入口 docstring + 全部 from analysis.xxx import *, **不复制代码**
- 测试保持 import 不变 (`from analysis.quant_analyzer_v3 import compute_three_levels` 仍能拿到, 透传)
- 180+ 测试无回退

## 五、不在范围

- v2 / v1 旧文件不拆 (deprecated, 沿用)
- html_report_v3 不拆 (2462 行, 单独 plan)
- md_to_docx 不拆 (单独 plan)
- 重新设计类/接口 (规范 §1 不修改业务口径, 只动结构)

## 六、验收

- [ ] v3 主文件 < 400 行
- [ ] 6 个新模块各自 300-500 行
- [ ] 9 commits (每 task 1 commit)
- [ ] 180+ 测试全过
- [ ] 600693 + 002353 端到端无回退
- [ ] docs/08 同步 P2-A 收官

## 七、风险

- 9 commits 累积改动大, 老板需要逐 PR 复审 (按你节奏)
- 拆分边界 (哪段去哪个文件) 可能要来回调整几次
- 测试可能因 import 路径变化短暂失败, 需要 CI 配套先稳定

## 八、本轮 (v0.17 Phase 1) 建议

先做 Phase 1 (utils.py + constants.py), 工作量 1.5h, 4 commits, 改动小, 验证拆分模式 + 测试透传 OK, 再推 Phase 2-5。

## 九、签字栏

- 立项: Mavis 2026-09-12 16:50
- 拍板: 老板 (待批)
- 开工: 老板 "开干" 后 Mavis 连续执行 Phase 1
