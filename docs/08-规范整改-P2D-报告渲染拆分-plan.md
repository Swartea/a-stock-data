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

### 2.1 行数口径（全文唯一定义，先于任何行数结论）

`analysis/html_report_v3.py` 物理总行数 **2771**（`wc -l` 实测）。全文出现三种行数，
**只有「符号行」允许参与模块行数比较**：

| 名称 | 定义 | 唯一允许用途 |
|---|---|---|
| **符号行**（唯一迁入口径） | 逐个顶层符号（`def` / 模块级常量 / `if __name__` 块）的 AST 声明块行数 `end_lineno - lineno + 1`；装饰器计入所属符号，docstring / 注释 / 块内空行一并计入 | §五「迁入行数」与 §11.2「300-500 区间」**只准用它** |
| 物理区间行 | §2.2 表「行区间」列的跨度，**含**区块前导横幅与符号之间的空行 | **只用于定位代码位置**，不得当作迁入量或模块大小 |
| 残留文件行 | 拆分后 `html_report_v3.py` 的文件行数（文件头 + import + re-export + 主函数 + `__main__` 转发） | **只用于** §11.2「< 400 行」门槛 |

符号行**不含**符号之间的 `# ===...` 分隔横幅与空行 —— 那些行要么留在原文件，要么在新文件里
重新写，**都不是搬移量**。本计划此前把「物理区间行」和「符号行」混着写进「迁入行数」列
（`html_primitives` 记 312、`html_risk` 记 172、`html_modules` 记 404…），
导致同一列出现 5 处互斥数字（§五 已全部改为符号行）。

三段账必须自洽：

- 17 个区块物理合计 **2737**; 区块间共 34 行（`52/65/150-151/253-254/294-295/…/2222-2227/2508-2509/2573-2574` 等）,
  多数是空行, 其中 **L2222-2227 含 3 行 `# ===` 横幅**（主函数前）, 合计 2737 + 34 = **2771** ✅
- 区块 2-17 的**符号行合计 2531**; 区块 1 符号行 43（文件头 docstring L2-22 + `import` L23-26 + L28 + 双路径 try 块 L32-51）, **保持原位不迁移**。
- **迁入总计 = 2531 − 主函数 280（留在薄壳）= 2251 符号行** = §五 十个新模块迁入行数之和 ✅
- 符号行小计 2531 + 43 = 2574; 物理 2737 − 2574 = **163 行** = 区块 **2-17 内部**的横幅与空行（2686 − 2531 = 155）
  + 区块 1 前导的 8 行（L1 与 docstring 前空行等）, **均不迁移**。

### 2.2 区块地图（物理区间用于定位，符号行用于比较）

| # | 区块 | 行区间(物理) | 物理行 | **符号行** | 关键符号（括号内为符号行区间） |
|---|---|---|---|---|---|
| 1 | 文件头 + 依赖导入 | 1-51 | 51 | *不迁移* | `import html_report as hr` (L28)；双路径 import `analysis.analytics.factor_status` (L32-41) 与 `sections.enabled_sections` (L45-51) |
| 2 | 语义色板 | 53-64 | 12 | **8** | `C_RED`…`C_GRAY` (L57-64)；L53-56 是段头注释 |
| 3 | 通用小工具 | 66-149 | 84 | **64** | `_esc`(70-75) `_clean_fname`(78-81) `_num`(84-94) `_num_or_dash`(97-99) `_first`(102-108) `_parse_date`(111-119) `_days_between`(122-127) `_is_error`(130-141) `_svg_safe`(144-149) |
| 4 | 错误提取 + 缺失模块降级 | 152-252 | 101 | **84** | `_MODULE_SCORE_WEIGHT`(161-169) `_blob_to_error_str`(172-180) `_source_error_msg`(183-202) `_extract_error_msg`(205-214) `_render_missing_module`(217-252) |
| 5 | 时点推导 | 255-293 | 39 | **31** | `_source_time`(259-279) `_blob_time`(282-289) `_time_label`(292-293) |
| 6 | 文本标签 + 语义配色 | 296-359 | 64 | **50** | `_trunc`(300-302) `_signal_text`(305-312) `_signal_direction`(315-329) `_rating_color`(332-343) `_sentiment_color`(346-353) `_sentiment_tag`(356-359) |
| 7 | **静态资产（CSS / JS）** | 362-1013 | **652** | **634** | `_CSS`(366-479, 114行) `_MINGLI_CSS`(484-610, 127行) `_ECHARTS_JS_TEMPLATE`(614-880, 267行) `_CSS_HEAD`(883-937, 55行) `_HERO_STYLE`(939-943, 5行) `_hero_style`(946-955, 10行) `_checklist_css()`(958-1013, 56行) |
| 8 | 图表数据 + ECharts 卡片 | 1016-1154 | 139 | **115** | `_chart_card`(1020-1031) `_kline_to_rawdata`(1039-1050) `_markline_data`(1053-1070) `_markpoint_data`(1073-1093) `_render_echarts_kline_block`(1096-1117) `_render_echarts_tech_block`(1120-1122) + `_ECHARTS_KLINE_CARD_HTML`(1126-1135) `_ECHARTS_TECH_CARD_HTML`(1138-1154) |
| 9 | hero 结论区 + 5 状态判定 | 1157-1274 | 118 | **112** | `_a_share_verdict_mark`(1157-1166) `_render_hero`(1169-1241) **`_state_of`(1244-1249)** `_state_key_of`(1252-1274) |
| 10 | 5 维评分构成卡片 | 1277-1364 | 88 | **76** | `_BREAKDOWN_RENDER_KEYS`(1285-1291) `_scoring_breakdown_color`(1294-1304) `_render_scoring_breakdown`(1307-1364) |
| 11 | **操作检查清单** | 1367-1538 | **172** | **172** | `_render_checklist`（单函数 172 行 = **全文最长的非主函数**; 主函数 280 行更长; 内含 `CHECKLIST_5T` 与 `items5` 块 L1528-1533） |
| 12 | 风险警报 | 1541-1712 | 172 | **170** | `_risk_items`(1541-1668, 128) `_render_risk`(1671-1712, 42)；两符号间 2 行空行不迁移 |
| 13 | **6 块内容模块** | 1715-2118 | **404** | **386** | `_src_tag`(1715-1718) `_module_research`(1725-1793) `_module_announcements`(1796-1825) `_finance_comment`(1828-1849) `_module_finance`(1852-1912) `_module_peer`(1915-1998) `_module_margin`(2001-2049) `_module_news`(2052-2118) |
| 14 | 附录（抽屉 + run_log） | 2121-2221 | 101 | **95** | `_detail_drawer`(2125-2178) `_render_run_log`(2181-2221) |
| 15 | **主函数** | **2228**-2507 | **280** | **280** | `write_html_report_v3`；**L2224-2227 是主函数前的 4 行横幅，不属于函数体**（此前记 2224 起 / 284 行是把横幅算进了函数） |
| 16 | HTML → PDF | 2510-2572 | 63 | **63** | `_render_html_to_pdf`（真实拉起 Chrome headless 子进程；`import subprocess` 在**块内** L2522） |
| 17 | 自测脚手架 | 2575-2771 | 197 | **191** | `_self_test_dict`(2579-2726, 148) + `if __name__ == "__main__":` 自检块 (2729-2771, 43)；`import random` 在**块内** L2581 |
| — | **合计** | — | **2737** | **2531**（区块 2-17） | 块间空行 34 → 2771 ✅ |

