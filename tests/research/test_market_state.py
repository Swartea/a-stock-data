from dataclasses import FrozenInstanceError

import pytest

from analysis.research.index_registry import A_SHARE_INDEX_IDENTITIES
from analysis.research.market_availability import MarketAvailability
from analysis.research.market_state import MarketIndexObservation


def test_observation_is_immutable_and_absence_is_not_zero():
    item = MarketIndexObservation(A_SHARE_INDEX_IDENTITIES[0], "上证指数")
    assert item.close is None
    assert item.availability is MarketAvailability.UNKNOWN
    with pytest.raises(FrozenInstanceError):
        item.close = 0.0


def test_observation_rejects_nonfinite_close():
    with pytest.raises(ValueError, match="finite numeric"):
        MarketIndexObservation(A_SHARE_INDEX_IDENTITIES[0], "上证指数", close=float("nan"))
