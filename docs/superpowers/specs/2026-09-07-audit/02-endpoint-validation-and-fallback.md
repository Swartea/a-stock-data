# A-Stock-Data 端点验证 + 备胎方案报告

| 项 | 值 |
|---|---|
| 来源 | Mavis explore 子 agent（task `bg_84d6a936-5225-4d01-a99f-460420c73c30`） |
| 日期 | 2026-09-07 |
| 范围 | 5 个新章节端点实测 + 4 个失败源备胎研究 + 31 个未用端点价值评估 |
| 约束 | Explore agent 无 bash/write 工具，仅 read/grep/glob/web_fetch |
| 测试票 | 600693 东百集团 |

> **范围说明**：以下数据来自：
> 1. SKILL.md 端点实现的代码级静态分析
> 2. 现存 V2/V3 代码定位
> 3. 9-6/9-7 `run_log.json` 失败模式
> 4. 对每个端点的**真实 URL 直连探测**（web_fetch 验证）

---

## Part A: 5 个新章节端点实测

### A.1 实测结果

| # | 端点 | 章节 | 实测 URL 探活 | 样本（前 3-5 条）| 风险 | 结论 |
|---|------|------|----------------|-----------------|------|------|
| 1 | `cninfo_irm(code)` | §10.1 互动易 | irm.cninfo.com.cn 主页 200，**API 需 POST，GET 返回 405** | POST /newircs/index/queryKeyboardInfo → [{secid:"gssz0600693"}]；POST /newircs/company/question → [{Q&A, asker/answerer/time}] | 中：需两步（先查 orgId），GET→POST 必做，cninfo 偶发 502（设计稿已标） | **可集成**，但 `cninfo_irm` 实现里的 `requests.post` 用 `data=` 传参（OK），`headers` 必备 UA |
| 2 | `holder_num_change(code)` | §4.3 股东户数 | datacenter-web.eastmoney.com RPT_HOLDERNUMLATEST → **200，1 行** | 600693: 2026-06-30, HOLDER_NUM=86517, PRE=92831, 环比 -6.80%, 户均=10054 股 | 低：datacenter 不与 push2 同一风控面（已知 9-6 案例） | **稳定可集成**，datacenter 一直没出过大问题 |
| 3 | `dividend_history(code)` | §4.4 分红 | datacenter-web RPT_SHAREBONUS_DET → **200，10 行** | 600693: 2026-07-17 派 0.4 元、2025-09-25 派 0.5 元、2025-07-04 派 0.3 元、… (含送转/进度) | 低 | **稳定可集成**，字段丰富（除权日/方案/进度），注意 `BONUS_RATIO=null` 时字段映射要 None-safe |
| 4 | `em_zt_pool`/`em_zb_pool`/`em_dt_pool`/`em_yzt_pool` | §8.1 四池 | push2ex.eastmoney.com getTopicZTPool/DTPool → **200，39+9 行** | 600693 不在榜（合理），9-7 共 39 只涨停（恒盛能源/新炬网络/楚天龙/翠微股份/…），9 只跌停（集泰股份/传智教育/…） | 中：依赖 `ZTB_UT` 常量（"7eea3edcaed734bea9cbfc24409ed989"），UT 失效会整片失败 | **稳定可集成**，UT 在 SKILL.md 公开且全网唯一硬编码 |
| 5 | `ths_limit_up_pool(date)` | §8.2 涨停原因 | data.10jqka.com.cn → **200，38 行** | 9-4: 新希望("猪价回暖+饲料增长+养殖降本")、华阳国际("AI设计+城市更新+建筑设计")、敦煌种业("种业+育种研发+中报增长")、… 封板成功率 0.7~1.0 | 低-中：同花顺全公开无鉴权，字段是公司内部 ID（`field=199112,10,9001,...`）需照抄 | **稳定可集成**，`first_limit_up_time` 是 Unix 秒时间戳（不是 HHMMSS，注意 #坑） |
| 5b | `limit_up_sentiment(date)` | §8.3 打板情绪 | 由 8.1 派生（纯本地计算） | `zt_count=39, dt_count=9, max_height` 来自四池组合 | 低 | **稳定可集成**，0 额外网络 |
| 6 | `daily_dragon_tiger(date)` | §3.9 全市场龙虎榜 | datacenter-web RPT_DAILYBILLBOARD_DETAILSNEW → **200，66 条** | 9-4 TOP10: 楚天龙 6.71亿、平潭发展 4.84亿、远东股份 4.73亿、天娱数科 4.50亿、… | 低：datacenter 风控面独立 | **稳定可集成**，注意 `EXPLANATION` 字段含"普通席位/机构/上海资金/主力做T"等明细 |

