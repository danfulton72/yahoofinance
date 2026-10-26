"""Tests for Yahoo Finance setup, YAML import and migration."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yahoofinance import (
    BOOLEAN_OPTIONS,
    build_domain_config,
    convert_to_float,
    get_scan_interval,
)
from custom_components.yahoofinance.const import (
    CONF_DECIMAL_PLACES,
    CONF_MANUAL_UPDATE,
    CONF_NO_UNIT,
    CONF_SHOW_TRENDING_ICON,
    CONF_SYMBOL,
    CONF_SYMBOLS,
    CONF_TARGET_CURRENCY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MINIMUM_SCAN_INTERVAL,
    SERVICE_REFRESH,
)
from custom_components.yahoofinance.dataclasses import SymbolDefinition
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component

from . import TEST_CRUMB

GET_JSON = "custom_components.yahoofinance.YahooSymbolUpdateCoordinator.get_json"
GET_CRUMB = "custom_components.yahoofinance.CrumbCoordinator.try_get_crumb_cookies"


def make_options(symbols: list, **overrides) -> dict:
    """Build entry options."""
    options = {
        CONF_SYMBOLS: [SymbolDefinition.from_stored(s).as_dict() for s in symbols],
        CONF_SCAN_INTERVAL: 3600,
        CONF_MANUAL_UPDATE: False,
        CONF_DECIMAL_PLACES: 2,
        **BOOLEAN_OPTIONS,
    }
    options.update(overrides)
    return options


def make_entry(hass: HomeAssistant, symbols: list, **overrides) -> MockConfigEntry:
    """Create and add a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Yahoo Finance",
        data={},
        options=make_options(symbols, **overrides),
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for every test."""


@pytest.fixture
def mock_fetch(mock_json):
    """Mock the network layer of the coordinator."""
    with (
        patch(GET_JSON, AsyncMock(return_value=mock_json)) as get_json,
        patch(GET_CRUMB, AsyncMock(return_value=TEST_CRUMB)),
    ):
        yield get_json


async def test_setup_and_unload_entry(hass: HomeAssistant, mock_fetch) -> None:
    """Entry sets up sensors and unloads cleanly."""
    entry = make_entry(hass, ["AAPL", "BABA"])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.yahoofinance_aapl") is not None
    assert hass.states.get("sensor.yahoofinance_baba") is not None
    assert entry.runtime_data.coordinator.update_interval == timedelta(hours=1)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_fetch_fails(hass: HomeAssistant) -> None:
    """A network failure during setup is retried instead of erroring permanently."""
    entry = make_entry(hass, ["AAPL"])

    with (
        patch(GET_JSON, AsyncMock(return_value=None)),
        patch(GET_CRUMB, AsyncMock(return_value=None)),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_entries_are_independent(hass: HomeAssistant, mock_fetch) -> None:
    """Reloading one entry does not affect the crumb handling of another."""
    entry1 = make_entry(hass, ["AAPL"])
    entry2 = make_entry(hass, ["BABA"])
    # Setting up the integration loads every entry
    assert await hass.config_entries.async_setup(entry1.entry_id)
    await hass.async_block_till_done()
    assert entry2.state is ConfigEntryState.LOADED

    assert (
        entry1.runtime_data.crumb_coordinator
        is not entry2.runtime_data.crumb_coordinator
    )

    crumb2 = entry2.runtime_data.crumb_coordinator
    assert await hass.config_entries.async_reload(entry1.entry_id)
    await hass.async_block_till_done()

    assert entry2.state is ConfigEntryState.LOADED
    assert entry2.runtime_data.crumb_coordinator is crumb2
    assert not crumb2._websession.closed


async def test_refresh_symbols_service(hass: HomeAssistant, mock_fetch) -> None:
    """The refresh service refreshes every loaded entry."""
    entry = make_entry(hass, ["AAPL"])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 1

    await hass.services.async_call(DOMAIN, SERVICE_REFRESH, {}, blocking=True)
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 2


async def test_service_registered_without_entries(hass: HomeAssistant) -> None:
    """The service is registered in async_setup."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH)
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH, {}, blocking=True)


