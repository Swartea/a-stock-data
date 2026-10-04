# v0.18 规范整改 P2-D · HTML 报告渲染层拆分 plan

> 上一线: v0.16 规范整改 P0+P1 收官; P2-A (`analysis/quant_analyzer_v3.py`) 渐进拆分; Phase 1 (`analysis/pipeline.py`) 拆解地图 Phase 1A-1J
> 触发: `docs/08-规范整改-P2A-模块拆分-plan.md:74` 明确写「html_report_v3 不拆 (2462 行, 单独 plan)」, 该专属计划至今缺失
> 范围: 渐进拆分 `analysis/html_report_v3.py` (实测 **2771 行**) 按规范 §2 模块边界
> 状态: 📋 待老板拍板开干（本文件只立计划, 未动任何源码 / 测试 / 既有文档）
> 纪律: 全部开发与审查只安排 MiniMax; 不安排 Kimi

---

## 一、上下文与本计划的位置

`docs/08-规范整改-P2A-模块拆分-plan.md` §五「不在范围」第 74 行把 `html_report_v3` 列为
「单独 plan」, 但 docs/ 下不存在该计划。本文件补上这一环, 使规范整改 §2 模块边界
(P2-A) 的三块遗留工作（P2-A v3 主文件 / P2-D HTML 渲染 / `md_to_docx`）只剩最后一块未立项。

本计划只做**结构拆分**, 不改任何业务口径 —— 与 `docs/08-规范整改-plan.md` §五
「不修改业务口径: §1 明确『不得为了通过测试修改既定业务口径』, 整改只动结构/契约,
不动评分公式」一致。执行纪律沿用 `docs/10-pipeline拆解地图-phase1a.md` §渐进式验收规则
（一次只拆一个职责 / 新模块先建独立测试再切调用 / 切换时保持输入·返回值·展示文案·业务阈值不变）。

---

## 二、事实基线: 2771 行是怎么组成的

以下区间由 `ast` 的 `end_lineno - lineno + 1` 实测, 非估算。合计 2740 行; 差额 31 行
是各区块之间的 `# ===...` 分隔横幅与空行。

| # | 区块 | 行区间 | 行数 | 关键符号 |
|---|---|---|---|---|
| 1 | 文件头 + 依赖导入 | 1-51 | 51 | `import html_report as hr` (L28); 双路径 import `analysis.analytics.factor_status` (L32-41) 与 `sections.enabled_sections` (L45-51) |
| 2 | 语义色板 | 53-64 | 12 | `C_RED`/`C_RED_DK`/`C_GREEN`/`C_GREEN_DK`/`C_AMBER`/`C_AMBER_DK`/`C_BLUE`/`C_GRAY` |
| 3 | 通用小工具 | 66-149 | 84 | `_esc` `_clean_fname` `_num` `_num_or_dash` `_first` `_parse_date` `_days_between` `_is_error` `_svg_safe` |
| 4 | 错误提取 + 缺失模块降级 | 152-252 | 101 | `_MODULE_SCORE_WEIGHT` `_blob_to_error_str` `_source_error_msg` `_extract_error_msg` `_render_missing_module` |
| 5 | 时点推导 | 255-293 | 39 | `_source_time` `_blob_time` `_time_label` |
| 6 | 文本标签 + 语义配色 | 296-359 | 64 | `_trunc` `_signal_text` `_signal_direction` `_rating_color` `_sentiment_color` `_sentiment_tag` |
| 7 | **静态资产（CSS / JS）** | 362-1013 | **652** | `_CSS` (114行/6503字符) `_MINGLI_CSS` (127行/9182字符) `_ECHARTS_JS_TEMPLATE` (267行/11856字符) `_CSS_HEAD` (55行/3682字符) `_HERO_STYLE` (5行) `_checklist_css()` (56行, 函数形式的 CSS) |
| 8 | 图表数据 + ECharts 卡片 | 1016-1154 | 139 | `_chart_card` `_kline_to_rawdata` `_markline_data` `_markpoint_data` `_render_echarts_kline_block` `_render_echarts_tech_block` + `_ECHARTS_KLINE_CARD_HTML` `_ECHARTS_TECH_CARD_HTML` |
| 9 | hero 结论区 + 5 状态判定 | 1157-1274 | 118 | `_a_share_verdict_mark` `_render_hero` `_state_of` `_state_key_of` |
| 10 | 5 维评分构成卡片 | 1277-1364 | 88 | `_BREAKDOWN_RENDER_KEYS` `_scoring_breakdown_color` `_render_scoring_breakdown` |
| 11 | **操作检查清单** | 1367-1538 | **172** | `_render_checklist`（单函数 172 行, 全文件最长的业务函数; 内含 `CHECKLIST_5T` 与 `items5` 块 L1528-1533） |
| 12 | 风险警报 | 1541-1712 | 172 | `_risk_items` (128) `_render_risk` (42) |
| 13 | **6 块内容模块** | 1715-2118 | **404** | `_src_tag` `_module_research` `_module_announcements` `_finance_comment` `_module_finance` `_module_peer` `_module_margin` `_module_news` |
| 14 | 附录（抽屉 + run_log） | 2121-2221 | 101 | `_detail_drawer` `_render_run_log` |
| 15 | **主函数** | 2224-2507 | **284** | `write_html_report_v3` |
| 16 | HTML → PDF | 2510-2572 | 63 | `_render_html_to_pdf`（真实拉起 Chrome headless 子进程） |
| 17 | 自测脚手架 | 2575-2771 | 197 | `_self_test_dict` (148) + `if __name__ == "__main__":` 自检块 (43) |

