from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .exceptions import ValidationError

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP"}
VALID_TIME_IN_FORCE = {"GTC", "IOC", "FOK"}


def validate_symbol(raw: str) -> str:
    if not raw or not raw.strip():
        raise ValidationError("Symbol is required (e.g. BTCUSDT).")
    symbol = raw.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise ValidationError(
            f"Invalid symbol '{raw}'. Expected 5-20 uppercase letters/digits, e.g. BTCUSDT."
        )
    return symbol


def validate_side(raw: str) -> str:
    side = (raw or "").strip().upper()
    if side not in VALID_SIDES:
        raise ValidationError(f"Invalid side '{raw}'. Must be one of {sorted(VALID_SIDES)}.")
    return side


def validate_order_type(raw: str) -> str:
    order_type = (raw or "").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ValidationError(f"Invalid order type '{raw}'. Must be one of {sorted(VALID_ORDER_TYPES)}.")
    return order_type


def validate_time_in_force(raw: str) -> str:
    tif = (raw or "GTC").strip().upper()
    if tif not in VALID_TIME_IN_FORCE:
        raise ValidationError(f"Invalid timeInForce '{raw}'. Must be one of {sorted(VALID_TIME_IN_FORCE)}.")
    return tif


def validate_positive_decimal(raw, field_name: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f"Invalid {field_name} '{raw}': must be a number.")
    if value <= 0:
        raise ValidationError(f"Invalid {field_name} '{raw}': must be greater than zero.")
    return value


def validate_order_request(
    symbol: str,
    side: str,
    order_type: str,
    quantity,
    price=None,
    stop_price=None,
    time_in_force: str = "GTC",
) -> dict:
    clean_symbol = validate_symbol(symbol)
    clean_side = validate_side(side)
    clean_type = validate_order_type(order_type)
    clean_quantity = validate_positive_decimal(quantity, "quantity")

    clean_price = None
    clean_stop_price = None
    clean_tif = validate_time_in_force(time_in_force)

    if clean_type == "LIMIT":
        if price is None:
            raise ValidationError("price is required for LIMIT orders.")
        clean_price = validate_positive_decimal(price, "price")
    elif clean_type == "STOP":
        if price is None:
            raise ValidationError("price is required for STOP orders.")
        if stop_price is None:
            raise ValidationError("stop_price is required for STOP orders.")
        clean_price = validate_positive_decimal(price, "price")
        clean_stop_price = validate_positive_decimal(stop_price, "stop_price")

    return {
        "symbol": clean_symbol,
        "side": clean_side,
        "order_type": clean_type,
        "quantity": clean_quantity,
        "price": clean_price,
        "stop_price": clean_stop_price,
        "time_in_force": clean_tif,
    }
