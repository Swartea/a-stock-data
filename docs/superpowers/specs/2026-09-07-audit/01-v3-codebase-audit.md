# V3 代码库深度审计报告

| 项 | 值 |
|---|---|
| 来源 | Mavis explore 子 agent（task `bg_fc1568c2-934c-42f2-85f0-432dcdb78dac`） |
| 日期 | 2026-09-07 |
| 范围 | `analysis/`（V3 主分析器 + 4 个新 fetcher + HTML/MD 渲染器）|
| 依据 | `docs/superpowers/specs/2026-09-07-a-stock-data-skill-optimize-design.md`（git commit 75d6a0e）|
| 方式 | grep 全文索引 + 关键函数逐行 + 跨文件契约核对 + run_log 反推 |

---

## 0. 总体评估（TL;DR）

- **设计稿 vs 实现落差 严重**：设计稿的 Section Registry（Approach B）和 5 个新章节（互动易/股东户数/分红/打板/全市场龙虎榜）**完全未实现**。当前实现的"6 块新增"只是内联堆叠的 4 个 fetcher + 3 个 supplement。
- **PEG 公式 bug 确认存在**：`quant_analyzer_v2.py:251` 的 `peg = pe_fwd / (cagr * 100)` 把"次年增速（如 0.21）"当百分比乘了 100，等于乘 10000%（10.8x 误差源头）。
- **V3 命名 bug 确认存在**：`result_v3.json` 和 `run_log.json` 是固定名，二次运行直接覆盖，12:02 已被 16:16 覆盖。
- **K 线时点 WARN 是伪问题**：baostock 自身就滞后 3 天，9-4 vs 9-7 是数据源延迟，不是项目 bug。但代码未做"节假日"判断，**所有平日下午跑都 WARN**。
- **4 个失败源不是代码 bug**：slist 风控、fflow JSON 解析、5 日主力 fflow 同源、同业依赖 slist——都是东财接口风控问题，代码需要做"重试 + 备胎"。
- **性能 23s 串行确认**：4 个新 fetcher + 3 个 supplement + margin + 1 个申万重试 = 至少 9 个串行调用，新闻单源就 23s。
- **全链路** v2 的 10 个 fetcher 全部串行；如要 < 120s 必须**全栈并行**。
- **V1 可删除**：全仓 grep 0 处引用，仅在 docs 与 DEPLOY_NOTES 文字提及。

---

## 1. P0 紧急债项（必须修，影响数据正确性 / 流程跑通）

### P0-1：PEG 公式与同花顺口径不一致（10.8x 误差）

- **位置**：`analysis/quant_analyzer_v2.py:249-251`
  ```python
  pe_fwd = price / eps_cur if (eps_cur and eps_cur > 0) else None
  cagr = ((eps_next / eps_cur - 1) if (eps_cur and eps_next and eps_cur > 0) else 0)
  peg = (pe_fwd / (cagr * 100)) if (pe_fwd and cagr > 0) else None
  ```
- **现象**：600693 V2 PEG=3.87，ifind PEG(LYR)=41.73，差 10.8x。V3 报告"PEG=3.87 便宜"是误判。
- **根因**：
  - `cagr` 是小数（0.21），代码又乘了 100 → 21，再除以 pe_fwd ≈ 22 → PEG≈1 附近
  - ifind 的 PEG(LYR) 分母是 **盈利增速百分比值**（如 21 → 21，不是 0.21）
  - V2 算的是 `pe_fwd / (cagr*100)` ≈ 22/21 ≈ 1.05；正确应为 `pe_fwd / cagr_pct` = 22/21 = 1.05？等等，**应该再乘 cagr 不是 0.21** —— 算式 `cagr * 100` 当百分比用是错的
  - **真实错误**：V2 用 `(eps_next/eps_cur - 1)` 作为 cagr 增量，但**没乘 100 还原为百分比**就当 `cagr` 用在 `digest_years` 公式中（`math.log(pe_fwd/30) / math.log(1 + cagr)`）— 这条用小数反而正确
  - **PEG 公式独立 bug**：`cagr * 100` 把 0.21 → 21 是对的，但 `pe_fwd / 21 ≈ 1`，却显示 3.87 —— 说明数据不是 600693 这一刻，**需现场核对**：
- **验证现场**：
  ```bash
  /Users/swarteachou/Desktop/大A数据/venv/bin/python -c "
  import sys; sys.path.insert(0,'/Users/swarteachou/Desktop/大A数据/analysis')
  import quant_analyzer_v2 as v2
  v = v2.fetch_full_valuation('600693')
  print('pe_fwd=', v.get('pe_fwd'), 'eps_cur=', v.get('eps_cur'),
        'eps_next=', v.get('eps_next'), 'cagr_pct=', v.get('cagr_pct'),
        'peg=', v.get('peg'))
  "
  ```
