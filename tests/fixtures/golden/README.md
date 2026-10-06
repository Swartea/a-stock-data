# golden result_v3 fixture (600693 / 002353)

版本化的 `result_v3` 基线, 供 `tests/test_scoring_breakdown.py` 的 golden 端到端用例使用。
生成器 = 本目录的 `golden_fixtures.py`(既是生成器也是加载器)。

## 为什么要它

`docs/10-pipeline拆解地图-phase1a.md` 的 Phase 1H 验收规则要求"Ubuntu 3.10/3.11/3.12 +
macOS 3.12 Pytest 全绿 + 600693 端到端 Smoke"。但这批 golden 用例是按
`reports/<code>_<name>/<date>/result_v3-<HHMM>.json` 找**历史跑批产物**的, 而:

- `reports/` 在 CI 矩阵 job 里只有 `.gitkeep`(smoke 是**另一个 job**, 在 test 之后跑);
- 产物含本机绝对路径与 PDF 渲染器报错串, 本来就不适合进版本库。

结果: 矩阵里的 result_v3 契约覆盖 = 0(全 skip)。本目录把仓库内已有证据固化成
可版本化 fixture, 让这批用例在矩阵里真跑。

## 文件

| 文件 | 票 | 性质 | 大小 (磁盘字节) |
|------|----|------|------|
| `result_v3-600693-20261003.json` | 600693 东百集团 | **capture** — 真实跑批产物裁剪 | 40,307 B（34,169 字符，中文 3 字节/字） |
| `result_v3-002353-20260912.json` | 002353 杰瑞股份 | **curation** — 按仓库已记录标量拼装 | 1,644 B |
| `golden_fixtures.py` | — | 生成器 + 加载器 | — |

## 600693 出处(capture)

| 项 | 值 |
|----|----|
| capture 源 | `reports/600693_东百集团/2026-10-03/result_v3-1618.json`(本地产物, 未追踪) |
| 跑批时间 | 2026-10-03 16:16:55 → 16:18:29 (+08:00), 94.7s |
| 源 sha256 | `609708186c3e26894484223d477b7a788c6d18180d28e55f9e93cb273b08d177` |
| 行情/估值 | 现价 9.32, PE(TTM) 165.65, PB 2.27, 总市值 81.07 亿 |
| 评分 | 综合 50/100, 10 因子全活, 5 维守恒 |
| 三价位 | 支撑 8.31(boll_lower) / 压力 11.63 / 止损 8.67(method=trading_plan) |
| 交付 | `deliverable_status=partial`(md/html/docx/result/run_log ok, pdf 降级) |

生成器退出码：capture 源缺失或 sha256 漂移 → `1`（**在任何写盘之前**失败，不创建也不改写任何文件）；已存在 golden 与本次重新生成的结果不一致 → `2`（**不写盘**，原基线保持原样）；只有显式加 `--force` 才会覆盖基线。初始创建（目标文件不存在）始终允许。

## 002353 出处(curation)

002353 **没有任何 result_v3 产物落在仓库里**。下列每个标量都有仓库内出处:

| 字段 | 值 | 出处 |
|------|----|----|
| `score` 10 因子 + total | 8/10/6/6/3/2/8/1/3/6, total 53 | `tests/test_scoring_breakdown.py:117-119`(原注释标注 `# 002353`) |
| `quote.price` / `valuation.price` | 118.94 | `analysis/references/three-levels-rules.md` §六 例子 5 |
| `valuation_hist.pe_percentile_3y` | 87.8 | `docs/09-报告质量债2.0-plan.md` 批次 E 痛 3 |
| `three_levels.support` / `support_op_key` | 108.37 / boll_lower | `tests/test_three_levels.py:588-589` |
| `three_levels.support_extreme` | 104.87 | `tests/test_three_levels.py:591` + 上面 例子 5 |
| `three_levels.stop_loss` / `stop_loss_method` | 110.61 / trading_plan | `tests/test_three_levels.py:593-594` + `docs/09` 批次 D 痛 2 |
| `report_date` | 2026-09-12 | `tests/test_three_levels.py:585` 的 fixture 路径 |

**故意不落 / 用自述式占位的字段**(避免把推断当观测):

