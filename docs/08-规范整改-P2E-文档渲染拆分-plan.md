# v0.18 规范整改 P2-E · DOCX 渲染器拆分 plan（**结论：不建议按 P2-D 形状拆**）

> 上一线: v0.16 规范整改 P0+P1 收官; P2-A (`analysis/quant_analyzer_v3.py`) 渐进拆分; P2-D (`analysis/html_report_v3.py`) 拆分 plan 已落地（`docs/08-规范整改-P2D-报告渲染拆分-plan.md`）
> 触发: `docs/08-规范整改-P2A-模块拆分-plan.md:75`「md_to_docx 不拆 (单独 plan)」—— 该专属计划至今缺失
> 范围: `analysis/md_to_docx.py`，实测 **584 物理行 / 520 符号行**（口径见 §2.1）
> 状态: ✅ **已拍板：S0-only**（2026-10-06 老板拍板，采纳 §一 建议）。**S0 已实施**（本轮新增 fixture / 语义基线 / 两处测试改读；`analysis/md_to_docx.py` 零改动）；**S1-S5 全量拆分未立项、未开工**，§五/§六 方案保留待后续单独拍板
> 纪律: 全部开发与审查只安排 MiniMax; 不安排 Kimi

---

## 一、结论先行（请先读这一节再决定是否往下读）

**建议：P2-E 立项，但只做 S0（补回归保护），不搬任何代码。**

> ✅ **2026-10-06 已拍板并落实**：老板**采纳本节建议**，P2-E 走 **S0-only**；S0 已实施完成（记录见 §十三）。
> 下面三条实测理由与「拆与不拆是二元的」硬结论**继续有效**——它们仍是「S1-S5 是否值得做」的判断依据，
> 只是**当前不立项**。

三条实测理由：

1. **规模差一个量级，拆不出合规模块。** P2-D 的目标是 2771 符号行 / 10 个模块（其中 3 个落在 300-500 区间）；
   本文件只有 **520 符号行**（P2-D 的 **19%**，P2-A 起点 v3 2184 行的 **24%**）。按 §五 全量拆成 4 个模块后，
   **最大模块 108 符号行，距 300-500 下限差 192 行，4 个模块全部落在下限之外**。
2. **P2-A 的病因在本文件不存在。** `docs/08-规范整改-plan.md:31` 给 v3 开的药方是「入口/采集/分析/报告/渲染混」。
   `md_to_docx.py` 是**单一职责渲染器**：文件内已有 9 段 `# ===` 横幅分区，最长函数 `md_to_docx` 仅 **124 符号行**
   （P2-D 的耦合中枢是 280）。这里没有职责混杂要解。
3. **拆分的成本单调递增，而收益是零。** 唯一的真实债不是「文件太长」，而是「**DOCX 输出零回归保护**」
   （§四 H6，实测：全仓库无任何测试断言 `md_to_docx` 的输出）。拆文件本身不能补上这个洞，
   反而会让两条源码文本**否定式**门禁随每一片单调变松（§四 H1，静默假绿）。

**同时给出一个反直觉的硬结论：拆与不拆是二元的，没有中间态。**
只抽叶子层（`docx_primitives` 108 符号行）后残留 **448 物理行**（584 − 136, 另净释放 5 行空行 L36/56-57/145-146）—— 既没过 `< 400` 门槛，
又已付出全部测试耦合代价，落在最差位置。要么全量拆（残留约 200-230 行），要么不拆。

> 本文件仍按要求给出**完整的可执行拆分方案**（§五 模块边界 / §六 拆分顺序 / §七 回归办法 / §十 验收门槛），
> 供老板在否决 S0-only 后直接开工。**方案本身不构成开工授权。**

---

## 二、事实基线: 584 行是怎么组成的

### 2.1 行数口径（全文唯一定义，先于任何行数结论）

沿用 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:26-49` 的定义，**不重新发明**。全文出现三种行数，
**只有「符号行」允许参与模块行数比较**：

| 名称 | 定义 | 唯一允许用途 |
|---|---|---|
| **符号行**（唯一迁入口径） | 逐个顶层符号（`def` / 模块级赋值 / 模块级 `try` 块 / `if __name__` 块）的 AST 声明块行数 `end_lineno - lineno + 1`；装饰器计入所属符号，docstring / 注释 / **块内空行**一并计入 | §五「迁入行数」与 §十「< 400 行」门槛**只准用它** |
| 物理区间行 | §2.2 表「行区间」列的跨度，**含**区块前导横幅与符号之间的空行 | **只用于定位代码位置**，不得当作迁入量或模块大小 |
| 残留文件行 | 拆分后 `analysis/md_to_docx.py` 的文件行数（文件头 + import + re-export + 主函数 + `__main__` 转发） | **只用于** §十「< 400 行」门槛 |

> ⚠️ 块内空行计入符号行这一点在本文件**特别重要**：`md_to_docx.py` 有 **23 行空行落在符号块内部**
> （文件头 docstring 2 行、`add_quote` 1 行、`flush_table` 4 行、`md_to_docx` 16 行），
> 手数行号时极易漏掉。下面的两向恒等式就是用来锁这个的。

**两向恒等式（`grep -n '^$' | wc -l` = 74 空行 / `grep -c '^#'` = 13 整行注释 / `wc -l` = 584 实测）：**

```
符号行 520 + 符号外空行 51 + 符号外整行注释 13 = 584 ✅
交叉校验: 非空行 510 = 符号行 520 − 符号内空行 23 + 符号外注释 13 ✅
```

- 符号行合计 **520**（§2.2 九个区块相加）。
- 符号外空行 **51** = 74 空行 − 23 符号内空行。
- 符号外整行注释 **13**：文件头 2（`L1` shebang / `L2` coding）+ 区块横幅 **7**（`L37/58/147/174/273/378/453`, 均为 `# ----` 段头）
  + 符号外散注释 **4**（`L28/29` Phase 1 段、`L38` token 段、`L54` emoji 段）。
  ⚠️ `L453` 与 `L37/58/147` 同为段头横幅, 计入「区块横幅」而非散注释, 故 2 + 7 + 4 = 13 ✅

### 2.2 区块地图（物理区间用于定位，符号行用于比较）

| # | 区块 | 行区间(物理) | 物理行 | **符号行** | 关键符号（括号内为符号行区间） |
|---|---|---|---|---|---|
| 1 | 文件头 + 依赖导入 + 容错 import | 1-35 | 35 | **29** | 文件头 docstring(3-16, 14) / `import`(17-20, 22-26, 共 9) / **模块级 `try:` 块**(30-35, 6) 内 `from sections import enabled_sections`(31) 与 `_SECTIONS_OK`(32/35) |
| 2 | 设计 token | 37-55 | 19 | **14** | 13 个模块级常量赋值(39-49, 51-52，含 `C_DARK`…`FILL_ZEBRA` `HX_RED/GREEN/AMBER` `F_CJK` `F_MONO`) + `_EMOJI_RE`(55) |
| 3 | XML 小工具 | 58-144 | 87 | **72** | `_set_fonts`(59-62) `_fmt`(65-76) `_ensure`(79-86) `p_border`(89-99) `cell_shade`(102-110) `table_borders`(113-125) `cell_bottom_border`(128-137) `header_repeat`(140-144) |
| 4 | 内容运行拆分 | 147-171 | 25 | **22** | `md_runs`(148-163) `add_runs`(166-171) |
| 5 | 样式段落 | 174-270 | 97 | **90** | `add_heading`(175-202) `add_quote`(205-237) `RISK_EMOJI`(240) `add_body`(243-270) |
| 6 | 表格 | 273-375 | 103 | **94** | `NUM_RANGE`(274) `DATE_ONLY`(275) `_clean_num`(278-280) `is_numeric_like`(283-296) `_cell_add`(299-307) `flush_table`(310-375) |
| 7 | Section Registry 辅助 | 378-450 | 73 | **70** | `_load_result_near`(379-399) `_render_md_block`(402-450) |
| 8 | **主流程** | 453-577 | 125 | **124** | `md_to_docx`(454-577)；内含**嵌套函数** `local_flush`(474-475)—— 嵌套定义**不单独计符号行**，已含在 124 内 |
| 9 | `__main__` CLI | 580-584 | 5 | **5** | argv 长度校验 + 报错(581-583) + 转发(584) |
| — | **合计** | 9 段 | **569** | **520** | 块间 15 行（`L36` / `56-57` / `145-146` / `172-173` / `271-272` / `376-377` / `451-452` / `578-579`）→ 584 ✅ |

**符号行逐块相加**: 29 + 14 + 72 + 22 + 90 + 94 + 70 + 124 + 5 = **520** ✅（与 §2.1 恒等式一致）

### 2.3 结构性事实（对设计起决定作用，逐条可复核）

