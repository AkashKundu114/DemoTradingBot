from decimal import Decimal

import pytest

from bot.exceptions import ValidationError
from bot.validators import validate_order_request, validate_positive_decimal, validate_side, validate_symbol


def test_validate_symbol_ok():
    assert validate_symbol("btcusdt") == "BTCUSDT"


def test_validate_symbol_rejects_garbage():
    with pytest.raises(ValidationError):
        validate_symbol("BTC-USDT!")


def test_validate_side_ok():
    assert validate_side("buy") == "BUY"


def test_validate_side_rejects_invalid():
    with pytest.raises(ValidationError):
        validate_side("HOLD")


def test_validate_positive_decimal_rejects_zero_and_negative():
    with pytest.raises(ValidationError):
        validate_positive_decimal("0", "quantity")
    with pytest.raises(ValidationError):
        validate_positive_decimal("-1", "quantity")


def test_validate_positive_decimal_rejects_non_numeric():
    with pytest.raises(ValidationError):
        validate_positive_decimal("abc", "quantity")


def test_market_order_request_ok():
    result = validate_order_request("btcusdt", "buy", "market", "0.01")
    assert result == {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": Decimal("0.01"),
        "price": None,
        "stop_price": None,
        "time_in_force": "GTC",
    }


def test_limit_order_requires_price():
    with pytest.raises(ValidationError):
        validate_order_request("BTCUSDT", "BUY", "LIMIT", "0.01")


def test_stop_order_requires_price_and_stop_price():
    with pytest.raises(ValidationError):
        validate_order_request("BTCUSDT", "SELL", "STOP", "0.01", price="60000")
