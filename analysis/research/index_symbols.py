"""Provider-symbol mapping for Research Engine index identities.

This B2 layer maps an exact provider-specific index symbol to one stable
index_id. It does not infer publisher, normalize provider symbols, fetch data,
or model constituents, weights, valuation, quotes, or taxonomy membership.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Iterable, Optional

_INDEX_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class IndexProviderSymbolAlias:
    """One explicit provider index symbol mapped to one stable index identity."""

    index_id: str
    provider_id: str
    provider_symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.index_id, str):
            raise TypeError("index_id must be a string")
        if (
            not self.index_id
            or self.index_id != self.index_id.strip().lower()
            or not _INDEX_ID_RE.fullmatch(self.index_id)
        ):
            raise ValueError("index_id must be a canonical machine-readable token")

        if not isinstance(self.provider_id, str):
            raise TypeError("provider_id must be a string")
        if (
            not self.provider_id
            or self.provider_id != self.provider_id.strip().lower()
            or not _PROVIDER_ID_RE.fullmatch(self.provider_id)
        ):
            raise ValueError("provider_id must be a canonical lowercase provider token")

        if not isinstance(self.provider_symbol, str):
            raise TypeError("provider_symbol must be a string")
        if not self.provider_symbol:
            raise ValueError("provider_symbol must not be empty")
        if self.provider_symbol != self.provider_symbol.strip():
            raise ValueError("provider_symbol must not contain surrounding whitespace")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small provider-symbol mapping surface."""

        return tuple(field.name for field in fields(cls))


class IndexProviderSymbolRegistry:
    """Exact lookup from provider-specific index symbol to stable index id."""

    def __init__(
        self,
        aliases: Iterable[IndexProviderSymbolAlias] = (),
    ) -> None:
        self._lookup: dict[tuple[str, str], IndexProviderSymbolAlias] = {}
        self._by_index: dict[str, list[IndexProviderSymbolAlias]] = {}
        for alias in aliases:
            self.register(alias)

    def register(
        self,
        alias: IndexProviderSymbolAlias,
    ) -> IndexProviderSymbolAlias:
        """Register one explicit alias, rejecting provider-symbol collisions."""

        if not isinstance(alias, IndexProviderSymbolAlias):
            raise TypeError("alias must be an IndexProviderSymbolAlias")

        key = (alias.provider_id, alias.provider_symbol)
        existing = self._lookup.get(key)
        if existing is not None:
            raise ValueError(
                "provider index symbol collision for "
                f"{alias.provider_id!r}:{alias.provider_symbol!r}; "
                f"already mapped to {existing.index_id!r}"
            )

        self._lookup[key] = alias
        self._by_index.setdefault(alias.index_id, []).append(alias)
        return alias

    def resolve(
        self,
        provider_id: str,
        provider_symbol: str,
    ) -> Optional[str]:
        """Return the stable index id for an exact known provider symbol."""

        key = self._lookup_key(provider_id, provider_symbol)
        alias = self._lookup.get(key)
        if alias is None:
            return None
        return alias.index_id

    def require(
        self,
        provider_id: str,
        provider_symbol: str,
    ) -> str:
        """Resolve an exact provider index symbol or fail explicitly."""

        index_id = self.resolve(provider_id, provider_symbol)
        if index_id is None:
            raise KeyError(
                f"unknown provider index symbol: "
                f"{provider_id!r}:{provider_symbol!r}"
            )
        return index_id

    def aliases_for(
        self,
        index_id: str,
    ) -> tuple[IndexProviderSymbolAlias, ...]:
        """Return aliases for one index in registration order."""

        if not isinstance(index_id, str):
            raise TypeError("index_id lookup value must be a string")
        if (
            not index_id
            or index_id != index_id.strip().lower()
            or not _INDEX_ID_RE.fullmatch(index_id)
        ):
            raise ValueError("index_id lookup value must be canonical")
        return tuple(self._by_index.get(index_id, ()))

    @staticmethod
    def _lookup_key(
        provider_id: str,
        provider_symbol: str,
    ) -> tuple[str, str]:
        if not isinstance(provider_id, str):
            raise TypeError("provider_id lookup value must be a string")
        if (
            not provider_id
            or provider_id != provider_id.strip().lower()
            or not _PROVIDER_ID_RE.fullmatch(provider_id)
        ):
            raise ValueError("provider_id lookup value must be canonical")

        if not isinstance(provider_symbol, str):
            raise TypeError("provider_symbol lookup value must be a string")
        if not provider_symbol:
            raise ValueError("provider_symbol lookup value must not be empty")
        if provider_symbol != provider_symbol.strip():
            raise ValueError(
                "provider_symbol lookup value must not contain surrounding whitespace"
            )
        return provider_id, provider_symbol
