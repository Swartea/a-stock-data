from dataclasses import FrozenInstanceError

import pytest

from analysis.research.index_registry import IndexIdentity, IndexPublisher


def _identity(
    *,
    index_id: str = "cn.index.csi.000300",
    publisher: IndexPublisher = IndexPublisher.CSI,
    local_code: str = "000300",
) -> IndexIdentity:
    return IndexIdentity(
        index_id=index_id,
        publisher=publisher,
        local_code=local_code,
    )


def test_index_publisher_tokens_are_stable() -> None:
    assert IndexPublisher.CSI.value == "csi"
    assert IndexPublisher.SSE.value == "sse"
    assert IndexPublisher.SZSE.value == "szse"
    assert IndexPublisher.CNI.value == "cni"


def test_index_identity_contract_surface_is_exact() -> None:
    assert IndexIdentity.contract_fields() == (
        "index_id",
        "publisher",
        "local_code",
    )


@pytest.mark.parametrize(
    ("index_id", "publisher", "local_code"),
    (
        ("cn.index.csi.000300", IndexPublisher.CSI, "000300"),
        ("cn.index.csi.000905", IndexPublisher.CSI, "000905"),
        ("cn.index.csi.000852", IndexPublisher.CSI, "000852"),
        ("cn.index.sse.000688", IndexPublisher.SSE, "000688"),
        ("cn.index.szse.399006", IndexPublisher.SZSE, "399006"),
    ),
)
def test_representative_index_identities_are_explicit(
    index_id: str,
    publisher: IndexPublisher,
    local_code: str,
) -> None:
    identity = _identity(
        index_id=index_id,
        publisher=publisher,
        local_code=local_code,
    )

    assert identity.index_id == index_id
    assert identity.publisher is publisher
    assert identity.local_code == local_code


def test_index_identity_is_immutable() -> None:
    identity = _identity()

    with pytest.raises(FrozenInstanceError):
        identity.local_code = "000905"  # type: ignore[misc]


@pytest.mark.parametrize(
    "index_id",
    (
        "",
        "CN.INDEX.CSI.000300",
        " cn.index.csi.000300",
        "cn.index.csi.000300 ",
        "cn index csi 000300",
        ".cn.index.csi.000300",
    ),
)
def test_index_id_must_be_explicit_canonical_token(index_id: str) -> None:
    with pytest.raises(ValueError):
        _identity(index_id=index_id)


def test_index_id_does_not_have_to_equal_local_code() -> None:
    identity = _identity(index_id="benchmark.largecap.primary", local_code="000300")

    assert identity.index_id == "benchmark.largecap.primary"
    assert identity.local_code == "000300"


def test_raw_publisher_string_is_not_coerced() -> None:
    with pytest.raises(TypeError, match="publisher must be IndexPublisher"):
        IndexIdentity(
            index_id="cn.index.csi.000300",
            publisher="csi",  # type: ignore[arg-type]
            local_code="000300",
        )


@pytest.mark.parametrize(
    "local_code",
    (
        "",
        " 000300",
        "000300 ",
        "sh.000300",
        "000300.SH",
        "000-300",
        "000_300",
        "指数300",
    ),
)
def test_local_code_rejects_decorated_or_noncanonical_symbols(
    local_code: str,
) -> None:
    with pytest.raises(ValueError):
        _identity(local_code=local_code)


def test_local_code_rejects_lowercase_form() -> None:
    with pytest.raises(ValueError, match="canonical uppercase"):
        _identity(
            index_id="example.index.alpha",
            local_code="abc123",
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("index_id", 300),
        ("publisher", 1),
        ("local_code", 300),
    ),
)
def test_identity_rejects_wrong_field_types(
    field_name: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {
        "index_id": "cn.index.csi.000300",
        "publisher": IndexPublisher.CSI,
        "local_code": "000300",
    }
    kwargs[field_name] = value

    with pytest.raises(TypeError):
        IndexIdentity(**kwargs)  # type: ignore[arg-type]


def test_contract_does_not_mix_index_data_or_taxonomy_fields() -> None:
    forbidden = {
        "name",
        "display_name",
        "provider_id",
        "provider_symbol",
        "constituents",
        "members",
        "weights",
        "valuation",
        "quote",
        "industry",
        "theme",
        "region",
        "fetched_at",
        "data_as_of",
        "effective_from",
        "effective_to",
    }

    assert forbidden.isdisjoint(IndexIdentity.contract_fields())
