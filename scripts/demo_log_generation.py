import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.client import BinanceFuturesClient
from bot.logging_config import setup_logging
from bot.orders import OrderService

FAKE_MARKET_RESPONSE = {
    "orderId": 5001234567,
    "symbol": "BTCUSDT",
    "status": "FILLED",
    "clientOrderId": "mkt-demo0001",
    "side": "BUY",
    "type": "MARKET",
    "executedQty": "0.010",
    "avgPrice": "64872.30",
    "origQty": "0.010",
}

FAKE_LIMIT_RESPONSE = {
    "orderId": 5001234568,
    "symbol": "BTCUSDT",
    "status": "NEW",
    "clientOrderId": "lmt-demo0002",
    "side": "SELL",
    "type": "LIMIT",
    "executedQty": "0.000",
    "avgPrice": "0.00",
    "origQty": "0.010",
    "price": "70000.00",
    "timeInForce": "GTC",
}


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def main():
    setup_logging(log_file="logs/demo_trading_bot.log", secrets=["demo_key", "demo_secret"])
    client = BinanceFuturesClient("demo_key", "demo_secret")
    service = OrderService(client)

    with patch.object(client.session, "request", return_value=FakeResponse(FAKE_MARKET_RESPONSE)):
        result = service.market_order("BTCUSDT", "BUY", Decimal("0.01"))
        print("MARKET demo result:", result.summary())

    with patch.object(client.session, "request", return_value=FakeResponse(FAKE_LIMIT_RESPONSE)):
        result = service.limit_order("BTCUSDT", "SELL", Decimal("0.01"), Decimal("70000"))
        print("LIMIT demo result:", result.summary())

    print("\nDemo log written to logs/demo_trading_bot.log")


if __name__ == "__main__":
    main()