async def test_stale_entities_removed(hass: HomeAssistant, mock_fetch) -> None:
    """Entities for removed symbols are removed from the registry."""
    entry = make_entry(hass, ["AAPL"])
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "MSFT",
        config_entry=entry,
        suggested_object_id="yahoofinance_msft",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None
    assert registry.async_get_entity_id("sensor", DOMAIN, "AAPL") is not None


async def test_target_currency_and_no_unit(hass: HomeAssistant, mock_fetch) -> None:
    """Per-symbol target currency and no_unit are applied."""
    entry = make_entry(
        hass,
        [
            {CONF_SYMBOL: "EMIM.L", CONF_TARGET_CURRENCY: "USD"},
            {CONF_SYMBOL: "^SSMI", CONF_NO_UNIT: True},
            "GBPUSD=X",
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    emim = hass.states.get("sensor.yahoofinance_emim_l")
    assert emim.attributes["unit_of_measurement"] == "USD"
    ssmi = hass.states.get("sensor.yahoofinance_ssmi")
    assert "unit_of_measurement" not in ssmi.attributes


async def test_manual_update(hass: HomeAssistant, mock_fetch) -> None:
    """Manual update disables polling."""
    entry = make_entry(hass, ["AAPL"], **{CONF_MANUAL_UPDATE: True})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.update_interval is None


async def test_yaml_import(hass: HomeAssistant, mock_fetch) -> None:
    """YAML config is imported, grouped by scan interval, with a repair issue."""
    config = {
        DOMAIN: {
            CONF_SYMBOLS: [
                "aapl",
                {
                    CONF_SYMBOL: "emim.l",
                    CONF_TARGET_CURRENCY: "eur",
                    CONF_NO_UNIT: True,
                },
                {CONF_SYMBOL: "baba", CONF_SCAN_INTERVAL: "manual"},
                "aapl",
            ],
            CONF_SCAN_INTERVAL: {"minutes": 5},
            CONF_SHOW_TRENDING_ICON: True,
            CONF_DECIMAL_PLACES: 3,
        }
    }
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 2
    by_manual = {e.options[CONF_MANUAL_UPDATE]: e for e in entries}

    timed = by_manual[False]
    assert timed.source == SOURCE_IMPORT
    assert timed.options[CONF_SCAN_INTERVAL] == 300
    assert timed.options[CONF_SHOW_TRENDING_ICON] is True
    assert timed.options[CONF_DECIMAL_PLACES] == 3
    assert timed.options[CONF_SYMBOLS] == [
        {CONF_SYMBOL: "AAPL", CONF_TARGET_CURRENCY: None, CONF_NO_UNIT: False},
        {CONF_SYMBOL: "EMIM.L", CONF_TARGET_CURRENCY: "EUR", CONF_NO_UNIT: True},
    ]
    assert [s[CONF_SYMBOL] for s in by_manual[True].options[CONF_SYMBOLS]] == ["BABA"]

    issue = ir.async_get(hass).async_get_issue(
        HOMEASSISTANT_DOMAIN, f"deprecated_yaml_{DOMAIN}"
    )
    assert issue is not None


async def test_yaml_import_is_idempotent(hass: HomeAssistant, mock_fetch) -> None:
    """Importing the same YAML twice does not create duplicate entries."""
    config = {DOMAIN: {CONF_SYMBOLS: ["AAPL"]}}
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={
            "import_key": str(int(DEFAULT_SCAN_INTERVAL.total_seconds())),
            "options": make_options(["AAPL"]),
        },
    )
    assert result["type"] == "abort"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_yaml_import_adopts_existing_entities(
    hass: HomeAssistant, mock_fetch
) -> None:
    """Entities created by the YAML version keep their entity id."""
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, "AAPL", suggested_object_id="yahoofinance_aapl"
    )

    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {CONF_SYMBOLS: ["AAPL"]}})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    adopted = registry.async_get(old.entity_id)
    assert adopted is not None
    assert adopted.config_entry_id == entry.entry_id


