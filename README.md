# Binance Futures Trading Bot (Demo Trading / USDT-M)

A small, industrial-grade CLI for placing MARKET, LIMIT, STOP (stop-limit),
and TWAP orders on **Binance Futures Demo Trading (USDT-M)**, built with a
clean separation between the HTTP/signing layer, order logic, validation,
and CLI.

**Status: verified working against live Binance Demo Trading.** Market and
Limit orders placed with this bot show up correctly in Binance's own Order
History with real `orderId`s, `Filled` status, fill prices, and a live
position reflected in the account's Futures wallet (see
`docs/verification/` for screenshots).

## Why this isn't just a script that calls `python-binance`

- **Signing is hand-rolled and auditable** (`bot/client.py`) - HMAC-SHA256 over the exact query string sent, with `timestamp` + `recvWindow` on every signed call, so there's no hidden SDK behavior between you and the wire request.
- **Decimal, not float**, for every quantity/price, avoiding classic binary-rounding bugs that cause exchange APIs to reject orders.
- **Idempotent orders**: every order gets a generated `newClientOrderId`, so the automatic retry-on-5xx/429 policy can never silently double-place an order.
- **Secret redaction built into logging**, not bolted on after — see [SECURITY_REVIEW.md](./SECURITY_REVIEW.md).
- **A real bonus feature, not a toggle**: TWAP execution (see below) is genuinely useful and not something you get from wrapping `python-binance` in a CLI.

## A note on Binance's platform migration

Binance retired the old `testnet.binancefuture.com` **website** in August
2025 and merged Futures Testnet into **Demo Trading**. The website now
redirects to `demo.binance.com`, and the API host moved to
`https://demo.binance.com`. The signing scheme, endpoints, and request/
response shapes are unchanged - only the host and account-creation flow
moved. This bot targets the current host by default.

## Setup

1. **Create a Binance Demo Trading (Futures) account and API key**
   Go to https://demo.binance.com, log in, and generate a Futures API key + secret from Account → API Management. This is a full sandbox with simulated funds (typically pre-funded with demo USDT) - no real money is ever involved.

2. **Clone and install**
   ```bash
   git clone <this-repo>
   cd trading_bot
   python3 -m venv .venv && source .venv/bin/activate   
   pip install -r requirements.txt
   ```

3. **Configure credentials**
   ```bash
   cp .env.example .env
   ```

## How to run

All commands support `--dry-run` (validate + print the request, send nothing) and `--yes` (skip the confirmation prompt, for scripting). Both flags work before *or* after the subcommand.

```bash
# Market order
python cli.py market --symbol BTCUSDT --side BUY --quantity 0.01

# Limit order
python cli.py limit --symbol BTCUSDT --side SELL --quantity 0.01 --price 70000

# Bonus: Stop-limit order
python cli.py stop-limit --symbol BTCUSDT --side SELL --quantity 0.01 --price 60000 --stop-price 60500

# Bonus: TWAP — split 0.05 BTC into 5 market slices, 10s apart
python cli.py twap --symbol BTCUSDT --side BUY --quantity 0.05 --slices 5 --interval 10

# Preview without sending
python cli.py market --symbol BTCUSDT --side BUY --quantity 0.01 --dry-run
```

Every run appends to `logs/trading_bot.log` (rotating, 5MB × 5 backups): the full request summary, the raw response, and any errors, with API key/secret automatically redacted from every line.

## Bonus feature: TWAP execution

`twap` splits a large order into `--slices` equal MARKET orders fired every `--interval` seconds - the standard technique institutional desks use to reduce the market-impact / slippage of sweeping a large quantity in one shot. Each slice is its own idempotent order with its own client order ID, so a partial failure mid-sequence leaves a clean, resumable trail in the logs rather than an opaque partial fill.

## Architecture

```
trading_bot/
  bot/
    client.py           # signed REST layer: HMAC signing, retries, logging, error mapping
    orders.py            # order semantics: market/limit/stop/TWAP, independent of HTTP/CLI
    validators.py        # pure input validation (Decimal-based, no side effects)
    risk.py               # pre-trade max-notional guardrail
    exceptions.py         # ValidationError / APIError / NetworkError / AuthenticationError / RiskLimitExceeded
    logging_config.py     # rotating file logging + secret redaction filter
  cli.py                 # argparse CLI: parses, validates, confirms, dispatches, prints result
  tests/                 # offline unit tests (mocked client — no network/credentials needed)
  scripts/
    demo_log_generation.py  # generates a labeled sample log without hitting the network
  logs/                  # generated log files land here
  .env.example
  requirements.txt
```

The layering means: `orders.py` can be reused by a future web UI or scheduler without touching argparse; `validators.py` and `orders.py` are fully unit-testable with a mocked client (see `tests/`), with zero network calls.

## Log file deliverable

`logs/trading_bot.log` contains genuine request/response pairs from real
orders placed against Binance Demo Trading, including:

- A **MARKET BUY** order for BTCUSDT - filled (`status: FILLED`)
- A **LIMIT SELL** order for BTCUSDT - accepted (`status: NEW`)

Both are also independently confirmed in Binance's own Order History UI
(`Filled` status, real `orderId`s, fill prices), matching what the bot's own
logs recorded.

`logs/demo_trading_bot.log.SIMULATED_EXAMPLE` is a separate, clearly-labeled
file showing the same log format generated offline via
`scripts/demo_log_generation.py` (HTTP layer mocked) — kept only as a
reference for the log shape, not submitted as evidence of a real order.

## Running tests

```bash
pip install -r requirements.txt
pytest -q
```
15 tests, all offline (validators + mocked order-service logic, no network or credentials required).

## Assumptions

- Binance Demo Trading's `/fapi/v1/order` endpoint and signing scheme match Binance's mainnet USDT-M Futures API byte-for-byte; only the host (`demo-fapi.binance.com` vs `fapi.binance.com`) and credential source differ.
- Quantity/price precision (`tickSize`/`stepSize` per symbol) is enforced by the exchange itself; the client validates "is this a positive number" client-side but does not fetch and enforce per-symbol exchange filters, to keep the take-home scope focused (see Known limitations).
- `MAX_ORDER_NOTIONAL_USDT` (optional) is a simple client-side guardrail, not a replacement for the account-level risk limits Binance itself enforces.
- The `--yes` flag is intended for scripted/CI use against Demo Trading only; there is no equivalent unattended mode implied for a hypothetical mainnet build.

## Known limitations / next steps

- No per-symbol `exchangeInfo` filter validation (`stepSize`, `tickSize`, `minNotional`) - orders that violate these fail with a clear `APIError` from Binance rather than being caught earlier client-side.
- No OCO order type (STOP + LIMIT bracket) - only single-leg STOP is implemented as the bonus.
- `RiskManager` is a simple notional cap; a production system would also track open-position exposure, not just per-order notional.

## Further reading

- [SECURITY_REVIEW.md](./SECURITY_REVIEW.md) — self-audit of secret handling, transport, input validation, and dependency surface.
- [CODE_REVIEW.md](./CODE_REVIEW.md) — architecture rationale, correctness details, and what's still missing before this would be "production," not just "industrial-grade take-home."
