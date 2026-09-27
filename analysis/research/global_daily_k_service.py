"""V2 orchestration layer for the global-index daily-K fetcher.

This module sits on top of the V1 ``fetch_global_daily_k`` fetcher and adds:

* a small ``DailyKProvider`` descriptor so callers/tests can inject ordered
  fallback providers,
* an index-aware default provider list (Tencent primary, plus the scoped
  BaoStock fallback for four A-share indices),
* per-attempt health metadata (status, code, message) and an ordered
  ``provider_attempts`` list,
* a stable ``degraded`` flag and ``source_used`` marker identifying which
  provider actually produced the data,
* transparent envelope propagation: the top-level ``source`` and every
  normalized record ``source`` are always set to the provider that was used,
* primary-success is healthy/not degraded; fallback-success is degraded and
  identifies the primary failure,
* ``status=ok, data=[]`` is treated as empty so it triggers fallback,
* every return is contract-shaped (always carries ``status``/``data``/``error``),
  and the all-failed path re-synthesizes malformed last envelopes as
  ``PARSE`` (or ``UNKNOWN`` when the provider callable raised) using the
  *last attempted* provider's source.

This module is intentionally narrow. It does not:

* retry or cache, beyond a single ordered fallback walk per request,
* introduce a global mutable circuit breaker or wire V3 SourceStatusRecorder,
* change the V1 ``fetch_global_daily_k`` signature, payload, or error envelope,
* fall back when the caller supplied an invalid ``index_id`` — providers are
  never called for an unknown index,
* fall back on input-validation errors raised before any provider is invoked.

Input-validation precedence (matches V1):
    1. ``providers`` collection shape and member types,
    2. ``index_id`` / ``start_date`` / ``end_date`` / ``now`` shape and values,
    3. caller-supplied ``transport`` shape (``None`` is allowed and means
       "use V1's default transport"; any other non-callable value is
       ``VALIDATION`` and never reaches a provider),
    4. registered-id lookup — a syntactically valid unknown id returns
       ``status=unsupported`` without invoking any provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from typing import Any, Callable, Mapping

import requests

from analysis import fetcher_contract

from .global_daily_k import (
    _STRICT_DATE_RE,
    TENCENT_PROVIDER_ID,
    TENCENT_SCOPE,
    TENCENT_SOURCE,
    _coerce_finite_number,
    _parse_strict_date,
    fetch_global_daily_k,
)
from .global_indices import GlobalIndexSpec, get_global_index

# Type alias for a provider fetch callable. Mirrors the V1 public entrypoint
# surface so the default Tencent provider can delegate to ``fetch_global_daily_k``
# verbatim without any per-provider shim.
DailyKProviderFetch = Callable[..., dict[str, Any]]

# Status tokens surfaced in ``provider_attempts``. They mirror the existing
# fetcher contract statuses; a malformed envelope is classified ``error``.
_ATTEMPT_STATUS_OK = fetcher_contract.STATUS_OK
_ATTEMPT_STATUS_EMPTY = fetcher_contract.STATUS_EMPTY
_ATTEMPT_STATUS_UNSUPPORTED = fetcher_contract.STATUS_UNSUPPORTED
_ATTEMPT_STATUS_ERROR = fetcher_contract.STATUS_ERROR

# Overall ``provider_status`` values.
_PROVIDER_STATUS_OK = "ok"
_PROVIDER_STATUS_DEGRADED = "degraded"
_PROVIDER_STATUS_FAILED = "failed"

# Maximum inclusive window the service will accept. Larger windows are
# rejected up front rather than silently truncated so callers cannot mistake a
# partial result for a complete one.
_MAX_WINDOW_CALENDAR_DAYS = 366


@dataclass(frozen=True)
class DailyKProvider:
    """Descriptor for one Daily-K provider.

    ``name`` is the stable provider id surfaced in ``source_used``,
    ``primary_source`` and ``fallback_sources``; ``source`` is the wire-level
    ``source`` string written into the envelope and into every normalized
    record; ``scope`` is the data scope token (``"market"`` by default);
    ``fetch`` is a callable with the same surface as
    :func:`analysis.research.global_daily_k.fetch_global_daily_k`.
    """

    name: str
    source: str
    fetch: DailyKProviderFetch
    scope: str = TENCENT_SCOPE

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("provider name must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("provider source must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError("provider scope must be a non-empty string")
        if not callable(self.fetch):
            raise ValueError("provider fetch must be callable")


def tencent_daily_k_provider() -> DailyKProvider:
    """Build the default Tencent provider descriptor.

    The default primary delegates to the existing V1
    :func:`fetch_global_daily_k` so the V1 contract is preserved verbatim.
    """

    return DailyKProvider(
        name=TENCENT_PROVIDER_ID,
        source=TENCENT_SOURCE,
        scope=TENCENT_SCOPE,
        fetch=fetch_global_daily_k,
    )


def default_daily_k_providers(
    index_id: str | None = None,
) -> tuple[DailyKProvider, ...]:
    """Return the default chain, with BaoStock limited to four A-share ids.

    The optional id preserves the historical no-argument Tencent-only helper
    behavior. The service supplies its requested id to enable the first
    verified A-share fallback; HK and US indices remain Tencent-only.
    """

    primary = tencent_daily_k_provider()
    from .global_daily_k_baostock import (
        BAOSTOCK_INDEX_CODES,
        baostock_daily_k_provider,
    )

    if isinstance(index_id, str) and index_id in BAOSTOCK_INDEX_CODES:
        return (primary, baostock_daily_k_provider())
    return (primary,)


def _is_aware_iso_datetime(value: Any) -> bool:
    """Return ``True`` iff ``value`` is a non-empty ISO-8601 string with timezone."""

    if not isinstance(value, str) or not value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return False
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def _validate_ok_envelope_shape(envelope: Mapping[str, Any]) -> bool:
    """Verify the top-level fields of a ``status=ok`` envelope conform to V1.

    The envelope must carry all common Daily-K fields used by V1:

    * ``source`` — non-empty string,
    * ``data`` — a list,
    * ``as_of`` — strict ``YYYY-MM-DD`` string,
    * ``fetched_at`` — aware ISO-8601 datetime string,
    * ``scope`` — non-empty string,
    * ``units`` — a mapping,
    * ``error`` — exactly ``None``.

    Any missing or contract-inconsistent field classifies ``PARSE`` so the
    orchestrator can advance to the next fallback. Valid V1 envelopes produced
    by :func:`analysis.research.global_daily_k.fetch_global_daily_k` satisfy
    every check below verbatim.
    """

    for field in ("source", "scope"):
        value = envelope.get(field)
        if not isinstance(value, str) or not value:
            return False
    if not isinstance(envelope.get("data"), list):
        return False
    as_of = envelope.get("as_of")
    if not isinstance(as_of, str) or not _STRICT_DATE_RE.fullmatch(as_of):
        return False
    if not _is_aware_iso_datetime(envelope.get("fetched_at")):
        return False
    if not isinstance(envelope.get("units"), Mapping):
        return False
    return envelope.get("error") is None


def _validate_ok_row(row: Any, *, spec: GlobalIndexSpec) -> Date | None:
    """Validate one ``status=ok`` row against the V1 spec; return its parsed date.

    Returns ``None`` for any malformed row. The validator enforces the
    controller-decided contract:

    * canonical requested ``index_id`` plus matching ``market`` / ``symbol`` /
      ``name`` / ``currency`` / ``timezone`` from the V1 registry,
    * non-empty ``source`` string,
    * strict ``YYYY-MM-DD`` session date,
    * ``volume is None`` (V1 rule),
    * finite positive OHLC numbers (no ``bool`` / ``NaN`` / ``inf`` / string),
    * valid ``low <= min(open, close)`` and ``high >= max(open, close)``.
    """

    if not isinstance(row, Mapping):
        return None
    if row.get("index_id") != spec.identity.index_id:
        return None
    if row.get("market") != spec.market:
        return None
    if row.get("symbol") != spec.identity.local_code:
        return None
    if row.get("name") != spec.name:
        return None
    if row.get("currency") != spec.currency:
        return None
    if row.get("timezone") != spec.timezone:
        return None
    source = row.get("source")
    if not isinstance(source, str) or not source:
        return None
    try:
        parsed_date = _parse_strict_date(row.get("date"), field="row date")
    except (TypeError, ValueError):
        return None
    if row.get("volume") is not None:
        return None
    try:
        open_px = _coerce_finite_number(row.get("open"), field="open")
        close_px = _coerce_finite_number(row.get("close"), field="close")
        high_px = _coerce_finite_number(row.get("high"), field="high")
        low_px = _coerce_finite_number(row.get("low"), field="low")
    except (TypeError, ValueError):
        return None
    if low_px > high_px:
        return None
    if low_px > open_px or low_px > close_px:
        return None
    if high_px < open_px or high_px < close_px:
        return None
    return parsed_date


def _validate_ok_records(
    envelope: Mapping[str, Any], *, spec: GlobalIndexSpec
) -> bool:
    """Validate the ``data`` list: per-row canonical fields, unique ascending
    dates, and ``as_of`` agreeing with the last ordered session date."""

    data = envelope.get("data")
    if not isinstance(data, list) or len(data) == 0:
        return False
    seen_dates: set[Date] = set()
    last_date: Date | None = None
    for row in data:
        parsed = _validate_ok_row(row, spec=spec)
        if parsed is None:
            return False
        if parsed in seen_dates:
            return False
        seen_dates.add(parsed)
        if last_date is not None and parsed <= last_date:
            return False
        last_date = parsed
    if last_date is None:
        return False
    as_of = envelope.get("as_of")
    return isinstance(as_of, str) and as_of == last_date.isoformat()


def _classify_envelope(
    envelope: Any, *, spec: GlobalIndexSpec | None = None
) -> str:
    """Return one of the four fetcher statuses, or ``error`` for malformed.

    For ``status=ok`` the full V1 envelope shape AND every row are validated
    against the spec. Any structural violation is reclassified ``error`` (PARSE
    on the caller side) so the orchestrator can advance to the next fallback.

    ``spec`` must be supplied whenever the envelope could be ``status=ok``;
    ``error``/``empty``/``unsupported`` envelopes do not require it.
    """

    if not isinstance(envelope, Mapping):
        return _ATTEMPT_STATUS_ERROR
    status = envelope.get("status")
    if status == _ATTEMPT_STATUS_OK:
        if not _validate_ok_envelope_shape(envelope):
            return _ATTEMPT_STATUS_ERROR
        # ``status=ok`` with an empty ``data`` list is effectively empty
        # (no rows to deliver) and must advance fallback per the contract.
        data = envelope.get("data")
        if isinstance(data, list) and len(data) == 0:
            return _ATTEMPT_STATUS_EMPTY
        if spec is None or not _validate_ok_records(envelope, spec=spec):
            return _ATTEMPT_STATUS_ERROR
        return _ATTEMPT_STATUS_OK
    if status == _ATTEMPT_STATUS_EMPTY:
        if not _is_error_envelope_conform(envelope):
            return _ATTEMPT_STATUS_ERROR
        return _ATTEMPT_STATUS_EMPTY
    if status == _ATTEMPT_STATUS_UNSUPPORTED:
        if not _is_error_envelope_conform(envelope):
            return _ATTEMPT_STATUS_ERROR
        return _ATTEMPT_STATUS_UNSUPPORTED
    if status == _ATTEMPT_STATUS_ERROR:
        if not _is_error_envelope_conform(envelope):
            return _ATTEMPT_STATUS_ERROR
        return _ATTEMPT_STATUS_ERROR
    return _ATTEMPT_STATUS_ERROR


def _envelope_error_code(envelope: Mapping[str, Any]) -> str | None:
    """Return the stable error code from a fetcher envelope, or ``None``."""

    error = envelope.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _envelope_error_message(envelope: Mapping[str, Any]) -> str | None:
    """Return the error message from a fetcher envelope, or ``None``."""

    error = envelope.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return None


def _is_error_envelope_conform(envelope: Mapping[str, Any]) -> bool:
    """Verify an ``error``/``empty``/``unsupported`` envelope is contract-shaped.

    The fetcher contract requires ``data is None`` and ``error`` to be a
    mapping carrying a non-empty string ``code`` and a non-empty string
    ``message``. Envelopes that violate either rule are classified ``PARSE``
    so that fallback can advance (when another provider exists) and the
    all-failed path can synthesize a proper contract-shaped error envelope.
    """

    if envelope.get("data") is not None:
        return False
    code = _envelope_error_code(envelope)
    message = _envelope_error_message(envelope)
    return not (code is None or message is None)


def _rewrite_source(
    envelope: dict[str, Any],
    *,
    provider: DailyKProvider,
) -> dict[str, Any]:
    """Rewrite the top-level ``source`` and record-level ``source`` to the provider used.

    Returns a shallow copy so the caller's envelope (or its normalized records)
    is never mutated.
    """

    rewritten = dict(envelope)
    rewritten["source"] = provider.source
    records = rewritten.get("data")
    if isinstance(records, list):
        rewritten_records: list[Any] = []
        for record in records:
            if isinstance(record, Mapping):
                new_record = dict(record)
                new_record["source"] = provider.source
                rewritten_records.append(new_record)
            else:
                rewritten_records.append(record)
        rewritten["data"] = rewritten_records
    return rewritten


def _classify_provider_exception(
    exc: BaseException,
    *,
    provider: DailyKProvider,
) -> dict[str, Any]:
    """Map a provider-callable exception to a fetcher-contract error envelope.

    Never leaks the underlying exception message to the caller. Maps requests
    errors to the existing V1 taxonomy and treats any other exception as
    ``ERR_UNKNOWN``.
    """

    if isinstance(exc, requests.exceptions.Timeout):
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_TIMEOUT,
            f"{provider.name} request timed out",
            source=provider.source, retryable=True, scope=provider.scope,
        )
    if isinstance(exc, requests.exceptions.SSLError):
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_SSL,
            f"{provider.name} TLS error",
            source=provider.source, retryable=True, scope=provider.scope,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_CONN,
            f"{provider.name} connection error",
            source=provider.source, retryable=True, scope=provider.scope,
        )
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int):
            if status == 429:
                return fetcher_contract.make_error_result(
                    fetcher_contract.ERR_NET_RATELIMIT,
                    f"{provider.name} rate limited",
                    source=provider.source, retryable=True, scope=provider.scope,
                )
            if 400 <= status < 500:
                return fetcher_contract.make_error_result(
                    fetcher_contract.ERR_NET_4XX,
                    f"{provider.name} client error",
                    source=provider.source, retryable=False, scope=provider.scope,
                )
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_NET_5XX,
            f"{provider.name} server error",
            source=provider.source, retryable=True, scope=provider.scope,
        )
    if isinstance(exc, requests.exceptions.RequestException):
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            f"{provider.name} request failed",
            source=provider.source, retryable=True, scope=provider.scope,
        )
    return fetcher_contract.make_error_result(
        fetcher_contract.ERR_UNKNOWN,
        f"{provider.name} raised an unexpected error",
        source=provider.source, retryable=True, scope=provider.scope,
    )


def _build_attempt(
    *,
    provider: DailyKProvider,
    envelope: Any,
    index: int,
    spec: GlobalIndexSpec | None = None,
) -> dict[str, Any]:
    """Build one entry in the ``provider_attempts`` ordered list.

    ``index == 0`` means the primary; higher indices are fallbacks. The
    ``degraded`` flag is set when the attempt was a fallback call (regardless
    of whether the call succeeded). Malformed envelopes — those that
    classify as ``error`` because their structure violates the contract —
    carry ``code=PARSE`` so callers can see why fallback was triggered.
    """

    status = _classify_envelope(envelope, spec=spec)
    if isinstance(envelope, Mapping):
        code = _envelope_error_code(envelope)
        message = _envelope_error_message(envelope)
        original_status = envelope.get("status")
        if status == _ATTEMPT_STATUS_ERROR and (
            code is None or original_status == _ATTEMPT_STATUS_OK
        ):
            # Malformed: recognized non-ok status with no proper error
            # mapping, OR a ``status=ok`` envelope that failed full shape /
            # row validation. Either way, surface as PARSE so callers see
            # why fallback was triggered (and provider internals / arbitrary
            # ``error.code`` strings never leak through the attempt).
            code = fetcher_contract.ERR_PARSE
            message = message or "provider returned malformed envelope"
    elif envelope is None:
        message = None
        code = None
    else:
        message = f"provider returned non-mapping envelope: {type(envelope).__name__}"
        code = fetcher_contract.ERR_PARSE
    return {
        "provider": provider.name,
        "status": status,
        "code": code,
        "message": message,
        "degraded": index > 0,
    }


def _resolve_index(
    index_id: Any,
) -> tuple[dict[str, Any] | None, str | None, GlobalIndexSpec | None]:
    """Resolve ``index_id`` via the V1 registry.

    Returns ``(None, None, spec)`` when the index is valid.
    Returns ``(unsupported_envelope, None, None)`` when the id is unknown.
    Returns ``(None, message, None)`` when the id is malformed.
    """

    if not isinstance(index_id, str) or not index_id:
        return None, "index_id must be a non-empty string", None
    try:
        spec: GlobalIndexSpec = get_global_index(index_id)
    except KeyError:
        return (
            fetcher_contract.make_unsupported(
                source=TENCENT_SOURCE,
                scope=TENCENT_SCOPE,
                reason=f"unknown global index id: {index_id!r}",
            ),
            None,
            None,
        )
    except (TypeError, ValueError):
        return None, "index_id must use canonical lowercase form", None
    return None, None, spec


def _validate_service_inputs(
    index_id: Any,
    start_date: Any,
    end_date: Any,
    now: Any,
    transport: Any,
) -> str | None:
    """Service-level input validation that mirrors V1's input checks.

    Returns ``None`` when inputs are valid; otherwise returns a stable error
    message suitable for a VALIDATION envelope. Callers must NOT invoke any
    provider when this returns a non-None value. ``transport`` may be
    ``None`` (meaning "use V1's default"); any other non-callable value is a
    caller VALIDATION error.
    """

    if not isinstance(index_id, str) or not index_id:
        return "index_id must be a non-empty string"

    if not isinstance(start_date, str) or not start_date:
        return "start_date must be a non-empty YYYY-MM-DD string"
    if not _STRICT_DATE_RE.fullmatch(start_date):
        return f"start_date must match strict YYYY-MM-DD; got {start_date!r}"
    try:
        parsed_start = Date.fromisoformat(start_date)
    except ValueError:
        return f"start_date is not a valid calendar date: {start_date!r}"

    if not isinstance(end_date, str) or not end_date:
        return "end_date must be a non-empty YYYY-MM-DD string"
    if not _STRICT_DATE_RE.fullmatch(end_date):
        return f"end_date must match strict YYYY-MM-DD; got {end_date!r}"
    try:
        parsed_end = Date.fromisoformat(end_date)
    except ValueError:
        return f"end_date is not a valid calendar date: {end_date!r}"

    if parsed_start > parsed_end:
        return "start_date must be <= end_date"
    if (parsed_end - parsed_start).days + 1 > _MAX_WINDOW_CALENDAR_DAYS:
        return "date window exceeds 366 inclusive calendar days"

    if now is not None:
        if isinstance(now, bool) or not isinstance(now, datetime):
            return "now must be an aware datetime or None"
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            return "now must be timezone-aware"

    if transport is not None and not callable(transport):
        return "transport must be callable"

    return None


def _envelope_with_orchestration(
    base: dict[str, Any],
    *,
    primary: DailyKProvider,
    fallback_names: tuple[str, ...],
    source_used: str | None,
    degraded: bool,
    provider_status: str,
    failure_reason: str | None,
    provider_attempts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Return ``base`` enriched with the orchestration metadata fields."""

    enriched = dict(base)
    enriched.update(
        {
            "primary_source": primary.name,
            "fallback_sources": fallback_names,
            "source_used": source_used,
            "degraded": degraded,
            "provider_status": provider_status,
            "failure_reason": failure_reason,
            "provider_attempts": provider_attempts,
        }
    )
    return enriched


