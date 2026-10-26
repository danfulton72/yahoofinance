"""Config flow for Yahoo Finance integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DurationSelector,
    DurationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from . import BOOLEAN_OPTIONS, get_symbol_definitions
from .const import (
    CONF_DECIMAL_PLACES,
    CONF_MANUAL_UPDATE,
    CONF_SYMBOLS,
    CONF_TARGET_CURRENCY,
    DEFAULT_CONF_DECIMAL_PLACES,
    DEFAULT_CONF_MANUAL_UPDATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MINIMUM_SCAN_INTERVAL,
)
from .dataclasses import (
    InvalidSymbolSpecError,
    SymbolDefinition,
    format_symbol_specs,
    parse_symbol_specs,
)

SYMBOLS_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
DURATION_SELECTOR = DurationSelector(DurationSelectorConfig(enable_day=False))
DECIMAL_PLACES_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=-1, max=10, step=1, mode=NumberSelectorMode.BOX)
)


def _seconds_to_duration(seconds: int) -> dict[str, int]:
    """Convert seconds to the duration selector format."""
    return {
        "hours": seconds // 3600,
        "minutes": (seconds % 3600) // 60,
        "seconds": seconds % 60,
    }


def _duration_to_seconds(value: dict[str, Any] | None) -> int:
    """Convert a duration selector value to seconds."""
    if not value:
        return int(DEFAULT_SCAN_INTERVAL.total_seconds())
    return int(
        float(value.get("days", 0)) * 86400
        + float(value.get("hours", 0)) * 3600
        + float(value.get("minutes", 0)) * 60
        + float(value.get("seconds", 0))
    )


def _make_title(definitions: list[SymbolDefinition]) -> str:
    """Return an entry title for the symbols."""
    symbols = [item.symbol for item in definitions]
    suffix = "..." if len(symbols) > 3 else ""
    return f"Yahoo Finance ({', '.join(symbols[:3])}{suffix})"


class _SymbolValidationMixin:
    """Shared validation for the config and options flows."""

    hass: Any

    def _validate(
        self,
        user_input: dict[str, Any],
        errors: dict[str, str],
        placeholders: dict[str, str],
        exclude_entry_id: str | None = None,
    ) -> tuple[list[SymbolDefinition], int]:
        """Validate the symbols and interval, filling errors when invalid."""
        definitions: list[SymbolDefinition] = []
        try:
            definitions = parse_symbol_specs(user_input.get(CONF_SYMBOLS, ""))
        except InvalidSymbolSpecError as ex:
            errors[CONF_SYMBOLS] = "invalid_symbol"
            placeholders["symbol"] = ex.spec

        if not definitions and CONF_SYMBOLS not in errors:
            errors[CONF_SYMBOLS] = "no_symbols"

        in_use = _symbols_in_other_entries(self.hass, exclude_entry_id)
        duplicates = [item.symbol for item in definitions if item.symbol in in_use]
        if duplicates and CONF_SYMBOLS not in errors:
            errors[CONF_SYMBOLS] = "symbol_in_use"
            placeholders["symbol"] = ", ".join(duplicates)

        seconds = _duration_to_seconds(user_input.get(CONF_SCAN_INTERVAL))
        if seconds < MINIMUM_SCAN_INTERVAL.total_seconds():
            errors[CONF_SCAN_INTERVAL] = "interval_too_short"

        return definitions, seconds


def _symbols_in_other_entries(hass: Any, exclude_entry_id: str | None) -> set[str]:
    """Return symbols configured in other entries of this integration."""
    symbols: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        symbols.update(item.symbol for item in get_symbol_definitions(entry.options))
    return symbols


class YahooFinanceConfigFlow(_SymbolValidationMixin, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yahoo Finance."""

    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            definitions, seconds = self._validate(user_input, errors, placeholders)
            if not errors:
                return self.async_create_entry(
                    title=_make_title(definitions),
                    data={},
                    options={
                        CONF_SYMBOLS: [item.as_dict() for item in definitions],
                        CONF_SCAN_INTERVAL: seconds,
                        CONF_MANUAL_UPDATE: DEFAULT_CONF_MANUAL_UPDATE,
                        CONF_DECIMAL_PLACES: DEFAULT_CONF_DECIMAL_PLACES,
                        **BOOLEAN_OPTIONS,
                    },
                )

        user_input = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SYMBOLS, default=user_input.get(CONF_SYMBOLS, "")
                ): SYMBOLS_SELECTOR,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=user_input.get(
                        CONF_SCAN_INTERVAL,
                        _seconds_to_duration(
                            int(DEFAULT_SCAN_INTERVAL.total_seconds())
                        ),
                    ),
                ): DURATION_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import a group of symbols from configuration.yaml."""
        await self.async_set_unique_id(f"yaml_{import_data['import_key']}")
        self._abort_if_unique_id_configured()

        options: dict[str, Any] = dict(import_data["options"])
        in_use = _symbols_in_other_entries(self.hass, None)
        definitions = [
            item
            for item in get_symbol_definitions(options)
            if item.symbol not in in_use
        ]
        if not definitions:
            return self.async_abort(reason="already_configured")

        options[CONF_SYMBOLS] = [item.as_dict() for item in definitions]
        return self.async_create_entry(
            title=_make_title(definitions), data={}, options=options
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> YahooFinanceOptionsFlow:
        """Return the options flow."""
        return YahooFinanceOptionsFlow()


class YahooFinanceOptionsFlow(_SymbolValidationMixin, OptionsFlow):
    """Handle Yahoo Finance options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        current = dict(self.config_entry.options)

        if user_input is not None:
            definitions, seconds = self._validate(
                user_input, errors, placeholders, self.config_entry.entry_id
            )
            if not errors:
                target = (user_input.get(CONF_TARGET_CURRENCY) or "").strip().upper()
                if target and (len(target) != 3 or not target.isalpha()):
                    errors[CONF_TARGET_CURRENCY] = "invalid_currency"
                else:
                    options: dict[str, Any] = {
                        CONF_SYMBOLS: [item.as_dict() for item in definitions],
                        CONF_SCAN_INTERVAL: seconds,
                        CONF_MANUAL_UPDATE: bool(user_input.get(CONF_MANUAL_UPDATE)),
                        CONF_DECIMAL_PLACES: int(
                            user_input.get(
                                CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES
                            )
                        ),
                        CONF_TARGET_CURRENCY: target or None,
                    }
                    for key, default in BOOLEAN_OPTIONS.items():
                        options[key] = bool(user_input.get(key, default))
                    # Only options change, so the update listener reloads once
                    return self.async_create_entry(data=options)

        values = {**current, **(user_input or {})}
        symbols_default = (
            user_input[CONF_SYMBOLS]
            if user_input and CONF_SYMBOLS in user_input
            else format_symbol_specs(get_symbol_definitions(current))
        )
        interval_default = (
            user_input[CONF_SCAN_INTERVAL]
            if user_input and CONF_SCAN_INTERVAL in user_input
            else _seconds_to_duration(
                int(
                    current.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
                    )
                )
            )
        )

        fields: dict[Any, Any] = {
            vol.Required(CONF_SYMBOLS, default=symbols_default): SYMBOLS_SELECTOR,
            vol.Required(
                CONF_SCAN_INTERVAL, default=interval_default
            ): DURATION_SELECTOR,
            vol.Optional(
                CONF_MANUAL_UPDATE,
                default=bool(
                    values.get(CONF_MANUAL_UPDATE, DEFAULT_CONF_MANUAL_UPDATE)
                ),
            ): bool,
            vol.Optional(
                CONF_DECIMAL_PLACES,
                default=int(
                    values.get(CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES)
                ),
            ): DECIMAL_PLACES_SELECTOR,
            vol.Optional(
                CONF_TARGET_CURRENCY,
                description={"suggested_value": values.get(CONF_TARGET_CURRENCY) or ""},
            ): str,
        }
        for key, default in BOOLEAN_OPTIONS.items():
            fields[vol.Optional(key, default=bool(values.get(key, default)))] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=placeholders,
        )
