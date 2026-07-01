from __future__ import annotations

from decimal import Decimal

from .exceptions import RiskLimitExceeded


class RiskManager:
    def __init__(self, max_notional_usdt: Decimal | None = None):
        self.max_notional_usdt = max_notional_usdt

    def check_notional(self, quantity: Decimal, reference_price: Decimal, context: str = "") -> None:
        if self.max_notional_usdt is None:
            return
        notional = quantity * reference_price
        if notional > self.max_notional_usdt:
            raise RiskLimitExceeded(
                f"Order notional {notional:.2f} USDT{(' (' + context + ')') if context else ''} "
                f"exceeds configured MAX_ORDER_NOTIONAL_USDT={self.max_notional_usdt}."
            )