- **本文件零网络、零子进程、零外部转换器。** 全文检索 `subprocess|requests|urllib|socket|http|os.system|Popen|soffice|libreoffice` **零命中**。
  转换靠 `from docx import Document`(22) 在进程内直接 `doc.save(docx_path)`(572) 落盘。
  **唯一的副作用面 = `out.parent.mkdir`(571) + `doc.save`(572) + 两行 `print`(573, 574-577)**。
  → 与 P2-D 不同（那里有 Chrome headless 子进程块，63 符号行，副作用最重），**本文件没有「副作用重块」**。
  → LibreOffice 转换是**下游**消费者（`analysis/reporting/artifact_writer.py`），不在本文件。
- **三个模块级符号零调用点**（`grep -c` 实测计数 = 1，即只有定义行）：
  `_ensure`(79-86, 8 符号行) / `NUM_RANGE`(274, 1) / `HX_ACCENT`(49, 1)，合计 **10 符号行死代码**。
  与 P2-D §十二 的 `_state_of` 同类发现。**处置：随所属区块原样搬走，一律不删** ——
  删除是行为面清理，混进结构拆分会让「行为不变」这个判据失效（沿用 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:431-432` 纪律）。
- **`_render_md_block`(402-450) 与主循环(467-531) 是同一套 Markdown 行解析器的两份拷贝** ——
  前者 docstring L404 原文自述「逻辑与主流程的 while 循环等价, 但自带 cur_h2 / risk_zone / table_rows 状态」。
  两者已出现结构漂移（主流程多出 `local_flush` 闭包 474-475，块内版直接调 `flush_table`）。
  **本计划不动这个去重**（§九 第 7 条），但拆分后两份拷贝分处两个文件，**漂移会更容易发生** —— 记入 §八 R4。
- **纯叶子层（无本文件内模块级依赖）**: `_set_fonts` `_fmt` `_ensure` `p_border` `cell_shade` `table_borders`
  `cell_bottom_border` `header_repeat` `md_runs` `_clean_num` `is_numeric_like` —— 共 **11 个**，先搬最安全。
- **业务阈值只有 3 处，全在区块 6**: 数字列 60% 判定(L332 `* 100 >= 60 * len(vals)`)、
  「价位/数值」列特判(L335-338)、「综合」行加粗(L342)。区块 5 的分支是**中文关键词匹配**
  （L211/222 `看空|看多`、L227 `数据来源`、L230 `⚠`、L429/498 `风险警报`、L441/514 `🎯`）——
  这些是**用户可见文案契约**，一个字都不能动（`docs/08-规范整改-plan.md:75`「不修改业务口径」）。
- **`docs/06-排版美化方案.md` 不存在。** `L6` 与 `L38` 两处注释引用它（`§2/§3`、`§2.1`），
  `ls docs/06*` 无匹配。这是**已存在的悬空引用**，本计划不改（零改动既有文件原则），记入 §九 第 9 条。

---

## 三、耦合地图: 谁依赖谁

「扇入」= 本文件内谁在调它; 「扇出」= 它还依赖本文件哪些符号。

| 被搬区块 | 扇入（本文件内） | 扇出（还依赖本文件哪些符号） | 耦合强度 |
|---|---|---|---|
| 设计 token (2) | `_fmt`(67) `p_border`(89) `add_heading`(183/189/194/199) `add_quote`(214/215/221/223/225/228/231/234) `add_body`(250/266/268) `table_borders`(113) `cell_shade`(364) `cell_bottom_border`(128) `md_runs`(157) `md_to_docx`(460/461/462/463) | 无 | **零**（纯常量 + 1 个正则） |
| XML 小工具 (3) | `_fmt`(62 经 `_set_fonts`) `add_heading`(184) `add_quote`(226/229/232/235) `add_body`(251) `flush_table`(325/359/364) `md_to_docx`(462) `_render_md_block`(435) | token 区（`H_HEADER` `H_HAIR` `F_CJK` `F_MONO`） | 低（11 符号叶子） |
| 内容运行拆分 (4) | `add_quote`(218/228/231/234) `add_body`(264/268) `_cell_add`(304) | `_EMOJI_RE`(157) `_fmt`(171) | 低 |
| 样式段落 (5) | `md_to_docx`(495/514/523/527) `_render_md_block`(426/441/446/448) | token 区 + 区块 3 + 区块 4 | **高（关键词分支 = 文案契约）** |
| 表格 (6) | `md_to_docx`(475/487/531) `_render_md_block`(420/450) | 区块 3（`table_borders` `cell_shade` `cell_bottom_border` `header_repeat`）+ 区块 4（`md_runs`）+ token 区 | **高（3 处业务阈值）** |
| Section Registry 辅助 (7) | `md_to_docx`(537/544) | 区块 3 `_fmt` / 区块 4 / 区块 5 全部 4 个 `add_*` / 区块 6 `flush_table` | **最高（横跨 4 个区块）** |
| 主流程 (8) | `artifact_writer.py:109`（外部） | 区块 1 `enabled_sections`/`_SECTIONS_OK` + 区块 2 + 3 + 4 + 5 + 6 + 7 | **耦合中枢（124 符号行）** |

**文件内 import 人格**: 全文**无 `sys.path` 操作**（`grep -n 'sys.path'` 零命中）。
唯一的可选依赖是 `L31` 的**裸名** `from sections import enabled_sections`（在 `L30-35` 的模块级 `try:` 里，失败降级为
`enabled_sections = None` / `_SECTIONS_OK = False`）。CI 靠 `PYTHONPATH: ${{ github.workspace }}/analysis:${{ github.workspace }}`
（`.github/workflows/ci.yml:145` 与 `:182` 两处；⚠️ **2026-10-06 更正**：初版写 `:120` 与 `:157`，因工作区新增「Critical Ruff gate (config-excluded paths, narrow)」整块 `ci.yml:40-63`（+25 行，未提交）而整体下移 25 行）让裸名可解析。`analysis/pipeline.py:43` 注释亦确认这条路径。

**外部扇入（谁在调本文件）**:

| 调用方 | 形式 | 位置 |
|---|---|---|
| `analysis/reporting/artifact_writer.py` | **双人格**: ① `from md_to_docx import md_to_docx as _md2docx` ② `subprocess.run([sys.executable, os.path.join(_ANALYSIS_DIR, "md_to_docx.py"), md_path, docx_path], check=True, timeout=180)` | `:109` / `:115-127`（脚本路径拼在 `:120`） |
| `analysis/__init__.py` | 仅**文档字符串**提及（`:9` `md_to_docx: MD → DOCX 转换` / `:18` 渲染层），无代码引用 | `:9, :18` |
| `analysis/report_md.py` | 仅**注释**引用行号 `md_to_docx.py:538-548` | `:1245` |
| `pyproject.toml` | **无** `[project.scripts]` / entry point 引用（`grep -n md_to_docx pyproject.toml` 零命中） | — |
| `.github/workflows/ci.yml` | **无**直接引用；仅 `:203` 探 `*.docx` 落盘、`:223` 上传 `600693-*.docx` | `:203, :223`（⚠️ 2026-10-06 更正，初版 `:178, :198`） |

---

## 四、硬约束表（拆分前必须逐条钉死）

| 编号 | 约束 | 证据位置 | 拆分影响 |
|---|---|---|---|
| **H1** | **源码文本「否定式」契约 2 条**，读 `analysis/md_to_docx.py` 全文：① `assert "三价位(同源)" not in src` + `assert "support_candidates" not in src` ② `assert "分两批进" not in src` | `tests/test_three_levels.py:405-416`（`test_docx_renderer_follows_md_no_hardcode`）、`tests/test_multi_state_trading_plan.py:203-212`（`test_docx_renderer_does_not_hardcode_operation`）; fixture `tests/conftest.py:89-95`（`md_to_docx_source` = `analysis_dir / "md_to_docx.py"` 全文） | ⚠️ **与 P2-D 的 H1 方向相反 —— 这是本文件最大的陷阱。** 否定式断言在「薄壳变小」时**只会更容易通过**：搬走的代码若恰好含这些字面量，测试仍然绿。**每搬一片，门禁就松一分，且不会自己报警。** 必须在 **S0** 就修，不能拖到最后 |
| **H2** | **subprocess 路径耦合**: `artifact_writer` 的 DOCX 降级路径把 `analysis/md_to_docx.py` **当脚本路径**拼进 `subprocess.run` | `analysis/reporting/artifact_writer.py:115-127`，路径拼接 `:120`，`check=True` `:124`，`timeout=180` `:125` | 薄壳**必须**留在 `analysis/md_to_docx.py` 原路径，且必须**同时**满足两种人格：可 `import` 出 `md_to_docx` 函数 + 可 `python <path> <md> <docx>` 直接执行。`md_to_docx.py:15` docstring 记录的 CLI 契约即此 |
| **H3** | **`sys.modules` 假模块注入 5 处**: `monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)`，假模块**只挂 `md_to_docx` 一个属性** | `tests/reporting/test_artifact_delivery_contract.py:81`、`:99`、`:184`、`:354`、`:440` | `artifact_writer` 侧**不得**改成经 `analysis.reporting.docx_*` 路径取渲染器; 薄壳顶层必须仍有 `md_to_docx` 这个名字。**同 P2-D H6** |
| **H4** | **裸名 import 人格 + 容错降级**: `from sections import enabled_sections` 裸名，包在模块级 `try/except Exception` 里 | `analysis/md_to_docx.py:30-35`（`:31` import，`:33` 宽 except，`:34-35` 降级）; CI 路径 `.github/workflows/ci.yml:145` / `:182`（⚠️ 2026-10-06 更正，初版 `:120` / `:157`）; 佐证注释 `analysis/pipeline.py:43` | 新模块若需 import `sections`，**必须**沿用同样的裸名 + try 降级写法。改走 `analysis.sections` 包路径在 CI 矩阵下会 ImportError。**同 P2-D H9** |
| **H5** | **跨文件行号引用会漂移（已漂移）**: `report_md.py:1245` 注释称「DOCX 渲染器 (md_to_docx.py:**538-548**) pattern」，而该 Registry 循环**实际在 `md_to_docx.py:536-547`** | `analysis/report_md.py:1245` vs `analysis/md_to_docx.py:536-547` | 拆分后彻底失效。**本计划零改动既有文件，故不修** —— 记为已知残留债，需老板单独拍板（§九 第 5 条） |
| **H6** | **产物零回归保护（这才是真债）**: 全仓库**无任何测试**断言 `md_to_docx` 的输出。唯一的 docx 读回测试自建最小 docx（`:480-482` 直接 `Document()` + `add_paragraph` + `save`），**不经过 md_to_docx**; `tests/conftest.py:344` 的 `"docx": 57114` 是**手写 run_log fixture 值**，断言只覆盖 `md`/`result_json`/`run_log` 的 `> 0`，**从不断言 docx** | `tests/reporting/test_artifact_delivery_contract.py:466-496`（自建 docx，`:480-482`）; `:160-162`（`sizes_bytes` 仅断言 3 个键 `> 0`）; `tests/conftest.py:344` | **S0 的语义 golden（§七）是唯一能证明「行为不变」的东西。** 没有它，S1-S5 全都无法自证 —— 这正是 §一 建议 S0-only 的核心理由 |
| **H7** | **已存在可复用的语义校验器，但零调用方**: `analysis/verify_docx_style.py`（160 行）读回 docx 逐项打印 `key=value`，自称「对 md_to_docx 新版 DOCX 做样式层实测校验」 | `analysis/verify_docx_style.py:1-160`（`:4-5` 自述用途）; 全仓 `grep -rn verify_docx_style` **只命中它自己的 docstring**，无任何调用方 | S0 **应把它升级为可断言装置，而不是重造一套**。它本身是路径式 CLI（`argv[1]`/`argv[2]`），**不 import `md_to_docx`**，故与 H1-H4 无耦合。**本计划不改它**（§九 第 4 条） |

---

## 五、目标模块边界（**规划猜测，需老板签字**）

落在既有 `analysis/reporting/` 包（当前只有 `__init__.py` + `artifact_writer.py`），
文件名 `docx_*.py` 平铺。「迁入行数」为**符号行**（§2.1 口径），不含新文件自身的 import 块与文件头。

| 新模块 | 迁入符号（符号行区间） | **迁入符号行** | 职责一句话 |
|---|---|---|---|
| `analysis/reporting/docx_primitives.py` | 区块 2 (13 常量 + `_EMOJI_RE`) + 区块 3 (7 个 XML 小工具) + 区块 4 (`md_runs` `add_runs`) | **108** | 无业务语义的地基: 设计 token / OOXML 元素 / 加粗·emoji 运行拆分 |
| `analysis/reporting/docx_paragraphs.py` | 区块 5: `add_heading` `add_quote` `RISK_EMOJI` `add_body` | **90** | 标题 / 引用（结论区）/ 正文列表 / 免责声明 四类段落样式 |
| `analysis/reporting/docx_tables.py` | 区块 6: `NUM_RANGE` `DATE_ONLY` `_clean_num` `is_numeric_like` `_cell_add` `flush_table` | **94** | Markdown 表格 → docx 表格 + 数字列右对齐等宽 + 斑马纹 |
| `analysis/reporting/docx_sections.py` | 区块 7: `_load_result_near` `_render_md_block` | **70** | Section Registry 灰度块: 就近读 result JSON + 复用样式函数渲染 |
| **合计** | | **362** | = 符号行 520 − 留薄壳的区块 1 (29) + 区块 8 (124) + 区块 9 (5) = 520 − 158 ✅ |

**残留 `analysis/md_to_docx.py`（薄壳）**: 保留文件头依赖说明 + import + 容错 `try` 块（**29 符号行 / 35 物理行**）、
re-export 块、主函数 `md_to_docx`（**124 符号行 / 125 物理行**）与 5 行 `__main__` CLI 转发。

- 残留**符号行 = 29 + 124 + 5 = 158**（口径: 符号行）
- 残留**物理行 = 35 + 125 + 5 + 5（残留块间空行 `L36/451/452/578/579`）= 170**，加 re-export 块
  → **约 200-230 残留文件行**（re-export 块 **估 30-60 行, UNVERIFIED**, S5 实测为准）
- 对标门槛: `docs/08-规范整改-P2A-模块拆分-plan.md:80`「v3 主文件 < 400 行」✅ 满足

**关于 300-500 区间（必须写准口径）**:

- **来源**: `docs/08-规范整改-P2A-模块拆分-plan.md:81`「6 个新模块各自 300-500 行」。
  ⚠️ `docs/08-规范整改-plan.md` §二（目标）**无任何 300-500 条款** —— 引用时不要写成 docs/08 §2（同 P2-D 的更正）。
- **实测（符号行口径）**: 落在 300-500 的模块 —— **0 个**。
  四个模块分别是 108 / 94 / 90 / 70，**全部低于下限**。
- 这是 §一 建议不拆的**算术依据**：P2-A 的 300-500 门槛是为「2184 行拆 6 块」设计的；
  520 符号行拆 4 块，**任何切法都不可能落进这个区间**。硬凑只会引入填充代码
  （沿用 `docs/10-pipeline拆解地图-phase1a.md:281`「本阶段的价值是**边界与可测性, 不是行数**」的口径）。

**半拆陷阱（务必不要走中间态）**: 只抽 `docx_primitives`（108 符号行 / 131 物理行 + 6 行块间空行 = 137 行搬走）后
残留 **584 − 136 = 448 物理行**（含净释放的 5 行空行）—— 仍 > 400 门槛，却已付出 H1/H2/H3 全部代价。**这是最差位置。**

---

## 六、拆分顺序: 6 片可审查 checkpoint（**不自动获得提交授权**）

排序原则: **零行为面 → 叶子层 → 含业务阈值的块 → 契约耦合最深的块 → 收官**。
与 P2-D 不同的是：**本文件的契约风险（H1 否定式门禁）随每一片单调累积**，所以 H1 的修复必须放在 **S0**，
不能像 P2-D 那样压到靠后（`docs/08-规范整改-P2D-报告渲染拆分-plan.md:240` 把 H2 放在 S5 是因为 HTML 侧是**肯定式**断言，
搬走会**变红**、自己报警；这里是**否定式**断言，搬走只会**变绿**、静默假绿）。

| # | 片 | 内容（符号行, §2.1） | 触及硬约束 |
|---|---|---|---|
| **S0** | **冻结基线 + 修 H1** | **不搬任何代码**。① 建离线**语义** golden 装置（§七，非字节比对）; ② conftest 追加 `md_to_docx_split_source` fixture（拼接薄壳 + 全部新模块）+ 最小覆盖断言; ③ **2 处**源码文本测试改读新 fixture（实测全仓仅 2 个测试函数以 `md_to_docx_source` 为形参：`tests/test_three_levels.py:405` / `tests/test_multi_state_trading_plan.py:203`）; ④ 复用 `verify_docx_style.py` | **H1（唯一有风险的片）**、H6、H7 |
| **S1** | `docx_primitives` | 搬 **108** 符号行（区块 2+3+4）—— 9 个叶子符号（`_clean_num` / `is_numeric_like` 属区块 6, 归 S2）+ 13 行常量赋值（**15 个常量名**: `HX_RED`/`HX_GREEN`/`HX_AMBER` 同行三合一, 加 `HX_ACCENT`）, 零业务语义 | H4（新模块若 import `sections` 需裸名）、H2/H3 的 re-export 基线 |
| **S2** | `docx_tables` | 搬 **94** 符号行（区块 6）—— 含 3 处业务阈值（60% / 价位数值 / 综合行） | H2/H3 re-export、H1 覆盖断言必须已生效 |
| **S3** | `docx_paragraphs` | 搬 **90** 符号行（区块 5）—— 含全部中文关键词分支（文案契约） | H2/H3 re-export |
| **S4** | `docx_sections` | 搬 **70** 符号行（区块 7）—— 横跨 4 区块的最深耦合 | H2/H3/H4（`_render_md_block` 需 import 四个模块的样式函数） |
| **S5** | 薄壳收官 | re-export 块固化并**实测**残留行数; 三个死符号原样保留 | H1-H4 全部收口 |

每片统一形态（沿用 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:245-252` 已验证的「先搬后接、同片删原地」模式）:

1. 新建模块, 机械搬入符号（**不改函数体**; 跨模块引用改成 import）;
2. 新模块建自己的单测（只测搬入符号, 不测主流程）;
3. `md_to_docx.py` 改为 import + re-export, **同片删除原地定义**;
4. 跑 §十 全部验收门禁。

**硬规则: 禁止新旧两套实现并存**。并存会让本片回滚不干净, 也会让下一片无法判定基线。

### 6.1 版本控制纪律（**默认不 stage / 不 commit / 不 push**）

沿用 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:254-263`:

- 每片交付形态是**可审查、可回滚的 checkpoint**: 老板可直接看工作区 diff, 逐片拍板。
- **默认不执行 `git add` / `git commit` / `git push` / `git merge` / `git reset` / `git clean`**。
  本计划不因「写进了文档」就自动获得提交授权。
- **回滚手段**: 开工前留**本片前工作区快照**, 或用 `git diff` 生成的 patch 反向应用;
  **不依赖 `git revert`**（无提交就无从 revert）。
- 只有老板**逐片明确授权**后, 才另论提交粒度与合并方式; 未授权前不 squash、不合并、不整理历史。

---

## 七、每片保持行为不变的验收 / 回归办法

### 7.1 逐字节 golden **不适用于本文件**（诚实说明, 不打太极）

`.docx` 是 **zip 容器**而非纯文本, 逐字节相等有三重问题:

1. **zip entry 头含落盘时间戳。** `python-docx` 经标准库 `zipfile` 落盘，同一输入两次 `doc.save()` 字节不同。
   → **UNVERIFIED（推理，未实测）**: 本计划**未运行**任何代码验证，S0 **必须实测**确认，不能直接采信本条。
2. **`docProps/core.xml` 的 `modified` 随落盘时刻变化**，即使剥掉 zip 时间戳也不可复现。**同 UNVERIFIED**。
3. **最根本的**: 即便前两条都解决，逐字节相等会把 **`python-docx` / `lxml` 版本升级**变成阻断性失败 ——
   依赖版本一变，zip 内 XML 的序列化细节就可能变，而**版式语义一模一样**。这是**假回归**，
   长期只会诱导「更新基线以掩盖回归」，比没有门禁更危险。

**结论: 门禁应锁「版式语义」而非「容器字节」。** 这也正是 `analysis/verify_docx_style.py`（H7）已经在做的事 ——
S0 应升级它，而不是重造。

### 7.2 语义 golden 装置规格（S0 交付物）

- **投影**: 用 `python-docx` 读回产物，**按 `word/document.xml` 的 body 子元素顺序遍历**。
  ⚠️ **不能用 `doc.paragraphs` 与 `doc.tables` 两个独立列表** —— 那会丢失段落与表格的**交错顺序**，
  而顺序漂移正是拆分最易引入的回归。必须遍历 body 子元素。
- **投影内容**（每块一条记录）:
  - 段落 → `(kind="p", style_name, 全文 text, [(run.text, bold, italic, font.name, eastAsia 字体, size_pt, color.rgb_hex)])`
  - 表格 → `(kind="tbl", nrows, ncols, 表格属性[tblBorders 六边 val/sz/color, 首行 tblHeader 是否存在], [[(cell_text, 段落对齐, w:shd fill, runs...)]])` —— 覆盖 `flush_table` 的全部样式动作: hairline 边框 / 斑马纹 `FILL_ZEBRA` / 表头加粗 / 数字列右对齐等宽 / 「价位·数值」列 11pt 加粗
  - sectPr → 页脚 3 段文本（`md_to_docx.py:552-556`）
- **归一化只做一件事**: `生成时间:`（`md_to_docx.py:555`）的取值来自 `L465` 的 `Path(md_path).stat().st_mtime`。
  **S0 实测定稿（2026-10-06）= 钉 mtime + 掩码该字段，两步都做**:
  ① 用 `os.utime` 把输入 MD 的 mtime 钉死（`PINNED_MTIME`）→ 真实代码路径完整走通;
  ② 再把该字段替换为固定占位符 `<GEN_TIME>`，替换次数必须**恰好为 1**，否则装置抛错。
  ⚠️ **为什么加了第 ② 步**（偏离上文"无需掩码"的初版判断）: `datetime.fromtimestamp()` 取的是
  **本地时区**时间 —— 不钉时区则同一个 mtime 在 UTC+8 与 UTC 机器上产出不同字符串，
  基线**无法跨机复核**，而 CI 矩阵跨 Ubuntu / macOS。除该字段外一律不掩码。
  掩码一旦静默失效（模板改字样）基线就不再覆盖该字段，故用"次数必须为 1"把空门禁堵死。
- **落地（2026-10-06 拍板，与初版不同）**: **独立目录 `tests/fixtures/docx_semantic/`**，
  **不进 `tests/fixtures/golden/`**。
  ⚠️ 原因: `docs/13-阶段1-离线fixture出处登记与SHA256口径-plan.md` §十三-五 建议层 ⑤
  （`:537`）要求该目录下**任何**新增文件须同片具备 18 字段出处登记，缺任一项 → A4 **fail**；
  而同文件 §十三-六 `:559` 又**禁止**把 P2-E 基线登记进那 18 字段模板。两条规则在
  "落在 golden 目录"的前提下**无法同时满足**（死锁）。移出该目录后死锁消解：
  本基线**不进入** §五 18 字段管辖，§十三-六 `:558-559` 的"两套口径禁止互相套用"继续有效。
  ⚠️ **初版 `:257` 的"该目录含未提交的在途成果"已过期**（2026-10-06 只读核实）:
  `tests/fixtures/golden/` 现有 4 个文件（`README.md` / `golden_fixtures.py` /
  两份 `result_v3-*.json`）**均已入库且工作区干净**；未入库的是 **capture 源**
  `reports/600693_东百集团/`。本轮**未改**该目录任何文件。
- **输入（2026-10-06 拍板）**: **只用手工合成的最小 MD**（`tests/fixtures/docx_semantic/minimal.md`），
  🚫 不从 `reports/` 搬运任何内容（`docs/13:528` 禁令 1）、不依赖真实标的 / 网络数据 / 当日跑批。
  装置把输入复制到一次性工作目录再渲染，并对"工作目录出现 `result_v3-*.json`" **fail loud**
  （否则渲染器 `_load_result_near`（`:379-399`）会把 Section Registry 灰度块追加进产物，基线依赖环境）。
- **确定性自证（必须跨进程，同进程连跑两次不算）**:
  沿用 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:293-302` 的四步: ① 两个**独立子进程**;
  ② 各自显式设**不同的 `PYTHONHASHSEED`**（如 `0` 与 `12345`）; ③ 各渲染一次同一输入 → 归一化 → 输出 sha256;
  ④ **两个 sha256 必须相等**，该值才写进本文件作为 S1-S5 的比对基线。
  理由同 P2-D: 同进程共享 `sys.modules` 与模块级缓存，`PYTHONHASHSEED` 只有一个值，
  dict / set 迭代序换进程就可能变，而本文件 `stats["by_level"]` 等 dict 会被写进 summary 输出。
  哨兵自检只允许打 **loopback**（`127.0.0.1`/`::1`）; 渲染本身不触网（§2.3 已证零网络）。

  **S0 实测基线（2026-10-06 N2 后，权威值，S1-S5 比对就用它）**:
  ```
  语义投影 sha256 = a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93
  PYTHONHASHSEED=0     → a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93
  PYTHONHASHSEED=12345 → a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93
  ```
  ⚠️ **本块曾被记作 `f10752d432cd1df0c20cb278cf2e88a680431942de69c50341fb57b1f724d438`（历史值，保留不删；**该旧值不再充当权威值**）**:
  那是 **N1 增补真实 amber ⚠ quote 分支之前**的指纹。N1 给 `minimal.md` 补了一条真实的 `⚠` 琥珀色
  quote 段落（与普通 `⚠ 免责声明` 行结构可区分），投影**内容确实变了**，指纹随之变更是**语义真的变了**、
  属 §十 回滚条款允许的更新（不是"掩盖回归"）。该指纹以 `baseline.json` 的 `sha256` 字段为准，
  与 `tests/reporting/test_docx_semantic_golden.py` 门禁同源。N1 同时把 semantic golden 用例由
  **9 条增至 19 条**，记于 `docs/13` §十三-十一。
  三值相同 ⇒ §7.1 两条推理（zip 落盘时间戳 / `docProps/core.xml` modified）**已由实测坐实**
  （S0 前标 UNVERIFIED 的 `:235-236` 至此可关闭），**语义投影路线成立**。
  基线文件 `tests/fixtures/docx_semantic/baseline.json` = `{schema, sha256, projection}`
  （**指纹 + 完整投影**同存: 指纹是门禁契约，完整投影让门禁红了能定位到哪一段版式漂移）。
  装置与再生成纪律见 `tests/fixtures/docx_semantic/README.md`。
  ⚠️ 该基线由 `python-docx 1.2.0` / `lxml 6.1.3` / `venv Python 3.13.5` 产出；
  换依赖版本后若指纹变化，**先判定是"投影语义真的变了"还是"上游序列化细节变了"**，
  禁止直接更新基线（§十 回滚条款同向）。

