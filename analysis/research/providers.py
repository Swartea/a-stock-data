"""Canonical data-provider identities for the Research Engine.

This module answers only *who supplied the data*.

It deliberately does not model capabilities, endpoints, URLs, priorities,
health, freshness, or fallback order.  Those belong to later Research Engine
layers (A1 capability registry and the data envelope / quality contracts).

Legacy fetchers currently expose heterogeneous ``source`` strings.  Those
strings must remain untouched for compatibility; callers may resolve known
provider aliases through this registry without rewriting the legacy payload.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import re
from typing import Iterable, Optional


_PROVIDER_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ProviderSpec:
    """Stable provider identity independent from endpoint/capability details."""

    provider_id: str
    display_name: str
    provider_family: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "provider_family"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            if value != value.strip().lower() or not _PROVIDER_TOKEN_RE.fullmatch(value):
                raise ValueError(
                    f"{field_name} must be a lowercase stable token: {value!r}"
                )

        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string")

        if not isinstance(self.aliases, tuple):
            raise TypeError("aliases must be a tuple")

        seen = {self.provider_id}
        for alias in self.aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("provider aliases must be non-empty strings")
            key = alias.strip().lower()
            if key in seen:
                raise ValueError(f"duplicate provider alias: {alias!r}")
            seen.add(key)

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small A2 wire/identity surface."""
        return tuple(field.name for field in fields(cls))


class ProviderRegistry:
    """Resolve canonical provider identities and aliases deterministically."""

    def __init__(self, providers: Iterable[ProviderSpec] = ()) -> None:
        self._providers: dict[str, ProviderSpec] = {}
        self._lookup: dict[str, str] = {}
        for provider in providers:
            self.register(provider)

    @staticmethod
    def _lookup_key(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("provider lookup value must be a string")
        key = value.strip().lower()
        if not key:
            raise ValueError("provider lookup value must not be blank")
        return key

    def register(self, provider: ProviderSpec) -> ProviderSpec:
        """Register one provider, rejecting canonical-id and alias collisions."""
        if not isinstance(provider, ProviderSpec):
            raise TypeError("provider must be a ProviderSpec")

        keys = (provider.provider_id, *provider.aliases)
        normalized = tuple(self._lookup_key(key) for key in keys)
        for key in normalized:
            existing = self._lookup.get(key)
            if existing is not None:
                raise ValueError(
                    f"provider identity collision for {key!r}: already owned by {existing!r}"
                )

        self._providers[provider.provider_id] = provider
        for key in normalized:
            self._lookup[key] = provider.provider_id
        return provider

    def resolve(self, value: str) -> Optional[ProviderSpec]:
        """Resolve a canonical id or known alias; unknown values stay unknown."""
        provider_id = self._lookup.get(self._lookup_key(value))
        if provider_id is None:
            return None
        return self._providers[provider_id]

    def require(self, value: str) -> ProviderSpec:
        """Resolve a provider or raise ``KeyError`` for an unknown identity."""
        provider = self.resolve(value)
        if provider is None:
            raise KeyError(f"unknown provider: {value!r}")
        return provider

    def all(self) -> tuple[ProviderSpec, ...]:
        """Return providers in registration order as an immutable snapshot."""
        return tuple(self._providers.values())


# Initial catalog: identities already present in the current data/report stack,
# plus official providers explicitly planned for the Research Engine reference
# layers.  Adding another provider later is additive; tests do not freeze the
# catalog length.
DEFAULT_PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec("eastmoney", "东方财富", "eastmoney", ("em", "东方财富")),
    ProviderSpec("cninfo", "巨潮资讯", "cninfo", ("巨潮", "巨潮资讯")),
    ProviderSpec("ths", "同花顺", "hexin", ("10jqka", "同花顺")),
    ProviderSpec("iwencai", "i问财", "hexin", ("问财", "i问财")),
    ProviderSpec("sina", "新浪财经", "sina", ("新浪", "新浪财经")),
    ProviderSpec("tencent", "腾讯财经", "tencent", ("腾讯", "腾讯财经")),
    ProviderSpec("baostock", "Baostock", "baostock", ("bao_stock",)),
    ProviderSpec("mootdx", "mootdx", "mootdx", ("tdx", "通达信")),
    ProviderSpec("swsresearch", "申万研究", "swsresearch", ("申万", "申万研究")),
    ProviderSpec("cls", "财联社", "cls", ("财联社",)),
    ProviderSpec("baidu", "百度财经", "baidu", ("百度", "百度财经")),
    ProviderSpec("sse", "上海证券交易所", "sse", ("上交所",)),
    ProviderSpec("szse", "深圳证券交易所", "szse", ("深交所",)),
    ProviderSpec("bse", "北京证券交易所", "bse", ("北交所",)),
    ProviderSpec("hkex", "香港交易所", "hkex", ("港交所",)),
    ProviderSpec("csi", "中证指数", "csi", ("中证", "中证指数")),
    ProviderSpec("cni", "国证指数", "cni", ("国证", "国证指数")),
    ProviderSpec("pboc", "中国人民银行", "pboc", ("人民银行", "央行")),
    ProviderSpec("nbs", "国家统计局", "nbs", ("统计局", "国家统计局")),
)


def build_default_provider_registry() -> ProviderRegistry:
    """Build a fresh registry so tests/callers never share mutable state."""
    return ProviderRegistry(DEFAULT_PROVIDER_SPECS)
