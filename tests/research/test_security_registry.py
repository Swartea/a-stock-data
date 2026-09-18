import pytest

from analysis.research.security_lifecycle import ListingLifecycleRecord, ListingState
from analysis.research.security_master import Exchange, SecurityIdentity, SecurityType
from analysis.research.security_registry import SecurityMasterRegistry
from analysis.research.security_symbols import ProviderSymbolAlias
from analysis.research.time_semantics import TimeMetadata


def _identity(
    security_id: str = "cn.sse.600693",
    local_code: str = "600693",
) -> SecurityIdentity:
    return SecurityIdentity(
        security_id=security_id,
        exchange=Exchange.SSE,
        local_code=local_code,
        security_type=SecurityType.EQUITY,
    )


def _alias(
    *,
    security_id: str = "cn.sse.600693",
    provider_id: str = "eastmoney",
    provider_symbol: str = "1.600693",
) -> ProviderSymbolAlias:
    return ProviderSymbolAlias(
        security_id=security_id,
        provider_id=provider_id,
        provider_symbol=provider_symbol,
    )


def _lifecycle(
    *,
    security_id: str = "cn.sse.600693",
    state: ListingState = ListingState.LISTED,
    effective_from: str = "2020-01-01T00:00:00+08:00",
    effective_to: str | None = None,
) -> ListingLifecycleRecord:
    return ListingLifecycleRecord(
        security_id=security_id,
        state=state,
        time=TimeMetadata(
            fetched_at="2026-09-18T09:00:00+08:00",
            effective_from=effective_from,
            effective_to=effective_to,
        ),
    )


def test_registry_composes_identity_alias_and_lifecycle_lookup() -> None:
    identity = _identity()
    alias = _alias()
    lifecycle = _lifecycle()
    registry = SecurityMasterRegistry(
        identities=(identity,),
        aliases=(alias,),
        lifecycle_records=(lifecycle,),
    )

    assert registry.identity("cn.sse.600693") == identity
    assert registry.resolve_provider_symbol("eastmoney", "1.600693") == (
        "cn.sse.600693"
    )
    assert registry.identity_for_provider_symbol("eastmoney", "1.600693") == identity
    assert registry.aliases_for("cn.sse.600693") == (alias,)
    assert registry.lifecycle_records("cn.sse.600693") == (lifecycle,)
    assert registry.listing_state_on(
        "cn.sse.600693",
        "2026-09-18T09:00:00+08:00",
    ) is ListingState.LISTED


def test_unknown_identity_and_provider_symbol_stay_unknown() -> None:
    registry = SecurityMasterRegistry(identities=(_identity(),))

    assert registry.identity("cn.sse.600000") is None
    assert registry.resolve_provider_symbol("eastmoney", "1.600000") is None
    assert registry.identity_for_provider_symbol("eastmoney", "1.600000") is None


def test_require_identity_fails_explicitly_for_unknown_security() -> None:
    registry = SecurityMasterRegistry(identities=(_identity(),))

    with pytest.raises(KeyError, match="unknown security_id"):
        registry.require_identity("cn.sse.600000")


def test_duplicate_security_id_is_rejected() -> None:
    registry = SecurityMasterRegistry(identities=(_identity(),))

    with pytest.raises(ValueError, match="duplicate security_id"):
        registry.register_identity(_identity())


def test_alias_must_reference_registered_identity() -> None:
    registry = SecurityMasterRegistry()

    with pytest.raises(KeyError, match="unknown security_id"):
        registry.register_alias(_alias())


def test_lifecycle_must_reference_registered_identity() -> None:
    registry = SecurityMasterRegistry()

    with pytest.raises(KeyError, match="unknown security_id"):
        registry.register_lifecycle(_lifecycle())


def test_constructor_enforces_referential_integrity() -> None:
    with pytest.raises(KeyError, match="unknown security_id"):
        SecurityMasterRegistry(
            aliases=(_alias(),),
        )

    with pytest.raises(KeyError, match="unknown security_id"):
        SecurityMasterRegistry(
            lifecycle_records=(_lifecycle(),),
        )


