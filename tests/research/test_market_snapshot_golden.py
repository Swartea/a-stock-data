"""Offline golden tests for the 2026-10-12 real market-snapshot capture.

Unlike ``test_market_snapshot_projection.py`` (which drives synthetic contract
fixtures), this module exercises the **real archived capture**: four Eastmoney
response bodies captured once on 2026-10-13T00:21:21+08:00 for trading day
2026-10-12, the eight scalar observations they contain, and the checked-in
golden projection built from them.

Offline guarantee
-----------------

Nothing here touches the network.  The four ``*.raw.json`` archives beside
:mod:`tests.fixtures.golden.market_snapshot_capture` are the only data source,
and the capture module under test imports no network library at all -- a test
asserts that.  The suite runs identically on a machine that has never reached
Eastmoney.

What these tests claim
----------------------

* The archived bodies still hash to the recorded SHA-256 values, so the golden
  is traceable back to the exact bytes that were captured.
* The projection rebuilt from those bytes is byte-identical to the checked-in
  golden, and a **fresh Python process** reproduces the same SHA-256.
* The eight observations are the eight expected scalars, and every provenance
  field traces them to the right raw file, column, and raw text.
* Nothing was invented: unreported clocks are null, and no freshness verdict,
  PIT allowance, calendar decision, intraday timestamp, or unit appears.

What these tests do **not** claim
---------------------------------

That the provider is stable, reachable, or correct in general; that the numbers
are suitable for any production decision; or that any observation beyond these
eight was verified.  The capture is one-off evidence for one trading day.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from analysis.research.market_index_universe import A_SHARE_CORE_UNIVERSE
from analysis.research.market_snapshot_projection import SCHEMA_VERSION
from tests.fixtures.golden import market_snapshot_capture as capture

_GOLDEN_DIR: Final = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]

FIXTURE_PATH: Final = _GOLDEN_DIR / capture.FIXTURE_FILE
PROVENANCE_PATH: Final = _GOLDEN_DIR / capture.PROVENANCE_FILE

FETCHED_AT: Final = "2026-10-13T00:21:21+08:00"
KLINE_DATE: Final = "2026-10-12"

# The eight real scalars, written out literally.  These are the provider's own
# close and change_pct for 2026-10-12 and are asserted as exact Decimal text.
EXPECTED_OBSERVATIONS: Final = {
    ("sse.composite", "close"): "3797.24",
    ("sse.composite", "change_pct"): "-0.43",
    ("szse.component", "close"): "12384.87",
    ("szse.component", "change_pct"): "-2.03",
    ("szse.chinext", "close"): "2963.82",
    ("szse.chinext", "change_pct"): "-2.61",
    ("csi.300", "close"): "4287.98",
    ("csi.300", "change_pct"): "-0.68",
}

EXPECTED_ARCHIVES: Final = {
    "1.000001": ("market_snapshot-20261012-eastmoney-1.000001.raw.json", 280,
                 "50459b308e146e66e7e4f2defea013eb6b9a87d43a9de9f7c9e17ca0eb429a6c"),
    "0.399001": ("market_snapshot-20261012-eastmoney-0.399001.raw.json", 286,
                 "9100e54ec38961d67ffbac2dffb5ab9c44f436ad7ba70b00c4d0bbe25c10dcf9"),
    "0.399006": ("market_snapshot-20261012-eastmoney-0.399006.raw.json", 280,
                 "dd5880fddeaf8983e788ee5da8a642f32ea6cce96827058a2da98a9614b2a075"),
    "1.000300": ("market_snapshot-20261012-eastmoney-1.000300.raw.json", 277,
                 "5da3b3e6b3fcd348bc7baaecc7c0ed159296ae9aa064293dd7f3fff75a3e326f"),
}

_PROVENANCE: Final = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
_FIXTURE_TEXT: Final = FIXTURE_PATH.read_text(encoding="utf-8")
_FIXTURE: Final = json.loads(_FIXTURE_TEXT)


# --- archived bodies --------------------------------------------------------


@pytest.mark.parametrize("secid", sorted(EXPECTED_ARCHIVES))
def test_archived_body_matches_recorded_byte_length_and_sha256(secid: str) -> None:
    """Each archive is still exactly the captured bytes, verified before parsing."""

    filename, expected_bytes, expected_sha = EXPECTED_ARCHIVES[secid]
    payload = (_GOLDEN_DIR / filename).read_bytes()

    assert len(payload) == expected_bytes
    assert hashlib.sha256(payload).hexdigest() == expected_sha


@pytest.mark.parametrize("secid", sorted(EXPECTED_ARCHIVES))
def test_archived_body_reports_success_and_carries_provider_identity(secid: str) -> None:
    """Every captured response was HTTP 200 with rc=0 and a named payload."""

    filename, _bytes, _sha = EXPECTED_ARCHIVES[secid]
    payload = json.loads((_GOLDEN_DIR / filename).read_text(encoding="utf-8"))

    assert payload["rc"] == 0
    assert payload["data"]["code"] == secid.split(".")[1]
    assert payload["data"]["name"] in {"上证指数", "深证成指", "创业板指", "沪深300"}
    assert payload["data"]["klines"] == [payload["data"]["klines"][0]]
    assert payload["data"]["klines"][0].startswith(f"{KLINE_DATE},")


def test_all_four_provider_names_are_retained_as_evidence() -> None:
    """The provider's own Chinese names survive into the provenance sidecar."""

    recorded = {
        (entry["index_id"], entry["response_data_name"])
        for entry in _PROVENANCE["captures"]
    }

    assert recorded == {
        ("sse.composite", "上证指数"),
        ("szse.component", "深证成指"),
        ("szse.chinext", "创业板指"),
        ("csi.300", "沪深300"),
    }