### 7.3 S0 的 H1 修复规格（必须同片完成，否则门禁静默假绿）

| 测试 | 退化方式 | 是否会自己报警 |
|---|---|---|
| ① `test_docx_renderer_follows_md_no_hardcode` | 薄壳变小 → `三价位(同源)` / `support_candidates` 若被搬进新模块，**全文不再包含** → 断言恒真 | **不会 —— 静默假绿** ⚠️ |
| ② `test_docx_renderer_does_not_hardcode_operation` | 同上，`分两批进` | **不会 —— 静默假绿** ⚠️ |

修法（**不改动原断言语义**）:

1. conftest 追加 `md_to_docx_split_source` fixture: 拼接「薄壳 + 全部新模块」全文。**S0 之前**它等价于读单文件。
2. 2 个测试改读该 fixture（复用 P2-A 既有 `*_source` 模式，**行号口径 = `def` 行**，与 P2-D §四 引用一致:
   `quant_analyzer_v3_source` L72 / `html_report_v3_source` L81 / **`md_to_docx_source` L90** /
   `report_md_source` L99 / `pipeline_source` L112 / `result_builder_source` L125 —— 均在 `tests/conftest.py`）。
3. **加最小覆盖断言，让判据随代码搬迁保持有效**:
   - 断言扫描面**包含全部宿主符号**（拆分后即 4 个新模块的导出名 + 薄壳的 `md_to_docx`），缺任一即红;
   - 断言扫描面**总行数 ≥ 560**（拆分前 584 的 ~96%; 允许 import / 空行 churn，低于此说明有模块没被纳入扫描面）。
