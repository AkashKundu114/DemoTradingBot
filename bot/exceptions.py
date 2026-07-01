class TradingBotError(Exception):
    """Base class for all trading-bot errors."""


class ValidationError(TradingBotError):
    """Raised when user input fails validation before it ever reaches the network."""


class AuthenticationError(TradingBotError):
    """Raised when API credentials are missing or rejected by Binance."""


class NetworkError(TradingBotError):
    """Raised for connection failures, timeouts, or DNS errors."""


class APIError(TradingBotError):
    """Raised when Binance returns a non-2xx response or an error payload."""

    def __init__(self, message: str, status_code: int | None = None, binance_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.binance_code = binance_code


class RiskLimitExceeded(ValidationError):
    """Raised when an order would breach a configured pre-trade risk limit."""
