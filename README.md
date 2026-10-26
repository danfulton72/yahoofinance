[![GitHub Release](https://img.shields.io/github/v/release/danfulton72/yahoofinance)](https://github.com/danfulton72/yahoofinance/releases)
[![License](https://img.shields.io/github/license/danfulton72/yahoofinance)](LICENSE)
[![Validate](https://github.com/danfulton72/yahoofinance/actions/workflows/validate.yaml/badge.svg)](https://github.com/danfulton72/yahoofinance/actions/workflows/validate.yaml)

# Yahoo Finance for Home Assistant

A custom integration that shows stock, index, fund and currency quotes from [Yahoo Finance](https://finance.yahoo.com/) as sensors, configured entirely from the Home Assistant UI.

This is a fork of [iprak/yahoofinance](https://github.com/iprak/yahoofinance) that replaces YAML configuration with a config flow. It uses the same `yahoofinance` domain, so install one or the other, not both.

> Requests can fail in regions covered by GDPR, where Yahoo requires a consent step. The integration attempts it automatically, but results vary.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/danfulton72/yahoofinance` with type **Integration**.
3. Install **Yahoo Finance** and restart Home Assistant.

### Manual

Copy `custom_components/yahoofinance/` to `<config>/custom_components/yahoofinance/` and restart Home Assistant.

Requires Home Assistant 2025.12 or newer.

## Configuration

Go to **Settings → Devices & services → Add integration → Yahoo Finance** and enter:

- **Symbols** – separated by commas, spaces or new lines, in Yahoo ticker format.
- **Update interval** – how often to fetch data (default 6 hours, minimum 30 seconds).

Each symbol can carry per-symbol settings after a colon:

| Entry | Meaning |
| --- | --- |
| `AAPL` | Plain symbol |
| `LGEN.L:USD` | Convert prices to USD (`target_currency`) |
| `GBPUSD=X:nounit` | No unit of measurement (`no_unit`), useful for rates and indices |
| `EMIM.L:EUR:nounit` | Both |

Each symbol creates `sensor.yahoofinance_<symbol>`, e.g. `sensor.yahoofinance_aapl`. A symbol can only belong to one Yahoo Finance entry.

If some symbols need a different update interval, add another Yahoo Finance entry for them.

### Options

Select **Configure** on the entry to change symbols, the interval and:

| Option | Default | Description |
| --- | --- | --- |
| Disable automatic updates | off | Only refresh when `yahoofinance.refresh_symbols` is called |
| Decimal places | 2 | `-1` disables rounding, `0` gives whole numbers |
| Default target currency | – | Applied to symbols without their own `:CUR` |
| Show trending icon | off | `mdi:trending-up/down/neutral` instead of the currency icon |
| Show currency symbol as unit | off | `$` instead of `USD`* |
| Show off-market prices | off | Use the pre/post market price when it is newer than the regular price |
| Include pre-market / post-market / 50-day / 200-day / 52-week / dividend attributes | off | See below |

\* Changing the unit, or using `nounit`, affects long-term statistics. Home Assistant will raise a warning that you can resolve under **Developer tools → Statistics**.

### Currency conversion

With a target currency, prices are converted using the matching Yahoo rate symbol, e.g. `EMIM.L:EUR` on a USD-quoted symbol uses `USDEUR=X`. The rate symbol is fetched automatically. Prices quoted in pence (`GBp`) are converted to pounds. Only price attributes are converted.

## Migrating from YAML

Existing `yahoofinance:` YAML configuration is imported automatically on startup:

- Symbols are grouped into one entry per `scan_interval`, and `scan_interval: manual` becomes **Disable automatic updates**.
- `target_currency` and `no_unit` are kept, and existing entity IDs and history are preserved.
- A repair notice asks you to remove the YAML once it has been imported. Further changes are made in the UI.

## Attributes

Always present: `attribution`, `currencySymbol`, `symbol`, `quoteType`, `quoteSourceName`, `marketState`, `averageDailyVolume10Day`, `averageDailyVolume3Month`, `regularMarketChange`, `regularMarketChangePercent`, `regularMarketDayHigh`, `regularMarketDayLow`, `regularMarketPreviousClose`, `regularMarketPrice`, `regularMarketVolume`, `regularMarketTime`, `forwardPE`, `trailingPE` and `trending`.

Optional groups:

- **Pre-market**: `preMarketChange`, `preMarketChangePercent`, `preMarketPrice`, `preMarketTime`
- **Post-market**: `postMarketChange`, `postMarketChangePercent`, `postMarketPrice`, `postMarketTime`
- **50-day**: `fiftyDayAverage`, `fiftyDayAverageChange`, `fiftyDayAverageChangePercent`
- **200-day**: `twoHundredDayAverage`, `twoHundredDayAverageChange`, `twoHundredDayAverageChangePercent`
- **52-week**: `fiftyTwoWeekLow`, `fiftyTwoWeekLowChange`, `fiftyTwoWeekLowChangePercent`, `fiftyTwoWeekHigh`, `fiftyTwoWeekHighChange`, `fiftyTwoWeekHighChangePercent`
- **Dividend**: `dividendDate` (ISO date), `dividendRate`, `dividendYield`, `trailingAnnualDividendRate`, `trailingAnnualDividendYield`

Attributes are `null` when Yahoo has no data for them.

## Actions and events

- `yahoofinance.refresh_symbols` refreshes every Yahoo Finance entry.
- The event `yahoofinance_data_updated` fires after each update with the list of symbols.

## Example: coloured trending icons

Icons can be coloured with [card-mod](https://github.com/thomasloven/lovelace-card-mod), here combined with [auto-entities](https://github.com/thomasloven/lovelace-auto-entities):

```yaml
type: custom:auto-entities
card:
  type: entities
  title: Financial
filter:
  include:
    - entity_id: sensor.yahoofinance_*
      options:
        card_mod:
          style: |
            :host {
              --card-mod-icon-color: {% set value = state_attr(config.entity, "trending") %}
                {% if value == "up" %} green {% elif value == "down" %} red {% else %} var(--state-icon-color) {% endif %};
            }
```

## Breaking changes

- **2.1.1** – Numeric attributes Yahoo doesn't report are now `null` instead of `0`, e.g. `preMarketPrice` outside pre-market or `dividendRate` for non-dividend stocks. Templates that do maths on them should handle `none`, e.g. `state_attr('sensor.yahoofinance_aapl', 'dividendRate') | float(0)`.
- **2.1.1** – Configuration moved into entry options and the update interval is now set as a duration. Entries from 2.0.0 are migrated automatically. YAML configuration is imported instead of rejected.
- **2.0.0** – Configuration moved from YAML to the UI.
- **1.5.0** – Dividend values are controlled by `include_dividend_values`, and all optional attribute groups are excluded by default.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

### Releases

Releases are published by the **Validate** workflow after HACS validation, hassfest and the tests pass:

- **Automatic:** a push to `master` publishes the next patch release, but only if something under `custom_components/` or `hacs.json` changed since the last release. Docs and CI changes don't publish a release.
- **Manual:** to publish a minor or major release, run **Actions → Validate → Run workflow** on `master` and choose the bump.
- **Version:** the release tag points at a commit that sets the manifest version. Nothing is pushed to `master`, so branch protection is fine, and the manifest on `master` can lag behind the latest tag.