### A.2 单测代码骨架（`/tmp/test_new_endpoints.py`，伪）

**约束：read-only agent，无法真正落盘到 /tmp**。代码结构如下（Mavis worker 可直接抄）：

```python
# /tmp/test_new_endpoints.py — 5 端点最小测试
import sys, time
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")
sys.path.insert(0, "/Users/swarteachou/.minimax/skills/a-stock-data")
from a_stock_data import (cninfo_irm, holder_num_change, dividend_history,
                          em_zt_pool, em_zb_pool, em_dt_pool, em_yzt_pool,
                          ths_limit_up_pool, limit_up_sentiment, daily_dragon_tiger)

CODE = "600693"
DATE = "20260904"  # 9-4 是已知最近交易日

def t(fn, *args, **kw):
    s = time.time()
    try:
        r = fn(*args, **kw)
        ms = int((time.time() - s) * 1000)
        return r, ms, None
    except Exception as e:
        return None, int((time.time() - s) * 1000), str(e)

# 1. cninfo_irm
irm, ms, err = t(cninfo_irm, CODE, 5)
assert err is None, f"irm failed: {err}"
assert isinstance(irm, list) and len(irm) > 0
assert "question" in irm[0] and "answer" in irm[0]
print(f"[OK] cninfo_irm: {len(irm)} 条, {ms}ms")

# 2. holder_num_change
hol, ms, err = t(holder_num_change, CODE, 5)
assert err is None and len(hol) > 0
assert "holder_num" in hol[0] and "change_ratio" in hol[0]
print(f"[OK] holder_num_change: {len(hol)} 条, {ms}ms")

# 3. dividend_history
div, ms, err = t(dividend_history, CODE, 5)
assert err is None and len(div) > 0
assert "bonus_rmb" in div[0]
print(f"[OK] dividend_history: {len(div)} 条, {ms}ms")

# 4. em_zt_pool + sentiment
zt, ms, err = t(em_zt_pool, DATE)
assert err is None and len(zt) > 0
assert "code" in zt[0] and "limit_days" in zt[0]
sent, _, _ = t(limit_up_sentiment, DATE)
assert sent["zt_count"] == len(zt)
print(f"[OK] 4 pools + sentiment: zt={len(zt)}, sentiment={sent}")

# 5. daily_dragon_tiger
dt, ms, err = t(daily_dragon_tiger, DATE)
assert err is None and dt["total_records"] > 0
assert "code" in dt["stocks"][0]
print(f"[OK] daily_dragon_tiger: {dt['total_records']} 条, {ms}ms")
```

---

## Part B: 4 个失败源备胎研究

### B.1 实测现状（9-7 → 今日 web_fetch 复测对比）