结构性事实（对本计划的设计起决定作用）:

- **静态资产占 652 行 = 全文件 23.5%**, 是最大的单块, 且**零业务逻辑** —— 最低风险起步点。
- **`write_html_report_v3` 单函数 284 行, 引用 33 个模块级符号**, 是唯一的耦合中枢。
- **6 个 `_module_X` 签名完全同构**: `(result, report_date, run_log) -> (src_line, inner)`,
  由 L2388-2390 的循环统一消费 —— 天然的横向切分缝。
- 纯叶子层（无模块级依赖）: `_esc` `_clean_fname` `_num` `_first` `_parse_date` `_is_error`
  `_svg_safe` `_trunc` `_rating_color` `_sentiment_color` `_finance_comment` `_kline_to_rawdata`
  `_markline_data` `_markpoint_data` `_a_share_verdict_mark` `_state_key_of`
  `_scoring_breakdown_color` `_render_html_to_pdf` —— 共 18 个, 先搬它们最安全。

---

## 三、耦合地图: 谁依赖谁

按 `ast` 逐函数抽取的模块级依赖（`deps` 列只列本文件内符号）:

| 被搬区块 | 扇入（谁在用它） | 扇出（它还要什么） | 耦合强度 |
|---|---|---|---|
| 静态资产 (7) | 只有 `write_html_report_v3` 读 4 个常量 + `_checklist_css()` | 无 | **零**（纯字符串） |
| 通用小工具 (3) | 全文件 18 个函数中的 11 个 | 无 | 低（叶子） |
| 错误降级 (4) | 6 个 `_module_X` + `_risk_items` | `_esc` | 中（6+1 处扇入） |
| 时点 (5) | `write_html_report_v3` + 5 个 `_module_X` + `_chart_card` + `_src_tag` | `_esc` | 中（7 处扇入） |
| 标签配色 (6) | `_render_checklist` + `_module_*` | `_first` `_esc` `_sentiment_color` | 低 |
| 图表 (8) | `write_html_report_v3` + 测试直接 import | 无 | 低 |
| hero/状态 (9) | `write_html_report_v3` | `_hero_style` `_a_share_verdict_mark` `_esc` `_first` `_num` | 中 |
| 评分构成 (10) | `write_html_report_v3` | `_esc` `_num` `_scoring_breakdown_color` | 低 |
| 检查清单 (11) | `write_html_report_v3` | `_esc` `_first` `_num` `_signal_direction` `_signal_text` `_trunc` | 中（**读 `result["trading_plan"]["template_used"]`** L1384/L1417） |
| 风险 (12) | `write_html_report_v3` | `_days_between` `_extract_error_msg` `_is_error` `_num` `_trunc` | 中 |
| 6 模块 (13) | `write_html_report_v3` | 4+5 类共享 helper | **高（13 个依赖, 彼此间无依赖）** |
| 附录 (14) | `write_html_report_v3` | `_esc` `_is_error` `_num` `_num_or_dash` `_first` `_trunc` + `C_RED_DK`/`C_GREEN_DK` | 低 |
| PDF (16) | `write_html_report_v3` | 无（`os`/`subprocess` 局部 import） | 零 |
| 自测 (17) | 仅本文件 `__main__` | `math` `random` 局部 import | 零 |

两个必须记住的跨块耦合:

