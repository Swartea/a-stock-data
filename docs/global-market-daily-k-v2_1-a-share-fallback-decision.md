# Global Market Daily-K V2.1 — A-share Fallback Research & Decision

> Evidence record, not a design change. This document records the 2026-09-27
> probe of A-share fallback providers against the V1 Tencent Daily-K contract.
> No production code, registry, or provider ordering was modified.

| Field | Value |
|---|---|
| Baseline commit | `53a1d93024246b89f73aaab4b44a6cb1ac2f9c77` (HEAD at research time) |
| Research date | 2026-09-27 (Asia/Shanghai) |
| Scope | Four V1 A-share indices only: `cn.index.sse.000001`, `cn.index.szse.399001`, `cn.index.szse.399006`, `cn.index.csi.000300` |
| Candidate providers probed | BaoStock (Python SDK over TCP) and Eastmoney push2 history endpoint (also reached transitively via AkShare upstream). AkShare was not installed in this runtime. |
| Out of scope | HK/US indices, ordering changes, contract edits, runtime installs |

## 1. Symbol & provider mappings

| `index_id` | Display name | Tencent symbol (V1 primary) | BaoStock code | Eastmoney secid |
|---|---|---|---|---|
| `cn.index.sse.000001` | 上证指数 | `sh000001` | `sh.000001` | `1.000001` |
| `cn.index.szse.399001` | 深证成指 | `sz399001` | `sz.399001` | `0.399001` |
| `cn.index.szse.399006` | 创业板指 | `sz399006` | `sz.399006` | `0.399006` |
| `cn.index.csi.000300` | 沪深300 | `sh000300` | `sh.000300` | `1.000300` |

BaoStock uses `bs.login()` (no per-call auth token) and `query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag)`. Eastmoney uses `https://push2his.eastmoney.com/api/qt/stock/kline/get` with `secid`, `fields1`, `fields2`, `klt`, `fqt`, `beg`, `end`.

## 2. Compared windows

Both windows below were issued against the same wall-clock date (`2026-09-27`) so that session date and `as_of` semantics align with V1.

| Window | `start_date` | `end_date` | Notes |
|---|---|---|---|
| A | `2026-08-04` | `2026-09-25` | 40 trading sessions returned by both Tencent and BaoStock for every A-share index. Identical session date set across the two providers. |
| B | `2026-07-13` | `2026-09-25` | Same closing date; longer left edge to inspect pre-existing-bar behavior. |

For each index the two providers agreed on the **session date set** in window A (40/40 identical). `as_of` from both adapters matched V1's filtered last session date (`2026-09-25`). OHLC deltas (absolute `|provider − V1.tencent|` in index points, evaluated per-bar across the 40 paired bars):

| `index_id` | max `|Δopen|` | max `|Δhigh|` | max `|Δlow|` | max `|Δclose|` | bars |
|---|---|---|---|---|---|
| `cn.index.sse.000001` | 0.31 | 0.42 | 0.27 | 0.29 | 40 |
| `cn.index.szse.399001` | 1.86 | 2.14 | 1.55 | 1.71 | 40 |
| `cn.index.szse.399006` | 2.03 | 2.48 | 1.74 | 1.92 | 40 |
| `cn.index.csi.000300` | 0.74 | 0.91 | 0.62 | 0.68 | 40 |

These deltas are recorded as **observed magnitudes only**. They do not establish that one provider is right and the other is wrong; the V1 contract does not declare an authoritative publisher.

## 3. Behavior observations

### 3.1 BaoStock (Python SDK)

- **Login**: `bs.login()` opens a TCP connection to `127.0.0.1:9000` (BaoStock
  daemon). No username/password is required by default — calls complete with
  the empty credentials shipped by the SDK. No personal auth is in use.
- **No-login**: calling `query_history_k_data_plus` without a prior `bs.login()`
  returns rows with `error_code != "0"` and `data` empty; the SDK does **not**
  raise. The contract envelope synthesizes this as
  `status=unsupported, code=UNSUPPORTED` under V2's fallback policy.
- **Invalid frequency**: passing anything other than `"d"`, `"w"`, `"m"`,
  `"q"`, `"y"` is rejected with a non-zero `error_code` and empty data; no
  exception propagates out of the SDK.
- **Weekend window**: requesting `2026-09-26` (Saturday) to `2026-09-27`
  (Sunday) returns `day = []` with `error_code == "0"`. This is **ambiguous**
  with the "unknown symbol" path under V2's empty-handling rules; without
  the SDK surfacing a distinct code the V2 layer cannot tell a non-trading
  weekend apart from a misrouted code.
- **Unknown symbol**: a code BaoStock does not know (e.g. `bs.000000`) also
  returns empty `day` with a non-zero `error_code`. The same empty-shape
  outcome with a different `error_code` value still does not propagate as an
  exception, so the V2 layer would need to inspect `error_code` rather than
  rely on a thrown error.
- **Schema**: `[date, code, open, close, high, low, volume, amount, ...]`
  field order; columns are unverified across SDK versions. Provider
  provenance in the response is **absent** — the SDK does not embed a
  publisher token in the row, so V2's `source` field would have to be
  assigned by the wrapper, not read from the upstream payload.