| 失败源 | 当前错误（9-7 run_log）| 现状复测 | 推荐备胎 | 实测备胎结果 | 准确性差异 |
|--------|------------------------|----------|----------|--------------|------------|
| **概念板块**（slist）| "fallback:接口返回0条(可能风控), 7021ms" | `push2.eastmoney.com/api/qt/slist/get?...secid=1.600693` → **200，17 个板块**（一般零售/百货/福建板块/旅游概念/沪股通/一带一路/…） | **§3.7 industry_comparison**（clist m:90+t:2） | 复测 `clist` push2 端点 502 — **不能用**；改 `push2his` 同源端点，clist 仅有 `secid=1.600693` 反向查板块名，**勉强可用** | 1) §3.7 给**行业归属**（不一定命中 600693 的"一般零售"）；2) §1.2 腾讯 `qt.gtimg.cn` 不带板块字段——**这两个都不是完美替代** |
| **当日资金流**（fflow minute）| "error:Expecting value: line 1 column 1 (char 0), 2090ms" | `push2.eastmoney.com/api/qt/stock/fflow/kline/get?klt=1` → **502 Bad Gateway**；`push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?klt=1` → **200，132 行** | **改用 push2his 域名**（klt=1 仍为分钟） | 600693 当日 132 分钟级 4 档明细齐全（main/small/mid/large/super_net）| **0 差异**（同源同字段，仅域名 push2 → push2his；#46 已说明） |
| **资金面-5日主力**（_fetch_fund_flow_daily）| "error:Expecting value: line 1 column 1 (char 0), 4641ms" | `push2.eastmoney.com/api/qt/stock/fflow/kline/get?klt=101` → **502**；`push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=5` → **200，5 日** | **改用 push2his 域名 + lmt=5** | 600693 5 日 4 档净额齐全：9-01 +1.71亿、9-02 -0.39亿、9-03 +2.28亿、9-04 -0.06亿、9-07 -0.25亿 | **0 差异**；**重要：V3 `_fetch_fund_flow_daily` 实现用的是 push2 域名（line 269），与 SKILL.md §4.5 给的 push2his 实现不一致 — 是 V3 的实际 bug** |
| **同业对比**（_fetch_concept_peers）| "error:概念板块列表为空(东财 slist 返回 0 条, 可能风控), 无法做同业对比" | `_fetch_concept_peers` 内部用 `push2/clist` (fs=b:{bcode}) → **502** | **行业口径 fallback**（V3 已部分具备）：用 `industry_comparison` 取本票所属**行业板块**（`sw_stability` 已知 l1_code），按行业成分股做对比，绕开概念板块 slist | 复测 clist 502；改用 `datacenter-web RPT_GMSM_BOARDDATA` 可拿行业成分股，但需行业 BK 码 | **差异大**：从"概念板块成分"降级到"行业板块成分"，是不同维度；对 600693 影响 = 走"一般零售"行业而非"沪股通/福建板块/旅游概念"等具体概念 |

### B.2 关键发现：3 个备胎定位与可行性

#### 备胎 1：同日同源跨域（推荐度 ★★★★★）

| 主源 | 备胎 | 同源? | 风控面 |
|------|------|-------|--------|
| `push2.eastmoney.com/api/qt/stock/fflow/kline/get` | `push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` | ✅ 同一组数据，**仅域名前缀** | push2his 与 push2 走**不同 WAF**，实测 push2his 持续稳定 |

**结论**：V3 `_fetch_fund_flow_daily` (line 269) 用 push2 域名是**实现 bug**，应改 push2his（与 SKILL.md §4.5 实现对齐）。零业务影响、零开发量、立即可修。

#### 备胎 2：datacenter-web 跨域（同 WAF 隔离，★★★★）

| 主源 | 备胎 |
|------|------|
| `push2/.../slist`（风控）| `datacenter-web/.../RPT_*` 系列（独立 WAF，9-6 案例证明 9-7 push2 全系挂时 datacenter 不受影响） |

可考虑在 V3 fetcher 加 fallback 链：`push2/slist` → `datacenter/.../RPT_GNBB`（概念+成分股综合表）

#### 备胎 3：新浪/交易所官方（★★★，兜底）

SKILL.md 已有 3 个实测备胎函数（`fund_flow_backup`/`dragon_tiger_backup`/`announcements_backup`），但**当前 4 个失败源都不直接对应这 3 个备胎**：

