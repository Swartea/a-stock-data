"""Tests for the explicit A-share core index universe (S3).

Everything here is offline: no clock, no calendar, no quote source, no network.
The tests assert declaration facts -- order, identity, aliases, gating -- and
never claim that a declared alias is live or reachable.
"""

import dataclasses

import pytest

from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import IndexProviderSymbolAlias
from analysis.research.market_index_universe import (
    A_SHARE_CORE_UNIVERSE,
    MarketIndexUniverse,
)

# --- A-share core universe: exact identities and stable order ---------------


def test_core_universe_covers_exact_four_indexes_in_declared_order() -> None:
    assert A_SHARE_CORE_UNIVERSE.index_ids == (
        "sse.composite",
        "szse.component",
        "szse.chinext",
        "csi.300",
    )


def test_core_identities_are_exact() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    assert universe.identities[0] == IndexIdentity(
        "sse.composite", IndexPublisher.SSE, "000001"
    )
    assert universe.identities[1] == IndexIdentity(
        "szse.component", IndexPublisher.SZSE, "399001"
    )
    assert universe.identities[2] == IndexIdentity(
        "szse.chinext", IndexPublisher.SZSE, "399006"
    )
    assert universe.identities[3] == IndexIdentity("csi.300", IndexPublisher.CSI, "000300")


def test_identity_is_not_derived_from_local_code() -> None:
    """The internal id states the publisher; the local code is a separate space.

    ``sse.composite`` deliberately does not equal its local_code "000001", so a
    consumer cannot silently treat the publisher-local code as the internal id.
    """

    composite = A_SHARE_CORE_UNIVERSE.require_index("sse.composite")

    assert composite.index_id != composite.local_code
    assert composite.publisher is IndexPublisher.SSE
    assert A_SHARE_CORE_UNIVERSE.index_ids.count(composite.local_code) == 0


def test_require_index_returns_exact_identity_for_each_covered_index() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    assert universe.require_index("sse.composite") == universe.identities[0]
    assert universe.require_index("szse.component") == universe.identities[1]
    assert universe.require_index("szse.chinext") == universe.identities[2]
    assert universe.require_index("csi.300") == universe.identities[3]


# --- provider aliases -------------------------------------------------------


def test_alias_relations_are_exact_and_verbatim() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    assert universe.aliases_for("csi.300") == (
        IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300"),
    )
    assert universe.aliases_for("sse.composite") == (
        IndexProviderSymbolAlias("sse.composite", "tencent", "sh000001"),
    )


def test_covered_index_without_verified_alias_returns_empty_tuple() -> None:
    """Absence is an explicit state, never a guessed symbol."""

    universe = A_SHARE_CORE_UNIVERSE

    assert universe.aliases_for("szse.component") == ()
    assert universe.aliases_for("szse.chinext") == ()


def test_no_extra_aliases_are_prepopulated() -> None:
    aliased_ids = {alias.index_id for alias in A_SHARE_CORE_UNIVERSE.aliases}

    assert aliased_ids == {"sse.composite", "csi.300"}
    assert len(A_SHARE_CORE_UNIVERSE.aliases) == 2


def test_alias_order_is_preserved() -> None:
    universe = MarketIndexUniverse(
        identities=(
            IndexIdentity("x.first", IndexPublisher.CSI, "000001"),
            IndexIdentity("x.second", IndexPublisher.SSE, "000002"),
        ),
        aliases=(
            IndexProviderSymbolAlias("x.first", "alpha", "A1"),
            IndexProviderSymbolAlias("x.second", "beta", "B1"),
            IndexProviderSymbolAlias("x.first", "alpha", "A2"),
        ),
    )

    assert universe.aliases_for("x.first") == (
        IndexProviderSymbolAlias("x.first", "alpha", "A1"),
        IndexProviderSymbolAlias("x.first", "alpha", "A2"),
    )


# --- unknown-index gating ---------------------------------------------------


@pytest.mark.parametrize(
    "unknown_index_id",
    [
        "csi.500",
        "szse.chinext.extra",
        "sse.composite ",
        " sse.composite",
        "SSE.COMPOSITE",
        "sse.composi",
        "csi.3000",
    ],
)
def test_require_index_rejects_index_outside_universe(unknown_index_id) -> None:
    with pytest.raises(KeyError):
        A_SHARE_CORE_UNIVERSE.require_index(unknown_index_id)


def test_aliases_for_rejects_index_outside_universe() -> None:
    with pytest.raises(KeyError):
        A_SHARE_CORE_UNIVERSE.aliases_for("csi.500")


def test_require_index_rejects_non_string_lookup() -> None:
    with pytest.raises(TypeError):
        A_SHARE_CORE_UNIVERSE.require_index(("csi.300",))


# --- caller-supplied universes (no A-share-only branch) ----------------------


def test_constructor_accepts_caller_supplied_identities() -> None:
    """The identifiers below are synthetic samples, not real market indexes."""

    custom = MarketIndexUniverse(
        identities=(
            IndexIdentity("sample.alpha", IndexPublisher.CSI, "SAA1"),
            IndexIdentity("sample.beta", IndexPublisher.SSE, "SAB1"),
        )
    )

    assert custom.index_ids == ("sample.alpha", "sample.beta")
    assert custom.aliases == ()
    assert custom.aliases_for("sample.alpha") == ()
    assert custom.require_index("sample.beta") == IndexIdentity(
        "sample.beta", IndexPublisher.SSE, "SAB1"
    )


def test_custom_universe_gating_is_independent_of_the_a_share_default() -> None:
    custom = MarketIndexUniverse(
        identities=(IndexIdentity("sample.gamma", IndexPublisher.CNI, "SAG1"),)
    )

    with pytest.raises(KeyError):
        custom.require_index("csi.300")

    with pytest.raises(KeyError):
        A_SHARE_CORE_UNIVERSE.require_index("sample.gamma")


