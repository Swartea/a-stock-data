# Global Market Daily-K — V2 Provider Health & Fallback Contract

This document defines the V2 provider-health and fallback contract for the
global-index daily-K feature, and records the current source coverage at the
time of writing (base `e8415ca`). It is the companion to
`docs/global-market-daily-k-v1.md`, which remains the authoritative
description of the V1 fetcher.

> **Status: contract only. Nothing in this document is implemented.**
> No fallback chain exists in the codebase, no secondary provider is
> configured, and no secondary source has been verified for the V1 universe.
> The single live probe behind this feature (2026-09-27 Asia/Shanghai, nine
> indices, 18–19 bars each for the September 1–25 window) covered the Tencent
> endpoint only. Do not read this document as a reliability or coverage claim
> for any provider other than what the V1 document already states.

## 1. Scope

In scope:

* the V2 contract for the primary Tencent source, the injected ordered
  fallback interface, actual source provenance, failure reason, per-request
  degradation/health states, and the conditions under which fallback is
  attempted;
* the explicit statement that no verified secondary source is configured,
  including why Baostock and AkShare are not global-index Daily-K fallbacks;
* the per-fetch nature of the health state, the unchanged `empty` /
  `unsupported` behavior, and the fact that the V1 API is unchanged;
* current source coverage for this feature only.

Out of scope: volume semantics, index-registry extension, UI/report wiring,
any other fetcher or provider, and any persistent health-monitoring layer.

## 2. V2 contract

### 2.1 Primary provider: Tencent

The primary provider is the existing Tencent source
(`analysis.research.global_daily_k`, endpoint
`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get`, source token
`"tencent.daily_k"`, provider id `"tencent"`). The ordered chain always
attempts the primary first. The V2 layer adds candidates *after* the primary;
it never reorders, skips, or replaces the primary.

### 2.2 Injected ordered fallback interface

Fallback is an **injected, ordered** sequence of provider candidates, in the
same dependency-injection style as the V1 `transport` parameter:

* The V2 entrypoint accepts a keyword-only ordered collection of candidates.
  Each candidate is identified by a canonical provider id (the same token
  space as `analysis/research.providers`, e.g. `"tencent"`) and must resolve
  the requested `index_id` through an explicit provider-symbol mapping in the
  style of `analysis/research/index_symbols.IndexProviderSymbolAlias` — one
  alias per `(provider_id, provider_symbol)`. Bare-code inference stays
  forbidden; a candidate that cannot resolve the `index_id` contributes
  nothing for that request.
* Each candidate fetches through the same injectable transport boundary as V1
  (`transport(url, *, params, timeout) -> Any`), so tests can drive
  deterministic per-candidate fakes and record call order.
* The chain is tried strictly in the supplied order. The injection point
  exists so tests can exercise multi-candidate ordering deterministically and
  so a *future, verified* secondary can be appended without an API change.
* The production default chain contains exactly one candidate — Tencent. With
  the default chain the V2 layer must issue exactly one HTTP request per
  fetch, identical to V1.

### 2.3 Actual source provenance

Every returned envelope must state which provider actually served the rows —
not merely which provider was asked first:

* Envelope `source` is the serving provider's own source token (e.g.
  `"tencent.daily_k"` when the primary serves; the secondary's own token when
  a fallback serves). Per-record `source` matches the envelope.
* The envelope carries an ordered attempt trail, one entry per candidate
  tried, recording the provider id, its source token, and the outcome
  (`ok`, or the stable error code). This is what lets a caller tell
  "requested Tencent, served by fallback" apart from "served by Tencent".

### 2.4 Failure reason

* When the chain is exhausted without a usable payload, the result is
  `status=error` whose `error` object carries the stable error `code` and a
  short, secret-free `message` from the **last** candidate's failure, matching
  the existing `analysis.fetcher_contract` error shape.
* The attempt trail (§2.3) preserves each candidate's individual failure
  code, so the last-candidate `error` is the summary and the trail is the
  per-candidate evidence.

