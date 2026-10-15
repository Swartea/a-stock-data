"""Availability labels for evidence-backed market observations."""

from enum import Enum


class MarketAvailability(str, Enum):
    AVAILABLE = "available"
    DELAYED = "delayed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