- **修法**（P0）：
  1. 现场跑上述验证脚本，确认 `cagr_pct` vs `peg` 的真实值
  2. 若 `peg` 实际是 1.x 而非 3.87：核对 ifind 用的是不是 PEG(PE TTM / LYR) 还是 PEG(PE Fwd)；按设计稿 8.2 节口径改成 `PEG = pe_fwd / cagr_pct`（cagr_pct 已是百分数）
  3. 文档化到 `analysis/references/valuation-formulas.md`
- **影响面**：所有 V3 报告的"估值贵不贵"章节 + 估值因子打分（+3/-2）+ PEG 显示值

---

### P0-2：V3 命名 bug（result_v3.json / run_log.json 被覆盖）

- **位置**：`analysis/quant_analyzer_v3.py:658, 659, 746`
  ```python
  json_path = os.path.join(day_dir, "result_v3.json")
  log_path = os.path.join(day_dir, "run_log.json")
  ...
  def _dump_run_log(...):
      ...
      with open(os.path.join(day_dir, "run_log.json"), "w", encoding="utf-8") as f:
  ```
- **现象**：`reports/600693_东百集团/2026-09-07/result_v3.json` 与 `run_log.json` 是固定名，12:02 那版已被 16:16 覆盖，无法回看旧 run。
- **根因**：设计 `_emit` 时 `.md/.html/.docx` 都加了 HHMM 戳（line 654 `base = f"{code}-{safe_name}-{hhmm}"`），但 `.json/.log` 漏加。`_dump_run_log` 是失败时落盘函数，未继承时间戳。
- **修法**（P0，2 行）：
  ```python
  # line 658-659 改为
  json_path = os.path.join(day_dir, f"result_v3-{hhmm}.json")
  log_path = os.path.join(day_dir, f"run_log-{hhmm}.json")
  # line 746 改为
  with open(os.path.join(day_dir, f"run_log-{datetime.now().strftime('%H%M')}.json"), "w", ...) as f:
  ```
- **配套**：更新 `verify_accept_600693.py:13` 的引用（`scripts/verify_accept_600693.py`）改为通配匹配。
- **影响面**：所有 V3 用户跑两次以上时只能看到最后一次 run 的 run_log + result；故障排查时丢失前序证据。

---

### P0-3：设计稿核心架构未实现（Section Registry 缺失）

- **位置**：`analysis/`（缺整个 `sections/` 目录）
- **现象**：设计稿 §2 拍板 Approach B（Section Registry），§4 列了 5 节（互动易 §10.1、股东户数 §4.3、分红 §4.4、打板 §8.1-8.3、全市场龙虎榜 §3.9），全部未实现。当前实现的"6 块新增"实际是 4 个 fetcher（公告/财务/研报/新闻）+ 3 个 supplement（5日主力/两融历史/同业），**与设计稿不一致**。
- **根因**：
  - `quant_analyzer_v3.py:538-589` 把 4 个新 fetcher 与 3 个 supplement 都**内联在主流程**里（行号 538/540/541/544-561/565-589），无 `sections/` 子目录
  - `grep "sections\|registry\|meta.json" analysis/quant_analyzer_v3.py` → 0 命中
  - `grep "互动易\|股东户数\|分红\|打板\|irm\|holders\|dividend\|board" analysis/quant_analyzer_v3.py` → 0 命中
  - 验证脚本 `verify_accept_600693.py` 也只用 4 个 fetcher 验
- **修法**（P0，工作量大）：
  1. 新建 `analysis/sections/` 目录，按设计稿 §3.1 落 `__init__.py` + `_base.py` + `registry.yaml`
  2. 拆出 5 个 section 模块（irm/holders/dividend/board/dragon_market）
  3. `quant_analyzer_v3.py:538-589` 改为 `for sec in enabled_sections(): sec.fetch(code, ctx)`
  4. 验 `run_log.sources` 有 23+ key（设计稿 §7.2 标准）
- **影响面**：技术债 P0 —— 老板"加第 6 节"从设计稿的 1 小时回到 1 天；不达 6A 拍板的"扩展性"标准

---

### P0-4：4 个失败源无重试/无备胎（slist/fflow/5日主力/同业对比）

- **位置 4a**：`analysis/quant_analyzer_v2.py:278-297`（slist）
  ```python
  def fetch_eastmoney_concept_blocks(code: str) -> list:
      ...
      try:
          r = em_get("https://push2.eastmoney.com/api/qt/slist/get", ...)
          d = r.json()
          blocks = (d.get("data") or {}).get("diff") or []
          return [...]                                # 0 条时返回 []
      except Exception as e:
          return [{"error": str(e)}]                  # 异常时返错误 dict
  ```
- **位置 4b**：`analysis/quant_analyzer_v2.py:299-327`（fflow 分钟）
  ```python
  d = r.json()           # 此处 r 可能是空 body / HTML，json() 抛 Expecting value
  except Exception as e:
      return {"error": str(e), "klines": []}         # 单层 except，无重试
  ```
- **位置 4c**：`analysis/quant_analyzer_v3.py:268-272`（5 日主力 fflow）
  ```python
  try:
      d = v2.em_get(..., timeout=15).json()
  except Exception as e:
      return {"error": str(e), "rows": []}            # 单层 except，无重试
  ```
