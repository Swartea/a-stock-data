from dataclasses import FrozenInstanceError

import pytest

from analysis.research.security_master import Exchange, SecurityIdentity, SecurityType


def _identity(**overrides: object) -> SecurityIdentity:
    values: dict[str, object] = {
        "security_id": "cn.sse.600693",
        "exchange": Exchange.SSE,
        "local_code": "600693",
        "security_type": SecurityType.EQUITY,
    }
    values.update(overrides)
    return SecurityIdentity(**values)  # type: ignore[arg-type]


def test_security_identity_contract_surface_is_small_and_exact() -> None:
    assert SecurityIdentity.contract_fields() == (
        "security_id",
        "exchange",
        "local_code",
        "security_type",
    )


def test_exchange_values_are_stable_and_mainland_only() -> None:
    assert tuple(item.value for item in Exchange) == ("sse", "szse", "bse")


def test_security_type_values_are_stable() -> None:
    assert tuple(item.value for item in SecurityType) == (
        "equity",
        "etf",
        "fund",
        "bond",
        "reit",
        "other",
    )


def test_identity_preserves_explicit_stable_id_and_local_code_separately() -> None:
    identity = _identity(
        security_id="security-000001",
        exchange=Exchange.SZSE,
        local_code="000001",
    )

    assert identity.security_id == "security-000001"
    assert identity.exchange is Exchange.SZSE
    assert identity.local_code == "000001"
    assert identity.security_id != identity.local_code


def test_identity_is_immutable() -> None:
    identity = _identity()

    with pytest.raises(FrozenInstanceError):
        identity.local_code = "600694"  # type: ignore[misc]


def test_raw_strings_are_not_silently_coerced_to_enums() -> None:
    with pytest.raises(TypeError, match="exchange must be Exchange"):
        _identity(exchange="sse")

    with pytest.raises(TypeError, match="security_type must be SecurityType"):
        _identity(security_type="equity")


def test_security_id_requires_canonical_machine_token() -> None:
    for value in (
        "",
        " CN.SSE.600693",
        "cn.sse.600693 ",
        "CN.SSE.600693",
        "cn/sse/600693",
        "cn sse 600693",
    ):
        with pytest.raises((TypeError, ValueError)):
            _identity(security_id=value)


def test_security_id_must_be_explicit_string() -> None:
    with pytest.raises(TypeError, match="security_id must be a string"):
        _identity(security_id=600693)


def test_local_code_requires_canonical_exchange_local_token() -> None:
    for value in ("", " 600693", "600693 ", "ab123", "SH.600693", "sh.600693"):
        with pytest.raises((TypeError, ValueError)):
            _identity(local_code=value)


def test_local_code_accepts_provider_neutral_exchange_codes() -> None:
    assert _identity(local_code="600693").local_code == "600693"
    assert _identity(local_code="ABC123").local_code == "ABC123"


def test_identity_contract_does_not_embed_mutable_or_provider_specific_fields() -> None:
    fields = set(SecurityIdentity.contract_fields())

    assert fields.isdisjoint(
        {
            "name",
            "short_name",
            "provider",
            "provider_id",
            "provider_symbol",
            "industry",
            "theme",
            "region",
            "listed_at",
            "delisted_at",
            "status",
        }
    )


def test_contract_does_not_guess_exchange_or_security_id_from_code() -> None:
    with pytest.raises(TypeError):
        SecurityIdentity(  # type: ignore[call-arg]
            local_code="600693",
            security_type=SecurityType.EQUITY,
        )
