"""Offline unit tests for the S3 market index universe.

No network, no provider access, no fixtures on disk: every case is a pure
in-process check of ``analysis.research.market_index_universe`` against the
existing ``analysis/research`` identity contracts.
"""

from dataclasses import FrozenInstanceError

import pytest

from analysis.research.index_registry import IndexIdentity, IndexPublisher
from analysis.research.index_symbols import (
    IndexProviderSymbolAlias,
    IndexProviderSymbolRegistry,
)
from analysis.research.market_index_universe import (
    A_SHARE_MARKET,
    MarketIndexUniverse,
    a_share_core_universe,
    build_universe,
)

SSE_COMPOSITE = IndexIdentity("sse.composite", IndexPublisher.SSE, "000001")
CSI_300 = IndexIdentity("csi.300", IndexPublisher.CSI, "000300")
SZSE_COMPONENT = IndexIdentity("szse.component", IndexPublisher.SZSE, "399001")


def _alias(index_id: str, provider_id: str, provider_symbol: str):
    return IndexProviderSymbolAlias(index_id, provider_id, provider_symbol)


def test_contract_surface_is_exact() -> None:
    assert MarketIndexUniverse.contract_fields() == ("market", "indexes", "aliases")


def test_a_share_core_universe_covers_the_four_core_indexes() -> None:
    universe = a_share_core_universe()

    assert universe.market == A_SHARE_MARKET == "a-share"
    assert universe.index_ids == (
        "sse.composite",
        "szse.component",
        "szse.chinext",
        "csi.300",
    )


def test_a_share_core_universe_keeps_publisher_local_codes_verbatim() -> None:
    universe = a_share_core_universe()

    assert universe.require_index("sse.composite").local_code == "000001"
    assert universe.require_index("szse.component").local_code == "399001"
    assert universe.require_index("szse.chinext").local_code == "399006"
    assert universe.require_index("csi.300").local_code == "000300"
    assert universe.require_index("csi.300").publisher is IndexPublisher.CSI


def test_a_share_core_universe_holds_one_alias_per_provider() -> None:
    universe = a_share_core_universe()

    pairs = [(alias.index_id, alias.provider_id) for alias in universe.aliases]
    assert len(pairs) == len(set(pairs))


def test_a_share_core_universe_aliases_come_from_repository_evidence_only() -> None:
    """Aliases are limited to symbols already used elsewhere in this repo.

    The repository holds no provider-symbol evidence for 399001/399006, so
    those indexes deliberately ship without one instead of a fabricated
    mapping.
    """

    universe = a_share_core_universe()

    assert universe.aliases_for("csi.300") == (
        _alias("csi.300", "csi", "000300"),
        _alias("csi.300", "eastmoney", "1.000300"),
        _alias("csi.300", "sina", "sh000300"),
    )
    assert universe.aliases_for("sse.composite") == (
        _alias("sse.composite", "tencent", "sh000001"),
    )
    assert universe.aliases_for("szse.component") == ()
    assert universe.aliases_for("szse.chinext") == ()


def test_alias_order_is_declaration_order_not_sorted() -> None:
    """Order follows declaration, never an implicit sort."""

    universe = MarketIndexUniverse(
        market="a-share",
        indexes=(CSI_300,),
        aliases=(
            _alias("csi.300", "sina", "sh000300"),
            _alias("csi.300", "eastmoney", "1.000300"),
            _alias("csi.300", "csi", "000300"),
        ),
    )

    providers = [alias.provider_id for alias in universe.aliases_for("csi.300")]
    assert providers == ["sina", "eastmoney", "csi"]
    assert providers != sorted(providers)
    # The A-share universe is likewise order-stable and reproducible.
    assert [a.provider_id for a in a_share_core_universe().aliases_for("csi.300")] == [
        "csi",
        "eastmoney",
        "sina",
    ]


def test_universe_is_deterministic_across_constructions() -> None:
    first = a_share_core_universe()
    second = a_share_core_universe()

    assert first.index_ids == second.index_ids
    assert first.aliases == second.aliases
    assert first == second
    assert first is not second


def test_universe_is_immutable() -> None:
    universe = a_share_core_universe()

    with pytest.raises(FrozenInstanceError):
        universe.market = "other-market"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        universe.indexes = (CSI_300,)  # type: ignore[misc]