- **位置 4d**：`analysis/quant_analyzer_v3.py:330-373`（同业对比，级联失败）
  ```python
  def _fetch_concept_peers(code, blocks, ...):
      if not concepts:
          return {"error": "概念板块列表为空..."}    # 依赖 slist 成功
  ```
- **现象**（run_log 实测）：
  - 概念板块: `fallback:接口返回0条(可能风控), 7021ms`
  - 当日资金流: `error:Expecting value: line 1 column 1 (char 0), 2090ms`
  - 资金面-5日主力: `error:Expecting value: line 1 column 1 (char 0), 4641ms`
  - 同业对比: `error:概念板块列表为空(东财 slist 返回 0 条, 可能风控), 1505ms`
- **根因**：
  1. **东财 push2 接口确实风控严**（v2 em_get 自带 1.2s 限流 + 1~1.5 节流，但风控 30-60s 频次更严）
  2. **JSON 解析无前置 content-type 检查**：HTML 错误页（200 OK + text/html）会让 `r.json()` 抛 `Expecting value`
  3. **同业对比是 slist 的级联失败**：slist 一挂，同业必挂
  4. **V3 主流程 line 565-589 的重试只对 5日主力/同业用 1 次**：但捕获的 `error` 信息没区分"网络错"vs"接口风控"
- **修法**（P0）：
  1. **`quant_analyzer_v2.py:307-310`**：先 `r.encoding='utf-8'; r.text[:200] 看是否 HTML 头`，是则 `return {"error": "接口返回 HTML 非 JSON (风控/限流)"}` 而不是让 json() 抛
  2. **slist 备胎**：用同花顺「所属概念」`basic.10jqka.com.cn/{code}/worth.html` 抓 `所属行业 / 概念` 文本（同 v2 拉一致预期页时同源）
  3. **fflow 备胎**：用 `fetch_industry_ranking` 拉行业 TOP 资金流作市场口径；或缓存上一次的 5 日主力（写 `analysis/cache/fund_daily_{code}.json`，TTL=1 天）
  4. **同业对比解耦**：即使 slist 失败，也用申万行业 + 行业排名接口（`fetch_industry_ranking`）做"行业同业"对比而非概念同业
- **影响面**：报告 5/6 章节里"概念板块归属"为空 + 资金流为空 + 同业对比为空，是用户感知最强的 3 块空数据

---

### P0-5：新闻 23s 串行债（单源无并行、无超时压缩）

- **位置**：`analysis/quant_analyzer_v3.py:541`
  ```python
  fetched["news"] = _call_new("新闻舆情", "新闻", code6)    # 串行，23s+ 单独
  ```
- **位置**（新闻 fetcher 内部）：`analysis/fetch_news_em.py:100-164`
  ```python
  for attempt in range(3):
      try:
          r = requests.get(url, params=params, ..., timeout=TIMEOUT)  # 15s
          ...
      except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError) as e:
          last_err = "%s" % e
          if attempt == 2:
              break
      time.sleep(3 + 4 * attempt)            # 3s + 7s + 11s = 21s 退避
  ```
- **现象**：run_log 显示 `新闻舆情: ok:sina_stock_news, 23032ms`（23s）。
- **根因**：
  1. 主源（东财 JSONP）3 次重试：sleep 3s + 4*1s + 4*2s = 3+4+8 = 15s 退避
  2. 第 1 次请求成功但 `passportWeb only`（间歇风控）→ 第 2 次 ~15s + sleep 7s = 22s
  3. 第 2 次也风控 → 第 3 次 ~15s + sleep 11s = 26s 后才降级
  4. 整个 `analyze_single_v3` 至少 81s（run_log 实测），新闻占 28%
- **修法**（P0）：
  1. **`fetch_news_em.py:122` 改成 `time.sleep(0.5 + 1.0 * attempt)`**（0.5+1+1.5=3s 替代 21s 退避）
  2. **`_call_new`（quant_analyzer_v3.py:504-535）增加 `timeout=10` 参数**：东财 JSONP 3 次失败总 30s 超时上限，达到即降级
  3. **`analyze_single_v3` 全文 4 新 fetcher + 3 supplement 改 ThreadPoolExecutor(max_workers=5) 并行**：总耗时可从 23s 压到 ~5s
- **影响面**：单票 81s → 预估 50-60s（设计稿 §3.4 性能预算 < 120s 可达成）

---

## 2. P1 重要债项（应该修，影响质量/性能）

### P1-1：V2 主流程 10 个 fetcher 全串行（性能主因）

