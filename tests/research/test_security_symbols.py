from dataclasses import FrozenInstanceError

import pytest

from analysis.research.security_symbols import (
    ProviderSymbolAlias,
    ProviderSymbolRegistry,
)


def _alias(
    security_id: str = "cn.sse.600693",
    provider_id: str = "eastmoney",
    provider_symbol: str = "1.600693",
) -> ProviderSymbolAlias:
    return ProviderSymbolAlias(
        security_id=security_id,
        provider_id=provider_id,
        provider_symbol=provider_symbol,
    )


def test_provider_symbol_alias_contract_surface_is_exact() -> None:
    assert ProviderSymbolAlias.contract_fields() == (
        "security_id",
        "provider_id",
        "provider_symbol",
    )


def test_alias_preserves_provider_symbol_verbatim() -> None:
    alias = _alias(provider_symbol="sh.600693")
    assert alias.provider_symbol == "sh.600693"


def test_alias_is_immutable() -> None:
    alias = _alias()
    with pytest.raises(FrozenInstanceError):
        alias.provider_symbol = "SH600693"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("security_id", ""),
        ("security_id", "CN.SSE.600693"),
        ("security_id", " cn.sse.600693"),
        ("provider_id", ""),
        ("provider_id", "EastMoney"),
        ("provider_id", " eastmoney"),
        ("provider_symbol", ""),
        ("provider_symbol", " 1.600693"),
        ("provider_symbol", "1.600693 "),
    ),
)
def test_alias_rejects_noncanonical_or_blank_fields(
    field_name: str, value: str
) -> None:
    kwargs = {
        "security_id": "cn.sse.600693",
        "provider_id": "eastmoney",
        "provider_symbol": "1.600693",
    }
    kwargs[field_name] = value

    with pytest.raises(ValueError):
        ProviderSymbolAlias(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("security_id", 600693),
        ("provider_id", 1),
        ("provider_symbol", 600693),
    ),
)
def test_alias_rejects_non_string_identity_fields(
    field_name: str, value: object
) -> None:
    kwargs: dict[str, object] = {
        "security_id": "cn.sse.600693",
        "provider_id": "eastmoney",
        "provider_symbol": "1.600693",
    }
    kwargs[field_name] = value

    with pytest.raises(TypeError):
        ProviderSymbolAlias(**kwargs)  # type: ignore[arg-type]


def test_registry_resolves_multiple_provider_symbols_to_same_security() -> None:
    registry = ProviderSymbolRegistry(
        (
            _alias(provider_id="eastmoney", provider_symbol="1.600693"),
            _alias(provider_id="baostock", provider_symbol="sh.600693"),
            _alias(provider_id="sina", provider_symbol="sh600693"),
        )
    )

    assert registry.resolve("eastmoney", "1.600693") == "cn.sse.600693"
    assert registry.resolve("baostock", "sh.600693") == "cn.sse.600693"
    assert registry.resolve("sina", "sh600693") == "cn.sse.600693"


def test_unknown_symbol_stays_unknown_instead_of_being_guessed() -> None:
    registry = ProviderSymbolRegistry((_alias(),))

    assert registry.resolve("eastmoney", "600693") is None
    assert registry.resolve("eastmoney", "SH600693") is None


def test_lookup_is_exact_and_does_not_case_normalize_provider_symbol() -> None:
    registry = ProviderSymbolRegistry(
        (_alias(provider_id="baostock", provider_symbol="sh.600693"),)
    )

    assert registry.resolve("baostock", "sh.600693") == "cn.sse.600693"
    assert registry.resolve("baostock", "SH.600693") is None


def test_provider_id_lookup_requires_canonical_id_not_alias_guessing() -> None:
    registry = ProviderSymbolRegistry((_alias(),))

    assert registry.resolve("eastmoney", "1.600693") == "cn.sse.600693"
    with pytest.raises(ValueError):
        registry.resolve("EastMoney", "1.600693")


def test_same_provider_symbol_cannot_map_twice_even_to_same_security() -> None:
    registry = ProviderSymbolRegistry((_alias(),))

    with pytest.raises(ValueError, match="provider symbol collision"):
        registry.register(_alias())


def test_provider_symbol_collision_cannot_point_to_different_security() -> None:
    registry = ProviderSymbolRegistry((_alias(),))

    with pytest.raises(ValueError, match="provider symbol collision"):
        registry.register(
            _alias(
                security_id="cn.sse.600000",
                provider_symbol="1.600693",
            )
        )


def test_same_security_can_have_multiple_aliases_within_one_provider() -> None:
    registry = ProviderSymbolRegistry(
        (
            _alias(provider_symbol="1.600693"),
            _alias(provider_symbol="SH600693"),
        )
    )

    assert registry.resolve("eastmoney", "1.600693") == "cn.sse.600693"
    assert registry.resolve("eastmoney", "SH600693") == "cn.sse.600693"


def test_aliases_for_returns_immutable_registration_order_snapshot() -> None:
    first = _alias(provider_id="eastmoney", provider_symbol="1.600693")
    second = _alias(provider_id="baostock", provider_symbol="sh.600693")
    registry = ProviderSymbolRegistry((first, second))

    assert registry.aliases_for("cn.sse.600693") == (first, second)
    assert registry.aliases_for("cn.szse.000001") == ()


def test_require_fails_explicitly_for_unknown_symbol() -> None:
    registry = ProviderSymbolRegistry((_alias(),))

    assert registry.require("eastmoney", "1.600693") == "cn.sse.600693"
    with pytest.raises(KeyError, match="unknown provider symbol"):
        registry.require("eastmoney", "600693")


def test_registry_rejects_non_alias_registration() -> None:
    registry = ProviderSymbolRegistry()

    with pytest.raises(TypeError):
        registry.register("1.600693")  # type: ignore[arg-type]


def test_contract_contains_no_exchange_inference_or_endpoint_fields() -> None:
    forbidden = {
        "exchange",
        "local_code",
        "source",
        "url",
        "endpoint",
        "fetched_at",
        "effective_from",
        "effective_to",
        "name",
    }

    assert forbidden.isdisjoint(ProviderSymbolAlias.contract_fields())