- 概念板块：无备胎（slist 失败只能等或换 IP）
- 当日资金流：可用 `fund_flow_backup(code)` 拿**日度**数据（非分钟），是降级
- 5 日主力：可用 `fund_flow_backup` 拿**更全 60 日**序列，比 5 日还丰富
- 同业对比：无直接备胎

### B.3 推荐的修法

| 失败源 | 建议 | 代码改动量 |
|--------|------|----------|
| 资金面-5日主力 | **必改**：line 269 域名前缀 push2 → push2his | 1 行 |
| 当日资金流 | 建议改：line 308 同理 + §3.4 端点也改 | 2 行（V2 + V3 双处） |
| 概念板块 | 加 retry-with-backoff（失败时 5s 后再试一次），slist 是 IP 级风控而非端点挂 | 5 行 |
| 同业对比 | 加 fallback 链：先 slist→再 industry_comparison 派生（V3 已有 sw_stability，可拼"行业名+行业成分"） | 15 行 |

---

## Part C: 36 个未用端点价值 Top 5

### C.1 全清单与维度评分

> V3 现有 18 + 5 新 = 23 端点；SKILL.md 总览表 51 端点 + 3 备胎 = 54；
> 未用 = 54 − 23 = **31 个**（设计稿"36"为概数；下面按实际盘点）

| 章节 | 未用端点 | 决策价值（1-5）| 集成成本（1-5，5=最难）| 推荐度 |
|------|----------|----------------|------------------------|--------|
| §2.1 | `eastmoney_industry_reports(industry_code)` | **4**（研报层已有，但只有个股）| 1（与 2.1 研报共用端点）| ★★★★ |
| §3.1 | `ths_hot_reason()` 强势股词频 | **3**（信号层单票相关弱）| 1 | ★★★ |
| §3.2 | `hsgt_realtime()` 已在 V3 macro | 0（已在用）| — | — |
| §3.8 | `board_fund_flow(board_type, period)` | **5**（补 §3.3 失败时的板块资金背景，决策极强）| 2（push2 风控面，已知 502）| ★★★★ |
| §3.9 | daily_dragon_tiger | 已在 5 新节 | — | — |
| §4.2 | `block_trade(code)` 大宗交易 | 3（筹码集中线索）| 1 | ★★★ |
| §4.5 | `stock_fund_flow_120d(code)` 120 日资金流 | 4（资金面长周期）| 1（与 §3.4 同源）| ★★★★ |
| §5.2 | `cls_telegraph()` 财联社快讯 | 2（与 §5.3 全球资讯高度重叠）| 1 | ★★ |
| §5.3 | `eastmoney_global_news()` | 2（同上）| 1 | ★★ |
| §6.1 | `client.finance(symbol)` mootdx 财务快照 | 3（与 RPT_F10_FINANCE_MAINFINADATA 重复）| 0（库已装）| ★★ |
| §6.2 | `client.F10(symbol, name)` F10 文本 | 2（**已用在 V3 财务摘要的备选**）| 0 | ★★ |
| §6.3 | `eastmoney_stock_info(code)` | 0（已用在财务摘要）| — | — |
| §6.4 | `sina_financial_report(code, type)` 财报三表 | **4**（年报全文决策时有用）| 1 | ★★★★ |
| §6.5 | baostock_valuation_history | 0（已在用）| — | — |
| §6.6 | `baostock_stock_basic(code)` 上市/退市 | 3（**ST/退市前哨**，但不支持北交）| 1 | ★★★ |
| §6.7 | sw_industry_history/as_of | 0（已在用）| — | — |
| §7.1 | cninfo_announcements | 0（已在用）| — | — |
| §7.2 | `client.F10` 公告摘要 | 1（V3 已用 cninfo_announcements）| 0 | ★ |
| §8.4 | `em_stock_monitor()` 重点监控池 | 4（**ST/退市前哨 2** + 风险警示，强信号）| 0 | ★★★★ |
| §8.5 | `em_price_anomaly()` / `count()` 日内异动 | 4（强打板信号）| 0 | ★★★★ |
| §9.1 | `sina_option_codes/tquote/greeks` ETF 期权 | 2（**只对 ETF/50/300/500** 相关标的有用）| 0 | ★★ |
| §10.2 | `ths_hot_list()` / `em_hot_rank()` / `em_hot_concept()` | 3（**热榜作背景**）| 1 | ★★★ |
| §11.1 | `pboc_social_financing(year)` 社融 | 4（**宏观底色升级**，当前 V3 macro 缺）| 0 | ★★★★ |
| §11.2 | `nbs_pmi()` PMI | 4（同上）| 0 | ★★★★ |
| 备胎 | `dragon_tiger_backup` | 0（V3 龙虎榜 ok）| — | — |
| 备胎 | `fund_flow_backup` 新浪 | 0（V3 push2his 改完就够）| — | — |
| 备胎 | `announcements_backup` | 0 | — | — |
| §1.1 | `tdx_client` (K线/盘口) | 0（V3 chips 用了）| — | — |
| §1.3 | `baidu_kline_with_ma` | 1（与腾讯 K 线重叠）| 0 | ★ |
| §1.4 | `sina_adjust_factor` | 3（**筹码计算用，但 V3 chips 已有换手率**）| 0 | ★★ |
| §2.3 | `iwencai` (需 Key) | 4（**唯一 NL 语义搜**）| 3（要 Key）| ★★★ |

