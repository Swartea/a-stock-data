# Global Market Daily-K V1

V1 scope: a fixed, isolated daily-K fetcher for nine representative global
indices, backed by the Tencent `web.ifzq.gtimg.cn` `appstock/app/fqkline/get`
endpoint. This document describes the public surface, the supported universe,
date/time semantics, and the explicit limitations.

This is **not** a global coverage claim. Nikkei and every other non-listed
index are explicitly unsupported and will never be silently inferred.

## Supported V1 universe

| `index_id`                      | Publisher    | `local_code` | Market | Display name                | Currency | Timezone           | Tencent provider symbol |
|---------------------------------|--------------|--------------|--------|------------------------------|----------|--------------------|--------------------------|
| `cn.index.sse.000001`           | `sse`        | `000001`     | `cn`   | 上证指数                     | `CNY`    | `Asia/Shanghai`    | `sh000001`               |
| `cn.index.szse.399001`          | `szse`       | `399001`     | `cn`   | 深证成指                     | `CNY`    | `Asia/Shanghai`    | `sz399001`               |
| `cn.index.szse.399006`          | `szse`       | `399006`     | `cn`   | 创业板指                     | `CNY`    | `Asia/Shanghai`    | `sz399006`               |
| `cn.index.csi.000300`           | `csi`        | `000300`     | `cn`   | 沪深300                      | `CNY`    | `Asia/Shanghai`    | `sh000300`               |
| `hk.index.hang_seng.hsi`        | `hang_seng`  | `HSI`        | `hk`   | 恒生指数                     | `HKD`    | `Asia/Hong_Kong`   | `hkHSI`                  |
| `hk.index.hang_seng.hstech`     | `hang_seng`  | `HSTECH`     | `hk`   | 恒生科技指数                 | `HKD`    | `Asia/Hong_Kong`   | `hkHSTECH`               |
| `us.index.sp_dji.sp500`         | `sp_dji`     | `SP500`      | `us`   | S&P 500                      | `USD`    | `America/New_York` | `us.INX`                 |
| `us.index.nasdaq.composite`     | `nasdaq`     | `IXIC`       | `us`   | Nasdaq Composite             | `USD`    | `America/New_York` | `us.IXIC`                |
| `us.index.sp_dji.djia`          | `sp_dji`     | `DJI`        | `us`   | Dow Jones Industrial Average | `USD`    | `America/New_York` | `us.DJI`                 |

### Explicitly unsupported

* Nikkei 225 / Nikkei 400 / TOPIX / any JPX index.
* European indices (DAX, FTSE 100, CAC 40, STOXX 600, ...).
* Emerging-market indices (BSE Sensex, Hang Seng China Enterprises, ...).
* Any commodity, currency, or bond index.
* Any future V2 candidate — including Hong Kong `HSCEI` and CSI `000852` —
  must be added by extending the registry; bare-code inference is not
  permitted.

A live probe on **2026-09-27 Asia/Shanghai** against the Tencent endpoint
returned 18-19 daily-K bars (September 1-25) for each of the nine indices
above. That single probe is **availability evidence, not an SLA**. Production
uptime, completeness, and freshness are not guaranteed.

## Public entrypoint

```python
from datetime import datetime, timezone
from analysis.research.global_daily_k import fetch_global_daily_k

result = fetch_global_daily_k(
    "cn.index.csi.000300",
    "2026-09-01",
    "2026-09-25",
    now=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc),
)
```

The returned dict follows `analysis.fetcher_contract`:

```json
{
  "status": "ok",
  "data": [
    {
      "index_id": "cn.index.csi.000300",
      "market": "cn",
      "symbol": "000300",
      "name": "沪深300",
      "date": "2026-09-01",
      "open": 4250.12,
      "high": 4280.33,
      "low":  4245.10,
      "close": 4275.66,
      "volume": null,
      "currency": "CNY",
      "timezone": "Asia/Shanghai",
      "source": "tencent.daily_k"
    }
  ],
  "source": "tencent.daily_k",
  "as_of": "2026-09-25",
  "fetched_at": "2026-09-27T04:00:00+00:00",
  "scope": "market",
  "units": {"price": "index_points", "volume": "unavailable"},
  "error": null
}
```