def test_capture_records_ok_http_status_and_rc_zero_for_every_index() -> None:
    for entry in _PROVENANCE["captures"]:
        assert entry["http_status"] == 200
        assert entry["payload_rc"] == 0
        assert entry["fetched_at"] == FETCHED_AT


# --- the eight observations -------------------------------------------------


def test_exactly_eight_observations_two_per_index() -> None:
    assert len(_FIXTURE["evidence"]) == 8

    pairs: dict[str, set[str]] = {}
    for row in _FIXTURE["evidence"]:
        pairs.setdefault(row["subject"]["index_id"], set()).add(row["metric"])
    assert pairs == {
        index_id: {"change_pct", "close"}
        for index_id in ("sse.composite", "szse.component", "szse.chinext", "csi.300")
    }


@pytest.mark.parametrize(
    ("index_id", "metric"),
    [(key[0], key[1]) for key in sorted(EXPECTED_OBSERVATIONS)],
)
def test_each_observation_is_the_exact_provider_scalar(index_id: str, metric: str) -> None:
    """Decimal text, not a float round trip: the provider spelling is preserved."""

    row = next(
        item
        for item in _FIXTURE["evidence"]
        if item["subject"]["index_id"] == index_id and item["metric"] == metric
    )

    assert row["observation"] == EXPECTED_OBSERVATIONS[(index_id, metric)]
    assert row["observation_type"] == "decimal"
    assert Decimal(row["observation"]) == Decimal(EXPECTED_OBSERVATIONS[(index_id, metric)])


def test_evidence_rows_follow_project_projection_sort_semantics() -> None:
    """Rows are sorted by (subject.index_id, metric, evidence_id)."""

    keys = [
        (row["subject"]["index_id"], row["metric"], row["evidence_id"])
        for row in _FIXTURE["evidence"]
    ]
    assert keys == sorted(keys)


def test_observations_are_eastmoney_sourced_with_ok_status() -> None:
    for row in _FIXTURE["evidence"]:
        assert row["provider"]["provider_id"] == "eastmoney"
        assert row["provider"]["display_name"] == "东方财富"
        assert row["status"] == "ok"


def test_no_decisions_are_present_and_no_verdict_is_invented() -> None:
    """S4/S5 were not run; the fixture must not manufacture a verdict."""

    for row in _FIXTURE["evidence"]:
        assert row["decisions"] == []
        assert row["pit_status"] == "unknown"
        assert row["quality"]["freshness"] == "unknown"
        assert row["quality"]["completeness"] == "complete"
        assert row["quality"]["degraded"] is False


