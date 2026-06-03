"""The Yahoo finance component coordinator."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
import re
from typing import Any, Final

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BASE,
    CONSENT_HOST,
    CRUMB_RETRY_DELAY,
    CRUMB_RETRY_DELAY_429,
    DATA_REGULAR_MARKET_PRICE,
    EVENT_DATA_UPDATED,
    GET_CRUMB_URL,
    INITIAL_REQUEST_HEADERS,
    INITIAL_URL,
    LOGGER,
    MANUAL_SCAN_INTERVAL,
    NUMERIC_DATA_DEFAULTS,
    NUMERIC_DATA_GROUPS,
    STRING_DATA_KEYS,
    TOO_MANY_CRUMB_RETRY_FAILURES_COUNT,
    TOO_MANY_CRUMB_RETRY_FAILURES_DELAY,
    USER_AGENTS_FOR_XHR,
    XHR_REQUEST_HEADERS,
)
from .dataclasses import ConsentData

REQUEST_TIMEOUT: Final = 10
DELAY_ASYNC_REQUEST_REFRESH: Final = 5
RETRY_INTERVALS = (10, 20, 30, 60)


class CrumbCoordinator:
    """Class to gather crumb/cookie details."""

    _instance = None

    preferred_user_agent = ""

    def __init__(self, hass: HomeAssistant, websession: aiohttp.ClientSession) -> None:
        """Initialize."""
        self.cookies: SimpleCookie[str] = None
        self.crumb: str | None = None
        self._hass = hass
        self.retry_duration = CRUMB_RETRY_DELAY
        self._crumb_retry_count = 0
        self._websession = websession

    @staticmethod
    def get_static_instance(
        hass: HomeAssistant, websession: aiohttp.ClientSession
    ) -> CrumbCoordinator:
        """Get the singleton static CrumbCoordinator instance."""
        if CrumbCoordinator._instance is None:
            CrumbCoordinator._instance = CrumbCoordinator(hass, websession)
        return CrumbCoordinator._instance

    def reset(self) -> None:
        """Reset crumb and cookies."""
        self.crumb = self.cookies = None

    async def try_get_crumb_cookies(self) -> str | None:
        """Try to get crumb and cookies for data requests."""
        consent_data = await self.initial_navigation(INITIAL_URL)
        if consent_data is None:
            return None

        if consent_data.need_consent:
            if not await self.process_consent(consent_data):
                return None
            data = await self.initial_navigation(consent_data.successful_consent_url)
            if data is None:
                LOGGER.error("Post consent navigation failed")
                return None
            if data.need_consent:
                LOGGER.error("Yahoo reported needing consent even after we got it once")
                return None

        if self.cookies_missing():
            LOGGER.warning(
                "Attempting to get crumb but have no cookies, the operation might fail"
            )

        await self.try_crumb_page()
        return self.crumb

    async def initial_navigation(self, url: str) -> ConsentData | None:
        """Navigate to base page to determine if consent is needed."""
        LOGGER.debug("Navigating to base page %s", url)
        try:
            async with self._websession.get(
                url,
                headers=INITIAL_REQUEST_HEADERS,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                LOGGER.debug("Response %d, URL: %s", response.status, response.url)
                if response.status != HTTPStatus.OK:
                    LOGGER.error(
                        "Failed to navigate to %s, status=%d, reason=%s",
                        url,
                        response.status,
                        response.reason,
                    )
                    return None
                if response.cookies:
                    self.cookies = response.cookies
                if response.url.host.lower() == CONSENT_HOST:
                    LOGGER.info("Consent page %s detected", response.url)
                    return ConsentData(
                        need_consent=True,
                        consent_content=await response.text(),
                        consent_post_url=response.url,
                    )
                LOGGER.debug("No consent needed, have cookies=%s", bool(self.cookies))
        except TimeoutError as ex:
            LOGGER.error("Timed out accessing initial url. %s", ex)
        except aiohttp.ClientError as ex:
            LOGGER.error("Error accessing initial url. %s", ex)
        except Exception as ex:  # noqa: BLE001
            LOGGER.error("Unexpected error accessing initial url. %s", ex)
        return ConsentData()

    async def process_consent(self, consent_data: ConsentData) -> bool:
        """Process GDPR consent."""
        form_data = self.build_consent_form_data(consent_data.consent_content)
        LOGGER.debug("Posting consent %s", str(form_data))
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._websession.post(
                    consent_data.consent_post_url,
                    data=form_data,
                    headers=INITIAL_REQUEST_HEADERS,
                )
                if response.status != HTTPStatus.OK:
                    LOGGER.error(
                        "Failed to post consent %d, reason=%s",
                        response.status,
                        response.reason,
                    )
                    return False
                if response.cookies:
                    self.cookies = response.cookies
                consent_data.successful_consent_url = response.url
                LOGGER.debug(
                    "After consent processing, have cookies=%s", bool(self.cookies)
                )
                return True
        except TimeoutError as ex:
            LOGGER.error("Timed out processing consent. %s", ex)
        except aiohttp.ClientError as ex:
            LOGGER.error("Error accessing consent url. %s", ex)
        return False

    def cookies_missing(self) -> bool:
        """Check if we don't have any cookies."""
        return self.cookies is None or len(self.cookies) == 0

    async def try_crumb_page(self) -> str | None:
        """Try to get crumb from the end point."""
        LOGGER.info("Accessing crumb page")
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        last_status = 0

        for user_agent in USER_AGENTS_FOR_XHR:
            headers = {**XHR_REQUEST_HEADERS, "user-agent": user_agent}
            async with self._websession.get(
                GET_CRUMB_URL, headers=headers, timeout=timeout, cookies=self.cookies
            ) as response:
                last_status = response.status
                if last_status == HTTPStatus.OK:
                    self.preferred_user_agent = user_agent
                    self.crumb = await response.text()
                    if not self.crumb:
                        LOGGER.error("No crumb reported")
                    LOGGER.info("Crumb page reported %s", self.crumb)
                    self._crumb_retry_count = 0
                    return self.crumb
                if last_status == 429:
                    LOGGER.info(
                        "Crumb request responded with status 429 for '%s', re-trying with different agent",
                        user_agent,
                    )
                else:
                    LOGGER.error(
                        "Crumb request responded with status=%d, reason=%s",
                        last_status,
                        response.reason,
                    )
                    break

        self._crumb_retry_count += 1
        if self._crumb_retry_count > TOO_MANY_CRUMB_RETRY_FAILURES_COUNT:
            self.retry_duration = TOO_MANY_CRUMB_RETRY_FAILURES_DELAY
            self._crumb_retry_count = 0
        else:
            self.retry_duration = (
                CRUMB_RETRY_DELAY_429 if last_status == 429 else CRUMB_RETRY_DELAY
            )
        LOGGER.info("Crumb failure, will retry after %d seconds", self.retry_duration)
        return None

    def build_consent_form_data(self, content: str) -> dict[str, str]:
        """Build consent form data from response content."""
        pattern = r'<input.*?type="hidden".*?name="(.*?)".*?value="(.*?)".*?>'
        matches = re.findall(pattern, content)
        basic_data = {"reject": "reject"}
        additional_data = dict(matches)
        return {**basic_data, **additional_data}


class YahooSymbolUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Yahoo finance data update coordinator."""

    @staticmethod
    def parse_symbol_data(symbol_data: dict) -> dict[str, Any]:
        """Return data pieces which we care about, use 0 for missing numeric values."""
        data = {}
        for data_group in NUMERIC_DATA_GROUPS.values():
            for value in data_group:
                key = value[0]
                default_value = NUMERIC_DATA_DEFAULTS.get(key, 0)
                data[key] = symbol_data.get(key, default_value)
        for key in STRING_DATA_KEYS:
            data[key] = symbol_data.get(key)
        return data

    @staticmethod
    def fix_conversion_symbol(symbol: str, symbol_data: Any) -> str:
        """Fix the conversion symbol from data."""
        if symbol is None or symbol == "" or not symbol.endswith("=X"):
            return symbol
        short_name = symbol_data.get("shortName") or ""
        from_to = short_name.split("/")
        if len(from_to) != 2:
            return symbol
        from_currency = from_to[0]
        to_currency = from_to[1]
        if from_currency == "" or to_currency == "":
            return symbol
        conversion_symbol = f"{from_currency}{to_currency}=X"
        if conversion_symbol != symbol:
            LOGGER.info(
                "Conversion symbol updated to %s from %s", conversion_symbol, symbol
            )
        return conversion_symbol

    def __init__(
        self,
        symbols: list[str],
        hass: HomeAssistant,
        update_interval: timedelta,
        cc: CrumbCoordinator,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize."""
        self._symbols = symbols
        self.data = None
        self.loop = hass.loop
        self.websession = websession
        self._cc = cc
        self.failed_count = 0

        if isinstance(update_interval, str) and update_interval == MANUAL_SCAN_INTERVAL:
            update_interval = None

        super().__init__(
            hass,
            LOGGER,
            name="YahooSymbolUpdateCoordinator",
            update_interval=update_interval,
        )

    def get_symbols(self) -> list[str]:
        """Return symbols tracked by the coordinator."""
        return self._symbols

    async def _async_request_refresh_later(self, _now):
        """Request async_request_refresh."""
        await self.async_request_refresh()

    def add_symbol(self, symbol: str) -> bool:
        """Add symbol to the symbol list."""
        if symbol not in self._symbols:
            self._symbols.append(symbol)
            event.async_call_later(
                self.hass,
                DELAY_ASYNC_REQUEST_REFRESH,
                self._async_request_refresh_later,
            )
            LOGGER.info(
                "Added %s and requested update in %d seconds",
                symbol,
                DELAY_ASYNC_REQUEST_REFRESH,
            )
            return True
        return False

    async def get_json(self) -> dict:
        """Get the JSON data."""
        url = await self.build_request_url()

        preferred_user_agent = self._cc.preferred_user_agent
        if preferred_user_agent:
            LOGGER.info(
                "Requesting data request with the preferred agent '%s'",
                preferred_user_agent,
            )
            [result_json, status] = await self._fetch_json(url, preferred_user_agent)
            if status == HTTPStatus.OK:
                return result_json
            if status == 429:
                LOGGER.info(
                    "Data request responded with status 429 for '%s', re-trying other agents",
                    preferred_user_agent,
                )

        for user_agent in USER_AGENTS_FOR_XHR:
            if preferred_user_agent == user_agent:
                continue
            [result_json, status] = await self._fetch_json(url, user_agent)
            if status == HTTPStatus.OK:
                LOGGER.info("Successful data received for '%s'", user_agent)
                return result_json
            if status != 429:
                break
            LOGGER.info(
                "Data request responded with status 429 for '%s', re-trying with different agent",
                user_agent,
            )
        return None

    async def _fetch_json(self, url, user_agent) -> tuple[dict, int]:
        """Fetch JSON data with the specified user agent."""
        headers = {**XHR_REQUEST_HEADERS, "user-agent": user_agent}
        LOGGER.debug("Requesting data from '%s' with agent %s", url, user_agent)

        async with asyncio.timeout(REQUEST_TIMEOUT):
            response = await self.websession.get(
                url, headers=headers, cookies=self._cc.cookies
            )
            if response.status == 429:
                return [None, 429]

            result_json = await response.json()
            if response.status == HTTPStatus.OK:
                return [result_json, response.status]

            finance_error_code_tuple = (
                YahooSymbolUpdateCoordinator.get_finance_error_code(result_json)
            )
            if finance_error_code_tuple:
                finance_error_code, finance_error_description = finance_error_code_tuple
                LOGGER.info(
                    "Received status %d (%s %s) for %s",
                    response.status,
                    finance_error_code,
                    finance_error_description,
                    url,
                )
                if finance_error_code == "Unauthorized":
                    LOGGER.info("Resetting crumbs")
                    self._cc.reset()
            else:
                LOGGER.info(
                    "Received status %d for %s, result=%s",
                    response.status,
                    url,
                    result_json,
                )
        return [None, response.status]

    async def build_request_url(self) -> str:
        """Build the request url."""
        url = BASE + ",".join(self._symbols)
        crumb = self._cc.crumb
        if crumb is None:
            crumb = await self._cc.try_get_crumb_cookies()
        if crumb is not None:
            url = url + "&crumb=" + crumb
        return url

    @staticmethod
    def get_finance_error_code(error_json) -> tuple[str, str] | None:
        """Parse error code from the json."""
        if error_json:
            finance = error_json.get("finance")
            if finance:
                finance_error = finance.get("error")
                if finance_error:
                    return finance_error.get("code"), finance_error.get("description")
        return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Return updated data if new JSON is valid."""
        retry_after = RETRY_INTERVALS[min(self.failed_count, len(RETRY_INTERVALS) - 1)]

        try:
            json_data = await self.get_json()
        except (TimeoutError, aiohttp.ClientError) as error:
            self.failed_count += 1
            raise UpdateFailed(error, retry_after=retry_after) from error

        if json_data is None:
            self.failed_count += 1
            raise UpdateFailed("No data received", retry_after=retry_after)

        if "quoteResponse" not in json_data:
            self.failed_count += 1
            raise UpdateFailed(
                "Data invalid, 'quoteResponse' not found.", retry_after=retry_after
            )

        quoteResponse = json_data["quoteResponse"]  # noqa: N806

        if "error" in quoteResponse:
            if quoteResponse["error"] is not None:
                self.failed_count += 1
                raise UpdateFailed(quoteResponse["error"], retry_after=retry_after)

        if "result" not in quoteResponse:
            self.failed_count += 1
            raise UpdateFailed(
                "Data invalid, no 'result' found", retry_after=retry_after
            )

        result = quoteResponse["result"]
        if result is None:
            self.failed_count += 1
            raise UpdateFailed(
                "Data invalid, 'result' is None", retry_after=retry_after
            )

        (error_encountered, data) = self.process_json_result(result)
        self.failed_count = 0

        if error_encountered:
            LOGGER.info("Data = %s", result)
        else:
            LOGGER.debug("Data = %s", result)

        self.hass.bus.fire(EVENT_DATA_UPDATED, {"symbols": ",".join(self._symbols)})
        return data

    def process_json_result(self, result) -> tuple[bool, dict[str, Any]]:
        """Process json result and return (error status, updated data)."""
        data = self.data or {}
        symbols = self._symbols.copy()
        error_encountered = False

        for symbol_data in result:
            symbol = symbol_data["symbol"]

            if symbol in symbols:
                symbols.remove(symbol)
            else:
                fixed_symbol = self.fix_conversion_symbol(symbol, symbol_data)
                if fixed_symbol in symbols:
                    symbols.remove(fixed_symbol)
                    symbol = fixed_symbol
                else:
                    LOGGER.warning("Received %s not in symbol list", symbol)
                    error_encountered = True

            data[symbol] = self.parse_symbol_data(symbol_data)
            LOGGER.debug(
                "Updated %s to %s",
                symbol,
                data[symbol][DATA_REGULAR_MARKET_PRICE],
            )

        if len(symbols) > 0:
            LOGGER.warning("No data received for %s", symbols)
            error_encountered = True

        return (error_encountered, data)
