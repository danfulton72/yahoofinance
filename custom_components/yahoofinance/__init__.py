"""The Yahoo Finance integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
    HomeAssistant,
    ServiceCall,
)
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DECIMAL_PLACES,
    CONF_INCLUDE_DIVIDEND_VALUES,
    CONF_INCLUDE_FIFTY_DAY_VALUES,
    CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    CONF_INCLUDE_POST_VALUES,
    CONF_INCLUDE_PRE_VALUES,
    CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    CONF_MANUAL_UPDATE,
    CONF_NO_UNIT,
    CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    CONF_SHOW_OFF_MARKET_VALUES,
    CONF_SHOW_TRENDING_ICON,
    CONF_SYMBOL,
    CONF_SYMBOLS,
    CONF_TARGET_CURRENCY,
    DEFAULT_CONF_DECIMAL_PLACES,
    DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES,
    DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES,
    DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    DEFAULT_CONF_INCLUDE_POST_VALUES,
    DEFAULT_CONF_INCLUDE_PRE_VALUES,
    DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    DEFAULT_CONF_MANUAL_UPDATE,
    DEFAULT_CONF_NO_UNIT,
    DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    DEFAULT_CONF_SHOW_OFF_MARKET_VALUES,
    DEFAULT_CONF_SHOW_TRENDING_ICON,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MANUAL_SCAN_INTERVAL,
    MAX_LINE_SIZE,
    MINIMUM_SCAN_INTERVAL,
    SERVICE_REFRESH,
)
from .coordinator import CrumbCoordinator, YahooSymbolUpdateCoordinator
from .dataclasses import SymbolDefinition, YahooFinanceRuntimeData

PLATFORMS = [Platform.SENSOR]

type YahooFinanceConfigEntry = ConfigEntry[YahooFinanceRuntimeData]

# Boolean display options and their defaults, shared by setup, flows and import
BOOLEAN_OPTIONS: dict[str, bool] = {
    CONF_SHOW_TRENDING_ICON: DEFAULT_CONF_SHOW_TRENDING_ICON,
    CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT: DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    CONF_SHOW_OFF_MARKET_VALUES: DEFAULT_CONF_SHOW_OFF_MARKET_VALUES,
    CONF_INCLUDE_PRE_VALUES: DEFAULT_CONF_INCLUDE_PRE_VALUES,
    CONF_INCLUDE_POST_VALUES: DEFAULT_CONF_INCLUDE_POST_VALUES,
    CONF_INCLUDE_FIFTY_DAY_VALUES: DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES,
    CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES: DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES: DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    CONF_INCLUDE_DIVIDEND_VALUES: DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES,
}

# ---------------------------------------------------------------------------
# Legacy YAML schema, kept so existing configuration.yaml setups are imported
# into config entries instead of being rejected.
# ---------------------------------------------------------------------------

BASIC_SYMBOL_SCHEMA = vol.All(cv.string, vol.Upper)


def minimum_scan_interval(value: timedelta) -> timedelta:
    """Validate scan_interval is the minimum value."""
    if value < MINIMUM_SCAN_INTERVAL:
        raise vol.Invalid(
            "Scan interval should be at least "
            f"{MINIMUM_SCAN_INTERVAL.total_seconds()} seconds"
        )
    return value


MANUAL_SCAN_INTERVAL_SCHEMA = vol.All(vol.Lower, MANUAL_SCAN_INTERVAL)
CUSTOM_SCAN_INTERVAL_SCHEMA = vol.All(cv.time_period, minimum_scan_interval)
SCAN_INTERVAL_SCHEMA = vol.Any(MANUAL_SCAN_INTERVAL_SCHEMA, CUSTOM_SCAN_INTERVAL_SCHEMA)

COMPLEX_SYMBOL_SCHEMA = vol.All(
    dict,
    vol.Schema(
        {
            vol.Required(CONF_SYMBOL): BASIC_SYMBOL_SCHEMA,
            vol.Optional(CONF_TARGET_CURRENCY): BASIC_SYMBOL_SCHEMA,
            vol.Optional(CONF_SCAN_INTERVAL): SCAN_INTERVAL_SCHEMA,
            vol.Optional(CONF_NO_UNIT, default=DEFAULT_CONF_NO_UNIT): cv.boolean,
        }
    ),
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_SYMBOLS): vol.All(
                    cv.ensure_list,
                    [vol.Any(BASIC_SYMBOL_SCHEMA, COMPLEX_SYMBOL_SCHEMA)],
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): SCAN_INTERVAL_SCHEMA,
                vol.Optional(CONF_TARGET_CURRENCY): vol.All(cv.string, vol.Upper),
                vol.Optional(
                    CONF_DECIMAL_PLACES, default=DEFAULT_CONF_DECIMAL_PLACES
                ): vol.Coerce(int),
                **{
                    vol.Optional(key, default=default): cv.boolean
                    for key, default in BOOLEAN_OPTIONS.items()
                },
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def convert_to_float(value) -> float | None:
    """Convert specified value to float."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def get_scan_interval(options: dict[str, Any]) -> timedelta | None:
    """Return the update interval from options, None means manual updates."""
    if options.get(CONF_MANUAL_UPDATE, DEFAULT_CONF_MANUAL_UPDATE):
        return None
    raw = options.get(CONF_SCAN_INTERVAL)
    if raw is None:
        return DEFAULT_SCAN_INTERVAL
    try:
        interval = timedelta(seconds=int(raw))
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL
    return max(interval, MINIMUM_SCAN_INTERVAL)