1. **V2 SVG 只在主函数一个地方被调用**（L2255 / L2256 / L2259 / L2263）:
   `hr._svg_kline(klines, current_price=price)` / `hr._svg_chip_histogram(cd)` /
   `hr._svg_pe_history(pe_series, pe_pct)` / `hr._svg_radar(s, factor_notes=...)`。
   四个提供方签名见 `analysis/html_report.py:15/74/134/189`（`width`/`height` 都有默认值,
   `factor_notes=None` 是 P0-B 后加的）。**搬任何区块都不需要动这 4 个调用。**
2. **`result["scoring_breakdown"]` 由上游注入**: `analysis/pipeline.py` 的
   `_build_scoring_breakdown` → 已按 `docs/10` Phase 1D/1H 落到
   `analysis/analytics/scoring.py` 与 `analysis/orchestration/result_builder.py`。
   HTML 侧只**读**不写, 老 result JSON 无该字段时走 L1313-1322 的兜底卡。

---

## 四、硬约束: 测试与调用方对源码文本的耦合（本次拆分的真正难点）

这一节是 P2-A 没遇到过的。`html_report_v3` 的测试**大量断言源码文本本身**,
函数一旦搬出本文件就会红。逐条列出, 后续每一片都必须逐条守住。

| 编号 | 约束 | 证据位置 | 拆分影响 |
|---|---|---|---|
| **H1** | `inspect.getsource(write_html_report_v3)` 必须仍含字面量: `echarts@5.5.1`/`echarts.min.js`、`_MINGLI_CSS`、`<nav class="top-nav">`、`id="themeToggle"`、`<div class="v3-stock-report">`、`v3-stock-report-theme`、`light-mode`、`localStorage`、`☀️ 浅色模式`、`🌙 深色模式` | `tests/test_html_ui_template.py:109-191`（7 个测试） | **`write_html_report_v3` 必须继续定义在 `analysis/html_report_v3.py`**, 且 L2313/L2314/L2315/L2328/L2339/L2434-2452 这些字面量不得外移 |
| **H2** | 读 `analysis/html_report_v3.py` **全文**做正则审计: ①`for label, txt in items5:.*?</ul>` 块须含 `_esc(label)` 与 `_esc(txt)`; ②`def _render_risk\(rows\):(.*?)return.*?join\(h\)` 须 ≥5 处 `_esc(`; ③全文 `h.append(...%(result|it|x|b|a).get(...))` 命中数 < 5 | `tests/test_html_escape_audit.py:102-137`（3 个测试） | **搬走 `_render_checklist` 或 `_render_risk` 会直接打红这 3 个测试**。修法有现成先例: P2-A 当时给 `report_md` / `pipeline` / `result_builder` 各加了一个 `*_source` conftest fixture 让测试改读新宿主（`tests/conftest.py:99/112/125`）。S5 必须同片完成 fixture 迁移 |
| **H3** | `from html_report_v3 import _MINGLI_CSS`（裸模块名） | `tests/test_html_ui_template.py:29` | `_MINGLI_CSS` 搬走后必须在 `html_report_v3` 顶层 re-export |
| **H4** | `from html_report_v3 import _esc`（裸模块名）+ 8 个 `_esc` 行为用例（`&` 必须先于 `<` 转义等） | `tests/test_html_escape_audit.py:19-97` | `_esc` 必须在 `html_report_v3` 顶层 re-export, **且 5 步替换顺序一字不改** |
| **H5** | `monkeypatch.setattr(hrv3, "_render_html_to_pdf", ...)` 打桩模块对象 | `tests/analytics/test_factor_status.py:240-243` 与 `253-256` | **`write_html_report_v3` 必须在调用时从 `html_report_v3` 的模块全局解析 `_render_html_to_pdf`**。搬走定义可以, 但必须 `from analysis.reporting.pdf_render import _render_html_to_pdf` 显式导入进本模块命名空间; **禁止**用默认参数/闭包提前绑定 |
| **H6** | 往 `sys.modules["html_report_v3"]` 塞假模块 | `tests/reporting/test_artifact_delivery_contract.py:61-73, 85-91, 336-346, 422-432` | `analysis/reporting/artifact_writer.py:86-91` 的 `import html_report_v3 as _hrv3` 裸 import 必须原样保留; **HTML 侧不得改成经 `analysis.reporting.*` 路径被 artifact_writer 引用** |
| **H7** | 测试直接 import 的符号必须全部 re-export | `tests/test_html_ui_template.py:234-329`（`_kline_to_rawdata`/`_markline_data`/`_markpoint_data`/`_render_echarts_kline_block`/`_render_echarts_tech_block`）、`:372-386`（`_render_html_to_pdf`） | S1/S3 搬完这些名字必须仍在 `html_report_v3` 顶层可见 |
| **H8** | `html_report_v3_source` fixture 断言全文含 `template_used` 与 `操作口诀` | `tests/test_multi_state_trading_plan.py:180-187` | 同 H2, 由 S5 的 fixture 迁移一并解决 |
| **H9** | 单文件同时服务**两种 import 人格**: `import html_report as hr`（裸） + `try/except` 双路径（`analysis.analytics.factor_status` / `sections`） | `html_report_v3.py:28-51`；`analysis/pipeline.py:43` 注释「兄弟目录加 sys.path … 让 v2 / html_report_v3 / md_to_docx 裸 import 可解析」；CI 以 `PYTHONPATH=<repo>/analysis:<repo>` 跑 | 每个新模块都要沿用**同样的双路径 import 写法**, 否则 CI 矩阵会 ImportError |
| **H10** | Section Registry 灰度渲染循环（5 新节追加在 6 块之后, 每节独立 try/except, 失败注入 warn 卡） | `html_report_v3.py:2391-2407`（含「Task 1.3 教训: 不替换, 只追加」注释） | 位置、顺序、失败降级文案都不得改动 |