> **UNVERIFIED（未在仓库核实，不作已证事实引用）**：`_CSS`/`_MINGLI_CSS`/`_ECHARTS_JS_TEMPLATE`/`_CSS_HEAD`
> 的字符数、§二 末「引用 33 个模块级符号」这个依赖数、以及 300-500 区间的**外部规范版本号**。
> 这三项本次未跑脚本/未联网复核，正文凡引用处一律标 UNVERIFIED，不写入验收门槛。

结构性事实（对本计划的设计起决定作用）:

- **静态资产占 634 符号行 = 区块 7 物理 652 行, 是最大的单块, 且**零业务逻辑** —— 最低风险起步点。
- **`write_html_report_v3` 单函数 280 符号行（L2228-2507）, 是唯一的耦合中枢**; 它引用的模块级符号数记为
  **UNVERIFIED**（本次未用 ast 复算, 不写进验收门槛）。
- **6 个 `_module_X` 签名完全同构**: `(result, report_date, run_log) -> (src_line, inner)`,
  由 L2388-2390 的循环统一消费 —— 天然的横向切分缝。
- 纯叶子层（无模块级依赖）: `_esc` `_clean_fname` `_num` `_first` `_parse_date` `_is_error`
  `_svg_safe` `_trunc` `_rating_color` `_sentiment_color` `_finance_comment` `_kline_to_rawdata`
  `_markline_data` `_markpoint_data` `_a_share_verdict_mark` `_state_of` `_state_key_of`
  `_scoring_breakdown_color` `_render_html_to_pdf` —— 共 19 个（`_state_of` 虽零调用, 但依赖面上仍是叶子）,
  先搬它们最安全。

---

## 三、耦合地图: 谁依赖谁

按 `ast` 逐函数抽取的模块级依赖（`deps` 列只列本文件内符号）:

| 被搬区块 | 扇入（谁在用它） | 扇出（它还要什么） | 耦合强度 |
|---|---|---|---|
| 静态资产 (7) | `write_html_report_v3` 读 4 个常量 + `_checklist_css()`; **另: `_render_hero`(L1175) → `_hero_style()`, `_hero_style`(L952/954/955) → `_HERO_STYLE`** | 无 | **零**（纯字符串） |
| 通用小工具 (3) | 全文件 18 个函数中的 11 个 | 无 | 低（叶子） |
| 错误降级 (4) | 6 个 `_module_X` + `_risk_items` | `_esc` | 中（6+1 处扇入） |
| 时点 (5) | `write_html_report_v3` + 5 个 `_module_X` + `_chart_card` + `_src_tag` | `_esc` | 中（7 处扇入） |
| 标签配色 (6) | `_render_checklist` + `_module_*` | `_first` `_esc` `_sentiment_color` | 低 |
| 图表 (8) | `write_html_report_v3` + 测试直接 import | 无 | 低 |
| hero/状态 (9) | `write_html_report_v3` | `_hero_style` `_HERO_STYLE` `_a_share_verdict_mark` `_esc` `_first` `_num` | 中 |
| 评分构成 (10) | `write_html_report_v3` | `_esc` `_num` `_scoring_breakdown_color` | 低 |
| 检查清单 (11) | `write_html_report_v3` | `_esc` `_first` `_num` `_signal_direction` `_signal_text` `_trunc` | 中（**读 `result["trading_plan"]["template_used"]`** L1384/L1417） |
| 风险 (12) | `write_html_report_v3` | `_days_between` `_extract_error_msg` `_is_error` `_num` `_trunc` | 中 |
| 6 模块 (13) | `write_html_report_v3` | 4+5 类共享 helper | **高（13 个依赖, 彼此间无依赖）** |
| 附录 (14) | `write_html_report_v3` | `_esc` `_is_error` `_num` `_num_or_dash` `_first` `_trunc` + `C_RED_DK`/`C_GREEN_DK` | 低 |
| PDF (16) | `write_html_report_v3` | **模块级 `os`(L25) / `math`(L24) / `re`(L26) + 块内局部 `os`(L2521) `subprocess`(L2522) `shutil`(L2545)** | 零（无同文件符号依赖） |
| 自测 (17) | 仅本文件 `__main__` | **模块级 `math`(L24) + 块内局部 `random`(L2581)** | 零 |

> ⚠️ `os` / `math` / `re` 是**文件头模块级 import**（L23-26），不是块内局部 import。搬块到新模块时
> 这些名字要在**新模块顶层**各自 import；不能依赖「原文件已经 import 过」。
> **块内局部 import 共 7 处**（`grep -n '^\s\+import'` 实测, 搬块时逐处对照, 漏一处即 NameError）:
> `json as _json`(L1109, 图表块) / `json as _json`(L2472, 主函数) / `sys as _sys`(L2504, 主函数) /
> `os`(L2521, PDF) / `subprocess`(L2522, PDF) / `shutil`(L2545, PDF) / `random`(L2581, 自测)。
> 另: L33/38/46 的 `from ... import` 在**模块级 `try:` 块**内, 属 H9 双路径 import 模式, 不是块内局部。

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
| **H1** | `inspect.getsource(write_html_report_v3)` 必须仍含字面量: `echarts@5.5.1`/`echarts.min.js`、`_MINGLI_CSS`、`<nav class="top-nav">`、`id="themeToggle"`、`<div class="v3-stock-report">`、`v3-stock-report-theme`、`light-mode`、`localStorage`、`☀️ 浅色模式`、`🌙 深色模式` | `tests/test_html_ui_template.py:109-191`（**7 个测试 = 6 个 `inspect.getsource(write_html_report_v3)` + 1 个 CSS 长度断言** `test_mingli_css_size_reasonable` L137-141 断言 `8000 <= len(_MINGLI_CSS) <= 15000`, 它读模块对象不走 getsource） | **`write_html_report_v3` 必须继续定义在 `analysis/html_report_v3.py`**, 且 L2313/L2314/L2315/L2328/L2339/L2434-2452 这些字面量不得外移 |
| **H2** | 读 `analysis/html_report_v3.py` **全文**做正则审计: ①`for label, txt in items5:.*?</ul>` 块须含 `_esc(label)` 与 `_esc(txt)`; ②`def _render_risk\(rows\):(.*?)return.*?join\(h\)` 须 ≥5 处 `_esc(`; ③全文 `h.append(...%(result|it|x|b|a).get(...))` 命中数 < 5 | `tests/test_html_escape_audit.py:102-137`（3 个测试, L104/116/128 均**硬编码** `(WORKDIR / "analysis" / "html_report_v3.py").read_text()`, **不走 fixture**) | 见下方 **H2 拆分退化风险**（必须同片修） |
| **H3** | `from html_report_v3 import _MINGLI_CSS`（裸模块名） | `tests/test_html_ui_template.py:29` | `_MINGLI_CSS` 搬走后必须在 `html_report_v3` 顶层 re-export |
| **H4** | `from html_report_v3 import _esc`（裸模块名）+ **9 个** `_esc` 行为用例（`&` 必须先于 `<` 转义等） | `tests/test_html_escape_audit.py:19-97`（9 个: `test_esc_basic_amp_lt_gt` `test_esc_quotes` `test_esc_ampersand` `test_esc_none_safe` `test_esc_passthrough_safe_text` `test_esc_empty_string` `test_esc_img_onerror` `test_esc_javascript_url` `test_esc_event_handlers`） | `_esc` 必须在 `html_report_v3` 顶层 re-export, **且 5 步替换顺序一字不改** |

### H2 拆分退化风险（S5 必须同片修，否则门禁静默假绿）

这 3 个测试现在只读**一个硬编码文件路径**。拆分推进后若不改读法:

