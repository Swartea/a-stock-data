"""Provider-neutral index identity contract for the Research Engine.

B2 starts with index identity only. The contract deliberately separates a
stable internal index_id from publisher-local codes and from provider-specific
symbols. Constituents, weights, valuation, quote data, aliases, display names,
and source metadata belong to later B2/B3 layers.

Industry/theme taxonomy is also intentionally outside this module: an index may
track an industry or theme, but that does not make the index itself the taxonomy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import Enum
from types import MappingProxyType
from typing import Mapping

_INDEX_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_LOCAL_CODE_RE = re.compile(r"^[A-Z0-9]+$")


class IndexPublisher(str, Enum):
    """Initial canonical publishers/maintainers in A-share index scope."""

    CSI = "csi"
    SSE = "sse"
    SZSE = "szse"
    CNI = "cni"
    HANG_SENG = "hang_seng"
    SP_DJI = "sp_dji"
    NASDAQ = "nasdaq"


@dataclass(frozen=True)
class IndexIdentity:
    """Immutable identity of one index.

    index_id is the Research Engine's stable internal identifier. It is
    intentionally not inferred from publisher or local_code. local_code is the
    publisher-local index code, not a provider-decorated market symbol.
    """

    index_id: str
    publisher: IndexPublisher
    local_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.index_id, str):
            raise TypeError("index_id must be a string")
        if not self.index_id:
            raise ValueError("index_id must not be empty")
        if self.index_id != self.index_id.strip():
            raise ValueError("index_id must not contain surrounding whitespace")
        if self.index_id != self.index_id.lower():
            raise ValueError("index_id must use canonical lowercase form")
        if not _INDEX_ID_RE.fullmatch(self.index_id):
            raise ValueError("index_id must be a canonical machine-readable token")

        if not isinstance(self.publisher, IndexPublisher):
            raise TypeError("publisher must be IndexPublisher")

        if not isinstance(self.local_code, str):
            raise TypeError("local_code must be a string")
        if not self.local_code:
            raise ValueError("local_code must not be empty")
        if self.local_code != self.local_code.strip():
            raise ValueError("local_code must not contain surrounding whitespace")
        if self.local_code != self.local_code.upper():
            raise ValueError("local_code must use canonical uppercase form")
        if not _LOCAL_CODE_RE.fullmatch(self.local_code):
            raise ValueError("local_code must be a publisher-local code token")

    @classmethod
    def contract_fields(cls) -> tuple[str, ...]:
        """Return the intentionally small B2 identity surface."""

        return tuple(field.name for field in fields(cls))


# Shared A-share identities live here so universe and provider specifications
# refer to the same canonical objects instead of maintaining parallel facts.
A_SHARE_INDEX_IDENTITIES: tuple[IndexIdentity, ...] = (
    IndexIdentity("cn.index.sh_comp", IndexPublisher.SSE, "000001"),
    IndexIdentity("cn.index.sz_component", IndexPublisher.SZSE, "399001"),
    IndexIdentity("cn.index.chinext", IndexPublisher.SZSE, "399006"),
    IndexIdentity("cn.index.csi300", IndexPublisher.CSI, "000300"),
)
A_SHARE_INDEX_BY_ID: Mapping[str, IndexIdentity] = MappingProxyType(
    {identity.index_id: identity for identity in A_SHARE_INDEX_IDENTITIES}
)

# Accept identifiers from the pre-canonical Global Daily-K and S3 contracts
# at API boundaries, while always returning the single canonical identity.
# These aliases never create additional IndexIdentity entries.
INDEX_ID_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "cn.index.sse.000001": "cn.index.sh_comp",
        "cn.index.szse.399001": "cn.index.sz_component",
        "cn.index.szse.399006": "cn.index.chinext",
        "cn.index.csi.000300": "cn.index.csi300",
        "sse.composite": "cn.index.sh_comp",
        "szse.component": "cn.index.sz_component",
        "szse.chinext": "cn.index.chinext",
        "csi.300": "cn.index.csi300",
    }
)


def canonical_index_id(index_id: str) -> str:
    """Resolve a known historical identifier to its canonical index ID."""

    if not isinstance(index_id, str):
        raise TypeError("index_id must be a string")
    return INDEX_ID_ALIASES.get(index_id, index_id)