4. 由此无论宿主代码搬到哪个文件，判据都**跟着走**; 若有人把新模块漏出扫描面，覆盖断言先红。

> `tests/conftest.py` 的改动说明: 只在文件尾**追加**新 fixture，**保留现状、不重排既有 fixture**。

**S0 实装形态（2026-10-06，与上述规格的差异只有实现细节）**:

- fixture 返回的是 `str` **子类** `_SplitSource` 而非裸 `str`: 两个否定式测试只做 `in src` 判断，
  行为与全文完全一致；子类额外携带 `files` / `host_symbols` / `missing_symbols` / `missing_modules` /
  `absent_modules` / `registered_modules` / `line_count`，
  供覆盖断言使用。这样两个测试函数**只需换 fixture 名 + 加 3 行断言**，原两条否定式断言**逐字未动**。
- 宿主符号契约 `DOCX_HOST_SYMBOLS` 共 **41** 个（薄壳 3: `md_to_docx` / `enabled_sections` / `_SECTIONS_OK`
  \+ 四模块 38），**硬编码在 conftest 里**而不是"现扫现比"——否则"扫到什么就比什么"会退化成恒真。
- 覆盖断言落实为**三条**，且**前置**于否定式断言（扫描面不完整时先红，不让恒真断言跑起来）:
  ① `not src.missing_symbols`（契约符号齐全）; ② `not src.missing_modules`
  （`analysis/reporting/docx_*.py` 无一漏出扫描面）; ③ `src.line_count >= 560`（规模不低于 584 的 ~96%）。
  第 ② 条是初版规格没有的**加强项**: 只靠 ①③ 仍挡不住"新模块被建出来却没登记进扫描面"。

### 第 ② 条的加强项曾经是假的（2026-10-06 N2 修正）

初版实装把**同一个 glob 用在了差分两侧**: `host_files` 由
`sorted(reporting_dir.glob("docx_*.py"))` 拼出，`on_disk` 又由同一个 glob 算出，
于是 `missing_modules = on_disk - included` **恒为空集**——差别被自己抵消了。
上一节把它写成"加强项…挡不住新模块被建出来却没登记"，**与当时的代码不符**:
它当时既挡不住未登记的新模块（`included` 就是 glob 出来的），也完全看不见
"登记了但磁盘上没有"这一类（初版根本没有登记表）。S1 真按当时写法建出模块，
这道门禁不会红。

修正后的两侧**独立**:

| | 来源 | 作用 |
|---|---|---|
| `DOCX_HOST_MODULES` | **显式登记**（conftest 内常量，S0 为空） | 判据：host_files 的模块部分**只**认它 |
| `_scan_docx_modules()` | **独立磁盘扫描** `docx_*.py` | 事实：磁盘上现存的模块集合 |

双向差分 `_module_diff()` 产出两类可观察错误:

- `missing_modules` = 磁盘有、**没登记**（新模块漏出门禁扫描面）
- `absent_modules` = 登记了、磁盘**没有**（登记与事实脱节；单向差分挡不住这一半）

因此上一节最后一条"**fixture 自动纳入 `analysis/reporting/docx_*.py`（`sorted(glob)`），
S1-S5 无需再改本 fixture**"**已作废**，改为: **S1-S5 每建一个模块必须在
`DOCX_HOST_MODULES` 登记一行**，登记即纳入、漏登记即 `missing_modules` 报错。
这是有意的摩擦——自动 glob 正是当初让 ② 变成恒真的根因。
`DOCX_PLANNED_MODULES` 只作 S1-S5 落位时的对照抄写，**不参与判定**:
拿"计划"当现状会让 S0 一开局就误报，而豁免一旦挂上就会被忘记删除。

负向控制见 `tests/reporting/test_docx_semantic_golden.py` 文末小节（纯 helper 单测
\+ 隔离 `tmp_path` 副本，**不改真实源码树**）：当前模块集零发现、额外模块报
`missing`、登记缺失报 `absent`、一致态与空态均无误报。

---

## 八、风险清单

| # | 风险 | 严重度 | 证据 / 位置 | 缓解 |
|---|---|---|---|---|
| **R1** | **否定式门禁单调变松（静默假绿）** | **最高** | §四 H1; `tests/test_three_levels.py:405-416` / `tests/test_multi_state_trading_plan.py:203-212` | **S0 必须先修**（§7.3）。未修就搬码 = 放弃这两条门禁且无人察觉 |
| **R2** | **subprocess 路径耦合被破坏** | 高 | §四 H2; `analysis/reporting/artifact_writer.py:115-127` | 薄壳留在原路径 + 保留 `__main__` 转发（区块 9, 5 符号行）+ S5 实测一次真实 subprocess 降级路径 |
| **R3** | **业务阈值 / 中文关键词漂移** | 高 | 60% 判定 `md_to_docx.py:332`; 价位数值 `335-338`; 综合行 `342`; 关键词 `211/222/227/230/429/441/498/514/522` | 这些是**用户可见契约**。投影式 golden 会逐字捕获; 严禁借拆分「顺手清理」 |
| **R4** | **`_render_md_block` 与主循环两份拷贝漂移** | 中 | `md_to_docx.py:402-450` vs `467-531`（docstring `L404` 自述「等价」） | 本计划**不去重**（§九 第 7 条）。拆分后两份分处两文件，**漂移概率上升** —— 收官时人工对读一次两段分支顺序 |
| **R5** | **模板文案改动**: 页脚 3 行硬编码中文（数据来源 / 免责声明 / 生成时间） | 中 | `md_to_docx.py:552-556` | 原样搬移; 投影式 golden 覆盖页脚文本 |
| **R6** | **死符号被顺手删掉** | 中 | `_ensure`(79-86) / `NUM_RANGE`(274) / `HX_ACCENT`(49)，各计数 = 1 | **一律不删**（同 P2-D §十二 纪律）。删除另开单片 |
| **R7** | **裸名 import 在 CI 矩阵 ImportError** | 中 | §四 H4; `ci.yml:145` / `:182`（⚠️ 2026-10-06 更正，初版 `:120` / `:157`）; `pipeline.py:43` | 新模块沿用裸名 + try 降级; 门禁 4 跑全 Python 矩阵 |
| **R8** | **re-export 面被漏掉导致 `sys.modules` 假模块不匹配** | 中 | §四 H3（5 处假模块只挂 1 个属性） | S5 逐条复查 H3 的 5 处 |
| **R9** | **`.docx` 语义等价但字节变**被误判为回归，或反之掩盖真回归 | 中 | §7.1 | 投影式 golden 只比语义; **禁止**通过「更新基线 sha256」掩盖回归 |
| **R10** | **`docs/06-排版美化方案.md` 悬空引用** | 低 | `md_to_docx.py:6` / `:38` 引用; `ls docs/06*` 无匹配 | **已存在的债，不在本次范围**（§九 第 9 条）。若将来恢复该文档，样式依据需重新对齐 |
| **R11** | **副作用面** | 低 | §2.3: 全文零网络零子进程; 副作用仅 `mkdir`(571) + `save`(572) + 2 行 `print`(573/574-577) | 本文件**没有** P2-D 那种重副作用块（Chrome headless）。风险面显著小于 P2-D |

