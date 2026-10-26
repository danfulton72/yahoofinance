"""Data classes for Yahoo finance component."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import re
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL

from .const import CONF_NO_UNIT, CONF_SYMBOL, CONF_TARGET_CURRENCY

if TYPE_CHECKING:
    from .coordinator import CrumbCoordinator, YahooSymbolUpdateCoordinator

NO_UNIT_FLAG = "NOUNIT"

# Yahoo tickers use letters, digits and a handful of punctuation characters,
# e.g. AAPL, ^GSPC, GBPUSD=X, EMIM.L, BRK-B, 0P00008F5Y.L
_SYMBOL_RE = re.compile(r"^[A-Z0-9.^=\-_&]+$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class InvalidSymbolSpecError(ValueError):
    """Raised when a symbol specification cannot be parsed."""

    def __init__(self, spec: str) -> None:
        """Store the offending specification."""
        super().__init__(spec)
        self.spec = spec


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
        self.no_unit = bool(kwargs.get(CONF_NO_UNIT, False))

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

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable form stored in the config entry."""
        return {
            CONF_SYMBOL: self.symbol,
            CONF_TARGET_CURRENCY: self.target_currency,
            CONF_NO_UNIT: self.no_unit,
        }

    @classmethod
    def from_stored(cls, value: str | dict[str, Any]) -> SymbolDefinition:
        """Create from a stored value (plain string or dict)."""
        if isinstance(value, str):
            return cls(value.upper())
        target = value.get(CONF_TARGET_CURRENCY)
        return cls(
            str(value[CONF_SYMBOL]).upper(),
            target_currency=target.upper() if target else None,
            no_unit=value.get(CONF_NO_UNIT, False),
        )

    def as_spec(self) -> str:
        """Return the text form used in the configuration UI."""
        parts = [self.symbol]
        if self.target_currency:
            parts.append(self.target_currency)
        if self.no_unit:
            parts.append(NO_UNIT_FLAG.lower())
        return ":".join(parts)


def parse_symbol_specs(raw: str) -> list[SymbolDefinition]:
    """Parse the symbols text field into symbol definitions.

    Entries are separated by commas, spaces or new lines. Each entry is
    ``SYMBOL`` optionally followed by ``:CUR`` (target currency) and/or
    ``:nounit``, e.g. ``LGEN.L:USD``, ``GBPUSD=X:nounit``, ``EMIM.L:EUR:nounit``.
    Duplicate symbols are dropped (first one wins).

    Raises InvalidSymbolSpecError for the first entry that cannot be parsed.
    """
    definitions: list[SymbolDefinition] = []
    seen: set[str] = set()

    for spec in re.split(r"[\s,;]+", raw.strip()):
        if not spec:
            continue
        parts = spec.upper().split(":")
        symbol = parts[0]
        if not _SYMBOL_RE.match(symbol):
            raise InvalidSymbolSpecError(spec)

        target_currency: str | None = None
        no_unit = False
        for part in parts[1:]:
            if part == NO_UNIT_FLAG:
                no_unit = True
            elif _CURRENCY_RE.match(part) and target_currency is None:
                target_currency = part
            else:
                raise InvalidSymbolSpecError(spec)

        if symbol in seen:
            continue
        seen.add(symbol)
        definitions.append(
            SymbolDefinition(symbol, target_currency=target_currency, no_unit=no_unit)
        )

    return definitions


def format_symbol_specs(definitions: list[SymbolDefinition]) -> str:
    """Return the symbols text field for the given definitions."""
    return ", ".join(item.as_spec() for item in definitions)


@dataclass
class ConsentData:
    """Class for data related to GDPR consent."""

    consent_content: str = ""
    consent_post_url: str = ""
    successful_consent_url: str = ""
    need_consent: bool = False


@dataclass
class YahooFinanceRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: YahooSymbolUpdateCoordinator
    crumb_coordinator: CrumbCoordinator
    config: dict[str, Any] = field(default_factory=dict)