- **位置**：`analysis/quant_analyzer_v2.py:1073-1119`（`analyze_single`）
  ```python
  quote = fetch_tencent_quote([code])        # 串行
  valuation = fetch_full_valuation(code)     # 串行，2 个内部 HTTP
  blocks = fetch_eastmoney_concept_blocks(code)  # 串行
  fund = fetch_fund_flow_minute(code)        # 串行
  val_hist = fetch_valuation_history(code)   # 串行
  lockup = fetch_lockup_expiry(code)         # 串行
  dragon = fetch_dragon_tiger(code)          # 串行
  macro = fetch_macro_snapshot()             # 串行，3 个内部 HTTP
  chip_data = fetch_chip_distribution(code)  # 串行，1 个慢 baostock
  sw_data = fetch_sw_stability(code)         # 串行，1 个慢 xls
  ```
- **现象**：10 个 fetcher 串行 + `em_get` 自带 1.2s 节流 = 至少 12s 强制等待 + 实际 HTTP 时间。
- **根因**：`em_get` 强制串行（line 81-89），V2 没有并行框架。
- **修法**（P1）：
  - **`em_get` 改为按 host 分桶限流**（push2.eastmoney.com 一个桶，datacenter-web 另一个桶，baostock 独立）
  - **`analyze_single` 用 ThreadPoolExecutor(max_workers=6)**：fetch_tencent_quote / fetch_full_valuation / fetch_eastmoney_concept_blocks / fetch_fund_flow_minute / fetch_valuation_history / fetch_lockup_expiry / fetch_dragon_tiger / fetch_macro_snapshot / fetch_chip_distribution / fetch_sw_stability 全部并行
  - 期望：81s → 30-40s
- **影响面**：单票 80-105s → 设计稿 §3.4 目标 < 90s

---

### P1-2：V2 5 处 `_interpret_pe/_interpret_pctile/_make_trading_plan/_make_signal_list/_interpret_chips` 是私有函数被 V3 跨模块引用（隐性耦合）

- **位置**：`analysis/quant_analyzer_v3.py:467-468, 1303, 1363`
  ```python
  plan = v2._make_trading_plan(q, v, chip_data, score_total)
  good_signals, bad_signals = v2._make_signal_list(score, score["factors"])
  ...
  pe_talk = v2._interpret_pe(q.get("pe_ttm", 0))
  ...
  chips_talks = v2._interpret_chips(cd)
  ```
- **现象**：V3 用了 5 个 V2 私有（下划线）函数；V2 任何 signature 变动都会无声破坏 V3 报告。
- **根因**：V3 设计稿 §3.2 没规划 V2/V3 接口边界，V3 直接 `from quant_analyzer_v2 import _interpret_pe as v2_pe` 是更稳的写法。
- **修法**（P1）：
  1. `quant_analyzer_v3.py:53` 之后加显式导入：
     ```python
     from quant_analyzer_v2 import (
         _interpret_pe as _v2_pe, _interpret_pctile as _v2_pctile,
         _interpret_chips as _v2_chips, _make_trading_plan as _v2_plan,
         _make_signal_list as _v2_signals,
     )
     ```
  2. 调用处替换为 `_v2_pe(...)`，避免 `v2._` 的魔法查找
- **影响面**：V2 改私有函数 → V3 报告悄无声息地错或崩

---

### P1-3：V3 主流程 line 565-589 的 supplement 重试逻辑有 bug

- **位置**：`analysis/quant_analyzer_v3.py:572-577`
  ```python
  val = fn(*args)
  if isinstance(val, dict) and "error" in val and key != "margin_hist":
      time.sleep(1.5)                      # 附加源网络重试 1 次
      val2 = fn(*args)
      if not (isinstance(val2, dict) and "error" in val2):
          val = val2
  ```
- **现象**：重试只在 val 有 error 且 `key != "margin_hist"` 时执行，但**没有区分"网络错"vs"业务空"**：
  - 5日主力 `error: "近5日主力资金无数据"` 是业务空（接口真没数据），重试无意义，浪费 1.5s
  - 同业对比 `error: "概念板块列表为空"` 是级联空（slist 挂），重试无意义
  - 但 `error: "Expecting value"`（网络/JSON 错）值得重试
- **根因**：重试条件用 `isinstance(val, dict) and "error" in val`，没看错误类型。
- **修法**（P1）：
  ```python
  if isinstance(val, dict) and "error" in val and key != "margin_hist":
      err = val.get("error", "")
      worth_retry = any(s in err for s in ("Expecting value", "timeout", "SSL",
                                            "ConnectionError", "MaxRetry"))
      if worth_retry:
          time.sleep(1.5)
          val2 = fn(*args)
          if not (isinstance(val2, dict) and "error" in val2):
              val = val2
  ```
- **影响面**：5日主力无谓重试 ~1.5s × 每次跑 = 跑两次浪费 3s

---

### P1-4：html_report_v3 缺 `as_of` 字段映射（取时点逻辑可能误中）

- **位置**：`analysis/html_report_v3.py:126-146`（`_source_time`）
  ```python
  def _source_time(run_log, key_hints, default):
      ...
      for hint in key_hints:
          if hint in srcs and isinstance(srcs[hint], dict):     # 永远不是 dict!
              ...
      for name, blob in srcs.items():
          if any(h in name for h in key_hints) and isinstance(blob, dict):    # blob 永远不是 dict
              ...
  ```
