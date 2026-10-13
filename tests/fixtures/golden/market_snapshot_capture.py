"""Offline-only deterministic generator/loader for the 2026-10-12 market snapshot.

What this module is
-------------------

A **one-off capture replay**.  It reads the four archived Eastmoney response
bodies checked in beside it as ``*.raw.json``, rebuilds the exact
:class:`~analysis.research.market_snapshot.MarketSnapshot` /
:class:`~analysis.research.market_evidence.MarketEvidence` records described in
``market_snapshot-20261012.provenance.json``, and projects them with the real
S6 contract
(:func:`analysis.research.market_snapshot_projection.project_market_snapshot`).

The same call is both generator and loader:

* :func:`build_projection_text` returns the canonical projection text;
* :func:`main` compares that text with the checked-in
  ``market_snapshot-20261012.json`` and exits non-zero on any drift.

Offline guarantee
-----------------

**No network, ever.**  There is no ``socket``, ``http``, ``urllib``, ``requests``,
``httpx``, or ``urlopen`` import anywhere in this file, and the payload is only
ever read from the four archived raw files next to it.  Running this module can
not reach Eastmoney or anything else, so the test suite that drives it needs no
network access at all.

Determinism guarantee
---------------------

Every value is derived from the archived bytes plus the provenance sidecar.
There is no clock read (``datetime.now``), no environment variable, no locale
dependence, and no set/dict iteration that reaches the wire text, so a fresh
interpreter always reproduces the same bytes and the same SHA-256.

What this module deliberately does not do
-----------------------------------------

* **It does not fetch, refresh, or repair.**  If a raw file is missing or its
  SHA-256 does not match the provenance sidecar, this fails loudly instead of
  re-downloading.  A missing capture is a missing capture.
* **It does not re-derive provider data.**  Scalars come from the archived
  K-line rows via :data:`_COLUMN_CODES`; nothing is recomputed from a formula,
  rounded, re-scaled, or interpolated from an adjacent column.
* **It does not supply any clock, verdict, or policy the capture did not
  report.**  ``data_as_of`` is the K-line row's own date, ``fetched_at`` is the
  recorded capture clock, and the remaining five clocks stay ``None``.  No
  intraday close time, freshness verdict, PIT allowance, calendar decision, or
  unit is manufactured here.
* **It is not a production data path.**  This is a fixture replay pinned to one
  trading day; see the README section for what the capture does *not* establish.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

# Running this file directly as a CLI puts this directory -- not the project
# root -- on sys.path, so the ``analysis`` package would be unimportable.  The
# project root is prepended when it is missing, which keeps ``python
# tests/fixtures/golden/market_snapshot_capture.py verify`` working without
# changing anything for callers that already import this module normally.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from analysis.research.market_evidence import MarketEvidence  # noqa: E402
from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE  # noqa: E402
from analysis.research.market_snapshot import MarketSnapshot  # noqa: E402
from analysis.research.market_snapshot_projection import (  # noqa: E402
    project_market_snapshot,
)
from analysis.research.pit_guard import PITStatus  # noqa: E402
from analysis.research.providers import DEFAULT_PROVIDER_SPECS, ProviderSpec  # noqa: E402
from analysis.research.quality import (  # noqa: E402
    CompletenessStatus,
    FreshnessStatus,
    QualityMetadata,
)
from analysis.research.time_semantics import TimeMetadata  # noqa: E402

_GOLDEN_DIR: Final = Path(__file__).resolve().parent

RAW_FILES: Final = {
    "1.000001": "market_snapshot-20261012-eastmoney-1.000001.raw.json",
    "0.399001": "market_snapshot-20261012-eastmoney-0.399001.raw.json",
    "0.399006": "market_snapshot-20261012-eastmoney-0.399006.raw.json",
    "1.000300": "market_snapshot-20261012-eastmoney-1.000300.raw.json",
}

PROVENANCE_FILE: Final = "market_snapshot-20261012.provenance.json"
FIXTURE_FILE: Final = "market_snapshot-20261012.json"

# The Eastmoney historical daily K-line response used fields2=f51..f61, i.e. the
# row is comma-joined in exactly this order.  Column index is the zero-based
# position inside the single archived K-line string.
_COLUMN_CODES: Final = {
    "f51": ("date", 0),
    "f52": ("open", 1),
    "f53": ("close", 2),
    "f54": ("high", 3),
    "f55": ("low", 4),
    "f56": ("volume", 5),
    "f57": ("amount", 6),
    "f58": ("amplitude_pct", 7),
    "f59": ("change_pct", 8),
    "f60": ("change", 9),
    "f61": ("turnover_pct", 10),
}

# Only the two metrics the capture is on the record for.  The other nine
# columns stay in the raw file and out of the fixture.
_CAPTURED_METRICS: Final = ("close", "change_pct")

SNAPSHOT_ID: Final = "a-share.market.2026-10-12"
MARKET: Final = "a-share"


def _eastmoney_spec() -> ProviderSpec:
    """Return the Eastmoney :class:`ProviderSpec` from the project catalog."""

    for spec in DEFAULT_PROVIDER_SPECS:
        if spec.provider_id == "eastmoney":
            return spec
    raise LookupError("eastmoney provider spec missing from DEFAULT_PROVIDER_SPECS")


@dataclass(frozen=True)
class RawResponse:
    """One archived Eastmoney body plus its verified hash."""

    filename: str
    secid: str
    sha256: str
    byte_length: int
    payload: dict[str, object]


def load_provenance() -> dict[str, object]:
    """Return the parsed machine-readable provenance sidecar."""

    return json.loads((_GOLDEN_DIR / PROVENANCE_FILE).read_text(encoding="utf-8"))


def load_raw(secid: str, *, provenance: dict[str, object] | None = None) -> RawResponse:
    """Load one archived body and verify its length and SHA-256.

    Verification happens **before** the bytes are parsed, so a drifted capture
    is reported as a drifted capture rather than surfacing later as a confusing
    parse error.
    """

    provenance = provenance if provenance is not None else load_provenance()
    captures = {entry["secid"]: entry for entry in provenance["captures"]}
    entry = captures[secid]
    filename = entry["raw_file"]
    payload_bytes = (_GOLDEN_DIR / filename).read_bytes()

    actual_sha = hashlib.sha256(payload_bytes).hexdigest()
    if actual_sha != entry["sha256"]:
        raise ValueError(
            f"archived body {filename} drifted: sha256 {actual_sha} != {entry['sha256']}"
        )
    if len(payload_bytes) != entry["bytes"]:
        raise ValueError(
            f"archived body {filename} drifted: {len(payload_bytes)} B != {entry['bytes']} B"
        )

    return RawResponse(
        filename=filename,
        secid=secid,
        sha256=actual_sha,
        byte_length=len(payload_bytes),
        payload=json.loads(payload_bytes.decode("utf-8")),
    )


def load_raw_responses(*, provenance: dict[str, object] | None = None) -> tuple[RawResponse, ...]:
    """Return all four archived responses in universe declaration order."""

    provenance = provenance if provenance is not None else load_provenance()
    return tuple(
        load_raw(secid, provenance=provenance)
        for secid in ("1.000001", "0.399001", "0.399006", "1.000300")
    )


def kline_columns(kline: str) -> dict[str, str]:
    """Return the ``f51..f61`` code -> raw text mapping for one K-line row."""

    values = kline.split(",")
    if len(values) != 11:
        raise ValueError(f"unexpected K-line arity {len(values)}: {kline!r}")
    return {code: values[index] for code, (_, index) in _COLUMN_CODES.items()}


def build_snapshot() -> MarketSnapshot:
    """Return the snapshot: four core identities, four Eastmoney aliases only.

    The Tencent ``sh000001`` SSE alias stays declared in
    :data:`A_SHARE_CORE_UNIVERSE` but was **not** used by this capture, so it is
    not carried here.  ``provider_symbols`` therefore records exactly the four
    mappings the capture actually exercised, in the universe's own order.
    """

    eastmoney_aliases = tuple(
        alias for alias in A_SHARE_CORE_UNIVERSE.aliases if alias.provider_id == "eastmoney"
    )
    return MarketSnapshot(
        snapshot_id=SNAPSHOT_ID,
        market=MARKET,
        indexes=A_SHARE_CORE_UNIVERSE.identities,
        provider_symbols=eastmoney_aliases,
    )


def build_evidence(*, provenance: dict[str, object] | None = None) -> tuple[MarketEvidence, ...]:
    """Return the eight real scalar observations, two per index.

    ``close`` is the ``f53`` column and ``change_pct`` the ``f59`` column of the
    single archived 2026-10-12 daily row.  Both are parsed with
    :class:`~decimal.Decimal` straight from the raw text, so the exact provider
    spelling survives to the wire.
    """

    provenance = provenance if provenance is not None else load_provenance()
    provider = _eastmoney_spec()
    quality = QualityMetadata(
        freshness=FreshnessStatus.UNKNOWN,
        completeness=CompletenessStatus.COMPLETE,
        degraded=False,
        quality_flags=(),
    )
    fetch_meta = {entry["secid"]: entry["fetched_at"] for entry in provenance["captures"]}
    data_as_of = provenance["data_as_of"]

    records: list[MarketEvidence] = []
    for raw in load_raw_responses(provenance=provenance):
        identity = A_SHARE_CORE_UNIVERSE.require_index(_index_id(raw))
        index_id = identity.index_id
        data = raw.payload["data"]
        klines = data["klines"]
        if len(klines) != 1:
            raise ValueError(f"expected exactly one daily row in {raw.filename}, got {len(klines)}")
        columns = kline_columns(klines[0])
        row_date = columns["f51"]
        if row_date != provenance["kline_date"]:
            raise ValueError(f"row date {row_date} != capture date {provenance['kline_date']}")
        if data["code"] != raw.secid.split(".")[1]:
            raise ValueError(f"payload code {data['code']} != requested secid {raw.secid}")

        time = TimeMetadata(fetched_at=fetch_meta[raw.secid], data_as_of=data_as_of)
        for metric in _CAPTURED_METRICS:
            field_code = next(
                code for code, (name, _index) in _COLUMN_CODES.items() if name == metric
            )
            records.append(
                MarketEvidence(
                    evidence_id=f"{index_id}.{metric}.{raw.secid}",
                    subject=identity,
                    metric=metric,
                    observation=Decimal(columns[field_code]),
                    provider=provider,
                    time=time,
                    quality=quality,
                    pit_status=PITStatus.UNKNOWN,
                    status="ok",
                )
            )
    return tuple(records)


def _index_id(raw: RawResponse) -> str:
    """Map one Eastmoney secid to its universe ``index_id``."""

    for alias in A_SHARE_CORE_UNIVERSE.aliases:
        if alias.provider_symbol == raw.secid:
            return alias.index_id
    raise KeyError(f"no universe alias for captured secid {raw.secid}")


def build_projection_text() -> str:
    """Return the canonical S6 projection text for this capture.

    ``decisions`` is empty on purpose: S4/S5 were not run against a real trading
    calendar, and manufacturing a verdict here would be exactly the invention
    the provenance sidecar disclaims.
    """

    return project_market_snapshot(
        snapshot=build_snapshot(),
        evidence=build_evidence(),
        decisions=(),
    )


def projection_sha256() -> str:
    """Return the SHA-256 of the canonical projection text (UTF-8 bytes)."""

    return hashlib.sha256(build_projection_text().encode("utf-8")).hexdigest()


def fixture_sha256() -> str:
    """Return the SHA-256 of the checked-in fixture file as it sits on disk."""

    return hashlib.sha256((_GOLDEN_DIR / FIXTURE_FILE).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Regenerate, compare against the checked-in fixture, and report.

    Exit codes:

    ``0`` -- rebuilt text matches the checked-in fixture byte-for-byte.
    ``1`` -- a drift, missing archive, or integrity failure.  **Nothing is ever
    written**: this module is a verifier and a generator, never an updater, so a
    failing run can never silently bless a new baseline.
    """

    argv = sys.argv[1:] if argv is None else argv
    text = build_projection_text()
    rebuilt_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    fixture_path = _GOLDEN_DIR / FIXTURE_FILE
    if not fixture_path.exists():
        print(f"missing checked-in fixture: {FIXTURE_FILE}", file=sys.stderr)
        print(f"rebuilt sha256: {rebuilt_sha}", file=sys.stderr)
        return 1

    on_disk = fixture_path.read_text(encoding="utf-8")
    if on_disk != text:
        print(
            f"drift: {FIXTURE_FILE} does not match the rebuild from the archived raw files",
            file=sys.stderr,
        )
        print(f"on-disk sha256: {hashlib.sha256(on_disk.encode('utf-8')).hexdigest()}", file=sys.stderr)
        print(f"rebuilt sha256: {rebuilt_sha}", file=sys.stderr)
        return 1

    expected_sha = load_provenance()["projection"]["sha256"]
    if rebuilt_sha != expected_sha:
        print(
            f"projection sha256 {rebuilt_sha} != recorded {expected_sha}", file=sys.stderr
        )
        return 1

    if argv:
        print(f"OK {FIXTURE_FILE} sha256={rebuilt_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
