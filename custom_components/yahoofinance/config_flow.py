"""Config flow for Yahoo Finance integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DECIMAL_PLACES,
    CONF_INCLUDE_DIVIDEND_VALUES,
    CONF_INCLUDE_FIFTY_DAY_VALUES,
    CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
    CONF_INCLUDE_POST_VALUES,
    CONF_INCLUDE_PRE_VALUES,
    CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
    CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
    CONF_SHOW_OFF_MARKET_VALUES,
    CONF_SCAN_INTERVAL,
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
    DOMAIN,
)

DEFAULT_SCAN_INTERVAL_HOURS = 6


def _parse_symbols(raw: str) -> list[str]:
    """Parse a comma/space separated string into an uppercase symbol list."""
    symbols = re.split(r"[\s,]+", raw.strip())
    return [s.strip().upper() for s in symbols if s.strip()]


class YahooFinanceConfigFlow(config_entries.ConfigFlow, domain="yahoofinance"):
    """Handle a config flow for Yahoo Finance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            symbols = _parse_symbols(user_input.get(CONF_SYMBOLS, ""))
            if not symbols:
                errors[CONF_SYMBOLS] = "no_symbols"
            else:
                title = (
                    f"Yahoo Finance ({', '.join(symbols[:3])}"
                    f"{'...' if len(symbols) > 3 else ''})"
                )
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_SYMBOLS: symbols,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SYMBOLS): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL_HOURS
                ): vol.All(int, vol.Range(min=1, max=24)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example": "AAPL, MSFT, ^GSPC, GBPUSD=X"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> YahooFinanceOptionsFlow:
        """Return the options flow."""
        return YahooFinanceOptionsFlow()


class YahooFinanceOptionsFlow(config_entries.OptionsFlow):
    """Handle Yahoo Finance options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        existing_symbols: list[str] = self.config_entry.data.get(CONF_SYMBOLS, [])
        existing_interval: int = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS),
        )
        opts = self.config_entry.options

        if user_input is not None:
            symbols = _parse_symbols(user_input.get(CONF_SYMBOLS, ""))
            if not symbols:
                errors[CONF_SYMBOLS] = "no_symbols"
            else:
                # Update symbols in entry data so the sensor list reflects changes
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_SYMBOLS: symbols},
                )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS
                        ),
                        CONF_DECIMAL_PLACES: user_input.get(
                            CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES
                        ),
                        CONF_SHOW_TRENDING_ICON: user_input.get(
                            CONF_SHOW_TRENDING_ICON, DEFAULT_CONF_SHOW_TRENDING_ICON
                        ),
                        CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT: user_input.get(
                            CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
                            DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
                        ),
                        CONF_SHOW_OFF_MARKET_VALUES: user_input.get(
                            CONF_SHOW_OFF_MARKET_VALUES, DEFAULT_CONF_SHOW_OFF_MARKET_VALUES
                        ),
                        CONF_INCLUDE_PRE_VALUES: user_input.get(
                            CONF_INCLUDE_PRE_VALUES, DEFAULT_CONF_INCLUDE_PRE_VALUES
                        ),
                        CONF_INCLUDE_POST_VALUES: user_input.get(
                            CONF_INCLUDE_POST_VALUES, DEFAULT_CONF_INCLUDE_POST_VALUES
                        ),
                        CONF_INCLUDE_FIFTY_DAY_VALUES: user_input.get(
                            CONF_INCLUDE_FIFTY_DAY_VALUES, DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES
                        ),
                        CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES: user_input.get(
                            CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
                            DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
                        ),
                        CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES: user_input.get(
                            CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
                            DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
                        ),
                        CONF_INCLUDE_DIVIDEND_VALUES: user_input.get(
                            CONF_INCLUDE_DIVIDEND_VALUES, DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SYMBOLS,
                    default=", ".join(existing_symbols),
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=existing_interval,
                ): vol.All(int, vol.Range(min=1, max=24)),
                vol.Optional(
                    CONF_DECIMAL_PLACES,
                    default=opts.get(CONF_DECIMAL_PLACES, DEFAULT_CONF_DECIMAL_PLACES),
                ): vol.All(int, vol.Range(min=-1, max=10)),
                vol.Optional(
                    CONF_SHOW_TRENDING_ICON,
                    default=opts.get(CONF_SHOW_TRENDING_ICON, DEFAULT_CONF_SHOW_TRENDING_ICON),
                ): bool,
                vol.Optional(
                    CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
                    default=opts.get(
                        CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
                        DEFAULT_CONF_SHOW_CURRENCY_SYMBOL_AS_UNIT,
                    ),
                ): bool,
                vol.Optional(
                    CONF_SHOW_OFF_MARKET_VALUES,
                    default=opts.get(
                        CONF_SHOW_OFF_MARKET_VALUES, DEFAULT_CONF_SHOW_OFF_MARKET_VALUES
                    ),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_PRE_VALUES,
                    default=opts.get(CONF_INCLUDE_PRE_VALUES, DEFAULT_CONF_INCLUDE_PRE_VALUES),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_POST_VALUES,
                    default=opts.get(CONF_INCLUDE_POST_VALUES, DEFAULT_CONF_INCLUDE_POST_VALUES),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_FIFTY_DAY_VALUES,
                    default=opts.get(
                        CONF_INCLUDE_FIFTY_DAY_VALUES, DEFAULT_CONF_INCLUDE_FIFTY_DAY_VALUES
                    ),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
                    default=opts.get(
                        CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
                        DEFAULT_CONF_INCLUDE_TWO_HUNDRED_DAY_VALUES,
                    ),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
                    default=opts.get(
                        CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
                        DEFAULT_CONF_INCLUDE_FIFTY_TWO_WEEK_VALUES,
                    ),
                ): bool,
                vol.Optional(
                    CONF_INCLUDE_DIVIDEND_VALUES,
                    default=opts.get(
                        CONF_INCLUDE_DIVIDEND_VALUES, DEFAULT_CONF_INCLUDE_DIVIDEND_VALUES
                    ),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )