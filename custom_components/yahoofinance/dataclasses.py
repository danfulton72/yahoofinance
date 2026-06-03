"""Data classes for Yahoo finance component."""

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.const import CONF_SCAN_INTERVAL

from .const import CONF_NO_UNIT, CONF_TARGET_CURRENCY


class SymbolDefinition:
    """Symbol definition."""

    symbol: str
    target_currency: str | None = None
    scan_interval: str | timedelta | None = None
    no_unit: bool = False

    def __init__(self, symbol: str, **kwargs) -> None:
        """Create a new symbol definition."""
        self.symbol = symbol
        self.target_currency = kwargs.get(CONF_TARGET_CURRENCY)
        self.scan_interval = kwargs.get(CONF_SCAN_INTERVAL)
        self.no_unit = kwargs.get(CONF_NO_UNIT, False)

    def __repr__(self) -> str:
        """Return the representation."""
        return (
            f"{self.symbol},{self.target_currency},{self.scan_interval},{self.no_unit}"
        )

    def __eq__(self, other) -> bool:
        """Return the comparison."""
        return (
            isinstance(other, SymbolDefinition)
            and self.symbol == other.symbol
            and self.target_currency == other.target_currency
            and self.scan_interval == other.scan_interval
            and self.no_unit == other.no_unit
        )

    def __hash__(self) -> int:
        """Make hashable."""
        return hash(
            (self.symbol, self.target_currency, self.scan_interval, self.no_unit)
        )


@dataclass
class ConsentData:
    """Class for data related to GDPR consent."""

    consent_content: str = ""
    consent_post_url: str = ""
    successful_consent_url: str = ""
    need_consent: bool = False