def _build_failure_reason(envelope: Any) -> str:
    """Build a stable ``failure_reason`` string from the last envelope."""

    if not isinstance(envelope, Mapping):
        return "all providers failed"
    code = _envelope_error_code(envelope)
    message = _envelope_error_message(envelope)
    if isinstance(code, str) and isinstance(message, str):
        return f"{code}: {message}"
    if isinstance(code, str):
        return code
    status = envelope.get("status")
    if isinstance(status, str):
        return f"status={status}"
    return "all providers failed"


def _synthesize_final_envelope(
    last_provider: DailyKProvider,
    last_envelope: Any,
    *,
    spec: GlobalIndexSpec | None = None,
) -> dict[str, Any]:
    """Build a contract-shaped envelope for the all-failed path.

    Uses ``last_provider.source`` / ``scope`` for provenance. ``status=ok``
    with empty data is preserved as ``empty``; properly-shaped
    ``error``/``empty``/``unsupported`` envelopes are passed through with
    the last provider's source. Malformed last envelopes — including those
    with a recognized ``status`` whose structure violates the contract —
    are re-synthesized as ``PARSE`` so the final envelope always carries
    a proper ``error`` mapping.
    """

    if not isinstance(last_envelope, Mapping):
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            "all providers failed",
            source=last_provider.source,
            retryable=True,
            scope=last_provider.scope,
        )

    status = last_envelope.get("status")
    if status == _ATTEMPT_STATUS_OK:
        classification = _classify_envelope(last_envelope, spec=spec)
        if classification == _ATTEMPT_STATUS_EMPTY:
            return fetcher_contract.make_empty(
                source=last_provider.source,
                as_of=None,
                scope=last_provider.scope,
                reason="no daily-K rows in window",
            )
        if classification == _ATTEMPT_STATUS_ERROR:
            # ``status=ok`` but data does not conform to the V1 normalized
            # schema (missing fields, bad rows, non-canonical identity,
            # duplicate/out-of-order dates, as_of mismatch, …). Re-synthesize
            # as PARSE so the caller always sees a contract-shaped envelope.
            return fetcher_contract.make_error_result(
                fetcher_contract.ERR_PARSE,
                "all providers failed",
                source=last_provider.source,
                retryable=False,
                scope=last_provider.scope,
            )
        # Should not happen — the loop would have returned success for a
        # conforming ok envelope. Defensively surface as UNKNOWN.
        return fetcher_contract.make_error_result(
            fetcher_contract.ERR_UNKNOWN,
            "all providers failed",
            source=last_provider.source,
            retryable=True,
            scope=last_provider.scope,
        )

    if status in {
        _ATTEMPT_STATUS_EMPTY,
        _ATTEMPT_STATUS_UNSUPPORTED,
        _ATTEMPT_STATUS_ERROR,
    }:
        if not _is_error_envelope_conform(last_envelope):
            # Malformed recognized status: e.g. ``{"status":"error","data":None,"error":None}``
            # or ``{"status":"empty","data":[]}`` without an error mapping.
            # Re-synthesize as PARSE so the caller always sees a proper
            # contract-shaped error envelope and provider internals don't leak.
            return fetcher_contract.make_error_result(
                fetcher_contract.ERR_PARSE,
                "all providers failed",
                source=last_provider.source,
                retryable=False,
                scope=last_provider.scope,
            )
        final = dict(last_envelope)
        # Always stamp the last attempted provider's source so envelope
        # provenance matches ``source_used is None`` semantics for the
        # all-failed path. The original envelope's ``source`` may have
        # pointed at a different provider (e.g. when a stubbed provider
        # returned a pre-built envelope), so we override it here.
        final["source"] = last_provider.source
        return final

    # Mapping but unrecognized shape → PARSE.
    return fetcher_contract.make_error_result(
        fetcher_contract.ERR_PARSE,
        "all providers failed",
        source=last_provider.source,
        retryable=False,
        scope=last_provider.scope,
    )