---

## 五、目标分层与模块边界

统一落在既有 `analysis/reporting/` 包（当前只有 `artifact_writer.py`）, 文件名 `html_*.py` 平铺,
避免引入 `html` 同名包与标准库 `html` 混淆。「迁入行数」为**源码实测行的机械搬移量**,
不含新文件的 import 块与文件头。

| 新模块 | 迁入符号（源码行区间） | 迁入行数 | 职责一句话 |
|---|---|---|---|
| `analysis/reporting/html_primitives.py` | 色板 (53-64) + 小工具 (66-149) + 错误降级 (152-252) + 时点 (255-293) + 标签配色 (296-359) + `_chart_card` (1020-1031) | 312 | 无业务语义的地基: 转义 / 数值 / 字段回退 / 时点 / 配色 / 缺失降级 |
| `analysis/reporting/html_theme.py` | `_CSS`(366-479) `_MINGLI_CSS`(484-610) `_CSS_HEAD`(883-937) `_HERO_STYLE`(939-943) `_hero_style`(946-955) `_checklist_css`(958-1013) | 367 | 主题 CSS + token + 响应式覆盖 |
| `analysis/reporting/html_charts.py` | `_ECHARTS_JS_TEMPLATE`(614-880) `_ECHARTS_KLINE_CARD_HTML`(1126-1135) `_ECHARTS_TECH_CARD_HTML`(1138-1154) `_kline_to_rawdata`(1039-1050) `_markline_data`(1053-1070) `_markpoint_data`(1073-1093) `_render_echarts_kline_block`(1096-1117) `_render_echarts_tech_block`(1120-1122) | 370 | ECharts JS 模板 + 4 个占位符的数据装配 + 2 张卡片模板 |
| `analysis/reporting/html_summary.py` | `_a_share_verdict_mark`(1157-1166) `_render_hero`(1169-1241) `_state_key_of`(1252-1274) `_BREAKDOWN_RENDER_KEYS`(1285-1291) `_scoring_breakdown_color`(1294-1304) `_render_scoring_breakdown`(1307-1364) | 188 | 「30 秒决策」区: hero 结论 + 5 维评分构成 |
| `analysis/reporting/html_checklist.py` | `_render_checklist`(1367-1538) | 172 | 操作检查清单（5 状态机文案） |
| `analysis/reporting/html_risk.py` | `_risk_items`(1541-1668) `_render_risk`(1671-1712) | 172 | 风险事件归集 + 大表渲染 |
| `analysis/reporting/html_modules.py` | `_src_tag`(1715-1718) + `_module_research`(1725-1793) `_module_announcements`(1796-1825) `_finance_comment`(1828-1849) `_module_finance`(1852-1912) `_module_peer`(1915-1998) `_module_margin`(2001-2049) `_module_news`(2052-2118) | 404 | 6 块内容模块（研报/公告/财务/同业/两融/新闻） |
| `analysis/reporting/html_appendix.py` | `_detail_drawer`(2125-2178) `_render_run_log`(2181-2221) | 101 | 详细数据抽屉 + run_log 附录 |
| `analysis/reporting/pdf_render.py` | `_render_html_to_pdf`(2510-2572) | 63 | Chrome headless → PDF（唯一有副作用的块） |
| `analysis/reporting/html_self_test.py` | `_self_test_dict`(2579-2726) + `__main__` 自检块 (2729-2771) | 197 | 离线版式自测脚手架（**实测全仓库零外部引用**） |

