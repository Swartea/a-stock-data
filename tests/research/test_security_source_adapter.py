import pytest

from analysis.research.security_lifecycle import ListingState
from analysis.research.security_master import Exchange, SecurityType
from analysis.research.security_source_adapter import (
    SecurityMasterBatch,
    SecurityMasterSourceError,
    normalize_security_master_payload,
)


def _payload() -> dict[str, object]:
    return {
        "securities": [
            {
                "security_id": "cn.sse.600693",
                "exchange": "sse",
                "local_code": "600693",
                "security_type": "equity",
                "provider_symbols": ["1.600693", "SH600693"],
                "lifecycle": [
                    {
                        "state": "listed",
                        "effective_from": "2020-01-01T00:00:00+08:00",
                        "effective_to": "2024-01-01T00:00:00+08:00",
                        "published_at": "2019-12-20T09:00:00+08:00",
                    },
                    {
                        "state": "delisted",
                        "effective_from": "2024-01-01T00:00:00+08:00",
                        "effective_to": None,
                        "published_at": "2023-12-15T09:00:00+08:00",
                    },
                ],
            }
        ]
    }


def test_normalizes_identity_aliases_lifecycle_and_registry() -> None:
    batch = normalize_security_master_payload(
        _payload(),
        provider_id="eastmoney",
        fetched_at="2026-09-18T09:00:00+08:00",
    )

    assert isinstance(batch, SecurityMasterBatch)
    assert len(batch.identities) == 1
    identity = batch.identities[0]
    assert identity.security_id == "cn.sse.600693"
    assert identity.exchange is Exchange.SSE
    assert identity.local_code == "600693"
    assert identity.security_type is SecurityType.EQUITY

    assert [alias.provider_symbol for alias in batch.aliases] == [
        "1.600693",
        "SH600693",
    ]
    assert all(alias.provider_id == "eastmoney" for alias in batch.aliases)
    assert all(alias.security_id == "cn.sse.600693" for alias in batch.aliases)

    assert [record.state for record in batch.lifecycle_records] == [
        ListingState.LISTED,
        ListingState.DELISTED,
    ]
    assert batch.lifecycle_records[0].time.fetched_at == (
        "2026-09-18T09:00:00+08:00"
    )
    assert batch.lifecycle_records[0].time.published_at == (
        "2019-12-20T09:00:00+08:00"
    )

    registry = batch.to_registry()
    assert registry.resolve_provider_symbol("eastmoney", "1.600693") == (
        "cn.sse.600693"
    )
    assert registry.listing_state_on(
        "cn.sse.600693",
        "2023-12-31T23:59:59+08:00",
    ) is ListingState.LISTED
    assert registry.listing_state_on(
        "cn.sse.600693",
        "2024-01-01T00:00:00+08:00",
    ) is ListingState.DELISTED


def test_empty_securities_payload_is_valid_empty_batch() -> None:
    batch = normalize_security_master_payload(
        {"securities": []},
        provider_id="eastmoney",
        fetched_at="2026-09-18T09:00:00+08:00",
    )

    assert batch.identities == ()
    assert batch.aliases == ()
    assert batch.lifecycle_records == ()
    assert batch.to_registry().all_identities() == ()


