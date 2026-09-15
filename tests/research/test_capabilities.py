from dataclasses import FrozenInstanceError

import pytest

from analysis.research.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    build_default_capability_registry,
)


def test_capability_contract_surface_is_small_and_provider_free():
    assert CapabilitySpec.contract_fields() == (
        "capability_id",
        "display_name",
        "domain",
        "description",
    )

    spec = CapabilitySpec("stock.news", "个股新闻", "stock")
    assert not hasattr(spec, "provider")
    assert not hasattr(spec, "provider_id")
    assert not hasattr(spec, "endpoint")
    assert not hasattr(spec, "url")
    assert not hasattr(spec, "priority")
    assert not hasattr(spec, "fallback")


def test_capability_identity_must_be_namespaced_by_domain():
    with pytest.raises(ValueError):
        CapabilitySpec("news", "个股新闻", "stock")

    with pytest.raises(ValueError):
        CapabilitySpec("market.news", "个股新闻", "stock")

    with pytest.raises(ValueError):
        CapabilitySpec("Stock.News", "个股新闻", "stock")


def test_capability_display_name_is_required():
    with pytest.raises(ValueError):
        CapabilitySpec("stock.news", "   ", "stock")


def test_capability_description_must_be_text():
    with pytest.raises(TypeError):
        CapabilitySpec("stock.news", "个股新闻", "stock", description=None)  # type: ignore[arg-type]


def test_capability_spec_is_immutable():
    spec = CapabilitySpec("stock.news", "个股新闻", "stock")

    with pytest.raises(FrozenInstanceError):
        spec.domain = "market"  # type: ignore[misc]


def test_registry_resolves_semantic_identity_and_keeps_unknown_unknown():
    registry = CapabilityRegistry(
        (
            CapabilitySpec("stock.news", "个股新闻", "stock"),
            CapabilitySpec("index.membership", "指数成分", "index"),
        )
    )

    assert registry.resolve("stock.news").display_name == "个股新闻"
    assert registry.resolve(" STOCK.NEWS ").capability_id == "stock.news"
    assert registry.resolve("stock.unknown") is None

    with pytest.raises(KeyError):
        registry.require("stock.unknown")


def test_registry_rejects_duplicate_capability_ids():
    registry = CapabilityRegistry(
        (CapabilitySpec("stock.news", "个股新闻", "stock"),)
    )

    with pytest.raises(ValueError):
        registry.register(CapabilitySpec("stock.news", "新闻副本", "stock"))


def test_registry_filters_by_domain_without_mixing_industry_and_theme():
    registry = CapabilityRegistry(
        (
            CapabilitySpec("industry.taxonomy", "行业分类体系", "industry"),
            CapabilitySpec("industry.membership", "行业成员关系", "industry"),
            CapabilitySpec("theme.taxonomy", "题材分类体系", "theme"),
        )
    )

    assert tuple(item.capability_id for item in registry.for_domain("industry")) == (
        "industry.taxonomy",
        "industry.membership",
    )
    assert tuple(item.capability_id for item in registry.for_domain("theme")) == (
        "theme.taxonomy",
    )


def test_default_catalog_contains_current_and_planned_foundation_capabilities():
    registry = build_default_capability_registry()

    expected = {
        "reference.security_master",
        "market.trading_calendar",
        "index.membership",
        "index.weights",
        "industry.taxonomy",
        "theme.taxonomy",
        "stock.quote",
        "stock.valuation_history",
        "stock.margin",
        "stock.announcements",
        "stock.finance",
        "stock.research_reports",
        "stock.news",
    }

    assert expected.issubset({item.capability_id for item in registry.all()})


def test_default_catalog_ids_are_unique_and_domain_consistent():
    registry = build_default_capability_registry()
    capabilities = registry.all()
    ids = [item.capability_id for item in capabilities]

    assert len(ids) == len(set(ids))
    assert all(item.capability_id.startswith(f"{item.domain}.") for item in capabilities)


def test_default_registry_instances_do_not_share_mutable_state():
    first = build_default_capability_registry()
    second = build_default_capability_registry()

    first.register(CapabilitySpec("stock.custom_probe", "测试能力", "stock"))

    assert first.resolve("stock.custom_probe") is not None
    assert second.resolve("stock.custom_probe") is None


def test_capability_catalog_does_not_encode_endpoint_count():
    registry = build_default_capability_registry()

    # The Research Engine capability catalog is semantic and additive.  Its
    # length must not be treated as the repository's public endpoint count.
    assert len(registry.all()) > 0
    assert all("endpoint" not in item.capability_id for item in registry.all())