---

## 九、明确不动范围

| # | 不动 | 理由 |
|---|---|---|
| 1 | `analysis/html_report.py` / `analysis/html_report_v3.py` | 归 P2-D（`docs/08-规范整改-P2D-报告渲染拆分-plan.md`） |
| 2 | `analysis/sections/**`（Registry + 5 个 Section） | 灰度机制本身不在本次范围; 只保证 H4 的调用位置与降级不变 |
| 3 | `analysis/reporting/artifact_writer.py` 的 DOCX 双路径（`:109` / `:115-127`） | H2 / H3 硬约束 |
| 4 | `analysis/verify_docx_style.py`（160 行） | H7: 复用为 S0 装置，**但不改它**。它自身零调用方，改它等于改验收工具本身，另立议题 |
| 5 | `analysis/report_md.py:1245` 的行号引用（**已漂移 ±2**） | H5。本计划零改动既有文件; 需老板单独拍板是否在收官时一并修 |
| 6 | 死符号 `_ensure`(79-86) / `NUM_RANGE`(274) / `HX_ACCENT`(49) 的删除 | R6。行为面清理混进结构拆分会让「行为不变」判据失效 |
| 7 | `_render_md_block` 与主循环的**去重** | 结构重设计，会改解析分支顺序（R3/R4），收益不抵风险，另立议题 |
| 8 | `.github/workflows/ci.yml` 与 `pyproject.toml` 的 lint / marker / addopts 配置 | 门禁本身不得被本次拆分改动 |
| 9 | `docs/06-排版美化方案.md`（**实测不存在**） | R10，已存在的悬空引用; 补文档不在本次范围 |
| 10 | 全部业务阈值与用户可见文案（60% / 价位 / 综合行 / 看空看多 / 数据来源 / ⚠ / 🎯 / 风险警报 / 页脚 3 行） | `docs/08-规范整改-plan.md:75`「不修改业务口径」 |
| 11 | `result_v3` 键集契约 / `trading_plan` 结构 / `three_levels` 结构 | 上游 `pipeline` / `result_builder` 的契约，DOCX 侧只读（`_load_result_near` 379-399） |
| 12 | `docs/08-规范整改-plan.md` / `docs/08-规范整改-P2A-*` / `docs/08-规范整改-P2D-*` / `docs/10-*` | 本次只新增本文件，不改既有文档; 收官同步另行提 |
| 13 | `reports/` 现有产物 | 全程不产生新的跑批产物 |

---

## 十、验收门槛

### 10.1 收官门槛

- [ ] `analysis/md_to_docx.py` **< 400 残留文件行**（对标 `docs/08-规范整改-P2A-模块拆分-plan.md:80`）; 预估 **约 200-230 行**（S5 实测为准）
- [ ] **符号行守恒**: 薄壳 158 + 四模块 362 = **520**，与拆分前实测 520 **完全一致**（§2.1 / §五）
- [ ] 落在 300-500 **符号行**区间的模块 —— **0 个**（108 / 94 / 90 / 70 全部低于下限，已在 §五 完整说明并给出理由）
- [ ] **语义 golden sha256 与 S0 基线逐字节相同**（跨全部 5 片 S1-S5，一路不变）;
      且 S0 基线本身已通过**跨进程双 `PYTHONHASHSEED`** 确定性自证（§7.2）