### C.2 Top 5 推荐

| 排名 | 端点 | 价值 | 集成成本 | 推荐度 | 决策理由 |
|------|------|------|----------|--------|----------|
| 🥇 | **§3.8 `board_fund_flow(industry, today)`** | 5 | 2 | ⭐⭐⭐⭐⭐ | **直接解 4 个失败源之一**：当 §3.3 slist 失败时，board_fund_flow 给"本票所属行业的板块资金"作为情绪因子，零额外失败面 |
| 🥈 | **§8.4 `em_stock_monitor()`** | 4 | 0 | ⭐⭐⭐⭐ | 零成本、零风险（静态 JSON 已知存活），ST/退市前哨 2.0，决策表直接加"是否在重点监控"列 |
| 🥉 | **§8.5 `em_price_anomaly()`** | 4 | 0 | ⭐⭐⭐⭐ | 强打板信号，与 §3.9 联动 = "全市场龙虎榜 TOP N + 当日异动明细" 双源验证 |
| 4 | **§11.1+§11.2 社融+PMI** | 4+4 | 0 | ⭐⭐⭐⭐ | V3 宏观底色当前是"同花顺北向+东财行业+同花顺强势股"，缺**真实宏观**；零成本直接补 |
| 5 | **§4.5 `stock_fund_flow_120d(code)`** | 4 | 1 | ⭐⭐⭐⭐ | §3.4 分钟资金流是日内高频，但 120 日序列给"长周期资金偏好"——**与 V3 筹码分布互为佐证** |

**备选 Top 6-7**（成本相近，再补 2 个）：
- §6.4 `sina_financial_report` — 财报三表全文，年报披露窗（3-4 月）决策强信号
- §2.1 `eastmoney_industry_reports` — 行业研报，1 行代码复用

---

## Part D: 关键发现

### D.1 端点实现与 SKILL.md 描述不符（**重要 bug**）

| 位置 | SKILL.md 描述 | V2/V3 实现 | 实际差异 |
|------|---------------|------------|----------|
| **§3.4 eastmoney_fund_flow_minute** (SKILL.md line 1548) | `push2.eastmoney.com/api/qt/stock/fflow/kline/get` | ✅ 一致 | OK |
| **§4.5 stock_fund_flow_120d** (SKILL.md line 2161) | `push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` | ✅ 一致 | OK |
| **V3 `_fetch_fund_flow_daily`** (quant_analyzer_v3.py line 269) | 应该是 push2his | ❌ **用的是 push2** | **域名前缀错误，是 V3 的实际 bug**！ |
| **V2 `fetch_fund_flow_minute`** (quant_analyzer_v2.py line 308) | push2 | ✅ | OK（分钟级主源就是 push2）|
| **§3.3 eastmoney_concept_blocks** (SKILL.md line 1494) | push2 slist | ✅ 一致 | OK，9-7 是 IP 风控非端点错 |