### 2.5 Per-request degradation / health states

Each V2 result carries a per-request health annotation:

* `degraded` — `false` when the primary candidate served the data; `true`
  when any non-primary candidate served it. This mirrors
  `analysis.research.quality.QualityMetadata.degraded`: fallback-served data
  may be fresh and complete and is still marked degraded, so callers can
  weight it differently without conflating it with an error.
* `served_by` — the provider id that actually served the rows.
* `attempts` — the ordered attempt trail from §2.3.

A request whose chain is exhausted has no health annotation beyond the error
envelope: the health state describes a completed fetch, not a failed one.

### 2.6 Fallback conditions

Fallback from one candidate to the next is attempted **only** when the current
candidate fails with a retryable transport-level error and produced no usable
payload: `NET_TIMEOUT`, `NET_SSL`, `NET_CONN`, `NET_RATELIMIT`, `NET_5XX`,
`UNKNOWN` (the retryable codes of `analysis.fetcher_contract`).

Fallback is **never** attempted on:

* `VALIDATION` — bad inputs are rejected before the chain runs; no candidate
  is called.
* `UNSUPPORTED` — the `index_id` does not resolve for any candidate; the
  registry check happens before any network call.
* `empty` — a candidate returned a valid payload whose filtered window has no
  sessions. That is a definitive business answer, not a provider failure, and
  it is returned as-is.
* `PARSE` / `NET_4XX` — non-retryable, definitive answers from that candidate
  for this request; the chain does not treat them as health signals.

The first candidate to return a usable payload ends the chain. A candidate
that returns `empty` also ends the chain successfully (with `degraded` set
per §2.5 if it was a non-primary candidate).

## 3. No verified secondary source is configured

There is **no verified secondary source** for global-index Daily-K. The
production chain is Tencent-only. Two names that already exist in this
repository's dependency and provider registries are explicitly **not**
fallbacks:

### 3.1 Why Baostock is not a global-index Daily-K fallback

* **Different verified scope.** Baostock (a TCP client library,
  `requirements.txt`: `baostock>=0.9,<1.0`) is wired into this project only
  for A-share fundamentals — valuation history (`baostock_valuation_history`)
  and stock basic info (`baostock_stock_basic`). Its documented coverage is
  mainland A-share stocks; it is known to reject 北交所 (4/8/92/920) codes
  server-side. No code path uses it for index Daily-K.
* **No verified global-index coverage.** Nothing has live-probed Baostock for
  the nine-index V1 universe; HK (`HSI`, `HSTECH`) and US (`SP500`, `IXIC`,
  `DJI`) index bars from it are unverified, and the project has no
  Baostock provider-symbol mapping for any index
  (`analysis/research/global_indices.py` registers exactly one Tencent alias
  per index).
* **Wire-shape mismatch.** Baostock is a stateful TCP client that requires a
  login session (`bs.login`/`logout`) and returns its own `ResultData` frames,
  not the stateless HTTP-JSON boundary the daily-K fetcher contract is built
  on. Adapting it is a new integration, not a drop-in candidate.
* The provider *identity* exists in `analysis/research/providers.py`, but that
  registry deliberately models identities only — not endpoints, health, or
  fallback order — so its presence implies no capability.

### 3.2 Why AkShare is not a global-index Daily-K fallback

* **Dependency deliberately removed.** AkShare was dropped in the V3.0
  breaking change: it is a wrapper over Eastmoney/Tonghuashun/Sina public
  APIs whose middle layer adds failure points (version-compatibility bugs,
  pandas 3.0 `ArrowInvalid`, etc.). It is not in `requirements.txt` or
  `pyproject.toml`; the project's architecture principle is direct HTTP
  connections with no third-party data wrappers (only the `mootdx` and
  `baostock` TCP clients excepted).