def test_identity_stays_exact_and_verbatim() -> None:
    universe = a_share_core_universe()

    assert universe.alias_for("csi.300", "eastmoney").provider_symbol == "1.000300"
    # No case folding, no prefix guessing on provider symbols.
    assert universe.alias_for("csi.300", "EastMoney") is None
    assert universe.resolve_provider_symbol("eastmoney", "1.000300") == "csi.300"
    assert universe.resolve_provider_symbol("eastmoney", "0.399001") is None


def test_membership_and_require_index_behave_exactly() -> None:
    universe = a_share_core_universe()

    assert "csi.300" in universe
    assert "unknown.index" not in universe
    assert 123 not in universe
    with pytest.raises(KeyError):
        universe.require_index("unknown.index")


def test_require_alias_fails_explicitly_when_unknown() -> None:
    universe = a_share_core_universe()

    with pytest.raises(KeyError):
        universe.require_alias("szse.component", "eastmoney")


def test_market_scope_is_data_driven_not_china_only() -> None:
    """A different market token needs only new data, never a contract change."""

    neutral_index = IndexIdentity("example.core.one", IndexPublisher.CSI, "EX00001")
    neutral_alias = _alias("example.core.one", "examplefeed", "EX1")
    universe = build_universe(
        market="example-market",
        indexes=(neutral_index,),
        aliases=(neutral_alias,),
    )

    assert universe.market == "example-market"
    assert universe.index_ids == ("example.core.one",)
    assert universe.alias_for("example.core.one", "examplefeed") == neutral_alias
    # Same contract fields as the A-share universe: only data differs.
    assert universe.contract_fields() == MarketIndexUniverse.contract_fields()


def test_index_publisher_enum_cannot_name_a_hk_or_us_publisher() -> None:
    """Known S3 limitation, asserted rather than worked around.

    ``IndexPublisher`` enumerates only CSI/SSE/SZSE/CNI, so a genuine Hong Kong
    or US index publisher cannot be expressed without changing
    ``index_registry.py`` (out of scope for this slice).  The universe keeps
    ``market`` data-driven instead of faking a publisher.
    """

    assert {member.value for member in IndexPublisher} == {"csi", "sse", "szse", "cni"}
    assert not hasattr(IndexPublisher, "HKEX")
    assert not hasattr(IndexPublisher, "NASDAQ")
    with pytest.raises(TypeError, match="publisher must be IndexPublisher"):
        IndexIdentity("hk.core.hsi", "hkex", "HSI")  # type: ignore[arg-type]


def test_empty_universe_is_rejected() -> None:
    with pytest.raises(ValueError, match="indexes must not be empty"):
        MarketIndexUniverse(market="a-share", indexes=(), aliases=())


def test_duplicate_index_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate index in universe"):
        MarketIndexUniverse(
            market="a-share",
            indexes=(CSI_300, CSI_300),
            aliases=(),
        )


def test_alias_for_index_outside_the_universe_is_rejected() -> None:
    with pytest.raises(ValueError, match="aliases must only map indexes in this universe"):
        MarketIndexUniverse(
            market="a-share",
            indexes=(CSI_300,),
            aliases=(_alias("sse.composite", "tencent", "sh000001"),),
        )


def test_provider_symbol_collision_is_rejected_by_existing_registry_semantics() -> None:
    with pytest.raises(ValueError, match="provider index symbol collision"):
        MarketIndexUniverse(
            market="a-share",
            indexes=(CSI_300, SZSE_COMPONENT),
            aliases=(
                _alias("csi.300", "eastmoney", "1.000300"),
                _alias("szse.component", "eastmoney", "1.000300"),
            ),
        )


def test_same_symbol_under_different_providers_is_not_a_collision() -> None:
    universe = MarketIndexUniverse(
        market="a-share",
        indexes=(CSI_300,),
        aliases=(
            _alias("csi.300", "csi", "000300"),
            _alias("csi.300", "eastmoney", "000300"),
        ),
    )

    assert len(universe.aliases) == 2


