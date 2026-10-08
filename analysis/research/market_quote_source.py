"""Injected index quote-source boundary for the Research Engine (S3).

This module is the slice that turns a *declared* index universe into a
*transport call with a validated target*, and turns whatever the transport hands
back into the existing :mod:`analysis.fetcher_contract` result shape. It is a
boundary, not a data source.

What this module deliberately does **not** do
--------------------------------------------

* **No I/O on import or construction.** The module imports no network client, no
  HTTP library, no clock, and no calendar, and it defines no endpoint or
  registry. :class:`MarketIndexQuoteSource` cannot reach anything until a caller
  hands it a transport.
* **No default transport.** :class:`MarketIndexQuoteSource` requires both an
  explicit :class:`~analysis.research.market_index_universe.MarketIndexUniverse`
  and an explicit callable. There is no fallback client, no provider registry
  lookup, and no "if no transport then fetch it myself" branch.
* **No second status vocabulary.** The four states and the error codes are
  imported from :mod:`analysis.fetcher_contract` and re-used verbatim. This
  module never defines its own enum, never renames a state, and never maps a
  provider's ad-hoc shape onto a private status string.
* **No quote-bar schema and no evidence aggregation.** ``data`` travels
  through opaquely. This module does not know what a bar is, does not validate
  OHLC fields, and does not build
  :class:`~analysis.research.market_evidence.MarketEvidence` records. Turning
  opaque payload into evidence is a later slice.
* **No clock, no freshness, no market state, no PIT, no availability roll-up.**
  Time arrives as an explicit
  :class:`~analysis.research.time_semantics.TimeMetadata` and is copied verbatim.
  ``data_as_of`` is never derived from ``fetched_at`` and vice versa, and
  ``data_as_of=None`` stays ``None`` rather than being back-filled.

Three code spaces stay separate, and none is derived from another
----------------------------------------------------------------

* :class:`~analysis.research.index_registry.IndexIdentity.index_id` -- the
  engine's own stable id;
* :class:`~analysis.research.index_symbols.IndexProviderSymbolAlias.provider_symbol`
  -- the provider's symbol for that index;
* :class:`~analysis.research.providers.ProviderSpec.provider_id` -- who is asked.

A caller asking for provider ``tencent`` for index ``csi.300`` gets
``unsupported``, because this repository declares no tencent symbol for
``csi.300``. Guessing, normalizing, case-folding, or falling back to another
provider's symbol would be a fabrication, so the module refuses instead.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable, Mapping, Optional

from analysis.fetcher_contract import (
    ERR_UNKNOWN,
    ERR_UNSUPPORTED,
    ERR_VALIDATION,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    VALID_STATUSES,
    make_error,
    make_result,
)
from analysis.research.index_registry import IndexIdentity
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_index_universe import MarketIndexUniverse
from analysis.research.providers import ProviderSpec
from analysis.research.time_semantics import TimeMetadata

# The fetcher contract's scope vocabulary, not a new one. Quote rows are market
# scope; this module does not extend the vocabulary with a "quote" scope.
SCOPE_MARKET = "market"

_EMPTY_REASON = "transport reported an empty result without an error object"


class MarketQuoteRequestError(ValueError):
    """Raised when a quote request violates the identity/provider/alias contract.

    This is a caller mistake, not a provider failure, so it propagates instead of
    being converted into an error envelope. In particular it is raised *before*
    any transport call happens.
    """


@dataclass(frozen=True)
class MarketQuoteRequest:
    """One fully resolved, transport-ready quote request.

    The four values are kept as distinct, separately typed fields on purpose:
    collapsing them would let a provider symbol be mistaken for an index id, or a
    provider id for a publisher, and that conflation is exactly what this
    codebase keeps refusing.
    """

    identity: IndexIdentity
    provider: ProviderSpec
    alias: IndexProviderSymbolAlias
    time: TimeMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.identity, IndexIdentity):
            raise TypeError("identity must be IndexIdentity")
        if not isinstance(self.provider, ProviderSpec):
            raise TypeError("provider must be ProviderSpec")
        if not isinstance(self.alias, IndexProviderSymbolAlias):
            raise TypeError("alias must be IndexProviderSymbolAlias")
        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")

        # The alias must describe the very index that was resolved, and it must
        # name the very provider the caller asked for. Both are cross-object
        # invariants that no single dataclass can enforce on its own.
        if self.alias.index_id != self.identity.index_id:
            raise MarketQuoteRequestError(
                "alias index must match identity index: "
                f"{self.alias.index_id!r} != {self.identity.index_id!r}"
            )
        if self.provider.provider_id != self.alias.provider_id:
            raise MarketQuoteRequestError(
                "alias provider must match requested provider: "
                f"{self.alias.provider_id!r} != {self.provider.provider_id!r}"
            )

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small request surface."""

        return tuple(field.name for field in fields(cls))