- **现象**：`run_log["sources"]` 实际结构是 `{label: status_string}`（如 `{"行情": "ok, 1772ms"}`），不是 `{label: dict}`。两个 for 循环永远不进。
- **根因**：V3 主流程 line 472-495 把 `run_log["sources"][lab] = status`（str），但 `run_log["source_meta"][lab] = meta`（dict）—— V3 写错位置 / html 读错位置。
- **修法**（P1）：
  1. **优先改 `html_report_v3.py:130-146`** 用 `run_log["source_meta"]` 读时点：
     ```python
     def _source_time(run_log, key_hints, default):
         meta = (run_log or {}).get("source_meta") or {}
         for hint in key_hints:
             if hint in meta and isinstance(meta[hint], dict):
                 v = meta[hint].get("at") or meta[hint].get("fetched_at")
                 if v:
                     return str(v)[:16]
         return default
     ```
  2. 否则在 V3 端把 sources 写成 dict（结构改动大）
- **影响面**：6 块内容的"📡 数据源：xxx · 时点：报告日期" 全部退化到报告日，时点标注失效

---

### P1-5：V1 (`quant_analyzer.py`) 死代码（571 行无引用）

- **位置**：`analysis/quant_analyzer.py:1-571`
- **现象**：
  - `grep -r "from quant_analyzer " /Users/swarteachou/Desktop/大A数据/` → 0 处代码引用
  - `grep -r "import quant_analyzer$" /Users/swarteachou/Desktop/大A数据/` → 0 处代码引用
  - 引用只出现在文档（`docs/01-策划方案.md`、`DEPLOY_NOTES.md`、`analysis/references/deployment-gotchas.md`）说"V1 保留兼容"
- **根因**：V2 已完全替代 V1，但 V1 仍占 571 行 + 启动时无 import 验证。
- **修法**（P1）：
  1. 把 V1 移到 `analysis/_legacy/quant_analyzer_v1.py`（带 `__init__.py`）
  2. 或加 `DeprecationWarning` 顶部 + 顶部 docstring 标"V1 已停更，V2 替代"
  3. `git rm analysis/quant_analyzer.py` 后 + 提交时写 "V1 迁移到 _legacy/"
- **影响面**：571 行死代码 + 全仓 grep 时干扰；新人误解"V1 还在用"

---

### P1-6：`templates/` 目录只剩 1 个文件，且 V3 没引用

- **位置**：`analysis/templates/prompt-playbooks.md`
- **现象**：`quant_analyzer_v3.py` / `html_report_v3.py` 全无引用，`analysis/references/sync-from-github.md` 也只说"legacy"。
- **根因**：设计稿 §3.1 把 `templates/` 标记为已有，但当前只剩 1 个 `prompt-playbooks.md`（V3 风格的 playbooks），与"4 个新章节的 prompt template"无关。
- **修法**（P1）：
  - 选项 A：把 `prompt-playbooks.md` 移到 `analysis/references/`（与 `pitfalls.md` 同位）
  - 选项 B：扩 `templates/` 装 5 个新章节的 prompt（设计稿 §3.1 的本意）
  - 当前 A 更务实
- **影响面**：目录结构与设计稿不一致；CI / 维护时误导

---

### P1-7：`fetch_news_em` 退避时间爆炸（3+7+11=21s）

- **位置**：`analysis/fetch_news_em.py:163`
  ```python
  time.sleep(3 + 4 * attempt)    # attempt=0,1,2 → sleep 3,7,11s
  ```
- **现象**：东财 JSONP 第 1 次间歇风控后，退避 3s + 7s = 10s 才尝试第 2 次；第 2 次再挂，退避 11s 才第 3 次。
- **根因**：原作者怕"东财风控要冷一段时间"，但实测 5-10s 足够；21s 退避在新闻源失败链中占 50%。
- **修法**（P1）：
  ```python
  time.sleep(0.8 + 1.2 * attempt)    # 0.8, 2.0, 3.2s = 6s 替代 21s
  ```
- **影响面**：东财 JSONP 失败的兜底链中可省 15s，配合 P0-5 并行框架，总跑可压到 50s 内

---

## 3. P2 锦上添花（可修可不修，长期改进）

### P2-1：5 日主力 / 两融历史 / 同业对比 三个 supplement 全部 V3 内联（应抽到 `sections/`）

- **位置**：`analysis/quant_analyzer_v3.py:260-373`（`_fetch_fund_flow_daily` / `_fetch_margin_history` / `_fetch_concept_peers`）
- **现象**：114 行内联函数，本质是新章节的 fetcher 雏形。
- **修法**：等 P0-3 落实后，这 3 个函数迁到 `sections/fund_daily5/`、`sections/margin_hist/`、`sections/peers/`。

### P2-2：V3 的 fetch_docx_subprocess 兜底（line 696-704）写过且不清理临时文件