def test_only_fetched_at_and_data_as_of_are_reported_and_the_rest_are_null() -> None:
    """No intraday close time is invented and no clock is interpolated."""

    for row in _FIXTURE["evidence"]:
        assert row["time"] == {
            "fetched_at": FETCHED_AT,
            "data_as_of": KLINE_DATE,
            "period_start": None,
            "period_end": None,
            "published_at": None,
            "effective_from": None,
            "effective_to": None,
        }


# --- identity and alias spine ----------------------------------------------


def test_snapshot_carries_all_four_core_universe_identities() -> None:
    assert _FIXTURE["schema_version"] == SCHEMA_VERSION
    assert _FIXTURE["snapshot"] == {
        "snapshot_id": "a-share.market.2026-10-12",
        "market": "a-share",
    }
    assert _FIXTURE["indexes"] == [
        {"index_id": index_id, "publisher": publisher.value, "local_code": local_code}
        for index_id, publisher, local_code in (
            (i.index_id, i.publisher, i.local_code) for i in A_SHARE_CORE_UNIVERSE.identities
        )
    ]


def test_only_the_four_eastmoney_aliases_are_carried() -> None:
    """The Tencent SSE alias stays in the universe but was not used here."""

    assert _FIXTURE["provider_symbols"] == [
        {
            "index_id": alias.index_id,
            "provider_id": alias.provider_id,
            "provider_symbol": alias.provider_symbol,
        }
        for alias in A_SHARE_CORE_UNIVERSE.aliases
        if alias.provider_id == "eastmoney"
    ]
    assert {item["provider_id"] for item in _FIXTURE["provider_symbols"]} == {"eastmoney"}
    assert "sh000001" not in json.dumps(_FIXTURE, ensure_ascii=False)


# --- provenance traceability -----------------------------------------------


def test_provenance_traces_every_observation_to_its_raw_column() -> None:
    """Each observation names its raw file, hash, secid, code, column, and scalar."""

    observations = _PROVENANCE["observations"]
    assert len(observations) == 8

    for entry in observations:
        filename, _bytes, sha = EXPECTED_ARCHIVES[entry["query_secid"]]
        assert entry["raw_file"] == filename
        assert entry["response_sha256"] == sha
        assert entry["kline_row_date"] == KLINE_DATE
        assert entry["response_data_code"] == entry["query_secid"].split(".")[1]
        assert entry["response_data_name"]
        assert entry["field_code"] in {"f53", "f59"}
        assert entry["column_index"] == (2 if entry["field_code"] == "f53" else 8)
        assert entry["raw_scalar"] == EXPECTED_OBSERVATIONS[(entry["index_id"], entry["metric"])]
        assert entry["normalized_decimal"] == entry["raw_scalar"]

        # The traced column really holds that scalar in the archived row.
        payload = json.loads((_GOLDEN_DIR / filename).read_text(encoding="utf-8"))
        row = payload["data"]["klines"][0].split(",")
        assert row[entry["column_index"]] == entry["raw_scalar"]


def test_provenance_covers_exactly_the_projected_evidence_ids() -> None:
    assert {entry["evidence_id"] for entry in _PROVENANCE["observations"]} == {
        row["evidence_id"] for row in _FIXTURE["evidence"]
    }


def test_provenance_traces_identities_to_official_publisher_references() -> None:
    identities = _PROVENANCE["identity_provenance"]

    assert len(identities) == 4
    for entry in identities:
        assert entry["source_module"] == "analysis/research/market_index_universe.py"
        assert entry["reference_url"].startswith("https://")
        identity = A_SHARE_CORE_UNIVERSE.require_index(entry["index_id"])
        assert identity.local_code == entry["local_code"]
        assert identity.publisher.value == entry["publisher"]


def test_provenance_traces_each_alias_to_its_captured_request_and_response() -> None:
    aliases = _PROVENANCE["alias_provenance"]
    assert len(aliases) == 4

    for entry in aliases:
        filename, _bytes, sha = EXPECTED_ARCHIVES[entry["provider_symbol"]]
        assert entry["verified_by_raw_file"] == filename
        assert entry["verified_by_response_sha256"] == sha
        assert entry["query_secid"] == entry["provider_symbol"]
        assert entry["provider_id"] == "eastmoney"
        assert entry["response_data_code"] == entry["provider_symbol"].split(".")[1]


