"""Tests for Yahoo Finance component."""

import asyncio
from http import HTTPStatus
import random
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from custom_components.yahoofinance import (
    DEFAULT_SCAN_INTERVAL,
    YahooSymbolUpdateCoordinator,
    coordinator,
)
from custom_components.yahoofinance.const import (
    BASE,
    DATA_REGULAR_MARKET_PRICE,
    MANUAL_SCAN_INTERVAL,
)
from custom_components.yahoofinance.coordinator import CrumbCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import TEST_CRUMB, TEST_SYMBOL  # noqa: TID251
from .conftest import create_mock_coordinator, mock_get_returning  # noqa: TID251

TEST_SYMBOL2 = "RBOT.L"
SECOND_TEST_SYMBOL = "^SSMI"
YSUC = "custom_components.yahoofinance.YahooSymbolUpdateCoordinator"
SESSION = async_get_clientsession


@pytest.mark.parametrize(
    ("parsed_json", "message"),
    [
        (None, "No data"),
        ({}, "quoteResponse missing"),
        ({"quoteResponse": {"error": "fake error"}}, "error present"),
        ({"quoteResponse": {}}, "result missing"),
        ({"quoteResponse": {"result": None}}, "result is None"),
    ],
)
async def test_incomplete_json(
    hass: HomeAssistant, parsed_json, message, mocked_crumb_coordinator
) -> None:
    """Existing data is not updated if JSON is invalid."""

    mock_coordinator = YahooSymbolUpdateCoordinator(
        None,
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )
    mock_coordinator.get_json = AsyncMock(return_value=parsed_json)

    existing_data = {TEST_SYMBOL: {DATA_REGULAR_MARKET_PRICE: random.random()}}
    mock_coordinator.data = existing_data

    # last_update_success is initially True
    assert mock_coordinator.last_update_success is True

    await mock_coordinator.async_refresh()
    await hass.async_block_till_done()

    # Data was invalid, existing data was left unchanged and last_update_success becomes False
    assert mock_coordinator.data is existing_data
    assert mock_coordinator.last_update_success is False


@pytest.mark.parametrize(
    "raised_exception",
    [
        (Exception),
        (aiohttp.ClientError),
        (asyncio.TimeoutError),
    ],
)
async def test_json_download_failure(
    hass: HomeAssistant, raised_exception, mocked_crumb_coordinator
) -> None:
    """Existing data is not updated if exception encountered while downloading json."""

    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )
    mock_coordinator.websession = Mock()
    mock_coordinator.websession.get = Mock(side_effect=raised_exception)

    existing_data = {TEST_SYMBOL: {DATA_REGULAR_MARKET_PRICE: random.random()}}
    mock_coordinator.data = existing_data

    mock_coordinator_listener = Mock()
    mock_coordinator.async_add_listener(mock_coordinator_listener)

    with patch.object(mock_coordinator, "_schedule_refresh") as mock_schedule_refresh:
        await mock_coordinator.async_refresh()
        await hass.async_block_till_done()

        assert mock_coordinator.data is existing_data
        assert mock_coordinator.last_update_success is False

        assert len(mock_coordinator_listener.mock_calls) == 1
        assert len(mock_schedule_refresh.mock_calls) == 1


async def test_successful_data_parsing(
    hass: HomeAssistant, mocked_crumb_coordinator, mock_json
) -> None:
    """Tests successful data parsing."""

    mock_coordinator = create_mock_coordinator(hass, mocked_crumb_coordinator)
    mock_coordinator.get_json = AsyncMock(return_value=mock_json)

    await mock_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert mock_coordinator.data is not None
    assert TEST_SYMBOL in mock_coordinator.data
    assert mock_coordinator.last_update_success is True


async def test_add_symbol(hass: HomeAssistant, mocked_crumb_coordinator) -> None:
    """Add symbol for load."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        [],
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )

    with patch("homeassistant.helpers.event.async_call_later") as mock_call_later:
        assert mock_coordinator.add_symbol(TEST_SYMBOL) is True
        assert TEST_SYMBOL in mock_coordinator.get_symbols()
        assert len(mock_call_later.mock_calls) == 1


async def test_add_symbol_existing(
    hass: HomeAssistant, mocked_crumb_coordinator
) -> None:
    """Test check for existing symbols."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )
    assert mock_coordinator.add_symbol(TEST_SYMBOL) is False