- [ ] 全量 Pytest `passed` 不减、**`skipped` 数与 S0 实测完全一致**（无新增 skip）——
      **S0 实测基线（2026-10-06，唯一权威值）: `1043 passed / 9 skipped / 2 deselected`，23.87s，1 warning**
      （`venv Python 3.13.5` / `pytest 9.1.1`; 命令 `venv/bin/python -m pytest`，**未加 `-m`**，
      走 `pyproject.toml` 的 `configfile` 与 addopts 默认值）。
      ⚠️ **2026-10-06 S1 开工复测更正（本行是本小节唯一被改动的计数）**: 原记
      `1033 passed / 9 skipped / 2 deselected`，25.52s —— **已被取代，但保留在本记述里不删**。
      复测环境 = **S1 开工前的 hash-identical 副本树**（`/tmp` 内自当前工作区复制后，把
      `analysis/md_to_docx.py` / `tests/conftest.py` / `tests/reporting/test_docx_semantic_golden.py`
      逐个 sha256 回滚至 S1 前状态再实测），`venv Python 3.13.5` / `pytest 9.1.1` /
      macOS 25.5.0 arm64 / 仓库默认 marker（未加 `-m`）/ 外层离线哨兵 0 命中。
      差额 **+10 来自 S0 之后新增的在途测试文件，非 S1 引入**。S1 收官实测 =
      `1073 passed / 9 skipped / 2 deselected / 1 warning`（+30 = S1 新增 30 条离线用例；
      `skipped` / `deselected` / `warning` 三项与本基线**完全一致**）。
      ⚠️ **2026-10-06 S2 收官复测（本小节仍只有这一处计数块被改动，上文数字全部保留不删）**:
      S2 收官实测 = **`1118 passed / 9 skipped / 2 deselected / 1 warning`，22.05s**
      （+45 = S2 新增 45 条离线用例 `tests/reporting/test_docx_tables.py`；`skipped` /
      `deselected` / `warning` 三项与 S0/S1 基线**完全一致，无新增 skip**）。
      实测环境 = **S2 开工后的当前工作树**（`venv Python 3.13.5` / `pytest 9.1.1` /
      macOS 25.5.0 arm64 / 仓库默认 marker，未加 `-m` / 走 `pyproject.toml` 的
      `configfile` 与 addopts 默认值），命令 `venv/bin/python -m pytest`。
      1 warning 的**内容不变但位置随迁出移动**：`NUM_RANGE` 的既有
      `FutureWarning: Possible set symmetric difference` 现报在
      **`analysis/reporting/docx_tables.py:53`**（S1 时为 `analysis/md_to_docx.py:191`，
      S0 记为 `:274`）—— 该正则在 S2 随区块 6 原样搬走，**既非新增也非修复**，仍是既有债。
      ⚠️ **外层离线哨兵本次未跑**（S2 实施中被老板叫停，改为只用仓库自带离线机制验证），
      故本行的「外层离线哨兵 0 命中」**只对 S0/S1 那次复测成立，对 S2 未验证**；
      S2 的离线证据改为仓库自带的 live 三层门禁仍生效（`2 deselected` 恒定、
      `DA_A_RUN_LIVE` 未设置、9 skipped 明细逐条未变）。
      9 skipped 明细: `test_artifact_delivery_contract.py:471`（soffice 未装）1 +
      `test_html_ui_template.py:406`（Chrome headless 不可用）1 + `test_scoring_breakdown.py:286` 3 +
      `test_three_levels.py:47` 4（缺历史 result fixture）。
      2 deselected = `test_peg_formula.py:664` 与 `test_fund_flow_domain.py:653` 两个
      `@pytest.mark.live` 用例，被 `tests/conftest.py:475` 收集期 fail-closed 选择层拦下（离线门禁第一/二层生效的证据）。
      1 warning = `analysis/md_to_docx.py:274` 的 `FutureWarning: Possible set symmetric difference`
      （`NUM_RANGE` 正则字符类里 `~` 重复，**既有债，非本轮引入**；该文件本轮零改动）。
      ⚠️ 上一行记的是 **S0 时点**的行号与「该文件本轮零改动」；**S2 起已不成立** ——
      该正则在 S2 随区块 6 迁到 `analysis/reporting/docx_tables.py:53`，而
      `analysis/md_to_docx.py` 在 S2 **有**改动（删原地定义 + 加 re-export）。
      上行原始数字与措辞**保留不删**（历史基线），当前位置以本小节 S2 收官复测段为准。
      ⚠️ 该基线是在**工作区既有 12 改 + 3 未跟踪测试文件**之上实测的（全部为在途成果，见 P2E §十二 的证据边界纪律）；
      若这些在途改动之后被提交/回退，本基线数字会变，S1 开工时须**重新实测并更新本行**。
      历史数字（Phase 1J 的 779 passed / 9 skipped，`docs/10-pipeline拆解地图-phase1a.md:284`）**仅作历史参考，已被本行取代**。
      ⚠️ **2026-10-06 S3 收官复测（本小节仍只有这一处计数块被改动，上文数字全部保留不删）**:
      S3 收官实测 = **`1161 passed / 9 skipped / 2 deselected / 1 warning`，22.53s**
      （+43 = S3 新增 43 条离线用例 `tests/reporting/test_docx_paragraphs.py`；`skipped` /
      `deselected` / `warning` 三项与 S0 / S1 / S2 基线**完全一致，无新增 skip**）。
      实测环境 = **S3 开工后的当前工作树**（`venv Python 3.13.5` / `pytest 9.1.1` /
      macOS 25.5.0 arm64 / 仓库默认 marker，未加 `-m` / 走 `pyproject.toml` 的
      `configfile` 与 addopts 默认值），命令 `venv/bin/python -m pytest -p no:cacheprovider`。
      9 skipped 明细与 2 deselected 明细**逐条未变**（`test_peg_formula.py:664` 与
      `test_fund_flow_domain.py:653` 两个 `@pytest.mark.live` 用例仍被
      `tests/conftest.py` 收集期 fail-closed 选择层拦下，`DA_A_RUN_LIVE` 未设置）。
      1 warning 仍是 `NUM_RANGE` 的既有 `FutureWarning`，位置**未再移动**：仍在
      `analysis/reporting/docx_tables.py:53` —— S3 迁的是区块 5，与该正则无关。
      ⚠️ **外层离线哨兵本次仍未跑**（沿用 S2 的禁令：不自制 network sentinel、不建仓库外临时文件），
      故本行的离线证据同样**只有**仓库自带的 live 三层门禁，该哨兵对 S3 **未验证**。
      ⚠️ 另记 S3 两项实测事实：**符号行守恒已实测** = 薄壳保留 **228**（区块1 29 + 区块7 70 +
      区块8 124 + 区块9 5，`ast` 逐块复算）+ 三模块 **292**（S1 108 + S2 94 + S3 **90**）= **520**，
      与 §2.1 拆分前实测**完全一致**；**薄壳 428 → 361 残留文件行，首次满足本节的「< 400」门槛**
      （该条原按 §五 预估属 S5 收官门槛，S3 后提前达成；S4 迁出区块 7 后将进一步下降）。
      ⚠️ **2026-10-06 S4 收官复测（本小节仍只有这一处计数块被改动，上文数字全部保留不删）**:
      S4 收官实测 = **`1200 passed / 9 skipped / 2 deselected / 1 warning`，22.96s**
      （+39 = S4 新增 39 条离线用例 `tests/reporting/test_docx_sections.py`；`skipped` /
      `deselected` / `warning` 三项与 S0 / S1 / S2 / S3 基线**完全一致，无新增 skip**）。
      实测环境 = **S4 开工后的当前工作树**（`venv Python 3.13.5` / `pytest 9.1.1` /
      macOS 25.5.0 arm64 / 仓库默认 marker，未加 `-m` / 走 `pyproject.toml` 的
      `configfile` 与 addopts 默认值），命令 `venv/bin/python -m pytest -p no:cacheprovider`
      （`PYTHONDONTWRITEBYTECODE=1`，`DA_A_RUN_LIVE` 未设置）。
      9 skipped 明细与 2 deselected 明细**逐条未变**（`test_artifact_delivery_contract.py:471`
      soffice 1 + `test_html_ui_template.py:406` Chrome headless 1 + `test_scoring_breakdown.py:286` 3 +
      `test_three_levels.py:47` 4；2 deselected 仍是 `test_peg_formula.py:664` 与
      `test_fund_flow_domain.py:653` 两个 `@pytest.mark.live` 用例被收集期 fail-closed 选择层拦下）。
      1 warning 仍是 `NUM_RANGE` 的既有 `FutureWarning`，位置**未再移动**：仍在
      `analysis/reporting/docx_tables.py:53` —— S4 迁的是区块 7，与该正则无关。
      ⚠️ **外层离线哨兵本次仍未跑**（沿 S2 / S3 的禁令：不自制 network sentinel、不建仓库外临时文件），
      故本行的离线证据同样**只有**仓库自带的 live 三层门禁，该哨兵对 S4 **未验证**。
      ⚠️ 另记 S4 四项实测事实：**符号行守恒已实测** = 薄壳保留 **158**（区块1 29 + 区块8 124 +
      区块9 5）+ 四模块 **362**（S1 108 + S2 94 + S3 90 + S4 **70**）= **520**，
      与 §2.1 拆分前实测**完全一致**；**薄壳 361 → 317 残留文件行**，**< 400** 门槛持续满足；
      **迁出块逐字节等价**（区块 7 的 2543 字节，sha256 `9145f91c…`，与原文**完全相同**）；
      **语义 golden 未变**（19 条用例全绿，`baseline.json` 的 `sha256` 仍是
      `a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93`，**未重生成**）。
      ⚠️ **2026-10-06 S5 收官复测（本小节仍只有这一处计数块被改动，上文数字全部保留不删）**:
      S5 收官实测 = **`1227 passed / 9 skipped / 2 deselected / 1 warning`，26.09s**
      （+27 = S5 新增 27 条离线用例 `tests/reporting/test_docx_thin_shell.py`；`skipped` /
      `deselected` / `warning` 三项与 S0 / S1 / S2 / S3 / S4 基线**完全一致，无新增 skip**）。
      实测环境 = **S5 开工后的当前工作树**（`venv Python 3.13.5` / `pytest 9.1.1` /
      macOS 25.5.0 arm64 / 仓库默认 marker，未加 `-m` / 走 `pyproject.toml` 的
      `configfile` 与 addopts 默认值），命令 `PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m
      pytest -p no:cacheprovider`（`DA_A_RUN_LIVE` 未设置）。
      9 skipped 明细与 2 deselected 明细**逐条未变**（`test_artifact_delivery_contract.py:471`
      soffice 1 + `test_html_ui_template.py:406` Chrome headless 1 + `test_scoring_breakdown.py:286` 3 +
      `test_three_levels.py:47` 4；2 deselected 仍是 `test_peg_formula.py:664` 与
      `test_fund_flow_domain.py:653` 两个 `@pytest.mark.live` 用例被收集期 fail-closed 选择层拦下）。
      1 warning 仍是 `NUM_RANGE` 的既有 `FutureWarning`，位置**未再移动**：仍在
      `analysis/reporting/docx_tables.py:53` —— S5 不搬码，与该正则无关。
      ⚠️ **外层离线哨兵本次仍未跑**（沿 S2 / S3 / S4 的禁令：不自制 network sentinel、
      不建仓库外临时文件），故本行的离线证据同样**只有**仓库自带的 live 三层门禁，
      该哨兵对 S5 **未验证**。
      ⚠️ 另记 S5 五项实测事实：
      ① **符号行守恒已实测** = 薄壳保留 **158**（区块1 29 + 区块8 124 + 区块9 5）+
        四模块 **362**（S1 108 + S2 94 + S3 90 + S4 70）= **520**，与 §2.1 拆分前实测
        **完全一致**；
      ② **薄壳残留文件行 = 317**，与 S4 收官值**逐行相同**（S5 不搬码，符合预期），
        **< 400** 门槛持续满足，距门槛余量 83 行；
      ③ **§十二 第 2 条 UNVERIFIED 由本片实测关闭**（§五 的 re-export 块「估 30-60 行,
        UNVERIFIED」→ 实测 **46 条 import 语句行**，落在原估算区间内；含横幅注释的
        re-export 区物理行 **144 行**，是 §五 预估「约 200-230 残留文件行」与实测 317
        差额的主因）；
      ④ **迁出块逐字节等价已按 S1-S4 四片全量复核**（19 个迁出函数体 + 19 条模块级赋值
        全部与 `HEAD:analysis/md_to_docx.py` 对应片段**逐字节相同**）；
      ⑤ **语义 golden 未变**（19 条用例全绿，`baseline.json` 的 `sha256` 仍是
        `a568ae4d3ddc1cf5366dc803c107944fd9d8d4845e59cc7c1cd084b48b526f93`，**未重生成**）。
      ⚠️ **勘误（2026-10-06 S5，独立只读验收发现；只补记，不改上方 S4 任何既有行）**:
      上方 S4 段记「区块 7 的 **2543 字节**，sha256 `9145f91c…`」——**字节数有误**。
      S5 复核实测：按 `HEAD:analysis/md_to_docx.py` 的**区块 7 物理区间 L379-450** 逐字节切片，
      实际为 **2704 字节**、sha256 前缀 **`9145f91c…`**（**哈希前缀与原文记载一致，仅字节数写错**）。
      另附两个函数的**纯函数体**（不含 def 之间的空行/注释）口径供后续对齐：
      `_load_result_near` 832 字节 + `_render_md_block` 1870 字节 = **2702 字节**，
      sha256 分别为 `30f212d3…` / `9dec1a8e…`。**三处数字都不同是因为口径不同**，
      故本片同时记下「区间口径 2704」与「函数体口径 2702」两个值，避免再次歧义。
      结论不变：迁出内容与原文**逐字节等价**成立，错误的只是 S4 那一个字节数。
- [ ] Critical Ruff `--select=E9,F63,F7,F82` 全绿（`.github/workflows/ci.yml:38`）; full ruff advisory 无新增告警
      （⚠️ 2026-10-06 补记: 工作区另有**第 2 道** Critical Ruff 门禁 `ci.yml:40-63`
      「Critical Ruff gate (config-excluded paths, narrow)」，用 `--isolated` 显式点名
      `analysis/sections/__init__.py` + `tests/sections/test_registry_gate.py`。
      本计划新建的 `analysis/reporting/docx_*.py` **不在**该门禁点名范围内，但仍受 `:38` 那道目录级门禁与 full advisory 约束）
