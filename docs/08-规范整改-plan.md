# v0.16 规范整改 plan

> 日期: 2026-09-11｜发起: Mavis｜状态: 📋 待老板拍板开干
> 上一线 v0.15-report-quality-phase2 (5 commits) 推完
> 触发: 老板发《08-项目代码规范与验收要求》V1.0

## 一、上下文与定位

**v0.15 收官** (98141e8 + tag, 2026-09-11):
- 报告接线债 Phase 2 4 task 全部完成
- docs/04 同步 H 章节归档

**v0.16 切入: 规范整改** (《08-项目代码规范与验收要求》V1.0, 2026-09-11 老板发)

V3.7.2 + Phase 2 实施后实测, 仍有以下违反 §1-12 的点 (按优先级):

### 现状差距扫描 (9-11)

| 违反点 | 位置 | 规范节 | 优先级 |
|---|---|---|---|
| fetcher 返回 `{"error": str, "rows": []}` ad-hoc, 非 4 状态契约 | analysis/quant_analyzer_v3.py:621/641/677/686 + fetch_*.py 全部 | §4 数据契约 | P0-B |
| `verify=False` 申万 SSL 兜底 | quant_analyzer_v3.py:793-836 | §5 网络/TLS | P0-C |
| 三价位规则: 4 支撑候选 + 3 压力候选取最近者, 缺统一语义文档 + 边界测试 | compute_three_levels 散落多文件 | §6 计算 / §12 P0 | P0-A |
| 6 件套缺统一 status (complete/partial/failed) | _emit() line 1077-1167 | §7 报告 / §12 P1 | P1-A |
| `default=str` 4 处静默序列化 | v3:1101/1156/1165/1180 | §3 注释 | P1-C |
| HTML 渲染外部文本未全 _esc | html_report_v3 多处 | §7 报告 | P1-D |
| 测试文件引用个人路径 / 当日报告 | tests/ 多处 | §9 测试 / §10 配置 | P1-E |
| except Exception 18 处 (含编排边界 5 处合规, 13 处偏宽) | v3 全文 | §8 日志 | P2-A 配套 |
| 报告首页未展示分析时点 + 关键缺失 | write_markdown_report_v3 头部 | §7 报告 | P1-B |
| 评分缺失数据如何影响得分未明确披露 | 评分 10 因子 | §6 计算 | P2 |
| quant_analyzer_v3.py 单文件 2184 行, 入口/采集/分析/报告/渲染混 | v3 全文 | §2 模块边界 | P2-A |
| 缺 CI (Ruff + pytest + GitHub Actions) | 无 | §10 配置 / §9 测试 | P2-B |
| 流程图 docs/07 未标注整改状态 | docs/07 | §11 文档 | P2-C |

## 二、目标

按规范整改, 让项目符合 §1-12 验收要求, P0 必修 + P1 必改 + P2 配套。

## 三、12 task 概览

| # | Task | 优先级 | 改动量 | 依赖 |
|---|---|---|---|---|
| 8.1 | docs/08 规范 plan (本文档) | P0 | 1 文件 | — |
| 8.2 | P0-A 三价位语义与实现统一 | P0 | docs + compute_three_levels 边界 + 测试 | 8.1 |
| 8.3 | P0-B fetcher 状态契约迁移 (4 状态 + error code) | P0 | 4 fetcher + v2 旧 fetcher 适配 | 8.1 |
| 8.4 | P0-C verify=False 移除 + 记 certifi 推荐 | P0 | v3:793-836 申万 SSL 补丁移除 | 8.1 |
| 8.5 | P1-A 6 件套 status complete/partial/failed | P1 | _emit 改写 + run_log 登记 | 8.3 |
| 8.6 | P1-B 报告首页展示分析时点 + 关键缺失 | P1 | write_markdown_report_v3 头部 | 8.3 |
| 8.7 | P1-C 移除 default=str 静默序列化 | P1 | 4 处改写 + 自定义 JSONEncoder | 8.3 |
| 8.8 | P1-D HTML 转义加固 (外部文本) | P1 | html_report_v3 全面 _esc 审计 | — |
| 8.9 | P1-E 测试脱离个人环境 | P1 | tests/ 14 文件 fixture 化 | — |
| 8.10 | P2-A 模块拆分 (入口/采集/分析/报告/渲染) | P2 | 渐进拆分 v3 主文件 | 8.3 |
| 8.11 | P2-B 依赖与 CI (Ruff + pytest + GitHub Actions) | P2 | requirements + .github/workflows | 8.9 |
| 8.12 | P2-C 流程图与文档同步 | P2 | docs/07 加整改状态 | 8.5/8.6/8.7 |

总耗时估: 8.2-8.4 (P0 共 ~1.5h) + 8.5-8.9 (P1 共 ~2.5h) + 8.10-8.12 (P2 共 ~2h) = ~6h

## 四、不在范围 (沿用 Phase 2 parked + 新增)

| # | 债项 | 备注 |
|---|---|---|
| α | 605162 三价位候选空 (数据层) | 沿用 Phase 2-A |
| β | PDF 优化 | 沿用 Phase 2-B |
| γ | 浅色主题稳定性 | 沿用 Phase 2-C |
| δ | 报告双主题切换 (正文) | 沿用 Phase 2-D |
| ε | ifind 接入 | 沿用 Phase 2-E |
| ζ | PEG vs 分位矛盾 | 沿用 Phase 2-F |
| η | 评分缺失披露规则 (P2 配套) | 新增, 跟 8.10 一起做 |

## 五、执行策略 (Mavis 决策)

- **本轮先干 P0 (3 task)**: 跟 Phase 2 一样, 1 task 1 commit
- **P0 完成后冒烟验证, 再开 P1**: 老板复审 P0 后再推
- **P2 暂缓**: 等 P1 验收通过, 单独立 plan
- **不修改业务口径**: §1 明确"不得为了通过测试修改既定业务口径", 整改只动结构/契约, 不动评分公式
- **不在 P0 动 v3 拆分**: §12 P0 修"三价位语义与实现统一", 不动架构 (P2-A 才动)
- **certifi 修复建议**: 移除 verify=False 后, run_log 推荐加 `pip install -U certifi` 一次性 fix; 老板决定后单独做

## 六、P0 验收 (本轮目标)

- [x] docs/08 规范 plan 落地
- [ ] 8.2 三价位: 规则有例子, 边界测试通过, 报告描述同步
- [ ] 8.3 fetcher: 4 状态契约, 错误不再计为成功
- [ ] 8.4 verify=False: 移除, 申万 SSL 失败显式记录并推荐 certifi 修复
- [ ] 600693 + 002353 端到端冒烟通过, run_log 状态可追溯

## 七、签字栏

- 立项: Mavis 2026-09-11 16:14
- 拍板: 老板 (待批)
- 开工: 老板 "开干" 后 Mavis 连续执行 P0