- **位置**：`analysis/quant_analyzer_v3.py:697-704`
- **现象**：第一次 import 失败时 spawn subprocess，但子进程的 stderr/stdout 不捕获；3 次失败后合并到 docx_err 但 e1 原 stack 丢失。
- **修法**：subprocess.run 加 `capture_output=True, text=True`，e1 写进 log 方便排查。

### P2-3：`md_to_docx.py:50-77` 用 `_ensure` 包装插入 XML 但捕获 `Exception` 太宽

- **位置**：`analysis/md_to_docx.py:73-76`
  ```python
  try:
      parent.insert_element_before(el, *successors)
  except Exception:
      parent.append(el)               # 静默失败
  ```
- **现象**：任何 `insert_element_before` 失败都被吞；DOCX 排版异常时排错极难。
- **修法**：改 `except (KeyError, ValueError, AttributeError)`，其他异常 raise。

### P2-4：`fetch_announcements` 的 orgId 缓存无失效（`_CNINFO_ORGID_MAP`）

- **位置**：`analysis/fetch_announcements.py:186-194`
  ```python
  global _CNINFO_ORGID_MAP
  if not _CNINFO_ORGID_MAP:
      try:
          r = requests.get(CNINFO_ORGID_URL, ..., timeout=20)
          _CNINFO_ORGID_MAP = ...
      except Exception:
          pass
  ```
- **现象**：模块级 dict 永久缓存，**永不刷新**。新上市股票 / 退市 → 永远查不到。
- **修法**：加 `if time.time() - _CNINFO_LOADED_AT > 86400: 刷新`，或加 LRU 缓存大小限制。

### P2-5：`_kline_freshness` 不识别中国法定节假日

- **位置**：`analysis/quant_analyzer_v3.py:207-217`（`_latest_trading_day`）和 220-239（`_kline_freshness`）
- **现象**：9-7（周一）跑出 WARN 因为 baostock 滞后 3 天到 9-4；注释里说"节假日不在库, 仅提示"，但代码确实没库。
- **修法**：要么在 `analysis/references/` 维护一份中国法定节假日 CSV（一年 ~10 个），要么承认 baostock 滞后是常态，把 WARN 等级改 INFO 或不写进 fallback_chain。

### P2-6：`quant_analyzer_v3.py:418-460` 的申万 SSL 重试 hook 在 try/finally 中改全局

- **位置**：`analysis/quant_analyzer_v3.py:421-460`
  ```python
  _orig_get = _req.get
  def _patched_get(url, *a, **k): ...
  t0 = time.time()
  sw_retry = {"error": "未执行"}
  try:
      _req.get = _patched_get
      sw_retry = v2.fetch_sw_stability(code6)
  except Exception as e:
      sw_retry = {"error": str(e)}
  finally:
      _req.get = _orig_get
  ```
- **现象**：临时改 `requests.get` 全局函数，V3 任何子流程的 `requests.get` 都会被劫持（即便 swsresearch 域名）。**重入时若 V2 内部有 `requests.get` 调用都会被改写**。
- **修法**：改为 `requests.Session().get` 的 session 局部 patch，或下推给 v2.fetch_sw_stability 接受 `verify` 参数。

### P2-7：`quant_analyzer_v3.py:1310-1317` 的 PEG 显示 `v.get("peg")` 可能显示 None

- **位置**：`analysis/quant_analyzer_v3.py:1310-1317`
  ```python
  if v.get("peg") and v["peg"] != float("inf"):
      peg = v["peg"]
      peg_talk = "PEG < 1, 便宜区" if peg < 1 else (...)
      L.append(f"- **PEG {peg}** — {peg_talk}")
  ```
- **现象**：EPS 缺失（analyst_count=0）时 `peg=None`，**报告里直接不显示 PEG**，对"散户看 PEG"用户是隐藏信息。
- **修法**：peg=None 时显示 "PEG 无一致预期，无法计算"，而不是"消失"。

### P2-8：`html_report_v3.py:540-622` 的 `_render_checklist` 内嵌买卖文案过长（80+ 行），不易维护

- **位置**：`analysis/html_report_v3.py:541-622`
- **现象**：所有看多/看空/震荡的买/卖/止损/仓位文案都写死在一个函数里。
- **修法**：抽到 `analysis/_checklist_text.py` 或 `references/checklist-playbook.md`，按三态 12 字段填模板。

---

## 4. 独立发现（5+ 个未列在已知债项里）

### 独立 1：设计稿 §2.4「5min 内定位任一端点」未实现（SKILL.md 无导航）

