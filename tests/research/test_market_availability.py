from analysis.research.market_availability import MarketAvailability


def test_availability_tokens_are_explicit():
    assert {item.value for item in MarketAvailability} == {
        "available", "delayed", "unavailable", "unknown"
    }
