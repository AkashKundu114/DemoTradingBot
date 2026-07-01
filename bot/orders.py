from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .client import BinanceFuturesClient
from .exceptions import ValidationError

logger = logging.getLogger("trading_bot.orders")


def _new_client_order_id(prefix: str = "bot") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class OrderResult:
    raw: dict

    @property
    def order_id(self):
        return self.raw.get("orderId")

    @property
    def status(self):
        return self.raw.get("status")

    @property
    def executed_qty(self):
        return self.raw.get("executedQty")

    @property
    def avg_price(self):
        return self.raw.get("avgPrice")

    def summary(self) -> str:
        return (
            f"orderId={self.order_id} status={self.status} "
            f"executedQty={self.executed_qty} avgPrice={self.avg_price}"
        )


class OrderService:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client

    def market_order(self, symbol: str, side: str, quantity: Decimal, client_order_id: Optional[str] = None) -> OrderResult:
        coid = client_order_id or _new_client_order_id("mkt")
        raw = self.client.place_order(
            symbol=symbol, side=side, type="MARKET", quantity=str(quantity), newClientOrderId=coid,
        )
        return OrderResult(raw)

    def limit_order(
        self, symbol: str, side: str, quantity: Decimal, price: Decimal,
        time_in_force: str = "GTC", client_order_id: Optional[str] = None,
    ) -> OrderResult:
        coid = client_order_id or _new_client_order_id("lmt")
        raw = self.client.place_order(
            symbol=symbol, side=side, type="LIMIT", quantity=str(quantity),
            price=str(price), timeInForce=time_in_force, newClientOrderId=coid,
        )
        return OrderResult(raw)

    def stop_limit_order(
        self, symbol: str, side: str, quantity: Decimal, price: Decimal, stop_price: Decimal,
        time_in_force: str = "GTC", client_order_id: Optional[str] = None,
    ) -> OrderResult:
        """Bonus order type: STOP (stop-limit). Triggers a LIMIT order once stop_price trades."""
        coid = client_order_id or _new_client_order_id("stp")
        raw = self.client.place_order(
            symbol=symbol, side=side, type="STOP", quantity=str(quantity),
            price=str(price), stopPrice=str(stop_price), timeInForce=time_in_force,
            newClientOrderId=coid,
        )
        return OrderResult(raw)

    def twap_order(
        self, symbol: str, side: str, total_quantity: Decimal, slices: int, interval_seconds: float,
        qty_precision: int = 3, sleep_fn=time.sleep,
    ) -> list[OrderResult]:
        if slices < 1:
            raise ValidationError("TWAP slices must be >= 1.")
        if interval_seconds < 0:
            raise ValidationError("TWAP interval_seconds must be >= 0.")

        quantum = Decimal(10) ** -qty_precision
        slice_qty = (total_quantity / slices).quantize(quantum)
        if slice_qty <= 0:
            raise ValidationError(
                f"total_quantity {total_quantity} split across {slices} slices rounds to zero "
                f"at precision {qty_precision}; use fewer slices or a larger quantity."
            )

        results: list[OrderResult] = []
        remaining = total_quantity
        logger.info(
            "TWAP start symbol=%s side=%s total_quantity=%s slices=%s interval_seconds=%s slice_qty=%s",
            symbol, side, total_quantity, slices, interval_seconds, slice_qty,
        )
        for i in range(slices):
            is_last = i == slices - 1
            this_qty = remaining if is_last else slice_qty  # last slice absorbs rounding remainder
            result = self.market_order(symbol, side, this_qty, client_order_id=_new_client_order_id(f"twap{i+1}"))
            results.append(result)
            remaining -= this_qty
            logger.info("TWAP slice %s/%s filled: %s", i + 1, slices, result.summary())
            if not is_last and interval_seconds > 0:
                sleep_fn(interval_seconds)
        return results