**残留 `analysis/html_report_v3.py`（薄壳）**: 保留文件头依赖说明 (1-51)、
re-export 块、主函数 `write_html_report_v3` (284 行) 与一个 3 行以内的 `__main__` 转发。
机械估算 **380-430 行**; S8 若把主函数内联的「6 块 + Registry 装配」和「ECharts 占位符替换」
两段各抽成 `html_modules._content_blocks()` / `html_charts.build_echarts_js()`, 降到 **330-360 行**,
满足 P2-A §六「v3 主文件 < 400 行」的对标门槛。

`html_summary`(~188) / `html_appendix`(~101) / `pdf_render`(~63) 低于规范 §2 的 300-500 下限 ——
**这是有意的**: 它们各自是单一内聚职责, 硬凑行数只会引入填充代码。行数是参考, 边界是硬要求。

---

## 六、拆分顺序: 9 片小 PR（1 片 1 commit）

排序原则: **零行为面 → 叶子层 → 被 H2/H8 源码文本契约锁住的块 → 收官**。
把最安全的静态资产放第一片, 先验证「搬文件不改行为」这个模式本身; 把唯一有契约风险的两个块
（checklist / risk）压到 golden 兜底已经就位之后。

| # | 片 | 内容 | 触及硬约束 |
|---|---|---|---|
| **S0** | 冻结基线 | **不改源码**。建离线 golden HTML 回归装置（见 §七） | 无 |
| **S1** | `html_theme` | 搬 367 行静态 CSS | H3（`_MINGLI_CSS` re-export）、H9 |
| **S2** | `html_primitives` | 搬 312 行地基 | H4（`_esc` re-export + 替换顺序） |
| **S3** | `html_charts` | 搬 370 行 ECharts 装配 | H7（5 个符号 re-export） |
| **S4** | `html_summary` | 搬 188 行 hero + 评分构成 | H1（主函数仍在本文件） |
| **S5** | `html_checklist` + `html_risk` | 搬 344 行；**同片**给 conftest 加 `html_checklist_source` / `html_risk_source` fixture，把 H2 的 3 个 + H8 的 1 个源码文本测试改读新 fixture | **H2 + H8（唯一有风险的片）** |
| **S6** | `html_modules` | 搬 404 行 6 块 | H2③ 全文正则的宿主文件会变小, 需复核 |
| **S7** | `html_appendix` + `pdf_render` | 搬 101 + 63 行 | **H5**（`_render_html_to_pdf` 必须留在 `html_report_v3` 模块全局里） |
| **S8** | `html_self_test` + 薄壳收官 | 搬 197 行自测；主函数两个可选内联块抽出；薄壳 re-export 固化 | H1/H5/H6/H7 全部收口 |

每片统一形态（沿用 `docs/10` Phase 1C/1D 已验证的「先搬后接、同片删原地」模式）:

1. 新建模块, 机械搬入符号（**不改函数体**; 跨模块引用改成 import）;
2. 新模块建自己的单测（只测搬入符号, 不测主流程）;
3. `html_report_v3.py` 改为 import + re-export, **同片删除原地定义**;
4. 跑 §七 全部验收门禁。

**硬规则: 禁止新旧两套实现并存**。并存会让 `git revert` 不干净, 也会让下一片无法判定基线。

---

## 七、每片保持行为不变的验收 / 回归办法

### 7.1 S0 必须先立的 golden 基线（没有它, S1-S8 全都无法证明「行为不变」）

现状: 仓库里**没有**任何测试对完整 HTML 输出做逐字节断言。现有断言只有
「源码里有某个字面量」(`inspect.getsource`) 和「HTML 里含某段中文」两类, 都无法发现
段落顺序、class 名、空格、属性顺序的漂移。因此 S0 是本计划的**前置硬依赖**, 不是可选项。

S0 装置规格:

- **输入**: 直接复用本文件已有的 `_self_test_dict()` —— `random.seed(7)` 确定性、
  覆盖契约全部字段、无网络、无外部引用（实测全仓库无其他引用点）。
- **落点**: 跟随 `docs/10` §Phase 1H 已建的 `tests/fixtures/golden/`。
  ⚠️ 该目录当前是**未提交的 Phase 1H 成果**, 新增 HTML golden 前必须先与在途改动对齐目录/命名
  与出处 README 写法, **不得覆盖既有 600693 capture / 002353 curation 两份 fixture**。