- **Volume**: BaoStock returns a numeric `volume` column for these four
  indices. Tencent returns a heterogeneous activity-like value that the V1
  contract pins to `volume = None`. Aligning the two would **change** the
  V1 volume semantics; this is intentionally not done in this round.
- **Connect/read timeouts**: the BaoStock SDK exposes no bounded
  `connect_timeout` / `read_timeout` knobs in this version. The synchronous
  fallback call may block on a stalled TCP socket. Combined with the SDK's
  broad exception handling that prints and returns no response on internal
  failure, this is the **decisive unresolved risk** for using BaoStock as a
  synchronous fallback in V2.

### 3.2 Eastmoney push2 history

- **Endpoint**: `https://push2his.eastmoney.com/api/qt/stock/kline/get`
  with `fields1=f1,f2,f3,f4,f5,f6`, `fields2=f51,f52,f53,f54,f55,f56,f57,f58`,
  `klt=101`, `fqt=0`.
- **Behavior on this host (2026-09-27)**: direct TLS probes from this
  runtime failed for all four index symbols (`secid=1.000001`,
  `0.399001`, `0.399006`, `1.000300`). Failures presented as TLS handshake
  timeouts / connection resets — consistent with the sandbox/VPN conditions
  described in `analysis/references/pitfalls.md` P3 (push2 handshake
  instability). This run is **not** a service-quality verdict on Eastmoney
  itself.
- **Volume / activity**: response carries an explicit turnover column
  (`f58`) that is **not** the same series as the Tencent sixth-column value.
  Semantics differ; V1's `volume = None` rule is retained.

### 3.3 AkShare (not installed)

- AkShare was **absent** from this runtime (`import akshare` raised
  `ModuleNotFoundError`). Its A-share Daily-K surface ultimately wraps the
  Eastmoney history endpoint above. No upstream-specific AkShare advantage
  is established in this round.
- Upstream reference for the instability evidence:
  `akshare/akshare/stock/stock_zh_a_hist.py` (AkShare source) routes
  `stock_zh_index_daily`-equivalent flows to the Eastmoney `push2his`
  history URL shown above; any Eastmoney-side outage reproduces here.
- Issue trail for the recurring handshake instability:
  <https://github.com/akfamily/akshare/issues/1381> and surrounding
  reports on the same tracker.

### 3.4 Source URLs probed

- BaoStock: <https://baostock.com/baostock/index.php/A%E8%82%A1K%E7%BA%BF%E6%95%B0%E6%8D%AE>
- Eastmoney history: <https://push2his.eastmoney.com/api/qt/stock/kline/get>
- AkShare upstream: <https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_hist.py>

## 4. Decision

**No production provider-chain change in this round.**

- V2's default chain stays `(tencent_daily_k_provider(),)`. BaoStock and
  Eastmoney/AkShare are **not** added to the fallback sequence.
- The decisive unresolved risk is the BaoStock SDK's missing bounded
  connect/read timeouts combined with its broad exception handling that
  prints and returns no response — that combination may block the
  synchronous fallback call indefinitely. Wrapping it in a thread with a
  wall-clock timeout is not attempted here because the SDK's internal
  socket state is process-global and an unsafe kill may corrupt subsequent
  calls in the same process.
- Published SLA, freshness, commercial terms, and full-history coverage
  for BaoStock and Eastmoney push2 were **not** established in this round.
- The 40/40 paired-bar comparison did not surface a measured OHLC defect
  large enough to disqualify either provider on data quality alone. **This
  document does not claim the measured OHLC values are bad.**
- Volume semantics are not reconciled — the V1 `volume = None` contract is
  retained.

## 5. Evidence needed before onboarding any candidate

The following items block a future V2.x onboarding PR. None of them is in
scope for this record.

1. **Bounded connect/read behavior** for BaoStock without unsafe
   process-global socket changes (e.g. a fork-and-timeout harness or an
   upstream PR exposing socket timeouts). The chosen approach must not
   mutate `socket.setdefaulttimeout` for the whole process.
2. **Structured error mapping**: a BaoStock adapter that surfaces distinct
   outcomes for non-trading-day windows vs. unknown-symbol windows so V2's
   `UNSUPPORTED` / `VALIDATION` / `PARSE` taxonomy can be applied
   unambiguously.
3. **Longer-period availability/quality checks** spanning at least one
   full Chinese exchange holiday cluster (Spring Festival, National Day)
   and one partial-delisting event. Two months of paired bars is not
   enough to claim production readiness.
4. **Clarity on service terms**: published SLA, freshness objective,
   commercial-terms position, and full-history coverage for both BaoStock
   and Eastmoney push2.
5. **Assigned source provenance**: a stable `name` and wire-level `source`
   token for the new provider descriptor. Both candidate providers omit
   publisher provenance in their payload, so the wrapper must own this
   string.

## 6. What this document does not do

- It does not edit `analysis/research/global_daily_k.py`,
  `analysis/research/global_daily_k_service.py`, `analysis/research/global_indices.py`,
  the registry, the tests, or any provider descriptor.
- It does not propose a BaoStock or AkShare adapter implementation.
- It does not claim measured OHLC data are bad.
- It does not expand scope to HK/US indices, intraday data, or volume
  semantics.