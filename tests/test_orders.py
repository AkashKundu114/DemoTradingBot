from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bot.exceptions import ValidationError
from bot.orders import OrderService


def make_service():
    client = MagicMock()
    client.place_order.return_value = {
        "orderId": 12345,
        "status": "FILLED",
        "executedQty": "0.01",
        "avgPrice": "65000.00",
    }
    return OrderService(client), client


def test_market_order_sends_correct_params():
    service, client = make_service()
    result = service.market_order("BTCUSDT", "BUY", Decimal("0.01"))
    client.place_order.assert_called_once()
    _, kwargs = client.place_order.call_args
    assert kwargs["symbol"] == "BTCUSDT"
    assert kwargs["side"] == "BUY"
    assert kwargs["type"] == "MARKET"
    assert kwargs["quantity"] == "0.01"
    assert "newClientOrderId" in kwargs
    assert result.order_id == 12345
    assert result.status == "FILLED"


def test_limit_order_sends_price_and_tif():
    service, client = make_service()
    service.limit_order("BTCUSDT", "SELL", Decimal("0.02"), Decimal("70000"), time_in_force="IOC")
    _, kwargs = client.place_order.call_args
    assert kwargs["type"] == "LIMIT"
    assert kwargs["price"] == "70000"
    assert kwargs["timeInForce"] == "IOC"


def test_stop_limit_order_sends_stop_price():
    service, client = make_service()
    service.stop_limit_order("BTCUSDT", "SELL", Decimal("0.01"), Decimal("60000"), Decimal("60500"))
    _, kwargs = client.place_order.call_args
    assert kwargs["type"] == "STOP"
    assert kwargs["stopPrice"] == "60500"


def test_twap_order_splits_into_correct_number_of_slices():
    service, client = make_service()
    sleeps = []
    results = service.twap_order(
        "BTCUSDT", "BUY", Decimal("0.05"), slices=5, interval_seconds=1,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert len(results) == 5
    assert client.place_order.call_count == 5
    assert len(sleeps) == 4


def test_twap_order_last_slice_absorbs_rounding_remainder():
    service, client = make_service()
    service.twap_order("BTCUSDT", "BUY", Decimal("0.10"), slices=3, interval_seconds=0)
    quantities = [call.kwargs["quantity"] for call in client.place_order.call_args_list]
    total = sum(Decimal(q) for q in quantities)
    assert total == Decimal("0.10")


def test_twap_order_rejects_zero_slices():
    service, _ = make_service()
    with pytest.raises(ValidationError):
        service.twap_order("BTCUSDT", "BUY", Decimal("0.05"), slices=0, interval_seconds=1)
