"""Tests for the Yahoo Finance config and options flows."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yahoofinance import BOOLEAN_OPTIONS
from custom_components.yahoofinance.const import (
    CONF_DECIMAL_PLACES,
    CONF_MANUAL_UPDATE,
    CONF_NO_UNIT,
    CONF_SHOW_TRENDING_ICON,
    CONF_SYMBOL,
    CONF_SYMBOLS,
    CONF_TARGET_CURRENCY,
    DOMAIN,
)
from custom_components.yahoofinance.dataclasses import (
    InvalidSymbolSpecError,
    SymbolDefinition,
    format_symbol_specs,
    parse_symbol_specs,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import TEST_CRUMB

ONE_HOUR = {"hours": 1, "minutes": 0, "seconds": 0}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for every test."""


@pytest.fixture(autouse=True)
def mock_network(mock_json):
    """Avoid network access when entries get set up."""
    with (
        patch(
            "custom_components.yahoofinance.YahooSymbolUpdateCoordinator.get_json",
            AsyncMock(return_value=mock_json),
        ),
        patch(
            "custom_components.yahoofinance.CrumbCoordinator.try_get_crumb_cookies",
            AsyncMock(return_value=TEST_CRUMB),
        ),
    ):
        yield


def add_entry(hass: HomeAssistant, symbols: list[str], **options) -> MockConfigEntry:
    """Add an existing entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing",
        data={},
        options={
            CONF_SYMBOLS: [SymbolDefinition(s).as_dict() for s in symbols],
            CONF_SCAN_INTERVAL: 3600,
            **options,
        },
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow(hass: HomeAssistant) -> None:
    """A valid submission creates an entry with everything in options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SYMBOLS: "aapl, emim.l:eur:nounit\nGBPUSD=X:nounit aapl",
            CONF_SCAN_INTERVAL: {"minutes": 15},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Yahoo Finance (AAPL, EMIM.L, GBPUSD=X)"
    entry = result["result"]
    assert entry.data == {}
    assert entry.minor_version == 2
    assert entry.options[CONF_SCAN_INTERVAL] == 900
    assert entry.options[CONF_SYMBOLS] == [
        {CONF_SYMBOL: "AAPL", CONF_TARGET_CURRENCY: None, CONF_NO_UNIT: False},
        {CONF_SYMBOL: "EMIM.L", CONF_TARGET_CURRENCY: "EUR", CONF_NO_UNIT: True},
        {CONF_SYMBOL: "GBPUSD=X", CONF_TARGET_CURRENCY: None, CONF_NO_UNIT: True},
    ]


@pytest.mark.parametrize(
    ("user_input", "field", "error"),
    [
        (
            {CONF_SYMBOLS: " , ", CONF_SCAN_INTERVAL: ONE_HOUR},
            CONF_SYMBOLS,
            "no_symbols",
        ),
        (
            {CONF_SYMBOLS: "AAPL:EURO", CONF_SCAN_INTERVAL: ONE_HOUR},
            CONF_SYMBOLS,
            "invalid_symbol",
        ),
        (
            {CONF_SYMBOLS: "AAPL", CONF_SCAN_INTERVAL: {"seconds": 10}},
            CONF_SCAN_INTERVAL,
            "interval_too_short",
        ),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, user_input, field, error) -> None:
    """Invalid input shows an error and keeps the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}


async def test_user_flow_symbol_in_use(hass: HomeAssistant) -> None:
    """A symbol already tracked by another entry is rejected."""
    add_entry(hass, ["AAPL"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYMBOLS: "MSFT, AAPL", CONF_SCAN_INTERVAL: ONE_HOUR}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SYMBOLS: "symbol_in_use"}
    assert result["description_placeholders"]["symbol"] == "AAPL"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Options update symbols and settings, reloading the entry once."""
    entry = add_entry(hass, ["AAPL"], **BOOLEAN_OPTIONS)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema_defaults = {
        str(key): key.default()
        for key in result["data_schema"].schema
        if callable(getattr(key, "default", None))
    }
    assert schema_defaults[CONF_SYMBOLS] == "AAPL"

    with patch(
        "custom_components.yahoofinance.async_setup_entry",
        AsyncMock(return_value=True),
    ) as mock_setup:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_SYMBOLS: "AAPL, BABA:gbp",
                CONF_SCAN_INTERVAL: {"minutes": 1},
                CONF_MANUAL_UPDATE: True,
                CONF_DECIMAL_PLACES: 3,
                CONF_TARGET_CURRENCY: "eur",
                CONF_SHOW_TRENDING_ICON: True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_setup.call_count == 1
    assert entry.data == {}
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.options[CONF_MANUAL_UPDATE] is True
    assert entry.options[CONF_DECIMAL_PLACES] == 3
    assert entry.options[CONF_TARGET_CURRENCY] == "EUR"
    assert entry.options[CONF_SHOW_TRENDING_ICON] is True
    assert entry.options[CONF_SYMBOLS][1] == {
        CONF_SYMBOL: "BABA",
        CONF_TARGET_CURRENCY: "GBP",
        CONF_NO_UNIT: False,
    }


async def test_options_flow_errors(hass: HomeAssistant) -> None:
    """Options flow validates currency and symbols used elsewhere."""
    add_entry(hass, ["BABA"])
    entry = add_entry(hass, ["AAPL"])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SYMBOLS: "AAPL, BABA", CONF_SCAN_INTERVAL: ONE_HOUR},
    )
    assert result["errors"] == {CONF_SYMBOLS: "symbol_in_use"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SYMBOLS: "AAPL",
            CONF_SCAN_INTERVAL: ONE_HOUR,
            CONF_TARGET_CURRENCY: "euro",
        },
    )
    assert result["errors"] == {CONF_TARGET_CURRENCY: "invalid_currency"}

    # Keeping its own symbols is not a conflict
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SYMBOLS: "AAPL", CONF_SCAN_INTERVAL: ONE_HOUR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aapl", [SymbolDefinition("AAPL")]),
        ("^GSPC;BRK-B", [SymbolDefinition("^GSPC"), SymbolDefinition("BRK-B")]),
        ("lgen.l:usd", [SymbolDefinition("LGEN.L", target_currency="USD")]),
        ("x:NoUnit:eur", [SymbolDefinition("X", target_currency="EUR", no_unit=True)]),
        ("A, a:eur", [SymbolDefinition("A")]),
    ],
)
def test_parse_symbol_specs(raw, expected) -> None:
    """Symbol specification parsing."""
    assert parse_symbol_specs(raw) == expected


@pytest.mark.parametrize("raw", ["AA PL:", "A:EUR:USD", "A$B", "A:12"])
def test_parse_symbol_specs_invalid(raw) -> None:
    """Invalid specs raise."""
    with pytest.raises(InvalidSymbolSpecError):
        parse_symbol_specs(raw)


def test_format_round_trip() -> None:
    """Formatting then parsing returns the same definitions."""
    defs = parse_symbol_specs("AAPL, EMIM.L:EUR:nounit, GBPUSD=X:nounit")
    assert format_symbol_specs(defs) == "AAPL, EMIM.L:EUR:nounit, GBPUSD=X:nounit"
    assert parse_symbol_specs(format_symbol_specs(defs)) == defs
