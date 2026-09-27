"""Frozen V1 registry for global indices covered by the daily-K fetcher.

This module is intentionally narrow. It defines the small, fixed V1 universe of
indices whose daily bars are available from the Tencent endpoint, the market /
display / currency / timezone context attached to each, and the lookup helpers
used by :mod:`analysis.research.global_daily_k`.

It deliberately does not:

* fetch data,
* infer publisher or local code from a bare provider symbol,
* wire into the legacy V3 pipeline,
* model constituents, weights, valuation, taxonomy, or quote fields,
* treat the listed set as a global claim — Nikkei and every other non-listed
  index are explicitly unsupported (not silently inferred),
* silently lowercase arbitrary caller input to resolve it as an
  ``index_id``. A wrong casing of a *registered* canonical id is rejected
  as ``VALIDATION``; any other unknown / unqualified symbol (mixed-case
  provider symbols like ``"us.INX"`` or short names like ``"N225"``) is
  rejected as ``UNSUPPORTED``. Bare-code inference is not allowed either
  way.

Adding more indices later is additive: extend ``_GLOBAL_INDEX_SPECS`` and the
``build_global_index_symbol_registry`` mapping in lockstep, without changing
the public dataclass surface.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Iterable, Mapping

from .index_registry import IndexIdentity, IndexPublisher
from .index_symbols import (
    IndexProviderSymbolAlias,
    IndexProviderSymbolRegistry,
)

# IANA timezone tokens for the local exchange calendars the V1 set covers.
_TZ_ASIA_SHANGHAI = "Asia/Shanghai"
_TZ_ASIA_HONG_KONG = "Asia/Hong_Kong"
_TZ_AMERICA_NEW_YORK = "America/New_York"

# Market context tokens used in result records and metadata.
_MARKET_CN = "cn"
_MARKET_HK = "hk"
_MARKET_US = "us"

# ISO-4217 currency tokens for the V1 universe.
_CURRENCY_CNY = "CNY"
_CURRENCY_HKD = "HKD"
_CURRENCY_USD = "USD"

# Province / region tokens used as the ``region`` context on the spec.
_REGION_ASIA = "Asia"
_REGION_AMERICA = "America"

# City tokens used as the ``locality`` context on the spec.
_LOCALITY_SHANGHAI = "Shanghai"
_LOCALITY_HONG_KONG = "Hong_Kong"
_LOCALITY_NEW_YORK = "New_York"


@dataclass(frozen=True)
class GlobalIndexSpec:
    """Immutable spec for one V1-supported global index.

    ``identity`` is the existing :class:`IndexIdentity`. The remaining fields
    are *context* (not identity) and describe the market, currency, and
    trading timezone associated with the daily-K bar series. ``provider_symbol``
    is the exact Tencent endpoint symbol; it is part of the provider-symbol
    mapping in :mod:`analysis.research.index_symbols` and is surfaced here so
    callers do not have to touch the registry directly.
    """

    identity: IndexIdentity
    market: str
    name: str
    currency: str
    timezone: str
    provider_symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, IndexIdentity):
            raise TypeError("identity must be an IndexIdentity")

        if not isinstance(self.market, str) or not self.market.strip():
            raise ValueError("market must be a non-empty string")
        if self.market != self.market.strip().lower():
            raise ValueError("market must use canonical lowercase form")

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")

        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency must be a non-empty string")
        if self.currency != self.currency.strip().upper():
            raise ValueError("currency must use canonical uppercase ISO-4217 form")

        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty string")
        if self.timezone != self.timezone.strip():
            raise ValueError("timezone must not contain surrounding whitespace")

        if not isinstance(self.provider_symbol, str) or not self.provider_symbol:
            raise ValueError("provider_symbol must be a non-empty string")
        if self.provider_symbol != self.provider_symbol.strip():
            raise ValueError("provider_symbol must not contain surrounding whitespace")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small V1 global-index spec surface."""

        return tuple(field.name for field in fields(cls))