- [ ] Python 矩阵: Ubuntu 3.10/3.11/3.12 + macOS 3.12（`ci.yml:114-123`；⚠️ 2026-10-06 更正，初版 `:92-98`）; `pyproject.toml:94` `target-version = "py310"` / `:95` `line-length = 100`
- [ ] 硬约束 **H1-H7 逐条仍绿**（否定式源码文本 2 条 + fixture 覆盖断言 / subprocess 路径 1 处 / `sys.modules` 假模块 **5 处** / 裸名 import 降级 1 处 / 跨文件行号引用 / 语义 golden / `verify_docx_style` 复用）
- [ ] 离线哨兵计数 **0**: 跑测试前用**独立于 pytest 的外层哨兵**阻断非 loopback 出口并报告计数。
      live 门禁三层都要确认生效: ① `pyproject.toml:71` `-m "not live"`（**只是默认值**, 命令行任意 `-m` 会整体覆盖它, 见 `pyproject.toml:62` 注释）;
      ② `tests/conftest.py:475` `pytest_collection_modifyitems` 收集期「整表达式 opt-in」fail-closed 选择层;
      ③ 用例级 `skipif` 要求 `DA_A_RUN_LIVE` **精确等于 `"1"`**（口径见 `tests/conftest.py:413`）
- [ ] 600693 + 002353 端到端冒烟单独跑通（**需网络授权**; 离线验收阶段不得触发）;
      `ci.yml:203` 确认 `*.docx` 落盘状态符合预期（⚠️ 2026-10-06 更正，初版 `:177`）
- [ ] `reports/` 现有条目 sha256 逐字节未变
- [ ] 6 个 checkpoint 全部自洽可交付; **提交与否以老板逐片授权为准**（本计划不自动 stage/commit/push）

### 10.2 回滚

- 每片是**可审查、可回滚的 checkpoint**，无跨片强制依赖 —— 任一片出问题，回到**本片开工前的工作区快照**即可。
- **回滚手段二选一**: ① 本片开工前留的工作区快照; ② `git diff` 生成的 patch 反向应用。
  **不依赖 `git revert`** —— 默认不提交，没有 commit 可 revert。
- **默认不 squash、不合并、不整理历史**。是否合并由老板逐片拍板。
- **禁止通过「更新基线 sha256」掩盖回归**。若某片 golden 不一致，必须先判定是
  「volatile 字段漏掩码」还是「真行为漂移」; 只有能指出**哪一处投影、对应哪一行模板、
  为什么语义上等价于原行为**时才允许更新基线，并写进本文件。
- 遇到 S0（H1 契约迁移）受阻: 允许把 S0 拆成 S0a（只加 fixture + 覆盖断言 + 改测试，不搬代码）和
  S0b（先只做 §一 的 S0-only 版本），**不允许把 H1 的测试改成放宽断言来「变绿」**。

---

## 十一、顺带发现（归属已定; 删不删仍需老板单独拍板）

- **三个模块级符号零调用点**（`grep -c` 计数 = 1，即只有定义行）:
  `_ensure`(L79-86, **8 符号行**) / `NUM_RANGE`(L274, **1**) / `HX_ACCENT`(L49, **1**)，合计 **10 符号行**。
  与 `docs/08-规范整改-P2D-报告渲染拆分-plan.md:422-432` 记录的 `_state_of` 属同一类。
- **归属已明确（本计划执行）**: 分别随 **S1**（`_ensure` 属区块 3 XML 小工具 / `HX_ACCENT` 属区块 2 token）
  与 **S2**（`NUM_RANGE` 属区块 6 表格）迁走，并在 `md_to_docx` 顶层 re-export。
  **本次一律原样搬走、不删** —— 删除是行为面清理，混进结构拆分会让「行为不变」这个判据失效。
  若要删，另开单片单独决策。

---

## 十二、UNVERIFIED 清单（未在仓库核实，不作已证事实引用）

1. **`.docx` 逐字节不可复现的两条推理**（zip entry 落盘时间戳 / `docProps/core.xml` 的 `modified`）——
   §7.1 均标 UNVERIFIED: 本次**未运行任何代码**验证，S0 必须实测确认。
2. **re-export 块 30-60 行** —— 纯估算，S5 实测为准。
3. **300-500 区间的外部规范版本号** —— 沿用 P2-A 的历史约定，**不是** `docs/08-规范整改-plan.md` §二 的条款（同 P2-D 的更正）。
4. **pytest / ruff 的实际运行时数字**（含「当前 passed / skipped 基线」）—— 本次**未运行**，无任何实测值。
5. **各区块的模块级符号扇入/扇出计数** —— §三 表格的行号为人工逐点核对所得，
   **未用 `ast` 复算**（本次受限只读），S0 建议以 `ast` 复算校准后再开工。
6. **语义 golden 的最终 JSON schema** —— §7.2 是规格草案，S0 实测定型后才算定稿。
7. **`docs/06-排版美化方案.md` 是否存在于其它分支 / 远端** —— 仅核实**本地工作区** `ls docs/06*` 无匹配。
8. **LibreOffice / `python-docx` / `lxml` 的实际安装版本** —— 本次未查询，不影响拆分结构设计。

---

## 十三、签字栏

- 立项: Mavis 2026-10-04 17:04（补 `docs/08-规范整改-P2A-模块拆分-plan.md:75` 缺失的专属 plan）
- **建议方案: S0-only（补语义回归 + 修 H1 否定式门禁），不搬代码** —— 理由见 §一（三条实测理由 + 二元性硬结论）
- **拍板（2026-10-06 落实）: 老板选定 ① 采纳 S0-only。S1-S5 全量拆分未立项、未开工**；
  §五 模块边界 / §六 拆分顺序**原样保留**，将来若单独拍板 ② 可直接开工，**从 S0 的成果接续**（不必重做）
- 开工条件: S0 已于 2026-10-06 完成并自测通过（见下方「S0 实施记录」）；**S1 及以后仍需老板单独授权**
- 审查安排: 全部由 MiniMax 独立只读验收; 不安排 Kimi

### S0 实施记录（2026-10-06，S0-only）

- **新增**: `tests/fixtures/docx_semantic/{minimal.md, docx_semantic.py, baseline.json, README.md}`、
  `tests/reporting/test_docx_semantic_golden.py`（9 条用例，含跨进程双 seed 自证）
- **改动**: `tests/conftest.py`（**仅文件尾追加** `md_to_docx_split_source` + 宿主符号契约，既有 fixture 未重排）、
  `tests/test_three_levels.py:405` 与 `tests/test_multi_state_trading_plan.py:203`（各 1 个函数改读新 fixture，
  **原两条否定式断言逐字保留**，各前置 3 条覆盖断言）、本计划与 `docs/13` §十三-六 的直接相关条款
- **零改动**: `analysis/md_to_docx.py`（含工作区既有 mypy 注解 `L470`）、`verify_docx_style.py`、
  `artifact_writer.py`、`analysis/sections/**`、HTML 侧、CI、`pyproject.toml`、`report_md.py`、
  `tests/fixtures/golden/**`、`reports/**`
- **未做**: live / 端到端跑批（无网络授权）、Git 写操作（未 add/commit/push/reset/clean）、
  死符号清理、`_render_md_block` 去重、任何业务阈值或文案改动、哨兵脚本
- **§十二 UNVERIFIED 关闭情况**: 第 1 条（`.docx` 逐字节不可复现的两条推理）**已实测坐实**——
  同一输入在不同进程、不同 `PYTHONHASHSEED` 下产出同一语义指纹，而容器字节不可比（见 §7.2 实测基线块）；
  第 4 条（pytest/ruff 实际数字）**已实测**并写入 §十; 第 6 条（语义 golden 最终 JSON schema）**已定稿**为
  `p2e-s0-docx-semantic/1` + `p2e-s0-docx-semantic-baseline/1`;
  第 5 条（§三 扇入/扇出）**符号行已用 `ast` 复算校准**（49 个顶层符号、符号行 520、
  恒等式 520+51+13=584 与交叉校验 510=520−23+13 全部成立），**调用点计数仍是人工逐点核对**;
  第 8 条已查明 `python-docx 1.2.0` / `lxml 6.1.3` / `venv Python 3.13.5`。
  第 2（re-export 行数估算）与第 3（300-500 区间外部版本号）**仍为 UNVERIFIED**（属 S5 / 沿用历史约定，不因 S0 而关闭）
- **本记录不构成 P2E 收官**: §十 收官门槛的多数条目（薄壳 < 400 行、符号行守恒、5 片 golden 不变、
  600693 + 002353 端到端冒烟、`reports/` sha256 逐字节未变、6 个 checkpoint）**均属 S1-S5 范畴，尚未开始**。
  本轮**不做自评验收**，结论待主控安排**新鲜 MiniMax 只读验收**。
