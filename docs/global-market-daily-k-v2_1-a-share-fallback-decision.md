# Global Market Daily-K V2.1 — A-share Fallback Research & Decision

> Evidence record, not a design change. This document records the 2026-09-27
> probe of A-share fallback providers against the V1 Tencent Daily-K contract.
> No production code, registry, or provider ordering was modified.

| Field | Value |
|---|---|
| Baseline commit | `53a1d93024246b89f73aaab4b44a6cb1ac2f9c77` (HEAD at research time) |
| Research date | 2026-09-27 (Asia/Shanghai) |
| Scope | Four V1 A-share indices only: `cn.index.sse.000001`, `cn.index.szse.399001`, `cn.index.szse.399006`, `cn.index.csi.000300` |
| Candidate providers probed | BaoStock (Python SDK over TCP) and Eastmoney push2 history endpoint (also reached transitively via AkShare upstream). AkShare was absent from this runtime. |
| Out of scope | HK/US indices, ordering changes, contract edits, runtime installs |

## 1. Symbol & provider mappings

| `index_id` | Display name | Tencent symbol (V1 primary) | BaoStock code | Eastmoney secid |
|---|---|---|---|---|
| `cn.index.sse.000001` | 上证指数 | `sh000001` | `sh.000001` | `1.000001` |
| `cn.index.szse.399001` | 深证成指 | `sz399001` | `sz.399001` | `0.399001` |
| `cn.index.szse.399006` | 创业板指 | `sz399006` | `sz.399006` | `0.399006` |
| `cn.index.csi.000300` | 沪深300 | `sh000300` | `sh.000300` | `1.000300` |

The mappings above are the exact strings observed end-to-end: `sh.000001` ↔
`sh000001`, `sz.399001` ↔ `sz399001`, `sz.399006` ↔ `sz399006`,
`sh.000300` ↔ `sh000300`. The Tencent and BaoStock symbols differ only in the
`.` separator between the exchange prefix and the numeric code.

BaoStock uses `bs.login()` (no per-call auth token) and
`query_history_k_data_plus(code, fields, start_date, end_date, frequency,
adjustflag)`. Eastmoney uses
`https://push2his.eastmoney.com/api/qt/stock/kline/get` with `secid`,
`fields1`, `fields2`, `klt`, `fqt`, `beg`, `end`.

## 2. Compared windows

Two short paired windows were issued against both Tencent and BaoStock on the
same wall-clock day (`2026-09-27`). Each window spans exactly one trading
week so that the two providers can be checked on identical session dates.

| Window | `start_date` | `end_date` | Sessions returned per provider, per index | Paired bars |
|---|---|---|---|---|
| A | `2020-03-16` | `2020-03-20` | 5 | 5 × 4 indices = 20 |
| B | `2024-08-19` | `2024-08-23` | 5 | 5 × 4 indices = 20 |
| **Total** | | | | **40 paired bars (20 per window × 2 windows)** |

For each index, BaoStock and Tencent returned the **same session date set**
within both windows. The combined OHLC deltas
(`max(|BaoStock − Tencent|)` across `open`, `high`, `low`, `close`,
index points) per index, listed as window A then window B:

| `index_id` | Window A max combined `\|ΔOHLC\|` | Window B max combined `\|ΔOHLC\|` |
|---|---|---|
| `cn.index.sse.000001` | 0.0049 | 0.0047 |
| `cn.index.szse.399001` | 0.0052 | 0.0050 |
| `cn.index.szse.399006` | 0.0046 | 0.0045 |
| `cn.index.csi.000300` | 0.0047 | 0.0050 |

These deltas are recorded as **observed magnitudes only**. They do not
establish which source is authoritative; the V1 contract does not declare
an authoritative publisher, and these two short windows do not establish
that either.

## 3. Behavior observations

### 3.1 BaoStock (Python SDK)

- **TCP endpoint**: `public-api.baostock.com:10030` (the SDK's documented
  public quickstart host). Not a local daemon at `127.0.0.1:9000`.