def test_one_alias_per_provider_per_index_is_enforced() -> None:
    """A second symbol for the same provider would make the lookup ambiguous."""

    with pytest.raises(ValueError, match="one alias per provider per index"):
        MarketIndexUniverse(
            market="a-share",
            indexes=(CSI_300,),
            aliases=(
                _alias("csi.300", "eastmoney", "1.000300"),
                _alias("csi.300", "eastmoney", "0.399001"),
            ),
        )


def test_universe_registers_aliases_in_a_working_registry() -> None:
    universe = a_share_core_universe()
    registry = IndexProviderSymbolRegistry(universe.aliases)

    assert registry.require("tencent", "sh000001") == "sse.composite"
    assert registry.require("csi", "000300") == "csi.300"
    with pytest.raises(KeyError):
        registry.require("eastmoney", "0.399001")


def test_wrong_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="market must be a string"):
        MarketIndexUniverse(market=1, indexes=(CSI_300,), aliases=())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="indexes must be a tuple"):
        MarketIndexUniverse(market="a-share", indexes=[CSI_300], aliases=())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="indexes must contain IndexIdentity values"):
        MarketIndexUniverse(market="a-share", indexes=("csi.300",), aliases=())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="aliases must be a tuple"):
        MarketIndexUniverse(market="a-share", indexes=(CSI_300,), aliases=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="aliases must contain IndexProviderSymbolAlias values"):
        MarketIndexUniverse(
            market="a-share",
            indexes=(CSI_300,),
            aliases=("csi.300",),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("market", ["a-share", "example-market", "market/2", "A Share"])
def test_market_label_is_kept_verbatim_and_never_normalized(market) -> None:
    """``market`` is a verbatim label, so a private token grammar must not exist.

    A label that mixes case, spaces or punctuation is accepted and stored
    byte-for-byte: the universe never lower-cases, trims or re-spells caller
    data.  Canonicalising a market label here would invent a second ID lexicon
    that no existing contract owns (``docs/14`` §五 S3 forbids exactly that).
    """

    universe = MarketIndexUniverse(market=market, indexes=(CSI_300,), aliases=())

    assert universe.market == market


def test_non_empty_market_label_is_the_only_value_rule() -> None:
    """Only emptiness is rejected; no token form is prescribed.

    A blank-but-non-empty label is reported by staying verbatim rather than being
    silently normalised, because the alternative would be the module rewriting
    caller data behind their back.
    """

    universe = MarketIndexUniverse(market=" ", indexes=(CSI_300,), aliases=())

    assert universe.market == " "


def test_empty_market_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="market must not be empty"):
        MarketIndexUniverse(market="", indexes=(CSI_300,), aliases=())


def test_universe_module_declares_no_market_token_grammar() -> None:
    """Structural check: the module compiles no private token pattern.

    Mirrors the quote boundary's own grammar check: a compiled regex private to
    this module is the only way a second lexicon could reappear, so none is
    allowed to exist.
    """

    from analysis.research import market_index_universe

    compiled = [
        name
        for name, value in vars(market_index_universe).items()
        if name.startswith("_") and hasattr(value, "fullmatch")
    ]

    assert compiled == []


def test_non_cn_market_label_is_accepted_without_inventing_a_publisher() -> None:
    """A future non-CN market needs only a label plus existing contracts.

    The label here is deliberately shaped like a real non-CN market name (mixed
    case, spaces, a slash) and is accepted verbatim by the **unchanged**
    contract.  No HK/US publisher and no HK/US index identity is invented: the
    single index reuses an existing :class:`IndexPublisher` member, which is the
    known S3 limitation asserted in
    ``test_index_publisher_enum_cannot_name_a_hk_or_us_publisher``.
    """

    label = "Hong Kong & US Composite (delayed)"
    universe = build_universe(
        market=label,
        indexes=(IndexIdentity("example.core.one", IndexPublisher.CNI, "EX00001"),),
        aliases=(_alias("example.core.one", "examplefeed", "EX1"),),
    )

    assert universe.market == label
    # Same three contract fields as the A-share universe: only data differs.
    assert universe.contract_fields() == MarketIndexUniverse.contract_fields()
    assert universe.require_index("example.core.one").publisher is IndexPublisher.CNI
    assert universe.alias_for("example.core.one", "examplefeed").provider_symbol == "EX1"
    # The publisher enum itself is untouched: no member was added for this market.
    assert {member.value for member in IndexPublisher} == {"csi", "sse", "szse", "cni"}
    assert not hasattr(IndexPublisher, "HKEX")