# The fixed V1 universe. Controller live-probed these nine indices on
# 2026-09-27 Asia/Shanghai using the Tencent endpoint; each returned 18-19
# bars for the September 1-25 window. Single probe is availability evidence,
# not an SLA. Nikkei and all other symbols are explicitly unsupported.
_GLOBAL_INDEX_SPECS: tuple[GlobalIndexSpec, ...] = (
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="cn.index.sse.000001",
            publisher=IndexPublisher.SSE,
            local_code="000001",
        ),
        market=_MARKET_CN,
        name="上证指数",
        currency=_CURRENCY_CNY,
        timezone=_TZ_ASIA_SHANGHAI,
        provider_symbol="sh000001",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="cn.index.szse.399001",
            publisher=IndexPublisher.SZSE,
            local_code="399001",
        ),
        market=_MARKET_CN,
        name="深证成指",
        currency=_CURRENCY_CNY,
        timezone=_TZ_ASIA_SHANGHAI,
        provider_symbol="sz399001",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="cn.index.szse.399006",
            publisher=IndexPublisher.SZSE,
            local_code="399006",
        ),
        market=_MARKET_CN,
        name="创业板指",
        currency=_CURRENCY_CNY,
        timezone=_TZ_ASIA_SHANGHAI,
        provider_symbol="sz399006",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="cn.index.csi.000300",
            publisher=IndexPublisher.CSI,
            local_code="000300",
        ),
        market=_MARKET_CN,
        name="沪深300",
        currency=_CURRENCY_CNY,
        timezone=_TZ_ASIA_SHANGHAI,
        provider_symbol="sh000300",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="hk.index.hang_seng.hsi",
            publisher=IndexPublisher.HANG_SENG,
            local_code="HSI",
        ),
        market=_MARKET_HK,
        name="恒生指数",
        currency=_CURRENCY_HKD,
        timezone=_TZ_ASIA_HONG_KONG,
        provider_symbol="hkHSI",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="hk.index.hang_seng.hstech",
            publisher=IndexPublisher.HANG_SENG,
            local_code="HSTECH",
        ),
        market=_MARKET_HK,
        name="恒生科技指数",
        currency=_CURRENCY_HKD,
        timezone=_TZ_ASIA_HONG_KONG,
        provider_symbol="hkHSTECH",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="us.index.sp_dji.sp500",
            publisher=IndexPublisher.SP_DJI,
            local_code="SP500",
        ),
        market=_MARKET_US,
        name="S&P 500",
        currency=_CURRENCY_USD,
        timezone=_TZ_AMERICA_NEW_YORK,
        provider_symbol="us.INX",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="us.index.nasdaq.composite",
            publisher=IndexPublisher.NASDAQ,
            local_code="IXIC",
        ),
        market=_MARKET_US,
        name="Nasdaq Composite",
        currency=_CURRENCY_USD,
        timezone=_TZ_AMERICA_NEW_YORK,
        provider_symbol="us.IXIC",
    ),
    GlobalIndexSpec(
        identity=IndexIdentity(
            index_id="us.index.sp_dji.djia",
            publisher=IndexPublisher.SP_DJI,
            local_code="DJI",
        ),
        market=_MARKET_US,
        name="Dow Jones Industrial Average",
        currency=_CURRENCY_USD,
        timezone=_TZ_AMERICA_NEW_YORK,
        provider_symbol="us.DJI",
    ),
)


def _build_default_aliases() -> tuple[IndexProviderSymbolAlias, ...]:
    """Translate every V1 spec into one Tencent provider-symbol alias.

    The Tencent endpoint is the only V1 provider for these indices; the
    resulting registry therefore contains exactly one alias per index.
    """

    return tuple(
        IndexProviderSymbolAlias(
            index_id=spec.identity.index_id,
            provider_id="tencent",
            provider_symbol=spec.provider_symbol,
        )
        for spec in _GLOBAL_INDEX_SPECS
    )


def list_global_indices() -> tuple[GlobalIndexSpec, ...]:
    """Return the V1-supported global-index specs in registration order."""

    return _GLOBAL_INDEX_SPECS