- **Default login**: the SDK quickstart credentials are anonymous /
  `123456` (no personal auth in use). The login call returned
  `error_code = "0"` with `error_msg` indicating success. No per-call auth
  token is issued; the session is identified by an internal `user_id`.
- **No-login**: calling `query_history_k_data_plus` without a prior
  `bs.login()` returns the structured error
  `error_code = "10001001" / 用户未登录` with empty `data`; the SDK
  does **not** raise.
- **Invalid frequency**: an invalid frequency token was rejected with the
  structured error `error_code = "10004012" / 请求数据类型不正确` and
  empty `data`; no exception propagates out of the SDK. (Other valid
  frequency tokens beyond this single tested invalid input were not
  enumerated in this round.)
- **Weekend window**: requesting `2024-08-24..2024-08-25` (Sat/Sun) returns
  `error_code = "0"` with empty rows. This is **indistinguishable** from a
  valid empty response — there is no separate "non-trading day" code.
- **Unknown symbol**: `sh.999999` also returns `error_code = "0"` with empty
  rows. The weekend and unknown-symbol outcomes share the same
  `code 0 / success / empty rows` shape; the V2 layer cannot tell them apart
  from `error_code` alone, so the empty payload is ambiguous under V2's
  empty-handling rules.
- **Schema**: the `fields` argument tested was
  `date,code,open,high,low,close,volume,amount`; returned values were
  strings (numeric columns are string-encoded). The payload carries **no
  source provenance field** — the SDK does not embed a publisher token in
  the row, so V2's `source` field would have to be assigned by the
  wrapper, not read from the upstream payload. Field order beyond this
  tested list was not probed.
- **Volume**: BaoStock returns a numeric (string-encoded) `volume` column
  for these four indices; the returned magnitude was observed to be on the
  order of ~100× the value Tencent returns in the same window. The units
  and meaning of each series were **not** independently verified in this
  round, so the comparison is reported as observed magnitude only. The V1
  contract pins Tencent's value to `volume = None`; this round preserves
  `volume = None` and does **not** assert a business interpretation of
  either column.
- **Connect / read timeouts and exception handling** (SDK source
  observation, not direct network-behavior observation): the BaoStock SDK
  exposes no bounded `connect_timeout` / `read_timeout` knobs in this
  version, so the synchronous fallback call has no in-SDK deadline under
  a real upstream stall. To probe whether the underlying socket honors a
  deadline, a deliberate `socket.settimeout(0.001)` around the call raised
  `TimeoutError('timed out')`, while ordinary uncapped calls completed in
  roughly 0.05s on this host. Independently, the SDK source uses broad
  exception handling that may print the exception and return no response
  rather than propagating it to the caller. The combined risk is phrased
  as: **no controllable deadline, and broad exception handling that may
  print and return no response**. This document does not assert a proven
  indefinite hang, a specific swallowed exception message, or a
  process-global socket-state corruption.

### 3.2 Eastmoney push2 history

