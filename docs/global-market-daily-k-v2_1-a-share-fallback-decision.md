# Global Market Daily-K V2.1 — A-share Fallback Research & Decision

> Research evidence and implementation record for the 2026-09-27 V2.1 A-share
> fallback evaluation. Probe facts below were collected before implementation;
> the outcome section records the subsequent provider-chain change.

| Field | Value |
|---|---|
| Baseline commit | `53a1d93024246b89f73aaab4b44a6cb1ac2f9c77` (HEAD at research time) |
| Research date | 2026-09-27 (Asia/Shanghai) |
| Scope | Four V1 A-share indices only: `cn.index.sse.000001`, `cn.index.szse.399001`, `cn.index.szse.399006`, `cn.index.csi.000300` |
| Candidate providers probed | BaoStock (Python SDK over TCP) and Eastmoney push2 history endpoint (also reached transitively via AkShare upstream). AkShare was absent from this runtime. |
| Out of scope | HK/US fallback, volume contract changes, runtime installs |

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

## 4. Research decision

At the research gate, **no candidate had sufficient evidence for production
onboarding**. BaoStock's missing bounded timeout and the unresolved service
and data-coverage questions remained open; Eastmoney could not be reached from
the research host.

- The measured BaoStock / Tencent paired bars do not establish which provider
  is authoritative. The short two-window sample is availability evidence,
  not long-range coverage evidence.
- Volume semantics are not reconciled. V1 `volume = None` remains unchanged.

## 5. Implementation outcome

After the evidence record was reviewed, the user explicitly approved adding
BaoStock to the A-share fallback chain while retaining the open risks below.
The adapter runs each SDK login/query in a spawned child process with a hard
10-second deadline; the parent terminates and reaps a timed-out child.

- The four supported A-share chains are Tencent → BaoStock. HK and US remain
  Tencent-only. V2 orchestration metadata and error envelopes are reused.
- The adapter assigns source provenance `baostock.daily_k`, validates
  normalized identity/date/OHLC, and always emits `volume = None`.
- The implementation does not establish BaoStock SLA, freshness, service
  terms, full-history coverage, or a distinction between valid empty results
  and unsupported symbols. Those remain operational risks.
- An implementation smoke queried all four indices for `2024-08-19..23`;
  each source returned five matching sessions per index. Maximum absolute
  OHLC deltas (index points) were 0.0047 (上证), 0.0050 (深证成指), 0.0045
  (创业板指), and 0.0050 (沪深300). BaoStock rows kept `volume = None`.
  This remains a short sample, not a coverage or authority claim.

The following risks remain material for deployment:

- The BaoStock SDK exposes no internal connect/read deadline; the adapter
  bounds wall-clock time through process isolation. Process spawn availability
  and cleanup are tested offline, but a live upstream stall was not induced.
- Published SLA, freshness objective, license/commercial terms, and full
  history coverage for BaoStock and Eastmoney push2 were not established.
- BaoStock returns success with empty rows for both a weekend and an unknown
  symbol. The adapter only calls its fixed four-index map, but an empty
  response cannot prove that the upstream recognized a requested code.

## 6. Evidence needed to reduce remaining risk

1. Confirm BaoStock service terms, freshness expectations, and coverage for
   the required historical windows.
2. Validate date availability across longer historical periods and exchange
   holiday clusters.
3. Seek a distinct unsupported-symbol signal from BaoStock, or retain the
   ambiguity as a documented provider limitation.
4. Observe process-isolated timeout and cleanup behavior under controlled
   network-stall testing before increasing call concurrency.

## 7. What this implementation does not do

- It does not edit `analysis/research/global_daily_k.py`,
  `analysis/research/global_indices.py`, or any legacy pipeline/analyzer.
- It does not change the A-share `volume = None` contract.
- It does not add fallback for HK/US or introduce UI, intraday data, or
  automatic trading.