def fetch_global_daily_k_service(
    index_id: str,
    start_date: str,
    end_date: str,
    *,
    now: datetime | None = None,
    transport: Any = None,
    providers: Sequence[DailyKProvider] | None = None,
) -> dict[str, Any]:
    """Orchestrate a Daily-K fetch with ordered fallback providers.

    The contract is identical to :func:`fetch_global_daily_k` plus the
    following orchestration fields:

    * ``primary_source`` — provider name of the first configured provider,
    * ``fallback_sources`` — tuple of provider names after the primary,
    * ``source_used`` — name of the provider that produced the returned data
      (or ``None`` if every provider failed),
    * ``degraded`` — ``True`` only when a non-primary provider succeeded,
    * ``provider_status`` — ``"ok"`` if primary succeeded, ``"degraded"`` if a
      fallback succeeded, ``"failed"`` if every provider failed,
    * ``failure_reason`` — stable summary of the last failure, populated only
      when ``provider_status != "ok"``,
    * ``provider_attempts`` — ordered list with one entry per invocation.

    ``transport`` defaults to ``None`` which means "use V1's default
    transport" (the kwarg is omitted when forwarding to providers). Any
    explicit non-callable ``transport`` becomes caller ``VALIDATION`` before
    any provider or fallback is invoked.

    Unknown / non-canonical ``index_id`` values never reach any provider and
    return ``status=unsupported`` / ``status=error (VALIDATION)`` depending
    on the rejection path, matching V1.
    """

    if providers is None:
        providers = default_daily_k_providers(index_id)
    # Reject strings/bytes — both are Sequences but never valid provider
    # collections. ``isinstance(providers, Sequence)`` alone would silently
    # accept a string and then crash later with ``AttributeError`` on
    # ``provider.name``.
    if (
        isinstance(providers, (str, bytes))
        or not isinstance(providers, Sequence)
        or not providers
    ):
        raise ValueError(
            "providers must be a non-empty sequence of DailyKProvider descriptors"
        )
    validated_providers: list[DailyKProvider] = []
    for member in providers:
        if not isinstance(member, DailyKProvider):
            raise ValueError(
                "providers must contain only DailyKProvider descriptors"
            )
        validated_providers.append(member)
    providers = tuple(validated_providers)

    primary = providers[0]
    fallback_names = tuple(provider.name for provider in providers[1:])

    transport_was_supplied = transport is not None

    # Step 1: input validation (dates, now, transport) before registry lookup,
    # matching V1 precedence. Bad caller arguments never invoke any provider.
    validation_message = _validate_service_inputs(
        index_id, start_date, end_date, now, transport
    )
    if validation_message is not None:
        validation_envelope = fetcher_contract.make_error_result(
            fetcher_contract.ERR_VALIDATION,
            validation_message,
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )
        return _envelope_with_orchestration(
            validation_envelope,
            primary=primary,
            fallback_names=fallback_names,
            source_used=None,
            degraded=False,
            provider_status=_PROVIDER_STATUS_FAILED,
            failure_reason=validation_message,
            provider_attempts=(),
        )

    # Step 2: registry lookup. A syntactically valid unknown id returns
    # ``status=unsupported`` without invoking any provider.
    unsupported_envelope, bad_index_message, spec = _resolve_index(index_id)
    if unsupported_envelope is not None:
        message = (
            _envelope_error_message(unsupported_envelope)
            if isinstance(unsupported_envelope.get("error"), Mapping)
            else None
        )
        return _envelope_with_orchestration(
            unsupported_envelope,
            primary=primary,
            fallback_names=fallback_names,
            source_used=None,
            degraded=False,
            provider_status=_PROVIDER_STATUS_FAILED,
            failure_reason=message,
            provider_attempts=(),
        )
    if bad_index_message is not None:
        bad_envelope = fetcher_contract.make_error_result(
            fetcher_contract.ERR_VALIDATION,
            bad_index_message,
            source=TENCENT_SOURCE,
            retryable=False,
            scope=TENCENT_SCOPE,
        )
        return _envelope_with_orchestration(
            bad_envelope,
            primary=primary,
            fallback_names=fallback_names,
            source_used=None,
            degraded=False,
            provider_status=_PROVIDER_STATUS_FAILED,
            failure_reason=bad_index_message,
            provider_attempts=(),
        )

    # Step 3: walk providers. Any provider-callable exception is mapped to
    # the existing V1 taxonomy so it can trigger fallback consistently with
    # V1 envelopes; non-V1 envelopes that are well-formed are passed through
    # verbatim.
    attempts: list[dict[str, Any]] = []
    last_envelope: Any = None
    last_provider: DailyKProvider = primary
    # Track the earliest failed attempt envelope so a fallback-success
    # response can carry a deterministic ``failure_reason`` derived from
    # the primary failure (per the contract: fallback success must retain
    # the primary failure reason).
    first_failure_envelope: Any = None

    for index, provider in enumerate(providers):
        try:
            if transport_was_supplied:
                envelope = provider.fetch(
                    index_id,
                    start_date,
                    end_date,
                    transport=transport,
                    now=now,
                )
            else:
                # Omit the kwarg so V1 (and any provider with the same
                # default) falls back to its default transport.
                envelope = provider.fetch(
                    index_id,
                    start_date,
                    end_date,
                    now=now,
                )
        except Exception as exc:  # noqa: BLE001 — boundary guard by design
            envelope = _classify_provider_exception(exc, provider=provider)

        attempts.append(
            _build_attempt(provider=provider, envelope=envelope, index=index, spec=spec)
        )
        last_envelope = envelope
        last_provider = provider
        status = _classify_envelope(envelope, spec=spec)

        if status == _ATTEMPT_STATUS_OK:
            rewritten = _rewrite_source(envelope, provider=provider)
            is_fallback = index > 0
            if is_fallback and first_failure_envelope is not None:
                # Fallback success: synthesize the earliest failed attempt
                # (the primary, when present) to a contract-shaped envelope
                # using its own provider's source/scope, then derive a
                # stable failure_reason (e.g. ``NET_TIMEOUT: ...``). The
                # final envelope remains ``status=ok`` and ``degraded=True``.
                first_provider = providers[0]
                first_failure_synthesized = _synthesize_final_envelope(
                    first_provider, first_failure_envelope
                )
                failure_reason_value = _build_failure_reason(
                    first_failure_synthesized
                )
            else:
                failure_reason_value = None
            return _envelope_with_orchestration(
                rewritten,
                primary=primary,
                fallback_names=fallback_names,
                source_used=provider.name,
                degraded=is_fallback,
                provider_status=(
                    _PROVIDER_STATUS_DEGRADED
                    if is_fallback
                    else _PROVIDER_STATUS_OK
                ),
                failure_reason=failure_reason_value,
                provider_attempts=tuple(attempts),
            )

        # Record the earliest failed attempt so a later fallback success
        # can carry its deterministic failure_reason. The primary's
        # envelope is preferred — but if the primary somehow returned
        # ``ok`` (which the loop would have caught above), fall back to
        # the most recent failed attempt.
        if first_failure_envelope is None:
            first_failure_envelope = envelope

        # Continue walking the fallback chain only while a next provider exists.
        # Any non-ok status (empty / error / unsupported / malformed /
        # ok+empty) triggers fallback to the next provider per the contract.
        if index + 1 >= len(providers):
            break

    # Every provider failed. Synthesize a contract-shaped envelope using the
    # LAST attempted provider's source so consumers always see a fetcher
    # envelope with status/data/error fields.
    final_envelope = _synthesize_final_envelope(
        last_provider, last_envelope, spec=spec
    )
    failure_reason = _build_failure_reason(final_envelope)

    return _envelope_with_orchestration(
        final_envelope,
        primary=primary,
        fallback_names=fallback_names,
        source_used=None,
        degraded=False,
        provider_status=_PROVIDER_STATUS_FAILED,
        failure_reason=failure_reason,
        provider_attempts=tuple(attempts),
    )


__all__ = [
    "DailyKProvider",
    "default_daily_k_providers",
    "fetch_global_daily_k_service",
    "tencent_daily_k_provider",
]
