"""Semantic data-capability identities for the Research Engine.

A capability answers *what data can be requested* independently from *who*
provides it or *how* it is fetched.  Provider identity belongs to A2; endpoint
URLs, concrete fetcher functions, fallback order, health, freshness, and PIT
rules belong to later layers.

Capability ids are intentionally semantic rather than endpoint-shaped.  For
example, ``stock.news`` remains stable even if its implementation moves from
one provider or endpoint family to another.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Iterable, Optional

_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_CAPABILITY_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9_]*(?:\.[a-z0-9][a-z0-9_]*)+$"
)


@dataclass(frozen=True)
class CapabilitySpec:
    """Stable semantic identity for one requestable dataset/capability."""

    capability_id: str
    display_name: str
    domain: str
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string")
        if (
            self.capability_id != self.capability_id.strip().lower()
            or not _CAPABILITY_ID_RE.fullmatch(self.capability_id)
        ):
            raise ValueError(
                "capability_id must be a lowercase namespaced token such as "
                "'stock.news'"
            )

        if not isinstance(self.domain, str) or not self.domain.strip():
            raise ValueError("domain must be a non-empty string")
        if self.domain != self.domain.strip().lower() or not _DOMAIN_RE.fullmatch(
            self.domain
        ):
            raise ValueError("domain must be a lowercase stable token")
        if not self.capability_id.startswith(f"{self.domain}."):
            raise ValueError("capability_id must be namespaced by its domain")

        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small A1 identity surface."""
        return tuple(field.name for field in fields(cls))


class CapabilityRegistry:
    """Register and resolve semantic capabilities without implementation wiring."""

    def __init__(self, capabilities: Iterable[CapabilitySpec] = ()) -> None:
        self._capabilities: dict[str, CapabilitySpec] = {}
        for capability in capabilities:
            self.register(capability)

    @staticmethod
    def _lookup_key(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("capability lookup value must be a string")
        key = value.strip().lower()
        if not key:
            raise ValueError("capability lookup value must not be blank")
        return key

    def register(self, capability: CapabilitySpec) -> CapabilitySpec:
        """Register one capability, rejecting duplicate semantic identities."""
        if not isinstance(capability, CapabilitySpec):
            raise TypeError("capability must be a CapabilitySpec")
        if capability.capability_id in self._capabilities:
            raise ValueError(f"duplicate capability: {capability.capability_id!r}")
        self._capabilities[capability.capability_id] = capability
        return capability

    def resolve(self, value: str) -> Optional[CapabilitySpec]:
        """Resolve a capability id; unknown values remain explicitly unknown."""
        return self._capabilities.get(self._lookup_key(value))

    def require(self, value: str) -> CapabilitySpec:
        """Resolve a capability or raise ``KeyError`` for an unknown id."""
        capability = self.resolve(value)
        if capability is None:
            raise KeyError(f"unknown capability: {value!r}")
        return capability

    def all(self) -> tuple[CapabilitySpec, ...]:
        """Return capabilities in registration order as an immutable snapshot."""
        return tuple(self._capabilities.values())

    def for_domain(self, domain: str) -> tuple[CapabilitySpec, ...]:
        """Return registered capabilities for one semantic domain."""
        domain_key = self._lookup_key(domain)
        if not _DOMAIN_RE.fullmatch(domain_key):
            raise ValueError("domain must be a lowercase stable token")
        return tuple(
            capability
            for capability in self._capabilities.values()
            if capability.domain == domain_key
        )


# Initial semantic catalog.  This is deliberately not a mirror of the README's
# endpoint count: multiple providers/endpoints may satisfy one capability, and
# one provider can satisfy many capabilities.  The catalog is additive and its
# total length is intentionally not frozen by tests.
DEFAULT_CAPABILITY_SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec("reference.security_master", "证券主数据", "reference"),
    CapabilitySpec("market.trading_calendar", "交易日历", "market"),
    CapabilitySpec("index.registry", "指数主数据", "index"),
    CapabilitySpec("index.quote", "指数行情", "index"),
    CapabilitySpec("index.membership", "指数成分", "index"),
    CapabilitySpec("index.weights", "指数权重", "index"),
    CapabilitySpec("index.valuation", "指数估值", "index"),
    CapabilitySpec("industry.taxonomy", "行业分类体系", "industry"),
    CapabilitySpec("industry.membership", "行业成员关系", "industry"),
    CapabilitySpec("theme.taxonomy", "题材分类体系", "theme"),
    CapabilitySpec("theme.membership", "题材成员关系", "theme"),
    CapabilitySpec("stock.quote", "个股行情快照", "stock"),
    CapabilitySpec("stock.kline", "个股K线", "stock"),
    CapabilitySpec("stock.valuation", "个股估值快照", "stock"),
    CapabilitySpec("stock.valuation_history", "个股历史估值", "stock"),
    CapabilitySpec("stock.fund_flow", "个股资金流", "stock"),
    CapabilitySpec("stock.margin", "融资融券", "stock"),
    CapabilitySpec("stock.announcements", "公司公告", "stock"),
    CapabilitySpec("stock.finance", "公司财务数据", "stock"),
    CapabilitySpec("stock.research_reports", "个股研报", "stock"),
    CapabilitySpec("stock.news", "个股新闻", "stock"),
    CapabilitySpec("macro.social_financing", "社会融资规模", "macro"),
    CapabilitySpec("macro.pmi", "采购经理指数", "macro"),
)


def build_default_capability_registry() -> CapabilityRegistry:
    """Build a fresh default registry so callers do not share mutable state."""
    return CapabilityRegistry(DEFAULT_CAPABILITY_SPECS)
