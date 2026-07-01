# Security Review (self-audit)

Reviewed as if this code were about to handle real funds, even though it
targets testnet only. Findings are organized by what an attacker or a
careless deployment could actually exploit, with the mitigation already in
the code for each one.

## 1. Secret handling

| Risk | Mitigation |
|---|---|
| API key/secret committed to git | `.env` is git-ignored; only `.env.example` (placeholder values) is committed. |
| Secrets printed to console or written to log files | `RedactSecretsFilter` in `bot/logging_config.py` scrubs both configured secrets from **every** log record, on both the file and console handlers, applied at `setup_logging()` before any request is made. Verified with a direct test that injects the secret into a log message and confirms it comes out redacted. |
| Secret sent in URL query string logged verbatim | `client.py` explicitly builds a `loggable_params` dict that excludes the `signature` field before logging the request; the API secret itself is never placed in query params at all (only used to compute the HMAC), so it cannot leak via request logging even without the filter. |
| Secret exposed via error messages/tracebacks | Exceptions raised (`APIError`, `NetworkError`, etc.) carry Binance's response text, which does not include the caller's own secret (Binance never echoes it back). Redaction filter is a second line of defense regardless. |

## 2. Transport & request integrity

- All requests go to `https://` only (`base_url` defaults to `https://demo.binance.com`, Binance's current Demo Trading API host); no HTTP fallback path exists in the client.
- Every signed request includes `timestamp` and `recvWindow`, which is Binance's built-in **replay-protection** mechanism - a captured/replayed request older than `recvWindow` (default 5000ms) is rejected server-side.
- HMAC-SHA256 signature is computed with `hmac.new` (constant-time-safe comparison is Binance's responsibility server-side; on our side we never compare secrets, only generate a signature), avoiding a hand-rolled/insecure hash.

## 3. Input handling / injection surface

- No `eval`, `exec`, `subprocess` with `shell=True`, or `pickle.load` anywhere in the codebase (checked via grep as part of this review).
- All numeric input goes through `Decimal(str(x))` inside `validate_positive_decimal`, which raises a clean `ValidationError` on malformed input rather than silently coercing or crashing with an unhandled exception.
- `symbol` is validated against a strict `^[A-Z0-9]{5,20}$` regex before ever being interpolated into a request - this closes the door on both malformed-symbol API errors and any theoretical parameter-injection via unexpected characters in a query string.
- The CLI never constructs a shell command from user input; all "execution" is a direct Python function call into `requests`.

## 4. Dependency surface

- `requirements.txt` pins exact versions (`requests==2.32.3`, `python-dotenv==1.0.1`, `urllib3==2.2.2`) rather than floating ranges, so a `pip install` today and in six months resolves to the same audited versions rather than silently picking up a new (possibly compromised or behavior-changing) release.
- Dependency count is deliberately minimal (3 runtime deps) to keep the supply-chain attack surface small - no unnecessary SDKs pulled in.

## 5. Error handling / fail-safe defaults

- Every network call is wrapped in `try/except requests.exceptions.RequestException`, mapped to a typed `NetworkError` rather than leaking a raw stack trace to the end user.
- 401/403 responses are mapped to a specific `AuthenticationError` with an actionable hint (check testnet vs mainnet keys) instead of a generic failure.
- The CLI's top-level `except TradingBotError` ensures any expected failure exits cleanly with a non-zero code and a human-readable message - it does not print a raw traceback that could reveal internal paths/environment details.
- Orders are never sent without an explicit user confirmation (`input("Proceed?")`) unless `--yes` is passed, and never at all in `--dry-run` mode - reducing the blast radius of a scripting mistake.

## 6. What this review deliberately does *not* claim

- This has not been tested against Binance's live production API surface (only documented behavior + testnet), so exact error-code handling for every possible Binance error is not exhaustively verified.
- Rate-limit handling (`429`) is covered by generic retry/backoff, not by parsing Binance's specific weight-based rate-limit headers — acceptable for a take-home/testnet tool, worth hardening before any real-money use.
- No automated dependency vulnerability scan (`pip-audit`/`safety`) was run as part of this exercise; recommended as a CI step for a production fork.
