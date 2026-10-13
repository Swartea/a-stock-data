"""Offline unit tests for the S1 market snapshot container.

No network, no provider access, no fixtures on disk: every case is a pure
in-process check of ``analysis.research.market_snapshot`` against the existing
``analysis/research`` identity contracts.
"""

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from analysis.research.freshness import MaxAgePolicy
from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_snapshot import MarketSnapshot

CSI_300 = IndexIdentity("csi.300", IndexPublisher.CSI, "000300")
SSE_COMPOSITE = IndexIdentity("sse.composite", IndexPublisher.SSE, "000001")

CSI_300_ALIAS = IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300")
SSE_COMPOSITE_ALIAS = IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001")


def _snapshot(**overrides) -> MarketSnapshot:
    values = {
        "snapshot_id": "market-snapshot-20261007",
        "market": "a-share",
        "indexes": (CSI_300, SSE_COMPOSITE),
        "provider_symbols": (CSI_300_ALIAS, SSE_COMPOSITE_ALIAS),
    }
    values.update(overrides)
    return MarketSnapshot(**values)


# --------------------------------------------------------------------------
# contract surface
# --------------------------------------------------------------------------


def test_snapshot_contract_surface_is_exact_and_small():
    assert MarketSnapshot.contract_fields() == (
        "snapshot_id",
        "market",
        "indexes",
        "provider_symbols",
    )


def test_snapshot_contract_exposes_no_number_field():
    """A bare number cannot live on the container; it belongs to evidence."""

    snapshot = _snapshot()

    for forbidden in (
        "close",
        "change_pct",
        "change",
        "value",
        "price",
        "observations",
        "quotes",
        "evidence",
    ):
        assert not hasattr(snapshot, forbidden)


def test_snapshot_contract_declares_no_clock_or_threshold():
    """docs/14: no guessed time, no global freshness threshold.

    The data date belongs to evidence and the trading-day state belongs to
    explicit calendar evidence, both later slices.  A container-level clock or a
    stored max age would be a second, conflicting source of truth.
    """

    snapshot = _snapshot()

    for forbidden in (
        "as_of",
        "data_as_of",
        "fetched_at",
        "trading_day",
        "max_age",
        "freshness_policy",
        "freshness_threshold",
        "quality",
    ):
        assert not hasattr(snapshot, forbidden)

    # the policy exists, but only as something the caller brings
    assert MaxAgePolicy(max_age=timedelta(days=1)).max_age == timedelta(days=1)


def test_market_token_is_market_agnostic():
    """Another market must add data, not change the contract."""

    for market in ("a-share", "hk", "us"):
        assert _snapshot(market=market).market == market


def test_explicit_snapshot_content_is_preserved_verbatim():
    snapshot = _snapshot()

    assert snapshot.snapshot_id == "market-snapshot-20261007"
    assert snapshot.market == "a-share"
    assert snapshot.indexes == (CSI_300, SSE_COMPOSITE)
    assert snapshot.provider_symbols == (CSI_300_ALIAS, SSE_COMPOSITE_ALIAS)


# --------------------------------------------------------------------------
# identity vs exchange code vs data-source code
# --------------------------------------------------------------------------


def test_snapshot_keeps_index_exchange_and_source_codes_apart():
    """The three code spaces stay distinct and none is derived from another."""

    snapshot = _snapshot()

    index = snapshot.indexes[0]
    alias = snapshot.provider_symbols[0]

    # internal identity id
    assert index.index_id == "csi.300"
    # exchange / publisher-local code
    assert index.local_code == "000300"
    # data-source code
    assert alias.provider_symbol == "1.000300"
    assert alias.provider_id == "eastmoney"

    # the exchange code is never silently rewritten into the internal id
    assert index.index_id != index.local_code
    # and the source code is never rewritten into either of them
    assert alias.provider_symbol not in {index.index_id, index.local_code}


def test_lookup_returns_the_symbols_for_one_index_only():
    snapshot = _snapshot()

    assert snapshot.symbols_for("csi.300") == (CSI_300_ALIAS,)
    assert snapshot.symbols_for("sse.composite") == (SSE_COMPOSITE_ALIAS,)


def test_index_without_a_known_symbol_returns_empty_instead_of_guessing():
    snapshot = _snapshot(provider_symbols=(CSI_300_ALIAS,))

    assert snapshot.symbols_for("sse.composite") == ()
    assert snapshot.symbols_for("csi.300") == (CSI_300_ALIAS,)


def test_snapshot_rejects_a_symbol_for_an_index_it_does_not_cover():
    with pytest.raises(ValueError, match="must only map covered indexes"):
        _snapshot(indexes=(CSI_300,), provider_symbols=(CSI_300_ALIAS, SSE_COMPOSITE_ALIAS))


def test_duplicate_provider_symbols_are_rejected():
    with pytest.raises(ValueError, match="duplicate provider symbol"):
        _snapshot(provider_symbols=(CSI_300_ALIAS, CSI_300_ALIAS))


# --------------------------------------------------------------------------
# container invariants
# --------------------------------------------------------------------------


def test_snapshot_requires_at_least_one_index():
    with pytest.raises(ValueError, match="indexes must not be empty"):
        _snapshot(indexes=())


def test_snapshot_rejects_duplicate_indices():
    with pytest.raises(ValueError, match="duplicate index in snapshot"):
        _snapshot(indexes=(CSI_300, CSI_300))


@pytest.mark.parametrize("bad_value", ["Snapshot-20261007", "Snapshot", " snapshot", ""])
def test_snapshot_id_must_be_a_canonical_token(bad_value):
    with pytest.raises(ValueError, match="snapshot_id must be a canonical lowercase token"):
        _snapshot(snapshot_id=bad_value)


def test_snapshot_id_accepts_the_dashed_token_shape_used_by_snapshots():
    """The default snapshot id shape is valid; only canonicality is enforced."""

    assert _snapshot(snapshot_id="market-snapshot-20261007").snapshot_id == (
        "market-snapshot-20261007"
    )


@pytest.mark.parametrize("bad_value", ["A-share", "a share", ""])
def test_market_must_be_a_canonical_token(bad_value):
    with pytest.raises(ValueError, match="market must be a canonical lowercase token"):
        _snapshot(market=bad_value)


@pytest.mark.parametrize("bad_value", ["Csi.300", "csi 300", ""])
def test_index_lookup_value_must_be_canonical(bad_value):
    with pytest.raises(ValueError, match="index_id lookup value must be a canonical token"):
        _snapshot().symbols_for(bad_value)


# --------------------------------------------------------------------------
# type-level blocking: raw strings are not coerced, container stays immutable
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected"),
    [
        ("indexes", ["csi.300"], "indexes must be a tuple"),
        ("indexes", ("csi.300",), "indexes must contain IndexIdentity values"),
        ("provider_symbols", [CSI_300_ALIAS], "provider_symbols must be a tuple"),
        ("provider_symbols", ("1.000300",), "provider_symbols must contain IndexProviderSymbolAlias"),
    ],
)
def test_containers_must_be_immutable_tuples(field_name, bad_value, expected):
    with pytest.raises(TypeError, match=expected):
        _snapshot(**{field_name: bad_value})


def test_identity_fields_are_not_silently_coerced_from_strings():
    with pytest.raises(TypeError, match="indexes must contain IndexIdentity values"):
        _snapshot(indexes=("csi.300",))

    with pytest.raises(TypeError, match="provider_symbols must contain IndexProviderSymbolAlias"):
        _snapshot(provider_symbols=("1.000300",))


def test_snapshot_is_immutable():
    snapshot = _snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.market = "hk"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        snapshot.indexes = ()  # type: ignore[misc]


# --------------------------------------------------------------------------
# contract stays provider- and market-neutral
# --------------------------------------------------------------------------


def test_snapshot_defines_no_new_id_vocabulary():
    """docs/14 4.2-1: reuse the existing identity contracts, invent nothing."""

    import analysis.research.market_snapshot as module

    assert module.IndexIdentity is IndexIdentity
    assert module.IndexProviderSymbolAlias is IndexProviderSymbolAlias
    # no provider catalog, priority, fallback order, or capability wiring here
    for forbidden in (
        "ProviderSpec",
        "ProviderRegistry",
        "DEFAULT_PROVIDER_SPECS",
        "CAPABILITY",
    ):
        assert not hasattr(module, forbidden)