`fetch_global_daily_k` is the only public fetcher entrypoint. There is **no
automatic fallback, cache, or retry** — every call issues exactly one HTTP
request. There is no legacy analyzer re-export.

## Input contract

* `index_id` — canonical lowercase Research-Engine id from the table above.
  Bare provider symbols like `"sh000300"` or `"us.INX"` are **not** accepted
  by the fetcher and return `status=unsupported` (the bare-code lookup is
  intentionally absent). The fetcher distinguishes two rejection paths so
  callers do not confuse a known-but-mis-cased id with a genuinely unknown
  symbol:

  * **Uppercase / mixed-case *qualified* index id** — e.g. `"CN.INDEX.CSI.000300"`.
    Lowercasing the input lands on one of the nine canonical V1 ids above,
    so the fetcher returns `status=error, code=VALIDATION, retryable=False`
    ("wrong casing of a known id"). The transport is not called.
  * **Unqualified / unknown raw symbol** — e.g. `"hkHSI"`, `"us.INX"`,
    `"IXIC"`, `"HSI"`, `"^GSPC"`, `"^IXIC"`, `"N225"`, or `"sh000300"`.
    Lowercasing the input does **not** land on any canonical V1 id (mixed-case
    provider symbols, all-caps publisher local codes, Yahoo-style decorated
    short names, bare codes), so the fetcher returns
    `status=unsupported, code=UNSUPPORTED, retryable=False`. The transport
    is not called. Bare-code inference is intentionally absent in both
    directions — a wrong-cased known id is not silently coerced to its
    lowercase form, and an unknown token is not silently treated as a
    provider symbol.
* `start_date`, `end_date` — strict `YYYY-MM-DD` strings, inclusive window.
  `start_date <= end_date`. Maximum inclusive window: 366 calendar days.
* `transport` — keyword-only, defaults to `requests_json_transport`. Must be
  callable with the boundary
  `transport(url, *, params, timeout) -> Any`. Tests inject a deterministic
  fake.
* `now` — keyword-only, optional aware `datetime`. Defaults to
  `datetime.now(tz=timezone.utc)`. A naive `now` (or any non-datetime) returns
  `status=error, code=VALIDATION, retryable=False` **before** the transport
  is called.

Invalid inputs never reach the network. The fetcher validates inputs first
and returns a stable `VALIDATION` error dict.

## Date / time semantics

* Session dates are returned exactly as Tencent publishes them — no UTC
  conversion. A US session dated `2026-09-25` stays `2026-09-25` even when the
  fetcher runs after 16:00 New York.
* Foreign markets do **not** use the Shanghai trading calendar. Closed days
  and holidays appear only as the absence of a bar; the fetcher never
  forward-fills or synthesizes missing sessions.
* `cutoff_local = now.astimezone(spec.timezone).date()`. Any provider row
  whose session date is `>= cutoff_local` is dropped. This conservative
  policy excludes every current-local-day bar even after close; it does not
  claim intraday finality or that the history is complete.
* `fetched_at` is the aware retrieval instant, formatted by
  `fetcher_contract._now_iso()`. It is **not** a data timestamp.
* `as_of` is the latest returned session date in the filtered window, or
  `None` if the filtered result is empty.
* Empty filtered results are empty — including windows that cover only
  non-trading days. Holiday status is never inferred from a missing bar.

## Volume limitation

* `volume` is `null` for **every** V1 record.
* The provider's sixth column carries heterogeneous activity-like values
  (some look like HK turnover, some look like US share volume); their units
  are unverified and not comparable across markets.
* `units = {"price": "index_points", "volume": "unavailable"}`. OHLC is
  already index points, not currency-denominated price — no conversion is
  applied. No turnover rate is reported as volume, no zero-volume fallback is
  invented.
