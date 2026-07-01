from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

from dotenv import load_dotenv

from bot.client import BinanceFuturesClient
from bot.exceptions import TradingBotError
from bot.logging_config import setup_logging
from bot.orders import OrderResult, OrderService
from bot.risk import RiskManager
from bot.validators import validate_order_request


def build_parser() -> argparse.ArgumentParser:
    common_flags = argparse.ArgumentParser(add_help=False)
    common_flags.add_argument("--dry-run", action="store_true", help="Validate and print the order without sending it.")
    common_flags.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")

    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="Place orders on Binance Futures Testnet (USDT-M).",
        parents=[common_flags],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser):
        p.add_argument("--symbol", required=True, help="Trading pair, e.g. BTCUSDT")
        p.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"])
        p.add_argument("--quantity", required=True, help="Order quantity, e.g. 0.01")

    market = sub.add_parser("market", help="Place a MARKET order.", parents=[common_flags])
    add_common(market)

    limit = sub.add_parser("limit", help="Place a LIMIT order.", parents=[common_flags])
    add_common(limit)
    limit.add_argument("--price", required=True, help="Limit price.")
    limit.add_argument("--time-in-force", default="GTC", choices=["GTC", "IOC", "FOK"])

    stop_limit = sub.add_parser("stop-limit", help="[Bonus] Place a STOP (stop-limit) order.", parents=[common_flags])
    add_common(stop_limit)
    stop_limit.add_argument("--price", required=True, help="Limit price once triggered.")
    stop_limit.add_argument("--stop-price", required=True, help="Trigger price.")
    stop_limit.add_argument("--time-in-force", default="GTC", choices=["GTC", "IOC", "FOK"])

    twap = sub.add_parser("twap", help="[Bonus] Split a large order into N MARKET slices over time (TWAP).", parents=[common_flags])
    add_common(twap)
    twap.add_argument("--slices", type=int, default=5, help="Number of equal slices (default 5).")
    twap.add_argument("--interval", type=float, default=10.0, help="Seconds between slices (default 10).")

    return parser


def print_summary(order_type: str, validated: dict, extra: dict | None = None) -> None:
    print("\n=== ORDER REQUEST SUMMARY ===")
    print(f"  Type:      {order_type}")
    print(f"  Symbol:    {validated['symbol']}")
    print(f"  Side:      {validated['side']}")
    print(f"  Quantity:  {validated['quantity']}")
    if validated.get("price") is not None:
        print(f"  Price:     {validated['price']}")
    if validated.get("stop_price") is not None:
        print(f"  Stop price:{validated['stop_price']}")
    if validated.get("time_in_force"):
        print(f"  TIF:       {validated['time_in_force']}")
    for k, v in (extra or {}).items():
        print(f"  {k}: {v}")
    print("==============================\n")


def print_result(result: OrderResult) -> None:
    print("\n=== ORDER RESPONSE ===")
    print(f"  orderId:      {result.order_id}")
    print(f"  status:       {result.status}")
    print(f"  executedQty:  {result.executed_qty}")
    print(f"  avgPrice:     {result.avg_price}")
    print("SUCCESS: order accepted by Binance Futures Testnet.")
    print("=======================\n")


def confirm_or_exit(args: argparse.Namespace) -> None:
    if args.dry_run or args.yes:
        return
    answer = input("Proceed and send this order to Binance Futures Testnet? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted by user.")
        sys.exit(0)


def main() -> None:
    load_dotenv()
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    base_url = os.getenv("BINANCE_BASE_URL", "https://demo-fapi.binance.com")
    max_notional_env = os.getenv("MAX_ORDER_NOTIONAL_USDT")
    max_notional = Decimal(max_notional_env) if max_notional_env else None

    logger = setup_logging(secrets=[api_key, api_secret])
    args = build_parser().parse_args()

    try:
        if args.command == "market":
            validated = validate_order_request(args.symbol, args.side, "MARKET", args.quantity)
        elif args.command == "limit":
            validated = validate_order_request(
                args.symbol, args.side, "LIMIT", args.quantity,
                price=args.price, time_in_force=args.time_in_force,
            )
        elif args.command == "stop-limit":
            validated = validate_order_request(
                args.symbol, args.side, "STOP", args.quantity,
                price=args.price, stop_price=args.stop_price, time_in_force=args.time_in_force,
            )
        elif args.command == "twap":
            validated = validate_order_request(args.symbol, args.side, "MARKET", args.quantity)
            if args.slices < 1:
                raise TradingBotError("--slices must be >= 1")
        else:
            raise TradingBotError(f"Unknown command: {args.command}")

        extra = {}
        if args.command == "twap":
            extra = {"Slices": args.slices, "Interval (s)": args.interval}
        print_summary(args.command.upper(), validated, extra)

        if not api_key or not api_secret:
            print(
                "ERROR: BINANCE_API_KEY / BINANCE_API_SECRET not set.\n"
                "Copy .env.example to .env and fill in your Futures Testnet keys."
            )
            sys.exit(1)

        if args.dry_run:
            print("(dry run — no request was sent)")
            return

        confirm_or_exit(args)

        client = BinanceFuturesClient(api_key, api_secret, base_url=base_url)
        service = OrderService(client)
        risk = RiskManager(max_notional_usdt=max_notional)

        reference_price = validated.get("price")
        if reference_price is None and max_notional is not None:
            try:
                mark = client.mark_price(validated["symbol"])
                reference_price = Decimal(mark["markPrice"])
            except TradingBotError as exc:
                logger.warning("Could not fetch mark price for risk check: %s", exc)
        if reference_price is not None:
            risk.check_notional(validated["quantity"], reference_price, context=args.command)

        if args.command == "market":
            result = service.market_order(validated["symbol"], validated["side"], validated["quantity"])
            print_result(result)
        elif args.command == "limit":
            result = service.limit_order(
                validated["symbol"], validated["side"], validated["quantity"],
                validated["price"], time_in_force=validated["time_in_force"],
            )
            print_result(result)
        elif args.command == "stop-limit":
            result = service.stop_limit_order(
                validated["symbol"], validated["side"], validated["quantity"],
                validated["price"], validated["stop_price"], time_in_force=validated["time_in_force"],
            )
            print_result(result)
        elif args.command == "twap":
            results = service.twap_order(
                validated["symbol"], validated["side"], validated["quantity"],
                slices=args.slices, interval_seconds=args.interval,
            )
            for i, r in enumerate(results, 1):
                print(f"\n--- TWAP slice {i}/{len(results)} ---")
                print_result(r)

    except TradingBotError as exc:
        logger.error("Order failed: %s", exc)
        print(f"\nFAILED: {exc}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