| 测试 | 退化方式 | 是否会自己报警 |
|---|---|---|
| ① `test_audit_checklist_5state_uses_esc` | `_render_checklist` 搬走后正则找不到块 | **会**（`assert m, "P1-A 5 项 checklist 块未找到"` 直接红） |
| ② `test_audit_risk_table_uses_esc` | `_render_risk` 搬走后正则找不到块 | **会**（`assert m, "_render_risk 未找到"` 直接红） |
| ③ `test_audit_no_unscaped_user_text_in_template` | 薄壳只剩 ~380 行，正则命中数自然趋近 0，`len(bad) < 5` **更容易通过** | **不会 —— 静默假绿** ⚠️ |

③ 是本次拆分唯一「搬得越多、门禁越松」的判据。S5 的修法（**不改动原 `< 5` 语义阈值**）:

1. conftest 新增 `html_split_source` fixture: 拼接「薄壳 + 10 个新模块」全文，**S5 之前**它等价于读单文件。
2. 3 个测试改读该 fixture（复用 P2-A 既有 `*_source` 模式: `report_md_source`/`pipeline_source`/`result_builder_source` 在 `tests/conftest.py:99/112/125`）。
3. **加最小覆盖断言, 让判据随代码搬迁保持有效**:
   - 断言扫描面**包含 4 个宿主符号**: `_render_checklist` `_render_risk` `write_html_report_v3` `items5`（缺任一即红）；
   - 断言扫描面**总行数 ≥ 2600**（拆分前 2771 的 ~94%; 允许 import/空行churn, 低于此说明有模块没被纳入扫描面）。
4. 因此无论 ① ② ③ 的宿主代码搬到哪个文件, 判据都**跟着走**; 若将来有人把新模块漏出扫描面, 覆盖断言先红, 而不是让 ③ 假绿。

> `tests/conftest.py` 的 S5 改动说明: 该文件新增的 7 个 `*_source` fixture（`quant_analyzer_v3_source` L72 / **`html_report_v3_source` L81（已存在, 读 `analysis/html_report_v3.py`）** / `md_to_docx_source` L90 / `report_md_source` L99 / `pipeline_source` L112 / `result_builder_source` L125）+ live 选择门禁（L382-475）**已随 `1c053e1` 提交, 当前工作区干净**。S5 追加 `html_split_source` 时**保留现状、不重排既有 fixture**, 只在文件尾追加; 若与在途改动重叠, 先与在途改动对齐再动。
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

| 新模块 | 迁入符号（源码行区间） | **迁入行数**（符号行） | 职责一句话 |
|---|---|---|---|
| `analysis/reporting/html_primitives.py` | 色板 (57-64) + 小工具 (70-149) + 错误降级 (161-252) + 时点 (259-293) + 标签配色 (300-359) + `_chart_card` (1020-1031) | **249** | 无业务语义的地基: 转义 / 数值 / 字段回退 / 时点 / 配色 / 缺失降级 |
| `analysis/reporting/html_theme.py` | `_CSS`(366-479) `_MINGLI_CSS`(484-610) `_CSS_HEAD`(883-937) `_HERO_STYLE`(939-943) `_hero_style`(946-955) `_checklist_css`(958-1013) | **367** | 主题 CSS + token + 响应式覆盖 |
| `analysis/reporting/html_charts.py` | `_ECHARTS_JS_TEMPLATE`(614-880) `_ECHARTS_KLINE_CARD_HTML`(1126-1135) `_ECHARTS_TECH_CARD_HTML`(1138-1154) `_kline_to_rawdata`(1039-1050) `_markline_data`(1053-1070) `_markpoint_data`(1073-1093) `_render_echarts_kline_block`(1096-1117) `_render_echarts_tech_block`(1120-1122) | **370** | ECharts JS 模板 + 4 个占位符的数据装配 + 2 张卡片模板 |
| `analysis/reporting/html_summary.py` | `_a_share_verdict_mark`(1157-1166) `_render_hero`(1169-1241) **`_state_of`(1244-1249)** `_state_key_of`(1252-1274) `_BREAKDOWN_RENDER_KEYS`(1285-1291) `_scoring_breakdown_color`(1294-1304) `_render_scoring_breakdown`(1307-1364) | **188** | 「30 秒决策」区: hero 结论 + 5 维评分构成（含零调用的 `_state_of`, 见 §十二） |
| `analysis/reporting/html_checklist.py` | `_render_checklist`(1367-1538) | **172** | 操作检查清单（5 状态机文案） |
| `analysis/reporting/html_risk.py` | `_risk_items`(1541-1668) `_render_risk`(1671-1712) | **170** | 风险事件归集 + 大表渲染 |
| `analysis/reporting/html_modules.py` | `_src_tag`(1715-1718) + `_module_research`(1725-1793) `_module_announcements`(1796-1825) `_finance_comment`(1828-1849) `_module_finance`(1852-1912) `_module_peer`(1915-1998) `_module_margin`(2001-2049) `_module_news`(2052-2118) | **386** | 6 块内容模块（研报/公告/财务/同业/两融/新闻） |
| `analysis/reporting/html_appendix.py` | `_detail_drawer`(2125-2178) `_render_run_log`(2181-2221) | **95** | 详细数据抽屉 + run_log 附录 |
| `analysis/reporting/pdf_render.py` | `_render_html_to_pdf`(2510-2572) | **63** | Chrome headless → PDF（唯一有副作用的块） |
| `analysis/reporting/html_self_test.py` | `_self_test_dict`(2579-2726) + `__main__` 自检块 (2729-2771) | **191** | 离线版式自测脚手架（**实测全仓库零外部引用**） |
| **合计** | | **2251** | = 区块 2-17 符号行 2531 − 留薄壳的主函数 280 ✅ |