def test_alias_collision_remains_owned_by_symbol_registry_contract() -> None:
    registry = SecurityMasterRegistry(
        identities=(_identity(),),
        aliases=(_alias(),),
    )

    with pytest.raises(ValueError, match="provider symbol collision"):
        registry.register_alias(_alias())


def test_listing_state_changes_over_time_for_same_security_id() -> None:
    listed = _lifecycle(
        state=ListingState.LISTED,
        effective_from="2020-01-01T00:00:00+08:00",
        effective_to="2024-01-01T00:00:00+08:00",
    )
    delisted = _lifecycle(
        state=ListingState.DELISTED,
        effective_from="2024-01-01T00:00:00+08:00",
    )
    registry = SecurityMasterRegistry(
        identities=(_identity(),),
        lifecycle_records=(listed, delisted),
    )

    assert registry.listing_state_on(
        "cn.sse.600693",
        "2023-12-31T23:59:59+08:00",
    ) is ListingState.LISTED
    assert registry.listing_state_on(
        "cn.sse.600693",
        "2024-01-01T00:00:00+08:00",
    ) is ListingState.DELISTED


def test_missing_effective_lifecycle_returns_unknown_none() -> None:
    registry = SecurityMasterRegistry(
        identities=(_identity(),),
        lifecycle_records=(
            _lifecycle(effective_from="2024-01-01T00:00:00+08:00"),
        ),
    )

    assert (
        registry.listing_state_on(
            "cn.sse.600693",
            "2023-01-01T00:00:00+08:00",
        )
        is None
    )


def test_overlapping_lifecycle_records_are_not_silently_prioritized() -> None:
    first = _lifecycle(
        state=ListingState.LISTED,
        effective_from="2020-01-01T00:00:00+08:00",
        effective_to="2025-01-01T00:00:00+08:00",
    )
    second = _lifecycle(
        state=ListingState.SUSPENDED,
        effective_from="2024-01-01T00:00:00+08:00",
        effective_to="2024-06-01T00:00:00+08:00",
    )
    registry = SecurityMasterRegistry(
        identities=(_identity(),),
        lifecycle_records=(first, second),
    )

    with pytest.raises(ValueError, match="overlapping lifecycle records"):
        registry.listing_state_on(
            "cn.sse.600693",
            "2024-03-01T00:00:00+08:00",
        )


def test_aliases_and_lifecycle_snapshots_are_immutable_tuples() -> None:
    alias = _alias()
    lifecycle = _lifecycle()
    registry = SecurityMasterRegistry(
        identities=(_identity(),),
        aliases=(alias,),
        lifecycle_records=(lifecycle,),
    )

    assert isinstance(registry.aliases_for("cn.sse.600693"), tuple)
    assert isinstance(registry.lifecycle_records("cn.sse.600693"), tuple)
    assert isinstance(registry.all_identities(), tuple)


def test_all_identities_preserves_registration_order() -> None:
    first = _identity()
    second = SecurityIdentity(
        security_id="cn.sse.600000",
        exchange=Exchange.SSE,
        local_code="600000",
        security_type=SecurityType.EQUITY,
    )
    registry = SecurityMasterRegistry(identities=(first, second))

    assert registry.all_identities() == (first, second)


@pytest.mark.parametrize(
    "security_id",
    (
        "",
        "CN.SSE.600693",
        " cn.sse.600693",
    ),
)
def test_identity_lookup_requires_canonical_security_id(security_id: str) -> None:
    registry = SecurityMasterRegistry(identities=(_identity(),))

    with pytest.raises(ValueError):
        registry.identity(security_id)


def test_registry_rejects_wrong_registration_types() -> None:
    registry = SecurityMasterRegistry()

    with pytest.raises(TypeError):
        registry.register_identity("cn.sse.600693")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        registry.register_alias("1.600693")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        registry.register_lifecycle("listed")  # type: ignore[arg-type]


def test_registry_does_not_add_fetching_or_inference_surface() -> None:
    public_methods = {
        name
        for name in dir(SecurityMasterRegistry)
        if not name.startswith("_")
    }
    forbidden = {
        "fetch",
        "refresh",
        "infer_exchange",
        "normalize_symbol",
        "resolve_name",
        "pipeline",
    }

    assert forbidden.isdisjoint(public_methods)