* **Nothing to wire.** Because the package is not a dependency, there is no
  AkShare transport to inject, no symbol mapping, and no probe. Re-adding it
  would contradict the V3.0 decision and is out of scope for this feature.

### 3.3 What a secondary must satisfy before joining the chain

Before any provider id other than `"tencent"` may appear in the production
chain, it must: (a) be live-probed against the same nine-index V1 universe;
(b) expose an explicit provider-symbol alias per index; (c) fetch through the
existing transport boundary; and (d) pass the same row-level validation
(strict dates, finite positive OHLC, `low <= open, close <= high`). Until all
four hold, the injected ordered interface accepts test doubles only, and
production remains single-source.

## 4. Per-fetch health, not persistent uptime state

The V2 health state is **per fetch**: it is computed inside one call and
returned in that call's envelope, scoped to `fetched_at`. It is **not**:

* a persistent provider-uptime or SLA record — nothing is stored between
  calls, and no history is kept anywhere;
* a circuit breaker — there is no open/half-open/closed state, no cooldown,
  no consecutive-failure counter, and no cross-request memory of any kind;
* an input to the provider registry — `analysis/research/providers.py`
  explicitly does not model health, and the V2 contract adds no such modeling.

Every call re-evaluates the chain from scratch. Two consecutive fetches may
legitimately disagree about provider health; neither affects the other.

## 5. Empty and unsupported behavior (unchanged)

`empty` and `unsupported` keep their V1 meanings and remain terminal,
non-degraded, fallback-free outcomes:

* `unsupported` — unknown / unqualified / wrong-cased `index_id`, resolved
  before any candidate runs; the transport is never called.
* `empty` — a candidate answered successfully but the filtered window holds
  no sessions; this is a business answer, not a health signal, and never
  triggers fallback (§2.6).
* Error messages stay short and never include credentials or provider
  internals; `data` is `None` on any error or unsupported result.

## 6. V1 API unchanged

`fetch_global_daily_k(index_id, start_date, end_date, *, transport, now)` and
its envelope keep their V1 shape and semantics: exactly one HTTP request per
call, no retry, no fallback, no cache. The V2 layer is additive — a separate
entrypoint/wrapper that accepts the ordered candidate injection; with the
default Tencent-only chain its observable behavior is identical to V1. No V1
caller, test, registry entry, or document needs to change for V2 to exist.

## 7. Current source coverage (base `e8415ca`)

What exists today for this feature:

| Layer | File | Coverage |
|---|---|---|
| Fetcher | `analysis/research/global_daily_k.py` | V1 Tencent-only fetcher; injectable transport; zero retry/fallback/cache; full input/row validation; conservative same-day cut |
| Registry | `analysis/research/global_indices.py` | Frozen nine-index universe; exactly one Tencent alias per index |
| Envelope | `analysis/fetcher_contract.py` | `ok` / `empty` / `error` / `unsupported` statuses; stable error codes with `retryable` flags |
| Provider identities | `analysis/research/providers.py` | Identity-only registry (includes `baostock`, `tencent`); no health/fallback modeling |
| Quality semantics | `analysis/research/quality.py` | `QualityMetadata.degraded` definition the V2 health state mirrors |
| Tests | `tests/research/test_global_daily_k.py`, `tests/research/test_global_daily_k_smoke.py` | Contract + smoke coverage of the V1 surface |
| Docs | `docs/global-market-daily-k-v1.md` | V1 contract and the 2026-09-27 single-probe availability evidence |

What does **not** exist today: any V2 module or entrypoint, any ordered
fallback chain, any second provider-symbol alias, any health/degradation
field on the envelope, any circuit-breaker or uptime state, and any probe of
Baostock or AkShare for global-index Daily-K.

## 8. Explicit non-claims

* This document does not claim a fallback source is implemented, configured,
  or reliable.
* It does not claim any provider other than Tencent serves global-index
  Daily-K today.
* It does not extend coverage beyond the nine-index V1 universe.
* It does not modify the V1 API, the V1 document, or any code.