**残留 `analysis/html_report_v3.py`（薄壳）**: 保留文件头依赖说明 + import (1-51)、
re-export 块、主函数 `write_html_report_v3` (**280 符号行, L2228-2507**) 与一个 3 行以内的 `__main__` 转发。

- 这是**残留文件行**（口径见 §2.1 第三行）, **不是迁入行数**, 不参与 300-500 比较。
- 机械估算: 51（文件头 + import）+ 280（主函数）+ re-export 块（**估 45-95 行, UNVERIFIED**, S8 实测为准）+ 3（`__main__` 转发）
  = **380-430 行**。
- S8 若把主函数内联的「6 块 + Registry 装配」和「ECharts 占位符替换」两段各抽成
  `html_modules._content_blocks()` / `html_charts.build_echarts_js()`, 降到 **330-360 行**,
  满足 `docs/08-规范整改-P2A-模块拆分-plan.md:80`「v3 主文件 < 400 行」的对标门槛。

**关于 300-500 区间（口径与来源必须写准）**:

- **来源**: `docs/08-规范整改-P2A-模块拆分-plan.md:81`「6 个新模块各自 300-500 行」+ 同文件 `:80`「v3 主文件 < 400 行」。
  ⚠️ **`docs/08-规范整改-plan.md` §二（目标）里没有任何 300-500 条款** —— 该文件 §二 全文只有一句
  「按规范整改, 让项目符合 §1-12 验收要求, P0 必修 + P1 必改 + P2 配套」; 引用时**不要**写成 docs/08 §2。
  P2A 是 6 个模块, 本计划是 10 个, 区间本身是**同一门槛的沿用**, 不是新规范。
- **实测（符号行口径）**: 落在 300-500 的**只有 3 个** —— `html_theme` 367 / `html_charts` 370 / `html_modules` 386。
  **不是 7 个。**
- **低于 300 的共 7 个, 完整列出**:
  `html_primitives` 249 / `html_summary` 188 / `html_self_test` 191 / `html_checklist` 172 /
  `html_risk` 170 / `html_appendix` 95 / `pdf_render` 63。
- ⚠️ **口径陷阱**: 若按拆分前那份**混口径**表（`primitives` 记 312、`modules` 记 404、`risk` 记 172…）统计,
  会得到「4 个在区间内 / 6 个低于 300」。那是**旧算术的残留, 已作废** —— 统一到符号行口径后
  **`html_primitives` 从 312 降到 249（掉出区间）**, 故是 3/7, 不是 4/6。**任何单一口径都算不出 4/6**。
- **低于下限是有意的**: 各自是单一内聚职责, 硬凑行数只会引入填充代码。沿用 `docs/10` Phase 1J 已确立的口径
  （`docs/10-pipeline拆解地图-phase1a.md:281`「本阶段的价值是**边界与可测性, 不是行数**」, 同文件
  `:274-282` 记录 1J「本次刻意没有再降行数（如实记录）」: 搬走的是**短但 seam 密集**的一段, 函数口径反增 +3 行仍判定为正收益）。
  **行数是参考, 边界与可测性是硬要求。**

---

## 六、拆分顺序: 9 片可审查 checkpoint（**不自动获得提交授权**）

排序原则: **零行为面 → 叶子层 → 被 H2/H8 源码文本契约锁住的块 → 收官**。
把最安全的静态资产放第一片, 先验证「搬文件不改行为」这个模式本身; 把唯一有契约风险的两个块
（checklist / risk）压到 golden 兜底已经就位之后。

| # | 片 | 内容（行数=符号行, §2.1） | 触及硬约束 |
|---|---|---|---|
| **S0** | 冻结基线 | **不改源码**。建离线 golden HTML 回归装置（见 §七） | 无 |
| **S1** | `html_theme` | 搬 367 符号行静态 CSS | H3（`_MINGLI_CSS` re-export）、H9 |
| **S2** | `html_primitives` | 搬 249 符号行地基 | H4（`_esc` re-export + 替换顺序） |
| **S3** | `html_charts` | 搬 370 符号行 ECharts 装配 | H7（5 个符号 re-export） |
| **S4** | `html_summary` | 搬 188 符号行 hero + 评分构成（**含 `_state_of`**） | H1（主函数仍在本文件） |
| **S5** | `html_checklist` + `html_risk` | 搬 172 + 170 = **342** 符号行；**同片**给 conftest 加 `html_split_source` fixture（拼接薄壳 + 全部新模块）+ 覆盖断言，把 H2 的 3 个 + H8 的 1 个源码文本测试改读新 fixture | **H2 + H8（唯一有风险的片）**, 见 §四「H2 拆分退化风险」 |
| **S6** | `html_modules` | 搬 386 符号行 6 块 | H2③ 扫描面进一步缩小, 覆盖断言必须已生效 |
| **S7** | `html_appendix` + `pdf_render` | 搬 95 + 63 = 158 符号行 | **H5**（`_render_html_to_pdf` 必须留在 `html_report_v3` 模块全局里） |
| **S8** | `html_self_test` + 薄壳收官 | 搬 191 符号行自测；主函数两个可选内联块抽出；薄壳 re-export 固化并**实测**残留行数 | H1/H5/H6/H7 全部收口 |