- **归一化只做两件事**（沿用 `docs/10` 的 5 件事口径, 此处只保留 HTML 相关部分）:
  ① 掩码唯一的易变内容字段 `gen_now`（L2242 `datetime.datetime.now().strftime("%Y-%m-%d %H:%M")`,
  渲染进 L2337 导航与 L2423 页脚）; ② 剥落盘元数据。
  已核实**其余内容字段全部确定**: `report_date` 优先取 `result["report_date"]`（L2239-2241,
  缺失才回退 `now()`）; 文件名里的时间戳（L2246）只进路径不进正文。
- **PDF 必须打桩**: `monkeypatch` 掉 `_render_html_to_pdf`（`tests/analytics/test_factor_status.py:236-243`
  已有先例, 注释写明 Chrome PDF 渲染约 15s/次）。**不落盘生成的 PDF 与报告**。
- **自洽性验证**: 装置自身必须先证明「同一输入连续两次渲染的归一化 HTML sha256 相同」,
  然后把该 sha256 写进本文件作为 S1-S8 的比对基线。

### 7.2 每片的 6 道门禁（全部通过才算这片完成）

| # | 门禁 | 命令 / 判据 |
|---|---|---|
| 1 | **golden 逐字节** | 归一化 HTML sha256 与 S0 基线**完全相同** |
| 2 | **全量 Pytest** | `passed` 只增不减; **`skipped` 数与本片开工前完全一致（无新增 skip）** —— 这条是 `docs/10` Phase 1I/1J 已确立的验收口径 |
| 3 | **Critical Ruff** | `ruff check analysis tests --select=E9,F63,F7,F82` 全绿（`.github/workflows/ci.yml:38`）; full ruff advisory（`ci.yml:44`）**无新增告警** |
| 4 | **Python 矩阵** | Ubuntu 3.10 / 3.11 / 3.12 + macOS 3.12（`ci.yml:92-98`）; `pyproject.toml:94` 目标版本 py310, `line-length = 100` |
| 5 | **源码文本契约** | 第四节 H1-H8 全部仍绿: `inspect.getsource` 7 项 / raw-regex 转义审计 3 项 / `_esc` 行为 8 项 / `sys.modules` 假模块 4 处 / 直接 import 符号 7 个 |
| 6 | **离线门禁** | 跑测试前用**独立外层哨兵**阻断非 loopback 出口并报告计数; 计数必须为 0。`pyproject.toml:73` 的 `-m "not live"` 只是默认值, 真正的第一步门禁在 `tests/conftest.py:475` `pytest_collection_modifyitems` —— 两层都要确认生效 |

### 7.3 冒烟（独立 job, 不属于离线门禁）

`ci.yml:133-190` 的 `smoke` job 跑 `python analysis/quant_analyzer_v3.py 600693 东百集团`（2-3 分钟, **需要网络**）,
并断言 `deliverable_status ∈ (complete, partial)` 且 `required_failed` 为空。
本拆分**每片收官都要在获得网络授权后单独跑一次 600693 + 002353**; 离线验收阶段不得触发。

---

## 八、HTML 语义与输出兼容性风险

golden 逐字节比对是最后一道防线, 但下面这些是**人工必须逐片复看**的高风险点 —— 它们
正是本文件 `__main__` 自检块（L2740-2764）用字面量断言的内容:

| # | 风险 | 证据 / 位置 |
|---|---|---|
| **Y1** | **CSS token 与 class 名一字不能改**: `--up:#dc2626` / `--down:#16a34a`（红涨绿跌 A 股惯例）、`.hero.hero-bull`、`.chg-pill up`、`.adv-dot`、`.v3-stock-report`、`.light-mode`、`.top-nav` | 自检 L2754-2762 直接断言这些字面量 + `_a_share_verdict_mark` 的 bear→🟢 / bull→🔴 翻转映射（`_a_share_verdict_mark` L1157-1166） |
| **Y2** | **区块顺序 + emoji 逐字**: 研报观点 📚 / 公告速览 📢 / 财务体检 🩺 / 同业对比·行业定位 🏭 / 资金面（融资融券）💰 / 新闻舆情 📰, 且 Section Registry 5 新节**追加在 6 块之后**（不替换） | L2380-2387 列表 + L2391-2407 循环; 自检 L2750-2751 断言 6 个标题 |
| **Y3** | **来源与时点标注计数**: `html_src.count("数据源：") >= 6`、`html_src.count("数据截止") >= 4` | 自检 L2752-2753; 依赖 `_src_tag`(L1715) 与各 `_module_X` 的 `src_line` 文案与 `_chart_card` 的 `asof` 位置 |
| **Y4** | **SVG 数量恰为 4**（4 张 V2 SVG, ECharts 卡不是 svg） | 自检 L2740/L2743; 依赖 `hr` 的 4 个 `_svg_*` 返回空串时 `_svg_safe` 降级为「数据源暂缺」而非多/少一张 |
| **Y5** | **`_esc` 5 步替换顺序**（`&` 必须最先, 否则 `&lt;` 二次解析） | L70-75; `tests/test_html_escape_audit.py:38-42` 钉死 `A & B → A &amp; B` |
| **Y6** | **ECharts 4 个占位符** `__RAW_DATA__`/`__PIE_DATA__`/`__MARKLINE__`/`__MARKPOINT__` + **kline 空分支的 5 选 1 行为**（空时 4 个全置 `[]`, JS 仍可执行、5 图显示 no-data） | L2461-2486 |
| **Y7** | **`_THEME_JS` 注入位置敏感**: 单次 `str.replace('</body>', _THEME_JS + echarts_js + '</body>')`, 主题 JS 必须在 ECharts JS 之前、都在 `</body>` 之前 | L2488 |
| **Y8** | **PDF 降级四态语义**必须原样: `"ok"` / `"error: PDF 未生成"` / `"error:{ExcName}: {msg[:100]}"`（且向 stderr 打日志）/ 根本不设 | L2496-2505; 下游 `analysis/reporting/artifact_writer.py:134` 读 `result.get("pdf_status", "skipped:html_report_v3 未执行")` |
| **Y9** | **缺失模块降级文案**: `_render_missing_module`(L217-252) 的 8 类占位, 以及老 result JSON 无 `scoring_breakdown` 时的兜底卡（L1313-1322, 含「请重跑 V3（analyze_single_v3）」原文） | 这两处是**用户可见文案**, 改一个字都算行为变更 |
| **Y10** | **Section Registry 单节失败仍出卡**（`⚠️ {label} 渲染失败: {err}`）, 不阻断其它节 | L2402-2407 |

---

## 九、网络与黄金样例约束

1. **渲染器本身不联网, 但 HTML 内嵌 CDN**: L2313 注入
   `https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js`。
   纯文本断言不触发它; **但任何用浏览器（含 Chrome headless PDF）打开该 HTML 的验证都会出网**。
   → 离线验收**只允许「读文本 + 断言字符串」**, 禁止 headless 打开产物 HTML。
2. **`_render_html_to_pdf` 必须打桩**（L2510-2572 真拉起 Chrome 子进程, `timeout=60`）。
   golden 装置与新增单测一律 monkeypatch 掉, 走 `tests/analytics/test_factor_status.py:236-243` 的既有写法。
3. **外层哨兵**: 每次跑测试前用独立于 pytest 的哨兵阻断非 loopback 出口, 并在汇报里给出计数; 计数必须为 0。
4. **live 门禁是两层, 不是一层**: `pyproject.toml:73` 的 `-m "not live"` 会被命令行 `-m` 整体覆盖,
   真正生效的是 `tests/conftest.py:475` 的收集期门禁（只被正向点名 `live`/`integration` 才留）。
   拆分过程中**不得新增任何不带 `live` 标记却实际出网的新增用例**。
5. **黄金样例出处纪律**: 新增 HTML golden 必须写清输入来源（`__self_test_dict` 构造, 非实盘）、
   归一化规则、以及「不落盘 PDF 与报告」; 缺失的实盘标量**缺键不补**, 沿用
   `docs/10` Phase 1H 记录的 002353 `curation` 口径。
6. **`reports/` 产物**: 本计划全程**不产生新的 `reports/` 跑批产物**; 每次验收前后应核对
   `reports/` 现有条目 sha256 逐字节未变（`docs/10` Phase 1I/1J 使用的同一口径）。

---

## 十、明确不动范围