@pytest.mark.parametrize(
    ("symbol", "symbol_data", "expected_symbol"),
    [
        (None, None, None),
        ("TEST", None, "TEST"),  # Not conversion symbol
        ("TEST", {"shortName": "USD/EUR"}, "TEST"),  # Not conversion symbol
        ("USDEUR=X", {"shortName": "USD/EUR"}, "USDEUR=X"),  # No change necessary
        ("EUR=X", {"shortName": "USD/EUR"}, "USDEUR=X"),  # Missing USD
        (
            "SYMBOL=X",
            {"shortName": "USD/EUR"},
            "USDEUR=X",
        ),  # symbol does not match shortName at all
        ("EUR=X", {"shortName": "USDEUR"}, "EUR=X"),  # shortName is invalid
        ("EUR=X", {"shortName": "USD/"}, "EUR=X"),  # shortName is invalid
        ("EUR=X", {"shortName": "/EUR"}, "EUR=X"),  # shortName is invalid
    ],
)
async def test_fix_conversion_symbol(
    hass: HomeAssistant, symbol, symbol_data, expected_symbol, mocked_crumb_coordinator
) -> None:
    """Test conversion symbol correction."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        None,
        mocked_crumb_coordinator,
        SESSION,
    )
    assert (
        mock_coordinator.fix_conversion_symbol(symbol, symbol_data) == expected_symbol
    )


@pytest.mark.parametrize(
    ("symbols", "result", "expected_error_encountered", "expected_conversion_count"),
    [
        (  # Symbol missing in result
            [TEST_SYMBOL, TEST_SYMBOL2],
            [{"symbol": TEST_SYMBOL}],
            True,
            0,
        ),
        (  # All symbols present in result
            [TEST_SYMBOL, TEST_SYMBOL2],
            [
                {"symbol": TEST_SYMBOL},
                {"symbol": TEST_SYMBOL2},
            ],
            False,
            0,
        ),
        (["USDEUR=X"], [{"symbol": "EUR=X"}], False, 1),  # Symbol conversion fix test
        (  # Multiple conversion symbol fix test
            [
                TEST_SYMBOL,
                "USDEUR=X",
                "USDCHF=X",
            ],
            [{"symbol": "EUR=X"}, {"symbol": TEST_SYMBOL}, {"symbol": "CHF=X"}],
            False,
            2,
        ),
        (  # Symbol conversion missing test
            ["USDCHF=X"],
            [{"symbol": "EUR=X"}],
            True,
            1,
        ),
    ],
)
async def test_process_json_result(
    hass: HomeAssistant,
    symbols,
    result,
    expected_error_encountered,
    expected_conversion_count,
    mocked_crumb_coordinator,
) -> None:
    """No update is performed if update_interval is None."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        symbols,
        hass,
        None,
        mocked_crumb_coordinator,
        SESSION,
    )

    def prefix_conversion_symbol(symbol: str, symbol_data: any):
        return f"USD{symbol}"

    mock_fix_conversion_symbol = Mock(side_effect=prefix_conversion_symbol)
    mock_coordinator.fix_conversion_symbol = mock_fix_conversion_symbol

    (error_encountered, data) = mock_coordinator.process_json_result(result)

    assert len(mock_fix_conversion_symbol.mock_calls) == expected_conversion_count
    assert error_encountered is expected_error_encountered
    assert data is not None


