# Self-Review

## Architecture

- **Four clean layers**, each independently testable: `client.py` (HTTP/signing) → `orders.py` (order semantics) → `validators.py`/`risk.py` (pure functions, no I/O) → `cli.py` (argument parsing + orchestration only). No layer reaches "up" past the one that owns it - `orders.py` has no idea `argparse` exists.
- **`OrderService` takes a client in its constructor** (dependency injection), which is exactly why `tests/test_orders.py` can fully exercise TWAP slicing, param construction, and rounding-remainder logic with a `MagicMock` - zero network calls, zero test flakiness, sub-second test suite (15 tests in ~0.15s).
- **Typed exception hierarchy** (`ValidationError`, `APIError`, `NetworkError`, `AuthenticationError`, `RiskLimitExceeded`, all under `TradingBotError`) instead of bare `Exception`/`ValueError` - lets the CLI's single `except TradingBotError` block handle every expected failure mode uniformly while still preserving the specific type for anyone who wants to catch narrower.

## Correctness details that matter in a trading context

- **`Decimal` everywhere**, never `float`, for quantity/price/notional - avoids the classic `0.1 + 0.2 != 0.3` class of bug that causes either rejected orders or (worse) a silently wrong notional calculation.
- **TWAP rounding is handled correctly**: `total_quantity / slices` is quantized per-slice, but the *last* slice absorbs whatever remainder is left (`remaining -= this_qty` each loop) so the sum of all slices always equals the requested total exactly - covered by `test_twap_order_last_slice_absorbs_rounding_remainder`.
- **Idempotent client order IDs** on every single order (including every TWAP slice) mean the automatic retry policy in `client.py` (3 retries on 429/5xx) can never cause a duplicate fill.

## Observability

- Every request and response is logged at INFO with a redacted parameter dict - enough detail to debug a failed order after the fact without re-running it, and enough redaction that the log file is safe to attach to a bug report or, per the task requirements, submit as a deliverable.
- Rotating file handler (5MB × 5 backups) instead of an ever-growing single file - a real detail production code needs and take-homes usually skip.
- Console handler is capped at WARNING so a `--dry-run` loop doesn't spam the terminal, while the file handler keeps full INFO detail.

## Testability

- `tests/` runs fully offline: `test_validators.py` covers boundary/invalid input; `test_orders.py` mocks `BinanceFuturesClient` entirely and asserts on the exact kwargs passed to `place_order`, plus the TWAP slicing math. This is the same shape of test suite you'd want in CI before ever touching the real testnet.
- `sleep_fn` is injected into `twap_order()` specifically so the test suite doesn't have to actually sleep for 40 seconds to verify slicing behavior - a small detail that keeps the test suite fast forever as more slices/tests are added.

## Things to Do

- Fetch and cache `/fapi/v1/exchangeInfo` per symbol to validate `stepSize`/`tickSize`/`minNotional` client-side before sending (currently these are only caught when Binance itself rejects the order - noted explicitly in README's "Known limitations").
- Structured JSON logging (instead of plain text) if this were feeding a log aggregator like Loki/ELK - flagged as a natural next step given other recent work already uses Prometheus/Grafana/Loki stacks for observability.
- An async client (`httpx.AsyncClient`) if TWAP or multi-symbol order placement needed to run concurrently rather than sequentially — sequential is the right choice here since TWAP is explicitly *supposed* to be paced, not parallel.
- OpenTelemetry tracing around each order lifecycle if this became part of a larger service rather than a standalone CLI.