| 字段 | 处理 | 原因 |
|------|------|------|
| `trading_plan` | **整块缺键** | 仓库只记了 `stop_loss=110.61`; `report_md.py:636` 起对 plan 硬索引 8 个键(`entry_low`/`entry_high`/`tp1`/`tp2`/`tp3`/`stop_loss_pct`/`position`/`period`), 填一半必 KeyError。缺的部分不补 |
| `advice` / `emoji` | 自述式占位串 | `report_md.py:397` 硬索引这两个键, 缺键必崩。但 002353 那次的**观测值**仓库没留存 —— `docs/09` 痛 3 记的是改之前的"区间操作"和改法规则的两个候选("轻仓试探"/"观望"), 都不是当天实际输出。占位串本身写明"未记录", 渲染出来一眼可辨, 不冒充操作结论 |
| `chip_data` | `{}` | `v2._interpret_chips` 只判 `if not cd or "error" in cd`, 非空 dict 会硬索引 `cd["profit_ratio"]`。002353 筹码数据无记录 → 整块留空(与 `conftest.rendered_markdown_v3` 兜底口径一致) |
| `score.factors` | `[]` | 因子文案串无记录 → 渲染成"无明细", 不编造 |
| `score.change_pct` 等 | **缺键**(不写 `null`) | 未记录字段一律缺键让 `report_md` 走 `.get(k, 默认)`; 写显式 `None` 会让 `report_md.py:422` 的 `change_pct >= 0` 直接 TypeError |

⚠️ 002353 fixture **没有 K 线序列**, 因此三价位**不可重算**。里面的 `three_levels`
是从上表记录值搬过来的快照, 不能当成 `compute_three_levels()` 的回归基线用。

## 归一化口径(600693 capture 做了什么)

生成器只做 5 件事, 全部可用 `write_markdown_report_v3` 渲染等价性验证:

1. **白名单裁剪**: 只留 result_v3 契约键集 + 渲染层真正读到的键。
2. **剥离落盘产物元数据**: 顶层 `_files` / `pdf_path` / `pdf_status`, 以及
   `run_log.artifacts`(含产物文件名、字节数、Chrome/LibreOffice 报错串与本机路径)。
   三个块 `report_md` / `html_report_v3` 都不读(只由 pipeline 写), 剥掉不损失渲染覆盖。
3. **剥离本机路径**: 递归把含仓库绝对路径 / `/Users/` / `/home/` 的字符串置 `null`。
4. **剥掉耗时抖动**: 状态串尾部 `", 1716ms"` 用正则刮掉。**保留** `ok:` /
   `fallback:` / `error:` 前缀 —— 那是数据质量证据, 报告靠它解释降级章节。
5. **丢大体量可重算序列**: `chip_data.kline`(180 根 OHLCV)、`valuation_hist.pe_series` /
   `pb_series` / `close_series`; 以及派生的 `scoring_breakdown`(让测试自己从 `score` 重算,
   这样 e2e 用例才真的在验重算路径)。

**已知且刻意接受的副作用**: dump 用 `sort_keys=True` 保证 byte-stable, 因此
`three_levels.support_candidates` / `run_log.sources` 表的行序变成字典序。
4 个支撑候选与 3 个压力候选的**数值**完全不变, 20 条 source 状态**语义**完全不变,
只是行/列顺序不同。

渲染等价性实测(源产物 vs golden, 完整版 MD 396 行): 78 行变化, 全部落在上面 3 类
(耗时尾巴 66 行 + sort_keys 顺序 12 行), 业务内容零丢失。

## 缺失源数据(精确值基线仍不可得)

`tests/test_three_levels.py` 里有 4 个用例**按精确数值**断言, 需要 2026-09-12 /
2026-09-11 那几天**真实跑批的 baostock 前复权日 K 序列 + 筹码峰 + V2 交易计划**。
仓库里没有这些数据, 本目录也**没有**伪造。可复现性已实测确认:

- 600693: 唯一真实产物是 2026-10-03 那份, 拿它重算 `compute_three_levels` 得
  `support=8.31(boll_lower) / support_extreme=7.13 / stop_loss=8.67`,
  与用例期望的 `8.99(ma60) / 7.16 / 9.23` **三个值全不同**(日期不同, 行情本就不同)。
- 002353 / 605162: 仓库零产物。

补齐它需要的东西(任一即可):

1. 归档那两天的 `result_v3-*.json` 原文到 `tests/fixtures/golden/`, 或
2. 归档对应 K 线序列(日期/开/高/低/收/turn)成一份 CSV/JSON, 由生成器合成 result 形状。

在补齐之前, 这 4 个用例应保持 `pytest.skip`, 不要用合成行情把它们"跑绿"。

## 重新生成

```bash
python tests/fixtures/golden/golden_fixtures.py
```

- 600693 源缺失时生成器 **fail loud** 并提示先跑
  `python analysis/quant_analyzer_v3.py 600693 东百集团`; 不会凭空构造行情。
- 输出 byte-stable: `sort_keys=True` + `indent=2` + 末尾换行, 连续两次生成 sha256 相同。
- 002353 是声明式表(`EVIDENCE_002353`), 改它等于改证据, 需要一并更新本文件上表。

## 测试如何消费

`tests/test_scoring_breakdown.py`:

- `_load_sample_result()` → 600693 结构基线, golden 优先, 回落到
  `reports/600693_东百集团/2026-09-13/result_v3-0914.json`。
- `_latest_result_v3_for(code_name)` → golden 优先, 否则取 `reports/` 下最新一份。
  605162 无 golden, 仍走回落分支并 skip。