def get_symbol_definitions(options: dict[str, Any]) -> list[SymbolDefinition]:
    """Return the symbol definitions stored in options."""
    return [
        SymbolDefinition.from_stored(item) for item in options.get(CONF_SYMBOLS, [])
    ]


def build_domain_config(options: dict[str, Any]) -> dict[str, Any]:
    """Build the configuration dict consumed by the sensor platform."""
    global_target = options.get(CONF_TARGET_CURRENCY) or None
    symbol_definitions = get_symbol_definitions(options)
    for definition in symbol_definitions:
        if definition.target_currency is None and global_target:
            definition.target_currency = global_target.upper()

    config: dict[str, Any] = {
        CONF_SYMBOLS: symbol_definitions,
        CONF_DECIMAL_PLACES: int(
            options.get(CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES)
        ),
    }
    for key, default in BOOLEAN_OPTIONS.items():
        config[key] = bool(options.get(key, default))
    return config


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration: refresh service and YAML import."""

    async def handle_refresh(call: ServiceCall) -> None:
        """Refresh symbol data for all loaded entries."""
        LOGGER.info("Processing refresh_symbols")
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)

    if DOMAIN in config:
        await _async_import_yaml(hass, config[DOMAIN])

    return True


def _yaml_interval_key(value: Any) -> str:
    """Return a stable key for a YAML scan interval."""
    if isinstance(value, timedelta):
        return str(int(value.total_seconds()))
    return str(value)


async def _async_import_yaml(hass: HomeAssistant, yaml_config: dict) -> None:
    """Import YAML configuration, one config entry per scan interval."""
    global_interval = yaml_config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    groups: dict[str, dict[str, Any]] = {}

    for value in yaml_config[CONF_SYMBOLS]:
        if isinstance(value, str):
            definition = SymbolDefinition(value)
            interval = global_interval
        else:
            definition = SymbolDefinition(
                value[CONF_SYMBOL],
                target_currency=value.get(CONF_TARGET_CURRENCY),
                no_unit=value.get(CONF_NO_UNIT, False),
            )
            interval = value.get(CONF_SCAN_INTERVAL, global_interval)

        key = _yaml_interval_key(interval)
        group = groups.setdefault(key, {"interval": interval, "symbols": []})
        if all(item.symbol != definition.symbol for item in group["symbols"]):
            group["symbols"].append(definition)

    for key, group in groups.items():
        interval = group["interval"]
        options: dict[str, Any] = {
            CONF_SYMBOLS: [item.as_dict() for item in group["symbols"]],
            CONF_MANUAL_UPDATE: interval == MANUAL_SCAN_INTERVAL,
            CONF_SCAN_INTERVAL: (
                int(interval.total_seconds())
                if isinstance(interval, timedelta)
                else int(DEFAULT_SCAN_INTERVAL.total_seconds())
            ),
            CONF_DECIMAL_PLACES: yaml_config.get(
                CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES
            ),
            CONF_TARGET_CURRENCY: yaml_config.get(CONF_TARGET_CURRENCY),
        }
        for option, default in BOOLEAN_OPTIONS.items():
            options[option] = yaml_config.get(option, default)

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={"import_key": key, "options": options},
            ),
            eager_start=True,
        )

    ir.async_create_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        f"deprecated_yaml_{DOMAIN}",
        breaks_in_ha_version=None,
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        translation_placeholders={
            "domain": DOMAIN,
            "integration_title": "Yahoo Finance",
        },
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older config entries."""
    LOGGER.debug("Migrating from version %s.%s", entry.version, entry.minor_version)

    if entry.version > 1:
        return False

    if entry.minor_version < 2:
        # 1.1 stored symbols (plain strings) and the hourly interval in data, with
        # display options in options. 1.2 keeps everything in options, symbols as
        # dicts and the interval in seconds.
        merged = {**entry.data, **entry.options}
        merged[CONF_SYMBOLS] = [
            SymbolDefinition.from_stored(item).as_dict()
            for item in entry.data.get(CONF_SYMBOLS, [])
        ]
        hours = merged.get(CONF_SCAN_INTERVAL)
        try:
            seconds = int(hours) * 3600
        except (TypeError, ValueError):
            seconds = int(DEFAULT_SCAN_INTERVAL.total_seconds())
        merged[CONF_SCAN_INTERVAL] = seconds
        hass.config_entries.async_update_entry(
            entry, data={}, options=merged, minor_version=2
        )

    LOGGER.debug(
        "Migration to version %s.%s successful", entry.version, entry.minor_version
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: YahooFinanceConfigEntry
) -> bool:
    """Set up Yahoo Finance from a config entry."""
    options = dict(entry.options)
    domain_config = build_domain_config(options)
    symbol_definitions: list[SymbolDefinition] = domain_config[CONF_SYMBOLS]
    scan_interval = get_scan_interval(options)

    # The session is owned by this entry and closed by HA when it unloads, so the
    # crumb coordinator using it must be per-entry as well.
    websession = async_create_clientsession(
        hass, max_field_size=MAX_LINE_SIZE, max_line_size=MAX_LINE_SIZE
    )
    crumb_coordinator = CrumbCoordinator(hass, websession)
    coordinator = YahooSymbolUpdateCoordinator(
        [item.symbol for item in symbol_definitions],
        hass,
        scan_interval,
        crumb_coordinator,
        websession,
        config_entry=entry,
    )

    # Raises ConfigEntryNotReady on failure so HA retries setup with back-off.
    # The crumb is fetched lazily as part of the first refresh.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = YahooFinanceRuntimeData(
        coordinator=coordinator,
        crumb_coordinator=crumb_coordinator,
        config=domain_config,
    )

    _async_remove_stale_entities(hass, entry, symbol_definitions)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_remove_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    symbol_definitions: list[SymbolDefinition],
) -> None:
    """Remove entities for symbols that are no longer configured."""
    symbols = {item.symbol for item in symbol_definitions}
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.unique_id not in symbols:
            LOGGER.info(
                "Removing entity %s, symbol no longer configured",
                registry_entry.entity_id,
            )
            registry.async_remove(registry_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: YahooFinanceConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data.coordinator.cancel_delayed_refresh()
    return unload_ok