* Callers that need a comparable volume series must wait for V2.

## Output record shape

Exactly these 13 keys, in this order, on every returned record:

`index_id, market, symbol, name, date, open, high, low, close, volume, currency, timezone, source`

* `symbol` is the publisher `local_code` (e.g. `"000300"`, `"HSI"`, `"DJI"`),
  not the Tencent provider symbol. The provider symbol lives in the V1
  registry (`global_indices.GLOBAL_INDEX_PROVIDER_SYMBOLS`) and is used only
  to build the request URL.
* `currency` is the market's context currency. It is **not** a guarantee
  that OHLC is denominated in that currency.
* `date` is a strict `YYYY-MM-DD` string in the spec's local timezone.

## Validation rules

The fetcher rejects malformed provider payloads up front:

* Provider `code` must be the integer `0`. Booleans and nonzero values are
  errors.
* The payload must be a mapping with a `data` mapping containing a section
  for the exact requested symbol, and that section must contain a `day`
  list.
* Explicit `day = []` is a valid empty result.
* Adjusted-only fields (`qfqday`, `hfqday`) are ignored — the fetcher
  intentionally requests the unadjusted series.
* Each row must be a list with at least six fields
  `[date, open, close, high, low, activity, ...]`.
* Dates must be strict `YYYY-MM-DD`.
* OHLC must be finite positive real numbers (or decimal strings); `bool`,
  `NaN`, `±Inf`, and malformed values are rejected.
* `low <= open, close <= high` and `low <= high`.
* Duplicate normalized session dates with identical OHLC coalesce silently;
  duplicate dates with conflicting OHLC are an error (never "keep first" or
  "keep last").
* Malformed JSON or payload → `code=PARSE, retryable=False`.

## Provider failure behavior

| Condition                              | Returned `code`        | `retryable` |
|----------------------------------------|------------------------|-------------|
| Request timeout                        | `NET_TIMEOUT`          | `True`      |
| TLS / certificate failure              | `NET_SSL`              | `True`      |
| Connection error / DNS failure         | `NET_CONN`             | `True`      |
| HTTP 4xx (excluding 429)               | `NET_4XX`              | `False`     |
| HTTP 429 (rate limited)                | `NET_RATELIMIT`        | `True`      |
| HTTP 5xx                               | `NET_5XX`              | `True`      |
| Other `requests` exception             | `UNKNOWN`              | `True`      |
| Malformed JSON / payload structure     | `PARSE`                | `False`     |
| Unknown / unqualified `index_id`       | `UNSUPPORTED`          | `False`     |
| Bad input (dates, window, transport)   | `VALIDATION`           | `False`     |

Error messages are short and never include credentials or secrets.
`data` is `None` on any error or unsupported result.

## What this module is not

* **Not** a production uptime commitment. The single live probe on
  2026-09-27 is availability evidence, not an SLA.
* **Not** a global-coverage claim. Only the nine indices in the table above
  are supported; everything else is unsupported.
* **Not** an intraday or realtime feed. Bars are unadjusted daily closes;
  current-local-day bars are excluded entirely.
* **Not** wired into the legacy V3 analyzer. There is no UI, score, formula,
  report, or pipeline change in this V1 scope.
* **Not** an inference engine. Bare provider symbols and bare local codes
  are intentionally not resolved to `index_id`s.

## Additive evolution

Adding more indices is additive and lives entirely in
`analysis/research/global_indices.py`:

1. Add the `IndexIdentity` (with the appropriate `IndexPublisher` enum
   value, currently `csi`, `sse`, `szse`, `cni`, `hang_seng`, `sp_dji`,
   `nasdaq`).
2. Add the `GlobalIndexSpec` with `market`, `name`, `currency`, `timezone`,
   and Tencent `provider_symbol`.
3. Add the new entry to the doc table above.

Adding a new provider for the same index set is a separate V2 layer and is
out of scope here.