def test_payload_requires_securities_field() -> None:
    with pytest.raises(SecurityMasterSourceError, match="contain securities"):
        normalize_security_master_payload(
            {},
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


@pytest.mark.parametrize("bad_value", ("600693", b"600693", {"x": 1}))
def test_securities_must_be_non_string_sequence(bad_value: object) -> None:
    with pytest.raises(SecurityMasterSourceError, match="securities must be a sequence"):
        normalize_security_master_payload(
            {"securities": bad_value},
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


def test_security_rows_must_be_mappings() -> None:
    with pytest.raises(SecurityMasterSourceError, match=r"securities\[0\] must be"):
        normalize_security_master_payload(
            {"securities": ["600693"]},
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("security_id", None),
        ("security_id", ""),
        ("exchange", "sh"),
        ("exchange", "SSE"),
        ("local_code", None),
        ("local_code", "sh.600693"),
        ("security_type", "stock"),
        ("security_type", "EQUITY"),
    ),
)
def test_identity_fields_are_explicit_and_not_inferred(
    field_name: str,
    bad_value: object,
) -> None:
    payload = _payload()
    row = payload["securities"][0]  # type: ignore[index]
    row[field_name] = bad_value  # type: ignore[index]

    with pytest.raises(SecurityMasterSourceError):
        normalize_security_master_payload(
            payload,
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


def test_provider_symbols_are_preserved_exactly() -> None:
    payload = _payload()
    row = payload["securities"][0]  # type: ignore[index]
    row["provider_symbols"] = ["sh.600693", "SH.600693"]  # type: ignore[index]

    batch = normalize_security_master_payload(
        payload,
        provider_id="baostock",
        fetched_at="2026-09-18T09:00:00+08:00",
    )

    assert [alias.provider_symbol for alias in batch.aliases] == [
        "sh.600693",
        "SH.600693",
    ]


def test_provider_symbol_is_not_derived_when_missing() -> None:
    payload = _payload()
    row = payload["securities"][0]  # type: ignore[index]
    row.pop("provider_symbols")  # type: ignore[union-attr]

    batch = normalize_security_master_payload(
        payload,
        provider_id="eastmoney",
        fetched_at="2026-09-18T09:00:00+08:00",
    )

    assert batch.aliases == ()


def test_invalid_provider_symbol_shape_is_rejected() -> None:
    payload = _payload()
    row = payload["securities"][0]  # type: ignore[index]
    row["provider_symbols"] = ["1.600693", 600693]  # type: ignore[index]

    with pytest.raises(SecurityMasterSourceError, match="provider symbol must be"):
        normalize_security_master_payload(
            payload,
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


def test_lifecycle_defaults_to_empty_without_inference() -> None:
    payload = _payload()
    row = payload["securities"][0]  # type: ignore[index]
    row.pop("lifecycle")  # type: ignore[union-attr]

    batch = normalize_security_master_payload(
        payload,
        provider_id="eastmoney",
        fetched_at="2026-09-18T09:00:00+08:00",
    )

    assert batch.lifecycle_records == ()


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("state", "LISTED"),
        ("state", "halted"),
        ("effective_from", None),
        ("effective_from", ""),
        ("effective_to", ""),
        ("published_at", ""),
    ),
)
def test_lifecycle_fields_are_strict(
    field_name: str,
    bad_value: object,
) -> None:
    payload = _payload()
    lifecycle = payload["securities"][0]["lifecycle"][0]  # type: ignore[index]
    lifecycle[field_name] = bad_value  # type: ignore[index]

    with pytest.raises(SecurityMasterSourceError):
        normalize_security_master_payload(
            payload,
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


def test_duplicate_security_ids_are_rejected_by_registry_integrity() -> None:
    payload = _payload()
    duplicate = {
        "security_id": "cn.sse.600693",
        "exchange": "sse",
        "local_code": "600693",
        "security_type": "equity",
    }
    payload["securities"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(
        SecurityMasterSourceError,
        match="registry integrity",
    ):
        normalize_security_master_payload(
            payload,
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


def test_provider_symbol_collision_is_rejected_by_registry_integrity() -> None:
    payload = _payload()
    payload["securities"].append(  # type: ignore[union-attr]
        {
            "security_id": "cn.sse.600000",
            "exchange": "sse",
            "local_code": "600000",
            "security_type": "equity",
            "provider_symbols": ["1.600693"],
        }
    )

    with pytest.raises(
        SecurityMasterSourceError,
        match="registry integrity",
    ):
        normalize_security_master_payload(
            payload,
            provider_id="eastmoney",
            fetched_at="2026-09-18T09:00:00+08:00",
        )


@pytest.mark.parametrize(
    "provider_id",
    ("", "EastMoney", " eastmoney", "eastmoney "),
)
def test_provider_id_must_be_explicit_canonical_token(provider_id: str) -> None:
    with pytest.raises(ValueError):
        normalize_security_master_payload(
            _payload(),
            provider_id=provider_id,
            fetched_at="2026-09-18T09:00:00+08:00",
        )


@pytest.mark.parametrize("fetched_at", ("", None, 123))
def test_fetched_at_must_be_explicit_nonempty_string(fetched_at: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_security_master_payload(
            _payload(),
            provider_id="eastmoney",
            fetched_at=fetched_at,  # type: ignore[arg-type]
        )


def test_adapter_has_no_network_or_pipeline_surface() -> None:
    forbidden = {
        "fetch",
        "requests",
        "httpx",
        "pipeline",
        "infer_exchange",
        "normalize_provider_symbol",
    }

    public_names = set(dir(SecurityMasterBatch)) | {
        normalize_security_master_payload.__name__
    }
    assert forbidden.isdisjoint(public_names)