# --- immutability -----------------------------------------------------------


def test_universe_is_frozen_and_holds_immutable_tuples() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    assert dataclasses.is_dataclass(universe)
    assert universe.__dataclass_params__.frozen is True
    assert isinstance(universe.identities, tuple)
    assert isinstance(universe.aliases, tuple)
    assert isinstance(universe.index_ids, tuple)
    assert isinstance(universe.aliases_for("csi.300"), tuple)


def test_frozen_universe_rejects_field_mutation() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    with pytest.raises(dataclasses.FrozenInstanceError):
        universe.identities = ()

    with pytest.raises(dataclasses.FrozenInstanceError):
        universe.aliases = ()


def test_lookup_returns_no_mutable_registry_or_cache_attribute() -> None:
    universe = A_SHARE_CORE_UNIVERSE

    for attribute in ("_lookup", "_by_index", "registry", "_registry"):
        assert not hasattr(universe, attribute)

    assert not any(
        isinstance(value, (dict, list, set)) for value in vars(universe).values()
    )


# --- rejection of invalid collections ---------------------------------------


def test_empty_identity_collection_is_rejected() -> None:
    with pytest.raises(ValueError, match="identities must not be empty"):
        MarketIndexUniverse(identities=())


def test_non_tuple_identity_collection_is_rejected() -> None:
    with pytest.raises(TypeError, match="identities must be a tuple"):
        MarketIndexUniverse(
            identities=[IndexIdentity("csi.300", IndexPublisher.CSI, "000300")]
        )


def test_invalid_identity_item_is_rejected() -> None:
    with pytest.raises(TypeError, match="identities must contain IndexIdentity values"):
        MarketIndexUniverse(identities=("csi.300",))


def test_invalid_identity_instance_is_rejected() -> None:
    """IndexIdentity validation is reused, not re-implemented or bypassed."""

    with pytest.raises(ValueError, match="index_id must not be empty"):
        MarketIndexUniverse(
            identities=(IndexIdentity("", IndexPublisher.CSI, "000300"),)
        )

    with pytest.raises(TypeError, match="publisher must be IndexPublisher"):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", "csi", "000300"),)  # type: ignore[arg-type]
        )


def test_duplicate_index_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate index_id in universe"):
        MarketIndexUniverse(
            identities=(
                IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),
                IndexIdentity("csi.300", IndexPublisher.SSE, "000001"),
            )
        )


def test_non_tuple_alias_collection_is_rejected() -> None:
    with pytest.raises(TypeError, match="aliases must be a tuple"):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),),
            aliases=[IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300")],
        )


def test_invalid_alias_item_is_rejected() -> None:
    with pytest.raises(TypeError, match="aliases must contain IndexProviderSymbolAlias"):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),),
            aliases=("1.000300",),
        )


def test_invalid_alias_instance_is_rejected() -> None:
    with pytest.raises(ValueError):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),),
            aliases=(IndexProviderSymbolAlias("csi.300", "EastMoney", "1.000300"),),
        )


def test_alias_pointing_outside_universe_is_rejected() -> None:
    with pytest.raises(ValueError, match="alias index outside universe"):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),),
            aliases=(
                IndexProviderSymbolAlias("csi.500", "eastmoney", "1.000500"),
            ),
        )


# --- collision behaviour ----------------------------------------------------


def test_provider_symbol_collision_is_rejected() -> None:
    with pytest.raises(ValueError, match="provider index symbol collision"):
        MarketIndexUniverse(
            identities=(
                IndexIdentity("sse.composite", IndexPublisher.SSE, "000001"),
                IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),
            ),
            aliases=(
                IndexProviderSymbolAlias("sse.composite", "eastmoney", "1.000001"),
                IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000001"),
            ),
        )


def test_duplicate_alias_entry_is_rejected_as_a_collision() -> None:
    with pytest.raises(ValueError, match="provider index symbol collision"):
        MarketIndexUniverse(
            identities=(IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),),
            aliases=(
                IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300"),
                IndexProviderSymbolAlias("csi.300", "eastmoney", "1.000300"),
            ),
        )


def test_same_symbol_under_different_providers_is_not_a_collision() -> None:
    """Collision semantics are keyed on (provider_id, provider_symbol)."""

    universe = MarketIndexUniverse(
        identities=(
            IndexIdentity("sse.composite", IndexPublisher.SSE, "000001"),
            IndexIdentity("csi.300", IndexPublisher.CSI, "000300"),
        ),
        aliases=(
            IndexProviderSymbolAlias("sse.composite", "eastmoney", "1.000001"),
            IndexProviderSymbolAlias("csi.300", "tencent", "1.000001"),
        ),
    )

    assert len(universe.aliases) == 2


def test_core_universe_has_no_provider_symbol_collision() -> None:
    keys = [(alias.provider_id, alias.provider_symbol) for alias in
            A_SHARE_CORE_UNIVERSE.aliases]

    assert len(keys) == len(set(keys))


# --- contract surface -------------------------------------------------------


def test_contract_surface_is_minimal_and_data_free() -> None:
    assert MarketIndexUniverse.contract_fields() == ("identities", "aliases")

    forbidden = {
        "quotes",
        "price",
        "as_of",
        "observed_at",
        "clock",
        "calendar",
        "freshness",
        "max_age",
        "market_state",
        "provider_available",
        "status",
        "transport",
        "endpoint",
        "url",
        "display_name",
        "constituents",
        "weights",
    }
    assert forbidden.isdisjoint(MarketIndexUniverse.contract_fields())