async def test_migrate_1_1_to_1_2(hass: HomeAssistant, mock_fetch) -> None:
    """Entries from the first UI version are migrated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Yahoo Finance (AAPL)",
        data={CONF_SYMBOLS: ["AAPL", "BABA"], CONF_SCAN_INTERVAL: 6},
        options={CONF_SCAN_INTERVAL: 2, CONF_SHOW_TRENDING_ICON: True},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert entry.data == {}
    assert entry.options[CONF_SCAN_INTERVAL] == 7200
    assert entry.options[CONF_SHOW_TRENDING_ICON] is True
    assert [s[CONF_SYMBOL] for s in entry.options[CONF_SYMBOLS]] == ["AAPL", "BABA"]
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, DEFAULT_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: 600}, timedelta(minutes=10)),
        ({CONF_SCAN_INTERVAL: 5}, MINIMUM_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: "a"}, DEFAULT_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: 600, CONF_MANUAL_UPDATE: True}, None),
    ],
)
def test_get_scan_interval(options, expected) -> None:
    """Scan interval parsing."""
    assert get_scan_interval(options) == expected


def test_build_domain_config_global_target_currency() -> None:
    """Global target currency applies only to symbols without their own."""
    config = build_domain_config(
        make_options(
            ["AAPL", {CONF_SYMBOL: "BABA", CONF_TARGET_CURRENCY: "GBP"}],
            **{CONF_TARGET_CURRENCY: "eur"},
        )
    )
    targets = {s.symbol: s.target_currency for s in config[CONF_SYMBOLS]}
    assert targets == {"AAPL": "EUR", "BABA": "GBP"}


@pytest.mark.parametrize(
    ("sym1", "sym2", "expected"),
    [
        (SymbolDefinition("ABC"), SymbolDefinition("ABC"), True),
        (SymbolDefinition("ABC"), SymbolDefinition("DEF"), False),
        (
            SymbolDefinition("ABC", target_currency="USD"),
            SymbolDefinition("ABC", target_currency="USD"),
            True,
        ),
        (
            SymbolDefinition("ABC", target_currency="USD"),
            SymbolDefinition("ABC", target_currency="EUR"),
            False,
        ),
        (
            SymbolDefinition("ABC", scan_interval=timedelta(seconds=20)),
            SymbolDefinition("ABC", scan_interval=timedelta(seconds=20)),
            True,
        ),
        (
            SymbolDefinition("ABC", scan_interval=timedelta(seconds=20)),
            SymbolDefinition("ABC", scan_interval=timedelta(seconds=10)),
            False,
        ),
    ],
)
def test_symbol_definition_comparison(
    sym1: SymbolDefinition, sym2: SymbolDefinition, expected: bool
) -> None:
    """Test SymbolDefinition instance comparison."""
    if expected:
        assert sym1 == sym2
        assert hash(sym1) == hash(sym2)
        assert str(sym1) == str(sym2)
    else:
        assert sym1 != sym2
        assert hash(sym1) != hash(sym2)
        assert str(sym1) != str(sym2)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (1642118400, 1642118400),
        ("1646870400", 1646870400),
        ("164687040 0", None),
    ],
)
def test_convert_to_float(value, expected) -> None:
    """Tests float conversion."""
    assert convert_to_float(value) == expected


async def test_unload_cancels_delayed_refresh(hass: HomeAssistant, mock_fetch) -> None:
    """A refresh queued by add_symbol is cancelled when the entry unloads."""
    entry = make_entry(hass, ["AAPL"])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.add_symbol("USDEUR=X")
    assert coordinator._cancel_delayed_refresh is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._cancel_delayed_refresh is None

async def test_migrate_manual_interval(hass: HomeAssistant, mock_fetch) -> None:
    """Manual polling survives migrating an older config entry."""
    from custom_components.yahoofinance.const import MANUAL_SCAN_INTERVAL

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SYMBOLS: ["AAPL"], CONF_SCAN_INTERVAL: MANUAL_SCAN_INTERVAL},
        options={},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.options[CONF_MANUAL_UPDATE] is True
    assert entry.minor_version == 2