每片统一形态（沿用 `docs/10` Phase 1C/1D 已验证的「先搬后接、同片删原地」模式）:

1. 新建模块, 机械搬入符号（**不改函数体**; 跨模块引用改成 import）;
2. 新模块建自己的单测（只测搬入符号, 不测主流程）;
3. `html_report_v3.py` 改为 import + re-export, **同片删除原地定义**;
4. 跑 §七 全部验收门禁。

**硬规则: 禁止新旧两套实现并存**。并存会让本片回滚不干净, 也会让下一片无法判定基线。

### 6.1 版本控制纪律（**默认不 stage / 不 commit / 不 push**）

- 每片交付形态是**可审查、可回滚的 checkpoint**: 老板可直接看工作区 diff, 逐片拍板。
- **默认不执行 `git add` / `git commit` / `git push` / `git merge` / `git reset` / `git clean`**。
  本计划不因"写进了文档"就自动获得提交授权。
- **回滚手段**: 开工前留**本片前工作区快照**, 或用 `git diff` 生成的 patch 反向应用;
  **不依赖 `git revert`（无提交就无从 revert）**。
- 只有老板**逐片明确授权**后, 才另论提交粒度与合并方式; 未授权前不 squash、不合并、不整理历史。
- 依据: `docs/10` Phase 1J（`docs/10-pipeline拆解地图-phase1a.md`）的拆分是按 checkpoint 逐段验收的,
  并不以 commit 数为验收项; P2A 验收栏里的「9 commits」是 **P2-A 自身的历史约定, 不自动延伸到 P2-D**。

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
  **两个时间戳的归一化口径必须分开写清**:
  - `gen_now` = **正文内容字段**, 会渲染进 HTML → 用固定占位符（如 `{{GEN_NOW}}`）整串替换后取 sha256;
  - **文件名里的时间戳**（L2246 `{code}-{name}-v3-{YYYYMMDD}-{HHMM}`）**只进路径、不进正文** →
    归一化时**不改正文**, 也不把文件名纳入比对; 若需要可比对文件名, 单独对**时间戳段**做掩码后再比。
  - 已核实**其余内容字段全部确定**: `report_date` 优先取 `result["report_date"]`（L2239-2241,
    缺失才回退 `now()` —— 故 fixture 必须显式带 `report_date`, 否则这条回退会引入第二个时间源。
- **PDF 必须打桩**: `monkeypatch` 掉 `_render_html_to_pdf`（`tests/analytics/test_factor_status.py:236-243`
  已有先例, 注释写明 Chrome PDF 渲染约 15s/次）。**不落盘生成的 PDF 与报告**。
- **确定性自证（必须跨进程, 同进程连跑两次不算）**:
  「同一输入在同一进程里连续渲染两次」**证明不了确定性** —— 同一进程共享 `sys.modules`、已 import 的模块级缓存、
  同一个 `random`/`datetime` 单例状态, 且 `PYTHONHASHSEED` 只有一个值。**dict / set 迭代序在
  hash 随机化下换进程就可能变**, 而 `_self_test_dict()` 构造的 result 嵌套 dict 极多。
  装置必须满足:
  1. **两个独立子进程**（`subprocess` 起 `python -c` 或独立 pytest 进程, **不是两个函数调用**）;
  2. **两个进程各自显式设不同的 `PYTHONHASHSEED`**（例如 `PYTHONHASHSEED=0` 与 `PYTHONHASHSEED=12345`）;
  3. 两个进程各渲染一次 `_self_test_dict()` → 归一化 → 各自输出 sha256;
  4. **两个 sha256 必须相等**, 且该值才写进本文件作为 S1-S8 的比对基线。
  哨兵自检只允许打 **loopback**（`127.0.0.1`/`::1`）; 子进程渲染本身不触网, 也不得加载任何 fixture 依赖的出网路径。

### 7.2 每片的 6 道门禁（全部通过才算这片完成）

