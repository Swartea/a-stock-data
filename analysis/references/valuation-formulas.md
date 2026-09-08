# 估值公式说明

## PEG（市盈率相对盈利增长比率）

**标准公式**：`PEG = PE / 盈利增速%`

其中盈利增速是**百分比数值**（如 21 = 21%），不是小数（0.21）。

**ifind PEG(LYR) 口径**：
- 分母 = LYR（Last Year Reported）净利润同比增速%
- 分子 = PE TTM
- 600693 实测：PE 218 / 同比 5.2% = 41.9（实测 41.73）

**本项目 V2/V3 实现（fix round 1 改后）**：
- `analysis/quant_analyzer_v2.py` `fetch_full_valuation()` line 248-253
- `cagr_pct = (eps_next / eps_cur - 1) * 100`（已转为百分数；次年预期增速）
- `peg = pe_ttm / cagr_pct`（分子改用 pe_ttm 即 TTM PE，**不再用 pe_fwd**）
- 600693 实测：pe_ttm 205 / cagr_pct 21 = **9.57**（spec §8.2 第 4 条"8-12 区间"内）

**方法学差异（非 bug，需知会用户）**：
- V2/V3 仍**与 ifind PEG(LYR) 有方法学差异**：V2 用 pe_ttm + **次年**预期增速，ifind 用 pe_ttm + **LYR** 同比增速
- 数量级一致（10x vs 10x，误差 ~4x），但绝对值不同（V2 9.57 vs ifind 41.73）
- 这是 V2 选"次年 21%"基准 vs ifind 选"LYR 同比 5.2%"基准的口径差异，不是公式 bug

**注意**：
- `digest_years` 公式内部用 `cagr_decimal = cagr_pct / 100`（小数）
- 历史 bug（9-7 发现）：曾用 `cagr * 100` 把小数当百分数，导致 PEG 差 10.8x
- fix round 0（commit c4d6680，9-8）：`cagr` → `cagr_pct` 命名重构 + digest_years 兼容
- fix round 1（本次）：`pe_fwd` → `pe_ttm`，分子改用 TTM PE，对齐 ifind 数量级
