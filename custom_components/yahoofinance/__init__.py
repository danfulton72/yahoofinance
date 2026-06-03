"""The Yahoo Finance integration - UI configurable version."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_DECIMAL_PLACES,
    CONF_INCLUDE_DIVIDEND_VALUES,
    CONF_INCLUDE_FIFTY_DAY_VALUES,
    CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    CONF_INCLUDE_POST_VALUES,
    CONF_INCLUDE_PRE_VALUES,
    CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    CONF_SHOW_OFF_MARKET_VALUES,
    CONF_SHOW_TRENDING_ICON,
    CONF_SYMBOLS,
    DEFAULT_CONF_DECIMAL_PLACES,
    DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES,
    DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES,
    DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    DEFAULT_CONF_INCLUDE_POST_VALUES,
    DEFAULT_CONF_INCLUDE_PRE_VALUES,
    DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    DEFAULT_CONF_SHOW_OFF_MARKET_VALUES,
    DEFAULT_CONF_SHOW_TRENDING_ICON,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HASS_DATA_CONFIG,
    HASS_DATA_COORDINATORS,
    LOGGER,
    MAX_LINE_SIZE,
    MINIMUM_SCAN_INTERVAL,
    SERVICE_REFRESH,
)
from .coordinator import CrumbCoordinator, YahooSymbolUpdateCoordinator
from .dataclasses import SymbolDefinition

PLATFORMS = [Platform.SENSOR]


def convert_to_float(value) -> float | None:
    """Convert specified value to float."""
    try:
        return float(value)
    except:  # noqa: E722
        return None


def _build_domain_config(symbols: list[str], options: dict) -> dict:
    """Build the domain_config dict that sensor.py expects."""
    symbol_definitions = [SymbolDefinition(s.upper()) for s in symbols]
    scan_interval = _parse_scan_interval(options)

    for sym_def in symbol_definitions:
        sym_def.scan_interval = scan_interval

    return {
        CONF_SYMBOLS: symbol_definitions,
        CONF_SHOW_TRENDING_ICON: options.get(CONF_SHOW_TRENDING_ICON, DEFAULT_CONF_SHOW_TRENDING_ICON),
        CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT: options.get(CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT, DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT),
        CONF_DECIMAL_PLACES: options.get(CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES),
        CONF_SHOW_OFF_MARKET_VALUES: options.get(CONF_SHOW_OFF_MARKET_VALUES, DEFAULT_CONF_SHOW_OFF_MARKET_VALUES),
        CONF_INCLUDE_FIFTY_DAY_VALUES: options.get(CONF_INCLUDE_FIFTY_DAY_VALUES, DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES),
        CONF_INCLUDE_POST_VALUES: options.get(CONF_INCLUDE_POST_VALUES, DEFAULT_CONF_INCLUDE_POST_VALUES),
        CONF_INCLUDE_PRE_VALUES: options.get(CONF_INCLUDE_PRE_VALUES, DEFAULT_CONF_INCLUDE_PRE_VALUES),
        CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES: options.get(CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES, DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES),
        CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES: options.get(CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES, DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES),
        CONF_INCLUDE_DIVIDEND_VALUES: options.get(CONF_INCLUDE_DIVIDEND_VALUES, DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES),
    }


def _parse_scan_interval(options: dict) -> timedelta:
    """Parse scan interval from options, returning a timedelta."""
    raw = options.get(CONF_SCAN_INTERVAL, None)
    if raw is None:
        return DEFAULT_SCAN_INTERVAL
    try:
        interval = timedelta(hours=int(raw))
        if interval < MINIMUM_SCAN_INTERVAL:
            return MINIMUM_SCAN_INTERVAL
        return interval
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yahoo Finance from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    symbols: list[str] = entry.data.get(CONF_SYMBOLS, [])

    # Merge data + options; options take precedence (set via Configure button)
    merged_options = {**entry.data, **entry.options}
    domain_config = _build_domain_config(symbols, merged_options)
    scan_interval = _parse_scan_interval(merged_options)

    websession = async_create_clientsession(
        hass, max_field_size=MAX_LINE_SIZE, max_line_size=MAX_LINE_SIZE
    )

    crumb_coordinator = CrumbCoordinator.get_static_instance(hass, websession)
    crumb = await crumb_coordinator.try_get_crumb_cookies()
    if crumb is None:
        LOGGER.warning("Unable to get crumb during setup, will retry on first update")

    symbol_strings = [s.upper() for s in symbols]
    coordinator = YahooSymbolUpdateCoordinator(
        symbol_strings, hass, scan_interval, crumb_coordinator, websession
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        HASS_DATA_CONFIG: domain_config,
        HASS_DATA_COORDINATORS: {scan_interval: coordinator},
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register refresh service (once, shared across all entries)
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        async def handle_refresh(call: ServiceCall) -> None:
            """Handle refresh service call."""
            LOGGER.info("Processing refresh_symbols")
            for entry_id, entry_data in hass.data[DOMAIN].items():
                if not isinstance(entry_data, dict):
                    continue
                coordinators = entry_data.get(HASS_DATA_COORDINATORS, {})
                for coord in coordinators.values():
                    await coord.async_refresh()

        hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Reset crumb singleton so next setup starts fresh
        CrumbCoordinator._instance = None
    return unload_ok
