# Global Market Daily-K V2 — Provider Health & Fallback

This document describes the additive V2 orchestration layer over the accepted V1 global-index Daily-K fetcher. V1 remains the Tencent implementation in `analysis/research/global_daily_k.py`; the V2 layer is `analysis/research/global_daily_k_service.py`.

## Scope and current provider coverage

V2 adds ordered provider attempts, failure classification, provenance, and per-request degradation metadata. It does not add a second production data source. The default chain contains Tencent only because this project has no verified alternative Daily-K provider for the nine registered A/HK/US indexes.

Providers may be injected through `DailyKProvider` for integration and deterministic tests. This is an extension point, not evidence that any external provider is production-ready. Baostock's existing support is stock-focused; AkShare is not an installed/declared global-index Daily-K adapter here. Neither is silently used as fallback.

Out of scope: persistent health monitoring/circuit breakers, UI, new markets, intraday data, and changes to the A-share volume contract (`volume` remains `None`).

## Entry point and provider descriptor

Use `fetch_global_daily_k_service(index_id, start_date, end_date, *, now=None, transport=None, providers=None)`. It validates caller inputs and the index registry before invoking a provider. Unknown or invalid index IDs do not trigger provider calls.

`DailyKProvider` carries a stable provider `name`, a wire-level `source` token, a callable `fetch`, and a `scope`. `providers` is a non-empty ordered sequence; the first descriptor is primary and subsequent descriptors are fallback candidates. The default sequence is `(tencent_daily_k_provider(),)`.

When `transport` is omitted/`None`, the service omits that keyword when calling the provider, allowing V1's configured default transport to run. An explicit callable transport is passed through. Provider callables return the existing fetcher envelope shape.

## Fallback policy

For a registered index and valid inputs, the service advances to the next configured provider after any non-usable primary result:

- timeout, connection/TLS/HTTP/request failure or another provider exception;
- `empty` response, including `status=ok` with an empty row list;
- malformed envelope or normalized rows, including schema drift (`PARSE`);
- provider-specific `unsupported` result.

Input validation failures and unknown registry IDs are not provider-health failures and do not fall through the chain. If every provider fails, the service returns a contract-shaped terminal envelope using the last attempted provider's source. Empty/unsupported results retain their V1 meaning when their envelopes are valid; malformed envelopes are synthesized as `PARSE`.

The service does not retry an individual provider, cache responses, or maintain health between calls.

## Provenance and health fields

The ordinary V1 fields (`status`, `data`, `error`, `source`, `scope`, `as_of`, `fetched_at`, `units`) are preserved. V2 adds:

| Field | Meaning |
|---|---|
| `primary_source` | Primary provider descriptor's stable `name` (provider ID). |
| `fallback_sources` | Ordered tuple of fallback provider `name` values. |
| `source_used` | Provider `name` that produced usable rows; `None` if no provider produced rows. |
| `degraded` | `True` when a fallback provider produced the rows. |
| `provider_status` | `ok` for primary success, `degraded` for fallback success, `failed` when no provider produced rows. |
| `failure_reason` | Stable summary of the first failure when fallback succeeds; terminal failure summary when all candidates fail; `None` on primary success. |
| `provider_attempts` | Ordered per-call records with provider name, status, error code/message where present, and whether that attempt was a fallback. |

On success, the top-level and normalized row `source` values are rewritten to the descriptor's wire-level `source`, so provenance identifies the data-producing adapter. On all-failed results, the envelope source identifies the last attempted provider; `source_used` remains `None`.

`provider_status` is per-fetch degradation metadata. It is not a rolling availability metric and does not reuse `SourceStatusRecorder`, whose lifecycle is attached to the V3 run pipeline.

## Validation and data contract

Before accepting `status=ok`, the wrapper checks the V1 envelope's required fields and validates each normalized row against the canonical index registry identity (market, symbol, name, currency, timezone). Dates must be valid strict `YYYY-MM-DD`, unique, and chronological; `as_of` must match the final session date. OHLC values must be finite positive numbers and satisfy `low <= open/close <= high` (with the corresponding high/low inequalities). V1's volume rule (`None`) is retained.

A malformed success envelope/row is treated as a provider parse failure and allows the next configured candidate to run. A valid non-success V1 envelope must carry `data=None` and a structured non-empty error code/message.

## Reuse decisions

- `analysis/research/global_daily_k.py`: retained as the V1 Tencent adapter and normalized Daily-K contract.
- `analysis/fetcher_contract.py`: reused for the existing statuses and stable error taxonomy.
- `analysis/research/global_indices.py`: reused as the canonical nine-index registry and row identity source.
- `analysis/research/providers.py`: remains an identity registry; it does not establish Daily-K capability or fallback readiness.
- `SourceStatusRecorder`: not used because V2 health is request-scoped rather than tied to a multi-stage V3 run.

## Verification boundary

No external fallback source is configured by default. Before adding one, verify its endpoint, per-index symbol mapping, market/session date semantics, normalized row schema, empty/error behavior, and source provenance against the V1 contract. Add it only with explicit coverage and tests; provider names or generic library support alone do not prove index Daily-K capability.
