"""Provider-neutral security identity contract for the Research Engine.

B0 starts with identity only.  The contract deliberately separates a stable
internal ``security_id`` from exchange-local codes and from provider-specific
symbols.  Names, listing status, industry/theme membership, aliases, listing
periods, and source metadata are intentionally deferred to later B0 batches.

This module does not infer an exchange from a code prefix and does not derive a
stable security identifier from a mutable market symbol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import Enum


_SECURITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_LOCAL_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")


class Exchange(str, Enum):
    """Mainland listing venues in the initial A-share Security Master scope."""

    SSE = "sse"
    SZSE = "szse"
    BSE = "bse"


class SecurityType(str, Enum):
    """Small provider-neutral instrument taxonomy for listed securities."""

    EQUITY = "equity"
    ETF = "etf"
    FUND = "fund"
    BOND = "bond"
    REIT = "reit"
    OTHER = "other"


@dataclass(frozen=True)
class SecurityIdentity:
    """Immutable identity of one listed security.

    ``security_id`` is the Research Engine's stable internal identifier.  It is
    intentionally not inferred from ``exchange`` or ``local_code`` here.
    ``local_code`` is the exchange-local identifier as published by the venue,
    not a provider-specific decorated symbol such as ``sh.600693``.
    """

    security_id: str
    exchange: Exchange
    local_code: str
    security_type: SecurityType

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str):
            raise TypeError("security_id must be a string")
        if not self.security_id:
            raise ValueError("security_id must not be empty")
        if self.security_id != self.security_id.strip():
            raise ValueError("security_id must not contain surrounding whitespace")
        if self.security_id != self.security_id.lower():
            raise ValueError("security_id must use canonical lowercase form")
        if not _SECURITY_ID_RE.fullmatch(self.security_id):
            raise ValueError("security_id must be a canonical machine-readable token")

        if not isinstance(self.exchange, Exchange):
            raise TypeError("exchange must be Exchange")

        if not isinstance(self.local_code, str):
            raise TypeError("local_code must be a string")
        if not self.local_code:
            raise ValueError("local_code must not be empty")
        if self.local_code != self.local_code.strip():
            raise ValueError("local_code must not contain surrounding whitespace")
        if self.local_code != self.local_code.upper():
            raise ValueError("local_code must use canonical uppercase form")
        if not _LOCAL_CODE_RE.fullmatch(self.local_code):
            raise ValueError("local_code must be an exchange-local code token")

        if not isinstance(self.security_type, SecurityType):
            raise TypeError("security_type must be SecurityType")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small B0 identity surface."""

        return tuple(field.name for field in fields(cls))