def test_tencent_alias_is_recorded_as_unused_rather_than_dropped_silently() -> None:
    unused = _PROVENANCE["unused_aliases"]
    assert len(unused) == 1
    assert unused[0]["provider_symbol"] == "sh000001"
    assert unused[0]["provider_id"] == "tencent"


def test_sse_close_has_an_independent_check_scoped_to_that_scalar_only() -> None:
    checks = _PROVENANCE["independent_check"]

    assert len(checks) == 1
    entry = checks[0]
    assert entry["index_id"] == "sse.composite"
    assert entry["metric"] == "close"
    assert entry["raw_scalar"] == "3797.24"
    assert entry["check_url"] == "https://www.sse.com.cn/market/sseindex/overview/"
    assert "not_cross_checked" in entry


def test_clock_and_metadata_policy_explains_every_null_and_metadata_field() -> None:
    clocks = _PROVENANCE["clock_policy"]
    assert clocks["fetched_at"].startswith("the recorded local capture clock")
    assert clocks["data_as_of"].startswith("the K-line row date")
    for absent in ("period_start", "period_end", "published_at", "effective_from", "effective_to"):
        assert clocks[absent].startswith("null")

    policy = _PROVENANCE["metadata_policy"]
    assert policy["freshness"].startswith("unknown")
    assert policy["pit_status"].startswith("unknown")
    assert policy["trading_calendar"].startswith("no decision")
    assert policy["decisions"].startswith("none")
    assert "unit" in policy["units"]


def test_capture_records_its_one_off_nature_and_its_limits() -> None:
    nature = _PROVENANCE["capture_nature"]

    assert nature["one_off"] is True
    assert nature["captured_at"] == FETCHED_AT
    limits = " ".join(nature["does_not_establish"])
    assert "provider stability" in limits
    assert "production source selection" in limits


# --- offline + determinism --------------------------------------------------


def test_generator_source_contains_no_network_import() -> None:
    """The generator is offline-only: no networking module is imported anywhere."""

    source_path = _GOLDEN_DIR / "market_snapshot_capture.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported & {"socket", "http", "urllib", "requests", "httpx", "aiohttp"} == set()


def test_generator_never_calls_a_network_primitive() -> None:
    """No outbound-call helper exists in the generator's executable code."""

    tree = ast.parse((_GOLDEN_DIR / "market_snapshot_capture.py").read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "urlopen" not in called
    assert "urlretrieve" not in called
    assert "get" not in attributes
    assert "socket" not in attributes


def test_rebuild_from_archives_matches_checked_in_golden_byte_for_byte() -> None:
    assert capture.build_projection_text() == _FIXTURE_TEXT


def test_projection_sha256_matches_the_recorded_digest() -> None:
    assert capture.projection_sha256() == _PROVENANCE["projection"]["sha256"]
    assert capture.fixture_sha256() == _PROVENANCE["projection"]["sha256"]
    assert (
        hashlib.sha256(_FIXTURE_TEXT.encode("utf-8")).hexdigest()
        == _PROVENANCE["projection"]["sha256"]
    )


def test_a_fresh_python_process_reproduces_the_same_sha256() -> None:
    """Determinism is checked out-of-process, not just within this interpreter."""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, %r);"
            "from tests.fixtures.golden.market_snapshot_capture import projection_sha256;"
            "print(projection_sha256())" % str(_PROJECT_ROOT),
        ],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == _PROVENANCE["projection"]["sha256"]


def test_generator_main_reports_success_against_the_checked_in_golden() -> None:
    assert capture.main([]) == 0