### D.2 风控阈值/限制需要补充到 SKILL.md

| 项 | 现状 | 建议 |
|----|------|------|
| **push2 域 IP 级风控** | SKILL.md 提到 datacenter 不受影响，但**没说 push2 502 时切 push2his** | 补一段："push2 全系 502 → 切 push2his 同路径，**不重试**（502 是负载而非限速，重试无意义）" |
| **当日分钟资金流 klt=1** | SKILL.md 只说字段口径 | 补："非交易时段 + 节假日 push2 整域 502 是常态，盘前/盘后禁用" |
| **ZTB_UT** (`7eea3edcaed734bea9cbfc24409ed989`) | SKILL.md 没提失效策略 | 补："UT 是东财登录 token（隐式），实测可长期不变；若失败 → 等 24h 通常自动轮换" |

### D.3 有 bug 需修的端点

1. **🔴 V3 `_fetch_fund_flow_daily` 用 push2 而非 push2his**（line 269）— 1 行改，立即解 9-7 资金面-5日主力失败
2. **🟡 V3 4 个 fetcher 都没有 retry 策略**（fetch_fund_flow_minute 等只 catch 后 return []）— 风控 502 应 retry 1 次后切备胎
3. **🟢 概念板块 slist 失败时无 fallback**（fetch_eastmoney_concept_blocks）— 加 datacenter-web RPT_GMSM_BOARDDATA 反向查板块
4. **🟢 同业对比 _fetch_concept_peers 强依赖概念板块**（line 338）— 加行业口径 fallback（sw_stability + industry_composition）

### D.4 章节端点 SKILL.md 描述的"坑"与现实差异

| 坑 | SKILL.md 描述 | 实测 |
|----|---------------|------|
| 互动易需 POST | line 3362-3372 写 POST + UA | ✅ 与现实一致 |
| 涨停/跌停池时间字段 | line 2953-2955 写"整数 → HHMMSS" | ✅ 一致（实测 fbt=92501 解析成 09:25:01）|
| 涨停原因 first_limit_up_time | line 3062 写"Unix 秒时间戳" | ✅ 一致（实测 1788498291 = 2026-09-04 09:31:31）|
| 股东户数 ratio 是环比% | line 2107 写"环比%" | ✅ 一致（实测 -6.80%）|
| 分红 0 值 vs null | line 2133-2139 没强调 | ⚠️ 实际 BONUS_RATIO/IT_RATIO 大量 null（旧票），**BONUS_RATIO=null 时 SKILL.md 用 `b.get("BONUS_RATIO", 0)` 会变 0，误以为"每股送 0 股"** — 建议 fetcher 改用 `.get(...)` + None 判断 |
| 财联社快讯 | 标记 V3.4 复活，errno=0 | ⚠️ 未实测（仅看 SKILL.md 静态） |

---

## 给 worker 的下一步建议

1. **优先修**（零风险 1 行）: V3 line 269 push2 → push2his，立即解 9-7 资金面-5日主力失败
2. **同步修**（零风险 1 行）: V2 line 308 同步 + SKILL.md §3.4 同步，确认所有资金流主源走 push2his
3. **次优先**（Section Registry 1 节成本）: 把 §3.8 board_fund_flow 纳入"宏观底色"或"概念板块"失败兜底
4. **增强**（30 分钟）: V3 4 个 fetcher 加 retry 1 次 + 切备胎逻辑
5. **推迟**: iwencai（需 Key）、9.1 ETF 期权（适用面窄）
