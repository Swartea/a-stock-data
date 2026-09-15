from dataclasses import FrozenInstanceError

import pytest

from analysis.research.providers import (
    ProviderRegistry,
    ProviderSpec,
    build_default_provider_registry,
)


def test_provider_contract_stays_identity_only():
    assert ProviderSpec.contract_fields() == (
        "provider_id",
        "display_name",
        "provider_family",
        "aliases",
    )


def test_provider_spec_is_immutable():
    provider = ProviderSpec("fixture", "Fixture", "fixture")

    with pytest.raises(FrozenInstanceError):
        provider.provider_id = "changed"  # type: ignore[misc]


def test_provider_id_and_family_require_stable_lowercase_tokens():
    with pytest.raises(ValueError, match="provider_id"):
        ProviderSpec("EastMoney", "东方财富", "eastmoney")

    with pytest.raises(ValueError, match="provider_family"):
        ProviderSpec("eastmoney", "东方财富", "EastMoney")


def test_aliases_must_be_tuple_and_unique_case_insensitively():
    with pytest.raises(TypeError, match="tuple"):
        ProviderSpec("fixture", "Fixture", "fixture", ["alias"])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="duplicate provider alias"):
        ProviderSpec("fixture", "Fixture", "fixture", ("Alias", "alias"))


def test_registry_resolves_canonical_ids_and_aliases_case_insensitively():
    registry = ProviderRegistry(
        (ProviderSpec("eastmoney", "东方财富", "eastmoney", ("EM", "东方财富")),)
    )

    assert registry.require("eastmoney").provider_id == "eastmoney"
    assert registry.require(" em ").provider_id == "eastmoney"
    assert registry.require("东方财富").provider_id == "eastmoney"


def test_unknown_provider_stays_unknown_instead_of_being_guessed():
    registry = build_default_provider_registry()

    assert registry.resolve("datacenter RPT_F10_FINANCE_MAINFINADATA") is None
    assert registry.resolve("eastmoney.search-api-web.some-new-endpoint") is None


def test_registry_rejects_alias_collisions_between_providers():
    registry = ProviderRegistry(
        (ProviderSpec("first", "First", "first", ("shared",)),)
    )

    with pytest.raises(ValueError, match="collision"):
        registry.register(ProviderSpec("second", "Second", "second", ("SHARED",)))


def test_registry_rejects_canonical_id_colliding_with_existing_alias():
    registry = ProviderRegistry(
        (ProviderSpec("first", "First", "first", ("second",)),)
    )

    with pytest.raises(ValueError, match="collision"):
        registry.register(ProviderSpec("second", "Second", "second"))


def test_default_registry_keeps_ths_and_iwencai_distinct_but_same_family():
    registry = build_default_provider_registry()

    ths = registry.require("ths")
    iwencai = registry.require("iwencai")

    assert ths.provider_id != iwencai.provider_id
    assert ths.provider_family == "hexin"
    assert iwencai.provider_family == "hexin"


def test_default_registry_covers_current_and_planned_official_provider_identities():
    registry = build_default_provider_registry()
    provider_ids = {provider.provider_id for provider in registry.all()}

    assert {
        "eastmoney",
        "cninfo",
        "ths",
        "sina",
        "tencent",
        "baostock",
        "mootdx",
        "swsresearch",
        "sse",
        "szse",
        "bse",
        "csi",
        "cni",
    } <= provider_ids


def test_require_unknown_provider_is_explicit_failure():
    registry = build_default_provider_registry()

    with pytest.raises(KeyError, match="unknown provider"):
        registry.require("not-a-provider")


def test_all_returns_immutable_registration_order_snapshot():
    first = ProviderSpec("first", "First", "first")
    second = ProviderSpec("second", "Second", "second")
    registry = ProviderRegistry((first, second))

    assert registry.all() == (first, second)
    assert isinstance(registry.all(), tuple)