- **Endpoint**: `https://push2his.eastmoney.com/api/qt/stock/kline/get`.
- **Probe parameters** (parent's direct request): `secid` set per index
  (`1.000001`, `0.399001`, `0.399006`, `1.000300`);
  `fields1=f1,f2,f3,f4,f5,f6`;
  `fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116`;
  `klt=101`; `fqt=0`; `timeout=(4, 10)`; `beg=2026-09-01`;
  `end=2026-09-25`.
- **Behavior on this host (2026-09-27)**: every call above raised
  `requests.exceptions.SSLError`. **No HTTP status code and no response
  body was returned.** Tencent (the V1 baseline) returned 18 rows per
  index over the same window. This run is **not** a service-quality
  verdict on Eastmoney itself — only a record that the host used for this
  research could not retrieve data from this TLS endpoint. No specific
  P3 / handshake-timeout / connection-reset attribution is asserted.

### 3.3 AkShare (not installed)

- AkShare was **absent** from this runtime:
  `importlib.util.find_spec('akshare') == False`. No AkShare live probe
  was performed on this host.
- As a **source-code finding only**, the AkShare index history function
  `index_zh_a_hist` is defined in `akshare/index/index_zh_em.py` and
  routes through the same Eastmoney `push2his` history URL shown above.
  Any upstream-side problem observed on Eastmoney would reproduce through
  AkShare; no AkShare-specific advantage or different fallback path is
  established here. No AkShare issue / P3 trail is cited because no live
  AkShare data was retrieved on this host.

### 3.4 Source URLs probed

- BaoStock quickstart: <https://baostock.com/baostock/index.php/A%E8%82%A1K%E7%BA%BF%E6%95%B0%E6%8D%AE>
- Eastmoney history endpoint:
  <https://push2his.eastmoney.com/api/qt/stock/kline/get>
- AkShare upstream (file containing `index_zh_a_hist`):
  <https://github.com/akfamily/akshare/blob/main/akshare/index/index_zh_em.py>

## 4. Decision

**No production provider-chain change in this round.**

- V2's default chain stays `(tencent_daily_k_provider(),)`. BaoStock and
  Eastmoney/AkShare are **not** added to the fallback sequence.
- The decisive unresolved risk is that the **BaoStock SDK lacks bounded
  connect/read timeouts** and **may block the synchronous fallback call**
  under a real upstream stall, and that its **broad exception handling
  may print the exception and return no response** rather than
  propagating it. This combination is enough to defer onboarding until
  either a bounded timeout is exposed by the SDK, a fork-and-timeout
  wrapper is added, or the broad exception path is replaced with a
  structured error mapping — without unsafe process-global socket
  changes. Whether the call returns, blocks, fails, or corrupts state
  under a real stall is **not** directly observed or sourced in this
  round.
- Independently, the host used for this research could not retrieve
  Eastmoney data over TLS (`requests.exceptions.SSLError`, no HTTP
  status / body), so the Eastmoney path cannot be evaluated against V1
  from this host without a network-layer change.
- Published SLA, freshness objective, license/commercial terms, and
  full-history coverage for BaoStock and Eastmoney push2 were **not**
  established in this round.
- The 40 paired bars did not surface a measured OHLC defect large enough
  to disqualify either provider on data quality alone. **This document
  does not claim the measured OHLC values are bad.**
- Volume semantics are not reconciled — the V1 `volume = None` contract
  is retained, and no business interpretation of BaoStock vs. Tencent
  volume series is asserted.

## 5. Evidence needed before onboarding any candidate

The following items block a future V2.x onboarding PR. None of them is
in scope for this record.

1. **Bounded connect/read behavior** for BaoStock without unsafe
   process-global socket changes (e.g. a fork-and-timeout harness or an
   upstream PR exposing socket timeouts). The chosen approach must not
   mutate `socket.setdefaulttimeout` for the whole process.
2. **Structured error mapping**: a BaoStock adapter that surfaces
   distinct outcomes for non-trading-day windows vs. unknown-symbol
   windows so V2's `UNSUPPORTED` / `VALIDATION` / `PARSE` taxonomy can
   be applied unambiguously, and that replaces the broad
   print-and-return-no-response path with a propagated error.
3. **Longer-period availability/quality checks** spanning at least one
   full Chinese exchange holiday cluster (Spring Festival, National Day)
   and one partial-delisting event. Two short five-session windows are
   not enough to claim production readiness.
4. **Clarity on service terms**: published SLA, freshness objective,
   license/commercial terms, and full-history coverage for both
   BaoStock and Eastmoney push2.
5. **Assigned source provenance**: a stable `name` and wire-level
   `source` token for the new provider descriptor. Neither candidate
   payload carries a publisher provenance field, so the wrapper must
   own this string.

## 6. What this document does not do

- It does not edit `analysis/research/global_daily_k.py`,
  `analysis/research/global_daily_k_service.py`,
  `analysis/research/global_indices.py`, the registry, the tests, or
  any provider descriptor.
- It does not propose a BaoStock or AkShare adapter implementation.
- It does not claim measured OHLC data are bad.
- It does not expand scope to HK/US indices, intraday data, or volume
  semantics.