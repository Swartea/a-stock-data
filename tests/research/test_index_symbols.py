from dataclasses import FrozenInstanceError

import pytest

from analysis.research.index_symbols import (
    IndexProviderSymbolAlias,
    IndexProviderSymbolRegistry,
)


def _alias(
    *,
    index_id: str = "cn.index.csi.000300",
    provider_id: str = "csi",
    provider_symbol: str = "000300",
) -> IndexProviderSymbolAlias:
    return IndexProviderSymbolAlias(
        index_id=index_id,
        provider_id=provider_id,
        provider_symbol=provider_symbol,
    )


def test_index_provider_symbol_alias_contract_surface_is_exact() -> None:
    assert IndexProviderSymbolAlias.contract_fields() == (
        "index_id",
        "provider_id",
        "provider_symbol",
    )


def test_alias_preserves_provider_symbol_verbatim() -> None:
    alias = _alias(provider_id="eastmoney", provider_symbol="1.000300")

    assert alias.provider_symbol == "1.000300"


def test_alias_is_immutable() -> None:
    alias = _alias()

    with pytest.raises(FrozenInstanceError):
        alias.provider_symbol = "000905"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("index_id", ""),
        ("index_id", "CN.INDEX.CSI.000300"),
        ("index_id", " cn.index.csi.000300"),
        ("provider_id", ""),
        ("provider_id", "EastMoney"),
        ("provider_id", " eastmoney"),
        ("provider_symbol", ""),
        ("provider_symbol", " 1.000300"),
        ("provider_symbol", "1.000300 "),
    ),
)
def test_alias_rejects_noncanonical_or_blank_fields(
    field_name: str,
    value: str,
) -> None:
    kwargs = {
        "index_id": "cn.index.csi.000300",
        "provider_id": "eastmoney",
        "provider_symbol": "1.000300",
    }
    kwargs[field_name] = value

    with pytest.raises(ValueError):
        IndexProviderSymbolAlias(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("index_id", 300),
        ("provider_id", 1),
        ("provider_symbol", 300),
    ),
)
def test_alias_rejects_non_string_fields(
    field_name: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {
        "index_id": "cn.index.csi.000300",
        "provider_id": "eastmoney",
        "provider_symbol": "1.000300",
    }
    kwargs[field_name] = value

    with pytest.raises(TypeError):
        IndexProviderSymbolAlias(**kwargs)  # type: ignore[arg-type]


def test_registry_resolves_multiple_provider_symbols_to_same_index() -> None:
    registry = IndexProviderSymbolRegistry(
        (
            _alias(provider_id="csi", provider_symbol="000300"),
            _alias(provider_id="eastmoney", provider_symbol="1.000300"),
            _alias(provider_id="sina", provider_symbol="sh000300"),
        )
    )

    assert registry.resolve("csi", "000300") == "cn.index.csi.000300"
    assert registry.resolve("eastmoney", "1.000300") == "cn.index.csi.000300"
    assert registry.resolve("sina", "sh000300") == "cn.index.csi.000300"


def test_unknown_symbol_stays_unknown_instead_of_being_guessed() -> None:
    registry = IndexProviderSymbolRegistry(
        (_alias(provider_id="eastmoney", provider_symbol="1.000300"),)
    )

    assert registry.resolve("eastmoney", "000300") is None
    assert registry.resolve("eastmoney", "SH000300") is None


def test_lookup_is_exact_and_does_not_case_normalize_provider_symbol() -> None:
    registry = IndexProviderSymbolRegistry(
        (_alias(provider_id="sina", provider_symbol="sh000300"),)
    )

    assert registry.resolve("sina", "sh000300") == "cn.index.csi.000300"
    assert registry.resolve("sina", "SH000300") is None


def test_provider_id_lookup_requires_canonical_id() -> None:
    registry = IndexProviderSymbolRegistry(
        (_alias(provider_id="eastmoney", provider_symbol="1.000300"),)
    )

    assert registry.resolve("eastmoney", "1.000300") == "cn.index.csi.000300"
    with pytest.raises(ValueError):
        registry.resolve("EastMoney", "1.000300")


def test_same_provider_symbol_cannot_be_registered_twice() -> None:
    registry = IndexProviderSymbolRegistry((_alias(),))

    with pytest.raises(ValueError, match="provider index symbol collision"):
        registry.register(_alias())


def test_provider_symbol_collision_cannot_point_to_different_index() -> None:
    registry = IndexProviderSymbolRegistry(
        (_alias(provider_id="eastmoney", provider_symbol="1.000300"),)
    )

    with pytest.raises(ValueError, match="provider index symbol collision"):
        registry.register(
            _alias(
                index_id="cn.index.csi.000905",
                provider_id="eastmoney",
                provider_symbol="1.000300",
            )
        )


def test_same_index_can_have_multiple_aliases_within_one_provider() -> None:
    registry = IndexProviderSymbolRegistry(
        (
            _alias(provider_id="eastmoney", provider_symbol="1.000300"),
            _alias(provider_id="eastmoney", provider_symbol="SH000300"),
        )
    )

    assert registry.resolve("eastmoney", "1.000300") == "cn.index.csi.000300"
    assert registry.resolve("eastmoney", "SH000300") == "cn.index.csi.000300"


def test_aliases_for_returns_registration_order_tuple() -> None:
    first = _alias(provider_id="csi", provider_symbol="000300")
    second = _alias(provider_id="eastmoney", provider_symbol="1.000300")
    registry = IndexProviderSymbolRegistry((first, second))

    assert registry.aliases_for("cn.index.csi.000300") == (first, second)
    assert registry.aliases_for("cn.index.csi.000905") == ()


def test_require_fails_explicitly_for_unknown_symbol() -> None:
    registry = IndexProviderSymbolRegistry((_alias(),))

    assert registry.require("csi", "000300") == "cn.index.csi.000300"
    with pytest.raises(KeyError, match="unknown provider index symbol"):
        registry.require("csi", "000905")


def test_registry_rejects_non_alias_registration() -> None:
    registry = IndexProviderSymbolRegistry()

    with pytest.raises(TypeError):
        registry.register("000300")  # type: ignore[arg-type]


def test_contract_does_not_mix_index_data_or_publisher_fields() -> None:
    forbidden = {
        "publisher",
        "local_code",
        "name",
        "constituents",
        "members",
        "weights",
        "valuation",
        "quote",
        "industry",
        "theme",
        "fetched_at",
        "effective_from",
        "effective_to",
    }

    assert forbidden.isdisjoint(IndexProviderSymbolAlias.contract_fields())