def test_generator_refuses_to_run_when_a_raw_archive_drifts(tmp_path: Path) -> None:
    """Integrity failure is loud and non-destructive: nothing is written."""

    golden_copy = tmp_path / "golden"
    golden_copy.mkdir()
    archived = [value[0] for value in EXPECTED_ARCHIVES.values()]
    for name in (capture.FIXTURE_FILE, capture.PROVENANCE_FILE, *archived):
        (golden_copy / name).write_bytes((_GOLDEN_DIR / name).read_bytes())
    drifted = golden_copy / EXPECTED_ARCHIVES["1.000001"][0]
    drifted.write_bytes(drifted.read_bytes().replace(b"3797.24", b"9999.99"))

    saved_dir = capture._GOLDEN_DIR
    try:
        capture._GOLDEN_DIR = golden_copy
        with pytest.raises(ValueError, match="drifted"):
            capture.load_raw("1.000001")
    finally:
        capture._GOLDEN_DIR = saved_dir

    # The real golden is untouched: a failed run never rewrites a baseline.
    assert hashlib.sha256(
        (_GOLDEN_DIR / EXPECTED_ARCHIVES["1.000001"][0]).read_bytes()
    ).hexdigest() == EXPECTED_ARCHIVES["1.000001"][2]
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == _PROVENANCE["projection"]["sha256"]


def test_golden_is_utf8_and_readable_as_text_with_real_chinese() -> None:
    assert "上证指数" in PROVENANCE_PATH.read_text(encoding="utf-8")
    FIXTURE_PATH.read_bytes().decode("utf-8")


def test_existing_result_v3_fixtures_are_untouched() -> None:
    """The S6 golden adds files; it must not disturb the older golden set."""

    for name in ("result_v3-600693-20261003.json", "result_v3-002353-20260912.json"):
        assert (_GOLDEN_DIR / name).exists()


def test_snapshot_reconstruction_uses_only_project_contracts() -> None:
    """The snapshot is built from the universe, never re-declared by hand."""

    snapshot = capture.build_snapshot()
    assert snapshot.indexes == A_SHARE_CORE_UNIVERSE.identities
    assert all(alias.provider_id == "eastmoney" for alias in snapshot.provider_symbols)


def test_build_evidence_returns_exactly_eight_contract_records() -> None:
    from analysis.research.market_evidence import MarketEvidence

    evidence = capture.build_evidence()
    assert len(evidence) == 8
    assert all(isinstance(item, MarketEvidence) for item in evidence)
    assert {(item.subject.index_id, item.metric) for item in evidence} == set(EXPECTED_OBSERVATIONS)


def test_kline_column_mapping_matches_the_requested_fields2_order() -> None:
    """f51..f61 map to the eleven documented K-line columns in order."""

    row = "2026-10-12,3806.98,3797.24,3828.22,3791.00,461448981,714909910722.20,0.98,-0.43,-16.55,0.95"
    columns = capture.kline_columns(row)

    assert columns["f51"] == "2026-10-12"
    assert columns["f53"] == "3797.24"
    assert columns["f59"] == "-0.43"
    assert len(columns) == 11


def test_kline_column_parsing_rejects_a_wrong_arity_row() -> None:
    with pytest.raises(ValueError, match="arity"):
        capture.kline_columns("2026-10-12,3806.98,3797.24")


def test_provenance_query_template_matches_the_documented_capture_request() -> None:
    query = _PROVENANCE["capture_nature"]["query_template"]

    assert query["klt"] == "101"
    assert query["fqt"] == "0"
    assert query["lmt"] == "1"
    assert query["end"] == "20261012"
    assert query["fields1"] == "f1,f2,f3,f4,f5,f6"
    assert query["fields2"] == "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    assert _PROVENANCE["capture_nature"]["endpoint"] == (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    )


def test_provenance_declares_the_generator_and_its_offline_status() -> None:
    assert _PROVENANCE["generator"] == "tests/fixtures/golden/market_snapshot_capture.py"
    assert _PROVENANCE["generator_network_access"].startswith("none")


def test_capture_module_never_reads_a_clock_or_environment_variable() -> None:
    """Determinism: every clock is recorded in the sidecar, never sampled."""

    tree = ast.parse((_GOLDEN_DIR / "market_snapshot_capture.py").read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "now" not in called
    assert "time" not in called
    assert "utcnow" not in attributes
    assert "environ" not in attributes
    assert "getenv" not in called


def test_evidence_carries_no_unit_field_because_the_contract_has_none() -> None:
    """No unit is projected: the S6 contract has no such field to fill."""

    assert "unit" not in json.dumps(_FIXTURE["evidence"], ensure_ascii=False).lower()