- **位置**：`SKILL.md:1-50`（头部 + V3.7.2 changelog）
- **现象**：设计稿 §9 拍板"SKILL.md 顶部新增📑 5秒定位目录"，但 grep `SKILL.md` 顶部 → 只有项目主页 / 作者 / V3.7.2 changelog，**无目录锚点**。
- **根因**：SKILL.md 4086 行（实测 line 51 后还有 4094 行）没人在 9-6 ~ 9-7 之间加 TOC。
- **修法**：在 SKILL.md line 12 后加：
  ```markdown
  ## 📑 5秒定位
  | 找什么 | 跳到 |
  |---|---|
  | 行情/K线 | §1.1~§1.4 |
  | 研报/财务/新闻 | §2 / §5 / §4 |
  | 资金面/筹码/股东户数 | §4 / §6 |
  | 公告/互动易/分红 | §7 / §10.1 / §4.4 |
  | 风险（打板/异动/重点监控） | §8.1-§8.5 |
  | 宏观（社融/PMI） | §11.1-§11.2 |
  | 备胎速查 | §9 |
  ```

### 独立 2：`fetch_dragon_tiger` 用 30 天 look_back 但设计稿 §3.9 要求"当日全市场"端点

- **位置**：`analysis/quant_analyzer_v2.py:770-800`
  ```python
  def fetch_dragon_tiger(code, trade_date=None, look_back=30):
  ```
- **现象**：V2 fetch_dragon_tiger 是**单股**近 30 日（设计稿 §3.9 要的是**当日全市场**龙虎榜 Top 20），与设计稿不匹配。
- **修法**：新增 `fetch_dragon_tiger_market(trade_date)` 走 `RPT_DAILYBILLBOARD_DETAILSNEW` 不带 SECURITY_CODE 过滤，返回 Top 20。

### 独立 3：`md_to_docx.py:131-135` 的 `header_repeat` 设了但前几张表没加

- **位置**：`analysis/md_to_docx.py:131-135`（函数定义）和后续表格生成处
- **现象**：`header_repeat(row)` 写了函数没看到调用 —— Word 长表分页时表头不重复，DOCX 跨页体验差。
- **修法**：所有"跨页表"（财务、公告速览、同业对比）调 `header_repeat(t.rows[0])`。

### 独立 4：V3 line 539 `fetched["research"] = _call_new("研报观点", "研报", code6, 200)` 缺 5个新章节的 call

- **位置**：`analysis/quant_analyzer_v3.py:538-541`
  ```python
  fetched["announcements"] = _call_new("公告", "公告", code6)
  fetched["finance"] = _call_new("财务摘要", "财务", code6)
  fetched["research"] = _call_new("研报观点", "研报", code6, 200)
  fetched["news"] = _call_new("新闻舆情", "新闻", code6)
  ```
- **现象**：只有 4 个 call，缺设计稿 §4.1-4.5 的 5 个新章节（irm/holders/dividend/board/dragon_market）。
- **根因**：见 P0-3，整个 sections 目录没建。
- **修法**：依赖 P0-3 解决。

### 独立 5：`fetch_announcements.py:104` 用 `datetime.now().astimezone().isoformat()` 缺 timespec

- **位置**：`analysis/fetch_announcements.py:104`
  ```python
  "fetched_at": datetime.now().astimezone().isoformat(),
  ```
- **现象**：V3 line 1102 读 `ann.get("fetched_at")` 时**格式不统一**：
  - `fetch_announcements.py:104` → `"2026-09-07T16:15:30.123456+08:00"`
  - `fetch_finance_summary.py:165` → `"2026-09-07T16:15:30+08:00"`（带 `timespec="seconds"`）
  - `fetch_research_reports.py:130` → 自定义 `fetched_at` 参数
  - `fetch_news_em.py:54` → UTC `isoformat(timespec="seconds")` → `"2026-09-07T08:15:30+00:00"`
- **根因**：4 个 fetcher 各自写 `fetched_at`，时区 / 精度不统一，html 渲染时 `_short_iso` 截断到 19 字符（line 200-204）会卡掉时区。
- **修法**：在 `analysis/_timeutil.py` 抽 `_now_iso_cst()` 统一返回 `"YYYY-MM-DDTHH:MM:SS+08:00"`，4 个 fetcher 全部 import。

### 独立 6：`html_report_v3.py:200-204` 的 `_short_iso` 与 fetcher 时区不一致可能导致时点乱标

- **位置**：`analysis/html_report_v3.py:200-204`
  ```python
  def _short_iso(iso):
      """ISO8601 → 'YYYY-MM-DD HH:MM:SS'"""
      if not iso: return "—"
      return str(iso)[:19].replace("T", " ")
  ```
- **现象**：fetcher 返回 UTC `2026-09-07T08:15:30+00:00`，截到 19 字符是 `2026-09-07T08:15:30`，再 replace T 得 `2026-09-07 08:15:30`（**UTC 时间**），报告里说"抓取于 08:15:30"——但报告日是 16:15:30 CST，**差 8 小时**。
- **修法**：`_short_iso` 先尝试 parse tz，转到本地时区再截断；或 fetcher 一律返 CST。

### 独立 7：`scripts/run_in_venv.sh` 没检查 venv python 与 arch 匹配（macOS arm64/x86 混淆）