async def test_logging_when_process_json_result_reports_error(
    hass: HomeAssistant, mock_json, mocked_crumb_coordinator
) -> None:
    """Tests call to logger.info() when process_json_result reports an error."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )

    mock_response = Mock()
    mock_response.status = HTTPStatus.NO_CONTENT
    mock_response.json = AsyncMock(return_value=mock_json)

    mock_coordinator.websession = Mock()
    mock_coordinator.websession.get = mock_get_returning(mock_response)
    mock_coordinator.process_json_result = Mock(return_value=(True, None))

    with patch.object(coordinator, "LOGGER") as mock_logger:
        await mock_coordinator.async_refresh()
        await hass.async_block_till_done()

        assert mock_logger.info.call_count == 1


def test_crumbcoordinator_ctor(hass: HomeAssistant) -> None:
    """Test CrumbCoordinator contructor."""
    instance = CrumbCoordinator(hass, SESSION)
    assert instance.cookies is None
    assert instance.crumb is None


def test_crumbcoordinator_reset(hass: HomeAssistant) -> None:
    """Test CrumbCoordinator contructor."""
    instance = CrumbCoordinator(hass, SESSION)
    instance.cookies = "cookies"
    instance.crumb = "crumb"

    instance.reset()
    assert instance.cookies is None
    assert instance.crumb is None


async def test_build_request_url(hass: HomeAssistant, mocked_crumb_coordinator) -> None:
    """Test build_request_url."""

    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        DEFAULT_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )
    # print(await mock_coordinator.build_request_url())
    assert (
        await mock_coordinator.build_request_url()
        == BASE + TEST_SYMBOL + "&crumb=" + TEST_CRUMB
    )


def test_get_finance_error_code() -> None:
    """Test get_finance_error_code."""
    assert YahooSymbolUpdateCoordinator.get_finance_error_code(None) is None
    assert YahooSymbolUpdateCoordinator.get_finance_error_code({}) is None
    assert YahooSymbolUpdateCoordinator.get_finance_error_code({"finance": {}}) is None
    assert YahooSymbolUpdateCoordinator.get_finance_error_code(
        {"finance": {"error": {"code": "code", "description": "description"}}}
    ) == ("code", "description")


def test_manual_scan_interval(hass: HomeAssistant, mocked_crumb_coordinator) -> None:
    """Test manual scan interval."""
    mock_coordinator = YahooSymbolUpdateCoordinator(
        [TEST_SYMBOL],
        hass,
        MANUAL_SCAN_INTERVAL,
        mocked_crumb_coordinator,
        SESSION,
    )
    assert mock_coordinator.update_interval is None


async def test_initial_navigation_failure_returns_none(hass: HomeAssistant) -> None:
    """A network error during navigation is reported as failure, not 'no consent'."""
    session = Mock()
    session.get = Mock(side_effect=aiohttp.ClientError("boom"))
    instance = CrumbCoordinator(hass, session)

    assert await instance.initial_navigation("https://example.com") is None
    assert await instance.try_get_crumb_cookies() is None


@pytest.mark.parametrize(
    "raised_exception", [aiohttp.ClientError("boom"), TimeoutError()]
)
async def test_crumb_page_network_error_is_handled(
    hass: HomeAssistant, raised_exception
) -> None:
    """Crumb request errors do not propagate and schedule a retry."""
    session = Mock()
    session.get = Mock(side_effect=raised_exception)
    instance = CrumbCoordinator(hass, session)

    assert await instance.try_crumb_page() is None
    assert instance.crumb is None
    assert instance.retry_duration > 0


async def test_crumb_page_success(hass: HomeAssistant) -> None:
    """A successful crumb response is stored."""
    response = Mock(status=HTTPStatus.OK)
    response.text = AsyncMock(return_value=TEST_CRUMB)
    session = Mock()
    session.get = mock_get_returning(response)
    instance = CrumbCoordinator(hass, session)

    assert await instance.try_crumb_page() == TEST_CRUMB
    assert instance.crumb == TEST_CRUMB
    # The response context manager was exited, releasing the connection
    session.get.return_value.__aexit__.assert_awaited()


async def test_fetch_json_429_releases_response(
    hass: HomeAssistant, mocked_crumb_coordinator
) -> None:
    """429 responses are released and reported."""
    mock_coordinator = create_mock_coordinator(hass, mocked_crumb_coordinator)
    response = Mock(status=HTTPStatus.TOO_MANY_REQUESTS)
    mock_coordinator.websession = Mock()
    mock_coordinator.websession.get = mock_get_returning(response)

    assert await mock_coordinator._fetch_json("url", "agent") == (
        None,
        HTTPStatus.TOO_MANY_REQUESTS,
    )
    mock_coordinator.websession.get.return_value.__aexit__.assert_awaited()


async def test_fetch_json_unauthorized_resets_crumb(
    hass: HomeAssistant, mocked_crumb_coordinator
) -> None:
    """An Unauthorized finance error resets the crumb."""
    mock_coordinator = create_mock_coordinator(hass, mocked_crumb_coordinator)
    mocked_crumb_coordinator.crumb = TEST_CRUMB
    response = Mock(status=HTTPStatus.UNAUTHORIZED)
    response.json = AsyncMock(
        return_value={
            "finance": {"error": {"code": "Unauthorized", "description": "x"}}
        }
    )
    mock_coordinator.websession = Mock()
    mock_coordinator.websession.get = mock_get_returning(response)

    assert await mock_coordinator._fetch_json("url", "agent") == (
        None,
        HTTPStatus.UNAUTHORIZED,
    )
    assert mocked_crumb_coordinator.crumb is None


async def test_process_consent_releases_response(hass: HomeAssistant) -> None:
    """The consent POST uses a context manager so the connection is released."""
    response = Mock(status=HTTPStatus.OK, cookies=None, url="https://after")
    session = Mock()
    session.post = mock_get_returning(response)
    instance = CrumbCoordinator(hass, session)
    consent = coordinator.ConsentData(
        need_consent=True, consent_content="", consent_post_url="https://consent"
    )

    assert await instance.process_consent(consent) is True
    assert consent.successful_consent_url == "https://after"
    session.post.return_value.__aexit__.assert_awaited()


async def test_add_symbol_schedules_single_refresh(
    hass: HomeAssistant, mocked_crumb_coordinator
) -> None:
    """Adding several symbols queues only one delayed refresh."""
    mock_coordinator = create_mock_coordinator(hass, mocked_crumb_coordinator)
    with patch.object(coordinator.event, "async_call_later") as mock_call_later:
        assert mock_coordinator.add_symbol("A")
        assert mock_coordinator.add_symbol("B")
    assert mock_call_later.call_count == 1


def test_missing_numeric_fields_remain_unknown() -> None:
    """Missing quote values must never masquerade as real zeros."""
    from custom_components.yahoofinance.const import DATA_REGULAR_MARKET_PRICE

    value = YahooSymbolUpdateCoordinator.parse_symbol_data({"symbol": "AAPL"})
    assert value[DATA_REGULAR_MARKET_PRICE] is None


def test_actual_zero_is_preserved() -> None:
    """A real zero remains distinct from missing quote data."""
    from custom_components.yahoofinance.const import DATA_REGULAR_MARKET_PRICE

    value = YahooSymbolUpdateCoordinator.parse_symbol_data(
        {"symbol": "AAPL", DATA_REGULAR_MARKET_PRICE: 0}
    )
    assert value[DATA_REGULAR_MARKET_PRICE] == 0