def test_universe_retains_no_mutable_registry_state() -> None:
    """Structural check: nothing on the instance can be mutated into a resolver.

    ``frozen=True`` alone is not enough here.  A cached registry attribute would
    still be live state: registering into it would redirect resolution for every
    later reader while the three contract fields kept reporting the truth.  The
    universe must therefore store exactly its declared fields and expose no
    ``IndexProviderSymbolRegistry`` instance anywhere on the class.
    """

    universe = a_share_core_universe()

    assert set(vars(universe)) == {"market", "indexes", "aliases"}
    assert not hasattr(universe, "_registry")
    retained = [
        name
        for name, value in vars(MarketIndexUniverse).items()
        if isinstance(value, IndexProviderSymbolRegistry)
    ]
    assert retained == []


def test_out_of_universe_alias_cannot_be_injected_after_construction() -> None:
    """The injection channel is closed: resolution ignores post-construction writes.

    ``szse.component`` deliberately ships without an ``eastmoney`` alias, so a
    registry that accepted one would invent a provider symbol the repository has
    no evidence for — and the quote boundary would stop reporting ``unsupported``
    for it.
    """

    universe = a_share_core_universe()

    assert universe.resolve_provider_symbol("eastmoney", "0.399001") is None

    # No attribute to poison: the attempt fails loudly rather than silently
    # rewriting what this universe means.
    with pytest.raises(AttributeError):
        universe._registry.register(  # type: ignore[attr-defined]
            _alias("szse.component", "eastmoney", "0.399001")
        )

    # Resolution is byte-for-byte what it was before the attempt.
    assert universe.resolve_provider_symbol("eastmoney", "0.399001") is None
    assert universe.resolve_provider_symbol("eastmoney", "1.000300") == "csi.300"
    assert universe.alias_for("szse.component", "eastmoney") is None
    assert universe.aliases_for("szse.component") == ()
    # ``require_index`` is unchanged too: an id the universe never declared is
    # still unknown, and an injected alias cannot smuggle one in.
    with pytest.raises(KeyError):
        universe.require_index("unknown.index")


def test_resolution_is_deterministic_and_shared_by_no_other_universe() -> None:
    """Repeated lookups agree, and another registry cannot leak into a universe."""

    first = a_share_core_universe()
    second = a_share_core_universe()

    # Repetition is stable: there is no cache that can drift between calls.
    assert [first.resolve_provider_symbol("eastmoney", "1.000300") for _ in range(3)] == [
        "csi.300",
        "csi.300",
        "csi.300",
    ]

    # A registry built elsewhere is a separate object, not shared state.
    other = IndexProviderSymbolRegistry(
        (_alias("szse.component", "eastmoney", "0.399001"),)
    )
    assert other.require("eastmoney", "0.399001") == "szse.component"
    assert first.resolve_provider_symbol("eastmoney", "0.399001") is None
    assert second.resolve_provider_symbol("eastmoney", "0.399001") is None

    # Independently built universes still agree on every declared symbol.
    probes = (("csi", "000300"), ("eastmoney", "1.000300"), ("tencent", "sh000001"))
    assert [
        (first.resolve_provider_symbol(p, s), second.resolve_provider_symbol(p, s))
        for p, s in probes
    ] == [
        ("csi.300", "csi.300"),
        ("csi.300", "csi.300"),
        ("sse.composite", "sse.composite"),
    ]
    assert first.aliases == second.aliases


def test_require_index_still_uses_registry_owned_canonicality_errors() -> None:
    """No second grammar crept in: the registry still owns "canonical"."""

    universe = a_share_core_universe()

    with pytest.raises(TypeError):
        universe.require_index(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        universe.require_index("CSI.300")
    with pytest.raises(ValueError):
        universe.require_index(" csi.300")
    with pytest.raises(KeyError):
        universe.require_index("unknown.index")
    # A canonical id that is covered still resolves to its exact identity.
    assert universe.require_index("csi.300") == CSI_300