| # | 不动 | 理由 |
|---|---|---|
| 1 | `analysis/html_report.py`（V2, 529 行） | 只作为 4 个 `_svg_*` 的提供方被调用, 4 个调用点全在主函数; V2 属 deprecated 沿用线（同 P2-A §五） |
| 2 | `analysis/sections/**`（Registry + `registry.yaml` + 5 个 Section） | 灰度机制本身不在本次范围; 只保证 H10 的调用位置与降级不变 |
| 3 | `analysis/analytics/factor_status.py` | `factor_notes_from_sources` / `notes_summary` 是上游依赖, HTML 侧只调不改 |
| 4 | 6 个 `_module_X` 的字段口径、业务阈值、全部展示文案 | §1「不修改业务口径」 |
| 5 | `result_v3` 键集契约 / `scoring_breakdown` 结构 / `three_levels` 结构 | 上游 `result_builder` / `three_levels` 的契约, HTML 侧只读 |
| 6 | 5 状态机与 `trading_plan.template_used` 口径 | 归 `analysis/trading_plan.py`, 超出本计划 |
| 7 | PDF 的 Chrome 探测路径顺序（L2532-2550, 4 条硬编码 + `shutil.which` 兜底） | 行为面, 动它等于换实现 |
| 8 | **不把 6 个 `_module_X` 改造成 dispatch table / 循环注册** | 那是结构重设计, 会改 `blocks` 装配顺序（Y2）; 收益不抵风险, 列为后续独立议题 |
| 9 | `analysis/reporting/artifact_writer.py` 的裸 `import html_report_v3`（L86-91） | H6 硬约束 |
| 10 | `.github/workflows/ci.yml` 与 `pyproject.toml` 的 lint / marker / addopts 配置 | 门禁本身不得被本次拆分改动 |
| 11 | `md_to_docx.py` | P2-A §五 line 75 明确另立 plan |
| 12 | `docs/08-规范整改-plan.md` / `docs/08-规范整改-P2A-模块拆分-plan.md` / `docs/10-*` | 本次只新增本文件, 不改既有文档; 收官同步另行提 |

---

## 十一、回滚与验收门槛

### 11.1 回滚

- 每片 1 commit, 无跨片强制依赖 —— 任一片出问题 = `git revert` 单个 commit 即可回到上一片自洽态
  （因为每片收官时 golden 已绿, 前一片本身就是完整可交付状态）。
- **不 squash 跨片合并**: S8 收官时若 golden 仍逐字节相同, 保留全部中间 commit 以便二分定位。
- **禁止通过「更新基线 sha256」掩盖回归**。若某片 golden 不一致, 必须先判定是
  「volatile 字段漏掩码」还是「真行为漂移」; 只有能指出**哪一个字节、对应哪一行模板、
  为什么语义上等价于原行为**时才允许更新基线, 并写进本文件。
- 遇到 S5（H2/H8 契约迁移）受阻: 允许把 S5 拆成 S5a（先加 fixture + 改测试, 不搬代码）和
  S5b（再搬 `_render_checklist`/`_render_risk`）, 不允许把 H2 的测试改成放宽断言来「变绿」。

### 11.2 收官验收门槛

- [ ] `analysis/html_report_v3.py` **< 400 行**（对标 P2-A §六）
- [ ] 10 个新模块无一带走业务逻辑; 其中 7 个落在规范 §2 的 300-500 行区间,
      `html_summary`(~188) / `html_appendix`(~101) / `pdf_render`(~63) 有意低于下限并已在 §五 说明
- [ ] **归一化 HTML sha256 与 S0 基线逐字节相同**（跨全部 9 片, 一路不变）
- [ ] 全量 Pytest `passed` 不减、**`skipped` 数与拆分前完全一致**
- [ ] Critical Ruff `--select=E9,F63,F7,F82` 全绿; full ruff advisory 无新增告警
- [ ] 9 个 commit（1 片 1 commit）, 中途片全部自洽可交付
- [ ] 硬约束 H1-H10 逐条仍绿（7 + 3 + 8 + 4 + 7 + 1 个测试/断言点全部复查）
- [ ] 离线哨兵计数 0; 600693 + 002353 smoke 单独跑通（需网络授权）
- [ ] `reports/` 现有条目 sha256 逐字节未变

---

## 十二、顺带发现（需老板单独拍板, **不在本计划执行范围**）

- **`_state_of(score_total)`（L1244-1249, 6 行）实测全仓库零调用点** —— 定义存在, 但主函数用的是
  `_state_key_of`(L1252-1274), 仓库内无任何其他引用（已用全仓字面量检索确认）。
  这是**死代码, 但本次拆分一律原样搬走、不删**: 删除是行为面清理, 混进结构拆分会让「逐字节不变」
  这个判据失效。若要删, 另开单片单独决策。

---

## 十三、签字栏

- 立项: Mavis 2026-10-04 14:17（补 `docs/08-规范整改-P2A-模块拆分-plan.md:74` 缺失的专属 plan）
- 拍板: 老板（待批）
- 开工条件: 老板「开干」后**从 S0 开始**（golden 基线装置必须先落地, 否则后续 8 片无法证明行为不变）
- 审查安排: 全部由 MiniMax 独立只读验收; 不安排 Kimi