def get_global_index(index_id: str) -> GlobalIndexSpec:
    """Return the spec for ``index_id`` or raise if it is unknown / non-canonical.

    Two distinct rejection paths exist so callers can tell *bad casing of a
    known id* apart from *unknown / unqualified symbols*:

    * ``ValueError`` (mapped to ``VALIDATION`` by the fetcher) — the
      ``index_id`` lowercases to one of the nine canonical V1 ids in
      :data:`_GLOBAL_INDEX_SPECS` but the caller passed a non-canonical
      casing. The fetcher contract treats this as a malformed input, not
      as a "we don't know that one" answer, because the caller was clearly
      trying to address a known index and just got the case wrong.
    * ``KeyError`` (mapped to ``UNSUPPORTED`` by the fetcher) — the
      ``index_id`` is not in the V1 set, including bare provider symbols
      like ``"sh000001"`` / ``"us.INX"``, short names like ``"N225"``,
      and any other unknown token. Bare-code inference is intentionally
      not allowed; nothing here silently lowercases arbitrary input to
      make it match a spec.

    The lowercase check is the only shape gate — there is no regex pre-
    filter. ``"^GSPC"`` (a Yahoo-style decorator) is therefore rejected as
    ``KeyError``/``UNSUPPORTED``, not ``VALIDATION``, because no registered
    id lowercases to ``"^gspc"``.
    """

    if not isinstance(index_id, str):
        raise TypeError("index_id must be a string")
    canonical = index_id.strip()
    if not canonical:
        raise ValueError("index_id must not be empty")

    if canonical != canonical.lower():
        # Wrong casing. Check whether the lowercase form matches a registered
        # id: if it does, the caller is addressing a known index with bad
        # casing (VALIDATION); if it does not, the symbol is unqualified and
        # therefore unsupported. This keeps "uppercase canonical id" distinct
        # from "unknown / raw provider symbol / short name".
        for spec in _GLOBAL_INDEX_SPECS:
            if spec.identity.index_id == canonical.lower():
                raise ValueError("index_id must use canonical lowercase form")
        raise KeyError(f"unknown global index id: {index_id!r}")

    for spec in _GLOBAL_INDEX_SPECS:
        if spec.identity.index_id == canonical:
            return spec
    raise KeyError(f"unknown global index id: {index_id!r}")


def build_global_index_symbol_registry(
    aliases: Iterable[IndexProviderSymbolAlias] = (),
) -> IndexProviderSymbolRegistry:
    """Build an :class:`IndexProviderSymbolRegistry` for the V1 universe.

    ``aliases`` is appended to the default V1 set, allowing tests to extend
    the registry without mutating the production mapping. Each supplied alias
    must target one of the V1 ``index_id`` values; otherwise registration will
    raise via the underlying registry collision / canonical checks.
    """

    extras: list[IndexProviderSymbolAlias] = []
    extras.extend(aliases)
    return IndexProviderSymbolRegistry(_build_default_aliases() + tuple(extras))


# Friendly, read-only view of the static metadata that callers (docs, tests)
# may want to assert against without rebuilding the spec list themselves.
GLOBAL_INDEX_MARKETS: Mapping[str, str] = {
    spec.identity.index_id: spec.market for spec in _GLOBAL_INDEX_SPECS
}
GLOBAL_INDEX_CURRENCIES: Mapping[str, str] = {
    spec.identity.index_id: spec.currency for spec in _GLOBAL_INDEX_SPECS
}
GLOBAL_INDEX_TIMEZONES: Mapping[str, str] = {
    spec.identity.index_id: spec.timezone for spec in _GLOBAL_INDEX_SPECS
}
GLOBAL_INDEX_PROVIDER_SYMBOLS: Mapping[str, str] = {
    spec.identity.index_id: spec.provider_symbol for spec in _GLOBAL_INDEX_SPECS
}
GLOBAL_INDEX_NAMES: Mapping[str, str] = {
    spec.identity.index_id: spec.name for spec in _GLOBAL_INDEX_SPECS
}