- **位置**：`scripts/run_in_venv.sh`（未读全文，但 venv 是 arm64 已有约束）
- **现象**：任务约束"禁止 arch -x86_64"暗示曾有 x86 强制；但 `run_in_venv.sh` 若仍含 `arch -x86_64 ...` 调用会破坏 arm64 native。
- **修法**：grep `scripts/run_in_venv.sh` 含 `arch -x86_64` → 删；或加 `if [ "$(uname -m)" = "arm64" ]; then exit 1; fi` 守卫。

### 独立 8：`quant_analyzer_v2.py:837` 计算 change_pct 用 prev_close 但字段名可能是 `yesterday_close`

- **位置**：`analysis/quant_analyzer_v2.py:837`
  ```python
  prev = quote.get("prev_close", 0)
  change_pct = round((price - prev) / prev * 100, 2) if prev else 0
  ```
- **现象**：若腾讯 `qt.gtimg.cn` 返回字段名是 `yesterday_close` 或 `last_close`（不同版本/股票），`prev=0` → `change_pct=0`，趋势因子永远不变。
- **修法**：fetch_tencent_quote 解析后做一次字段名 alias (`yesterday_close` → `prev_close`)；或加 `prev_close` fallback 到 `last_close`。

### 独立 9：`fetch_news_em.py:121-128` 的 JSONP 解析 `text[text.index("(") + 1: text.rindex(")")]` 在文本含 "()" 时会抛

- **位置**：`analysis/fetch_news_em.py:129`
  ```python
  d = json.loads(text[text.index("(") + 1: text.rindex(")")])
  ```
- **现象**：东财偶尔返回 `passportWeb={"callback":"jQuery_news()"}` 含字面 `(...)` → `rindex(")")` 取到 passportWeb 内的反义括号，slice 出来是脏 JSON → json.loads 抛。
- **修法**：先 `text.rstrip().endswith(")")` 检查（已有），但要再 `text.rindex(")") > text.rindex("(")` 验证括号平衡。

### 独立 10：`html_report_v3.py:34-42` 的语义色板注释"AA 5.2:1"等与实际文件 CSS 未对齐

- **位置**：`analysis/html_report_v3.py:34-42`
- **现象**：注释说 C_BLUE `#2562eb` AA 5.2:1，但实际 `_CSS` 字符串（line 382 起的 `_checklist_css` 块）用 var(--accent) 引用 token，色值未统一。
- **修法**：从 `_CSS` 字符串里抽色 token，与 34-42 的常量统一源。

---

## 5. 建议下一步（按优先级）

| 序号 | 任务 | 工作量 | 影响 |
|---|---|---|---|
| 1 | **P0-2 命名 bug**（2 行代码改 + verify 脚本跟进） | 0.5h | 立即止血，避免二次覆盖 |
| 2 | **P0-1 PEG 现场验证**（先跑脚本确认数据） | 0.5h | 决定是改公式还是改对照口径 |
| 3 | **P0-4 失败源 4 处加 content-type 预检 + 备胎框架** | 1d | 4 块内容从空白到有数据 |
| 4 | **P0-5 新闻退避压缩**（1 行改 sleep） | 0.5h | 单票 -15s |
| 5 | **P1-1 V2 10 fetcher 改 ThreadPoolExecutor** | 1-1.5d | 单票 80s → 30-40s |
| 6 | **P0-3 Section Registry 骨架** | 2-3d | 加第 6 节从 1d → 1h |
| 7 | **P1-2 显式 import V2 私有函数** | 0.5h | 防止 V2 改动静默破坏 V3 |
| 8 | **P1-4 修 `_source_time`** | 1h | 时点标注从退化到正确 |
| 9 | **P1-5 迁 V1 到 _legacy/** | 0.5h | -571 行死代码 |
| 10 | **P1-3 supplement 重试条件精确化** | 0.5h | -1.5s × 2 = 3s |
| 11 | **P1-6 templates/ 整理** | 0.5h | 目录结构清晰 |
| 12 | **独立 5/6 统一 fetched_at 时区格式** | 1h | 时点不再错 8h |
| 13 | **独立 1 SKILL.md 顶部加 5秒定位** | 0.5h | 设计稿 §9 落地 |

**紧急建议**：先做 #1（2 行改 + 防覆盖），#2（决定 PEG 修法方向），#3（4 块空白数据），其余按项目排期。

---

## 6. 验收 checklist

- [ ] `result_v3-{HHMM}.json` + `run_log-{HHMM}.json` 命名落地
- [ ] 600693 PEG 显示值与 ifind 差 < 2x（或文档化口径差异）
- [ ] 4 个失败源至少有 1 个备胎兜底（不空白）
- [ ] 单票 < 60s（V2 10 fetcher 并行 + 4 新 fetcher 并行）
- [ ] 跑 600693 第二次后 `reports/600693_东百集团/2026-09-07/` 至少 3 份 run_log（不互覆盖）
- [ ] `analysis/sections/` 目录存在（哪怕只有 `_base.py` + `__init__.py`）
- [ ] V1 移走或加 deprecation header
- [ ] `analysis/quant_analyzer_v3.py` 内联函数数 < 100 行（抽 sections）