| # | 门禁 | 命令 / 判据 |
|---|---|---|
| 1 | **golden 逐字节** | 归一化 HTML sha256 与 S0 基线**完全相同** |
| 2 | **全量 Pytest** | `passed` 只增不减; **`skipped` 数与本片开工前完全一致（无新增 skip）** —— 这条是 `docs/10` Phase 1I/1J 已确立的验收口径。**基线来源**: Phase 1J 文档记录的 **779 passed / 9 skipped**（`docs/10-pipeline拆解地图-phase1a.md:284`, Phase 1J 小节起于 `:227`）—— 这是**历史基线, 本次未重跑, 不作本次实测声明**。⚠️ 其后 `1c053e1` 又新增 **9 个 `tests/*.py`**（该 commit 共 27 文件 +7052 行, 其中测试 `.py` 净增 4386 行）, 故**当前实际数必然已变**; S0 开工时必须**实测**并把新基线写进本文件, 不可沿用 779/9 |
| 3 | **Critical Ruff** | `ruff check analysis tests --select=E9,F63,F7,F82` 全绿（`.github/workflows/ci.yml:38`）; full ruff advisory（`ci.yml:44`）**无新增告警** |
| 4 | **Python 矩阵** | Ubuntu 3.10 / 3.11 / 3.12 + macOS 3.12（`ci.yml:92-98`）; `pyproject.toml:94` `target-version = "py310"`, `pyproject.toml:95` `line-length = 100`（注: `pyproject.toml:136-137` 另有一处 ruff 配置, `:136` line-length / `:137` target-version, 两处需保持一致） |
| 5 | **源码文本契约** | 第四节 H1-H8 全部仍绿, 逐项计数: `inspect.getsource` **6 项** + CSS 长度断言 **1 项**（合 H1 共 7 个测试）/ raw-regex 转义审计 **3 项**（H2, 且必须带 §四 的最小覆盖断言）/ `_esc` 行为 **9 项**（H4）/ `sys.modules` 假模块 **4 处**（H6）/ 直接 import 符号 **7 个**（H7 列出 6 个: `_kline_to_rawdata`/`_markline_data`/`_markpoint_data`/`_render_echarts_kline_block`/`_render_echarts_tech_block`/`_render_html_to_pdf`; 第 7 个是 `_MINGLI_CSS`, 已由 **H3** 覆盖, 计数时别漏也别重复） |
| 6 | **离线门禁** | 跑测试前用**独立外层哨兵**阻断非 loopback 出口并报告计数; 计数必须为 0。live 门禁共**三层**, 都要确认生效: ①`pyproject.toml:71` 的 `-m "not live"`（**只是默认值**, 命令行任意 `-m` 会整体覆盖它, 见 `pyproject.toml:62` 注释）; ②`tests/conftest.py:475` `pytest_collection_modifyitems` 的收集期"整表达式 opt-in"选择层; ③用例级 `skipif`（要求 `DA_A_RUN_LIVE` **精确等于 `"1"`**, 口径见 `tests/conftest.py:413`; 且 `tests/test_fund_flow_domain.py:602` 已有断言「live 用例必须有 env skipif」） |

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
| **Y1** | **CSS token 与 class 名一字不能改**: `--up:#dc2626` / `--down:#16a34a`（红涨绿跌 A 股惯例）、`.hero.hero-bull`、`.chg-pill up`、`.adv-dot`、`.v3-stock-report`、`.light-mode`、`.top-nav` | 前 5 个（`--up`/`--down`/`hero hero-bull`/`chg-pill up`/`adv-dot`）由**自检 L2754-2762 直接断言**（含 `_a_share_verdict_mark` 的 bear→🟢 / bull→🔴 翻转映射, 该函数 L1157-1166）; 后 3 个（`.v3-stock-report` / `.light-mode` / `.top-nav`）**不由自检断言**, 由 **H1** 的 6 个 `inspect.getsource` 用例覆盖 |
| **Y2** | **区块顺序 + emoji 逐字**: 研报观点 📚 / 公告速览 📢 / 财务体检 🩺 / 同业对比·行业定位 🏭 / 资金面（融资融券）💰 / 新闻舆情 📰, 且 Section Registry 5 新节**追加在 6 块之后**（不替换） | L2380-2387 列表 + L2391-2407 循环; 自检 L2750-2752 断言 6 个标题（L2750 键名 + L2751 标题元组, 闭合括号在 L2752） |
| **Y3** | **来源与时点标注计数**: `html_src.count("数据源：") >= 6`、`html_src.count("数据截止") >= 4` | 自检 L2752-2753; 依赖 `_src_tag`(L1715) 与各 `_module_X` 的 `src_line` 文案与 `_chart_card` 的 `asof` 位置 |
| **Y4** | **SVG 数量恰为 4**（4 张 V2 SVG, ECharts 卡不是 svg） | 自检 L2740/L2743; 依赖 `hr` 的 4 个 `_svg_*` 返回空串时 `_svg_safe` 降级为「数据源暂缺」而非多/少一张 |
| **Y5** | **`_esc` 5 步替换顺序**（`&` 必须最先, 否则 `&lt;` 二次解析） | L70-75; `tests/test_html_escape_audit.py:38-42` 钉死 `A & B → A &amp; B` |
| **Y6** | **ECharts 4 个占位符** `__RAW_DATA__`/`__PIE_DATA__`/`__MARKLINE__`/`__MARKPOINT__` + **kline 空分支行为**: `kline` 为空时 4 个占位符**全部**置 `[]`, JS 仍可执行, **5 个图表都会显示 no-data**（不是「5 选 1」; 源码注释 L2481 原文即「JS 仍可执行, 5 图会显示 no-data」） | L2461-2486（`if kline:` 在 L2471, `else` 分支 L2480-2486） |
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
4. **live 门禁是三层, 不是两层**:
   - ① `pyproject.toml:71` 的 `-m "not live"` —— **只是 addopts 默认值**, 命令行任意 `-m` 会**整体覆盖**它
     （`pyproject.toml:62` 注释已写明这个坑）;
   - ② `tests/conftest.py:475` `pytest_collection_modifyitems` 收集期"整表达式 opt-in"选择层 ——
     打了 `live` 标记的用例只有当**生效的 `-m` 表达式整体**正向点名 `live`/`integration` 才留（fail-closed）;
   - ③ 用例自己的 `skipif` —— `DA_A_RUN_LIVE` **精确等于 `"1"`** 才真跑（口径见 `tests/conftest.py:413`）;
     `tests/test_fund_flow_domain.py:602` 已有断言「live 用例必须有 env skipif」守着这一层。

   三层都要确认生效。拆分过程中**不得新增任何不带 `live` 标记却实际出网的新增用例**。
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

