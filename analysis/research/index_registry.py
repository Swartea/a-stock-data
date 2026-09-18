"""Provider-neutral index identity contract for the Research Engine.

B2 starts with index identity only. The contract deliberately separates a
stable internal index_id from publisher-local codes and from provider-specific
symbols. Constituents, weights, valuation, quote data, aliases, display names,
and source metadata belong to later B2/B3 layers.

Industry/theme taxonomy is also intentionally outside this module: an index may
track an industry or theme, but that does not make the index itself the taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import re


_INDEX_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_LOCAL_CODE_RE = re.compile(r"^[A-Z0-9]+$")


class IndexPublisher(str, Enum):
    """Initial canonical publishers/maintainers in A-share index scope."""

    CSI = "csi"
    SSE = "sse"
    SZSE = "szse"
    CNI = "cni"


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