@dataclass(frozen=True)
class MarketQuoteEnvelope:
    """Provenance of one quote call: what was asked, and what came back.

    The canonical fetcher ``result`` is stored beside the inputs instead of
    replacing them. A consumer can therefore tell *which* index was quoted, under
    *which* provider symbol, at *which* two separate clocks, and only then look
    at the payload.

    ``alias`` is ``None`` only when the declared universe has no alias matching
    the requested provider. That is a real, reportable state, so it is modelled
    as absence rather than as a placeholder symbol.
    """

    identity: IndexIdentity
    provider: ProviderSpec
    alias: Optional[IndexProviderSymbolAlias]
    time: TimeMetadata
    result: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, IndexIdentity):
            raise TypeError("identity must be IndexIdentity")
        if not isinstance(self.provider, ProviderSpec):
            raise TypeError("provider must be ProviderSpec")
        if not isinstance(self.time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")
        if not isinstance(self.result, dict):
            raise TypeError("result must be a fetcher-contract result dict")
        if self.alias is not None and not isinstance(
            self.alias, IndexProviderSymbolAlias
        ):
            raise TypeError("alias must be IndexProviderSymbolAlias or None")
        if self.alias is not None:
            if self.alias.index_id != self.identity.index_id:
                raise MarketQuoteRequestError("alias index must match identity index")
            if self.provider.provider_id != self.alias.provider_id:
                raise MarketQuoteRequestError(
                    "alias provider must match requested provider"
                )

    @property
    def is_unsupported(self) -> bool:
        """True when the declared universe cannot serve this provider."""

        return self.result["status"] == STATUS_UNSUPPORTED

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small envelope surface."""

        return tuple(field.name for field in fields(cls))


QuoteTransport = Callable[[MarketQuoteRequest], Mapping[str, Any]]


class MarketIndexQuoteSource:
    """Quote boundary over an explicitly injected universe and transport.

    The constructor takes exactly two arguments and offers no default for
    either. A caller that has not decided *which* indexes are in scope, and
    *who* will be asked, cannot construct this object -- which is how the module
    stays free of a hidden provider registry or a hidden HTTP client.
    """

    def __init__(self, *, universe: MarketIndexUniverse, transport: QuoteTransport):
        if not isinstance(universe, MarketIndexUniverse):
            raise TypeError("universe must be MarketIndexUniverse")
        if not callable(transport):
            raise TypeError("transport must be callable")
        self._universe = universe
        self._transport = transport

    def fetch(
        self,
        index_id: str,
        *,
        provider: ProviderSpec,
        time: TimeMetadata,
    ) -> MarketQuoteEnvelope:
        """Resolve one index/provider pair and call the transport exactly once.

        Order of operations, and the reason for it:

        1. ``universe.require_index`` -- an index outside the declared universe
           raises :class:`KeyError` here, before any transport exists in the
           call path.
        2. The ``provider``/``time`` types are checked, still before the
           transport exists in the call path, so a caller mistake can never be
           reported as a provider-level ``unsupported`` state.
        3. ``universe.aliases_for`` and an exact ``provider_id`` comparison --
           a covered index with no declared alias for this provider returns
           ``unsupported`` without calling the transport.
        4. :class:`MarketQuoteRequest` construction validates the
           identity/provider/alias/time quadruple.
        5. Only then is the transport called, exactly once.
        """

        identity = self._universe.require_index(index_id)
        self._require_typed_call_arguments(provider=provider, time=time)
        alias = self._select_alias(index_id, provider)

        if alias is None:
            return self._unsupported_envelope(
                identity=identity, provider=provider, time=time
            )

        request = MarketQuoteRequest(
            identity=identity, provider=provider, alias=alias, time=time
        )

        try:
            raw = self._transport(request)
        except Exception as exc:  # transport failures are data, not crashes
            result = self._canonical(
                status=STATUS_ERROR,
                data=None,
                error=make_error(
                    ERR_UNKNOWN,
                    f"transport raised {type(exc).__name__} for {request.alias.provider_symbol!r}",
                ),
                provider=provider,
                time=time,
            )
        else:
            result = self._normalize(raw, provider=provider, time=time)

        return MarketQuoteEnvelope(
            identity=identity, provider=provider, alias=alias, time=time, result=result
        )

    @staticmethod
    def _require_typed_call_arguments(
        *, provider: ProviderSpec, time: TimeMetadata
    ) -> None:
        """Reject a mistyped provider or time before any state is derived.

        Both values are only ever used as attribute carriers further down
        (``provider.provider_id`` during alias selection, ``time.data_as_of``
        when the result is built). Without this gate a caller mistake would
        escape as an ``AttributeError`` from deep inside alias lookup -- or,
        worse, would never be detected at all for an index that has no alias
        for that provider, because then ``provider.provider_id`` is only read
        while formatting a message. Both readings are wrong: a caller mistake
        is a :class:`TypeError`, raised here, with the transport untouched.
        """

        if not isinstance(provider, ProviderSpec):
            raise TypeError("provider must be ProviderSpec")
        if not isinstance(time, TimeMetadata):
            raise TypeError("time must be TimeMetadata")

    def _select_alias(
        self,
        index_id: str,
        provider: ProviderSpec,
    ) -> Optional[IndexProviderSymbolAlias]:
        """Return the exact provider match, or ``None`` when none is declared.

        Matching is a string equality test on ``provider_id``. Nothing is
        case-folded, trimmed, suffixed, or otherwise normalized, and the search
        never leaves the requested index.
        """

        for candidate in self._universe.aliases_for(index_id):
            if candidate.provider_id == provider.provider_id:
                return candidate
        return None

    def _unsupported_envelope(
        self,
        *,
        identity: IndexIdentity,
        provider: ProviderSpec,
        time: TimeMetadata,
    ) -> MarketQuoteEnvelope:
        """Report a declared-but-absent provider mapping, without calling out."""

        result = self._canonical(
            status=STATUS_UNSUPPORTED,
            data=None,
            error=make_error(
                ERR_UNSUPPORTED,
                f"no declared provider symbol for {identity.index_id!r} "
                f"on provider {provider.provider_id!r}",
                retryable=False,
            ),
            provider=provider,
            time=time,
        )
        return MarketQuoteEnvelope(
            identity=identity, provider=provider, alias=None, time=time, result=result
        )

    def _normalize(
        self,
        raw: Any,
        *,
        provider: ProviderSpec,
        time: TimeMetadata,
    ) -> dict[str, Any]:
        """Rebuild a transport payload into a canonical fetcher result.

        Anything this method cannot prove to be a valid status/data/error
        combination becomes a canonical ``error`` with
        :data:`~analysis.fetcher_contract.ERR_VALIDATION`. Malformed data is
        therefore never promoted to ``ok``.
        """

        if not isinstance(raw, Mapping):
            return self._reject(
                f"transport must return a mapping, got {type(raw).__name__}",
                provider=provider,
                time=time,
            )

        status = raw.get("status")
        # The isinstance guard matters: an unhashable status (a list, say) would
        # raise out of the ``in`` test below instead of being rejected.
        if not isinstance(status, str) or status not in VALID_STATUSES:
            return self._reject(
                f"transport status is not a fetcher-contract state: {status!r}",
                provider=provider,
                time=time,
            )

        units, units_problem = _validated_units(raw.get("units"))
        if units_problem is not None:
            return self._reject(units_problem, provider=provider, time=time)

        error, error_problem = _validated_error(raw.get("error"))
        if error_problem is not None:
            return self._reject(error_problem, provider=provider, time=time)

        data = raw.get("data")

        if status == STATUS_OK:
            if error is not None:
                return self._reject(
                    "ok must not carry an error object", provider=provider, time=time
                )
            if data is None:
                return self._reject(
                    "ok requires data; absent data is empty or error, never ok",
                    provider=provider,
                    time=time,
                )
            return self._canonical(
                status=STATUS_OK, data=data, error=None,
                units=units, provider=provider, time=time,
            )

        if status == STATUS_EMPTY:
            if data is not None:
                return self._reject(
                    "empty must not carry data", provider=provider, time=time
                )
            return self._canonical(
                status=STATUS_EMPTY,
                data=None,
                error=error
                or make_error(ERR_VALIDATION, _EMPTY_REASON, retryable=False),
                units=units,
                provider=provider,
                time=time,
            )

        if status == STATUS_ERROR:
            if data is not None:
                return self._reject(
                    "error must not carry data", provider=provider, time=time
                )
            if error is None:
                return self._reject(
                    "error requires an error object", provider=provider, time=time
                )
            return self._canonical(
                status=STATUS_ERROR, data=None, error=error,
                units=units, provider=provider, time=time,
            )

        # STATUS_UNSUPPORTED: the only remaining valid state.
        if data is not None:
            return self._reject(
                "unsupported must not carry data", provider=provider, time=time
            )
        if error is None or error["code"] != ERR_UNSUPPORTED:
            return self._reject(
                "unsupported requires an ERR_UNSUPPORTED error object",
                provider=provider,
                time=time,
            )
        return self._canonical(
            status=STATUS_UNSUPPORTED, data=None, error=error,
            units=units, provider=provider, time=time,
        )

    def _reject(
        self,
        message: str,
        *,
        provider: ProviderSpec,
        time: TimeMetadata,
    ) -> dict[str, Any]:
        """Build the single canonical rejection result."""

        return self._canonical(
            status=STATUS_ERROR,
            data=None,
            error=make_error(ERR_VALIDATION, message, retryable=False),
            provider=provider,
            time=time,
        )

    @staticmethod
    def _canonical(
        *,
        status: str,
        data: Any,
        error: Optional[dict[str, Any]],
        provider: ProviderSpec,
        time: TimeMetadata,
        units: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Rebuild one result with fixed scope/source and verbatim clocks.

        ``fetched_at`` is always passed explicitly, so the contract helper never
        falls back to its wall-clock default. ``data_as_of`` is copied as given
        and is never synthesized from ``fetched_at``.
        """

        return make_result(
            status=status,
            data=data,
            source=provider.provider_id,
            as_of=time.data_as_of,
            fetched_at=time.fetched_at,
            scope=SCOPE_MARKET,
            units=units,
            error=error,
        )


def _validated_units(
    raw_units: Any,
) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """Return ``(units, problem)``; a non-``None`` problem rejects the payload."""

    if raw_units is None:
        return None, None
    if not isinstance(raw_units, Mapping):
        return None, (
            f"transport units must be a mapping or absent, got {type(raw_units).__name__}"
        )

    units: dict[str, str] = {}
    for key, value in raw_units.items():
        if not isinstance(key, str) or not key:
            return None, "transport unit names must be non-empty strings"
        if not isinstance(value, str) or not value:
            return None, "transport unit values must be non-empty strings"
        units[key] = value
    return units, None


def _validated_error(
    raw_error: Any,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Return ``(error, problem)``; a non-``None`` problem rejects the payload.

    An error object is accepted only when it matches what
    :func:`~analysis.fetcher_contract.make_error` actually produces: a non-blank
    ``code``, a non-blank string ``message``, and an actual ``bool``
    ``retryable``. All three are *required*. Treating an absent field as a
    weaker form of valid would let ``make_error``'s defaults silently invent a
    ``retryable=True`` for a failure the provider never declared as retryable,
    and would invent a default code for one it never named.

    An accepted object is rebuilt through ``make_error`` rather than copied, so
    the canonical result carries exactly ``code``/``message``/``retryable`` and
    never forwards an ad-hoc extension field a provider attached to its own
    payload.
    """

    if raw_error is None:
        return None, None
    if not isinstance(raw_error, Mapping):
        return None, (
            f"transport error must be an error object or absent, got "
            f"{type(raw_error).__name__}"
        )

    code = raw_error.get("code")
    if not isinstance(code, str) or not code.strip():
        return None, "transport error must carry a non-blank code"

    message = raw_error.get("message")
    if not isinstance(message, str) or not message.strip():
        return None, "transport error must carry a non-blank string message"

    retryable = raw_error.get("retryable")
    if not isinstance(retryable, bool):
        return None, "transport error must carry a bool retryable"

    return make_error(code, message, retryable=retryable), None