- 每片是**可审查、可回滚的 checkpoint**, 无跨片强制依赖 —— 任一片出问题, 回到**本片开工前的工作区快照**
  即可回到上一片自洽态（因为每片收官时 golden 已绿, 前一片本身就是完整可交付状态）。
- **回滚手段二选一**: ① 本片开工前留的工作区快照; ② `git diff` 生成的 patch 反向应用。
  **不依赖 `git revert`** —— 默认不提交, 没有 commit 可 revert。
- **默认不 squash、不合并、不整理历史**。是否合并、是否压成一条, 由老板逐片拍板; 未授权前不动版本历史。
- **禁止通过「更新基线 sha256」掩盖回归**。若某片 golden 不一致, 必须先判定是
  「volatile 字段漏掩码」还是「真行为漂移」; 只有能指出**哪一个字节、对应哪一行模板、
  为什么语义上等价于原行为**时才允许更新基线, 并写进本文件。
- 遇到 S5（H2/H8 契约迁移）受阻: 允许把 S5 拆成 S5a（先加 fixture + 覆盖断言 + 改测试, 不搬代码）和
  S5b（再搬 `_render_checklist`/`_render_risk`）, 不允许把 H2 的测试改成放宽断言来「变绿」。

### 11.2 收官验收门槛

- [ ] `analysis/html_report_v3.py` **< 400 残留文件行**（对标 `docs/08-规范整改-P2A-模块拆分-plan.md:80`）
- [ ] 10 个新模块无一带走业务逻辑; 落在 300-500 **符号行**区间的**只有 3 个**
      （`html_theme` 367 / `html_charts` 370 / `html_modules` 386）;
      **低于 300 的 7 个已在 §五 完整列出并说明**: `html_primitives` 249 / `html_summary` 188 /
      `html_self_test` 191 / `html_checklist` 172 / `html_risk` 170 / `html_appendix` 95 / `pdf_render` 63
- [ ] **归一化 HTML sha256 与 S0 基线逐字节相同**（跨全部 9 片, 一路不变）;
      且 S0 基线本身已通过**跨进程双 `PYTHONHASHSEED`** 确定性自证
- [ ] 全量 Pytest `passed` 不减、**`skipped` 数与拆分前完全一致**（基线以 S0 实测为准;
      Phase 1J 文档记录的 779 passed / 9 skipped 仅为历史参考, 见 §7.2 门禁 2）
- [ ] Critical Ruff `--select=E9,F63,F7,F82` 全绿; full ruff advisory 无新增告警
- [ ] 9 个 checkpoint 全部自洽可交付; **提交与否以老板逐片授权为准**（本计划不自动 stage/commit/push）
- [ ] 硬约束 H1-H10 逐条仍绿（6 getsource + 1 CSS 长度 + 3 regex + 9 `_esc` + 4 `sys.modules` + 7 直接 import + 1 全文 fixture 全部复查）
- [ ] 离线哨兵计数 0; 600693 + 002353 smoke 单独跑通（需网络授权）
- [ ] `reports/` 现有条目 sha256 逐字节未变

---

## 十二、顺带发现（`_state_of` 的归属已定; 删不删仍需老板单独拍板）

- **`_state_of(score_total)`（L1244-1249, 6 符号行）实测全仓库零调用点** —— 定义存在, 但主函数用的是
  `_state_key_of`(L1252-1274), 仓库内无任何其他引用（已用全仓字面量检索确认）。
- **归属已明确（本计划执行）**: 随 **S4 一起迁入 `analysis/reporting/html_summary.py`**,
  并在 `html_report_v3` 顶层 re-export —— 它与 `_a_share_verdict_mark`/`_render_hero`/`_state_key_of`
  同属区块 9「hero 结论区 + 5 状态判定」, 放一起才不制造跨模块的孤儿符号。
  这也是 §五 中 `html_summary` 迁入行数取 **188**（= 6 个符号 182 + `_state_of` 6）的原因;
  此前 §五 漏列该符号才导致「188 vs 182」的 6 行差额。
- **本次拆分一律原样搬走、不删**: 删除是行为面清理, 混进结构拆分会让「逐字节不变」这个判据失效。
  若要删, 另开单片单独决策。

---

## 十三、签字栏

- 立项: Mavis 2026-10-04 14:17（补 `docs/08-规范整改-P2A-模块拆分-plan.md:74` 缺失的专属 plan）
- 拍板: 老板（待批）
- 开工条件: 老板「开干」后**从 S0 开始**（golden 基线装置必须先落地, 否则后续 8 片无法证明行为不变）
- 审查安排: 全部由 MiniMax 独立只读验收; 不安排 Kimi
