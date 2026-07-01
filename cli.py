from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal

from bot.client import BinanceFuturesClient
from bot.config import ConfigurationError, load_settings
from bot.exceptions import TradingBotError
from bot.exchange_info import ExchangeInfoCache
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
        description="Place and manage orders on Binance Futures Demo Trading (USDT-M).",
        parents=[common_flags],
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")

    sub = parser.add_subparsers(dest="command", required=False)

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

    status = sub.add_parser("status", help="[Ops] Look up an existing order.")
    status.add_argument("--symbol", required=True)
    status.add_argument("--order-id", type=int, required=True)

    cancel = sub.add_parser("cancel", help="[Ops] Cancel a single open order.")
    cancel.add_argument("--symbol", required=True)
    cancel.add_argument("--order-id", type=int, required=True)

    open_orders = sub.add_parser("open-orders", help="[Ops] List open orders (optionally filtered by symbol).")
    open_orders.add_argument("--symbol", required=False)

    cancel_all = sub.add_parser("cancel-all", help="[Ops] Cancel every open order for a symbol (flatten risk quickly).")
    cancel_all.add_argument("--symbol", required=True)
    cancel_all.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")

    sub.add_parser("balance", help="[Ops] Show futures wallet balance.")

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
    print("SUCCESS: order accepted by Binance Futures Demo Trading.")
    print("=======================\n")


def confirm_or_exit(prompt: str, dry_run: bool, skip: bool) -> None:
    if dry_run or skip:
        return
    answer = input(prompt).strip().lower()
    if answer != "y":
        print("Aborted by user.")
        sys.exit(0)


def apply_exchange_filters(
    exchange_cache: ExchangeInfoCache, validated: dict, enforce: bool
) -> dict:
    if not enforce:
        return validated
    filters = exchange_cache.get(validated["symbol"])
    if filters is None:
        return validated
    rounded_qty, rounded_price = filters.validate_and_round(
        validated["quantity"], validated.get("price") or validated.get("stop_price")
    )
    if rounded_qty != validated["quantity"]:
        print(f"  (quantity rounded to exchange stepSize: {validated['quantity']} -> {rounded_qty})")
    validated["quantity"] = rounded_qty
    if validated.get("price") is not None:
        _, rp = filters.validate_and_round(validated["quantity"], validated["price"])
        if rp != validated["price"]:
            print(f"  (price rounded to exchange tickSize: {validated['price']} -> {rp})")
        validated["price"] = rp
    return validated


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        from bot import __version__
        print(f"trading_bot {__version__}")
        return

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"\nCONFIGURATION ERROR: {exc}\n")
        sys.exit(1)

    logger = setup_logging(
        log_file=settings.log_file,
        level=getattr(logging, settings.log_level),
        secrets=[settings.api_key, settings.api_secret],
        log_format=settings.log_format,
    )

    client = BinanceFuturesClient(
        settings.api_key,
        settings.api_secret,
        base_url=settings.base_url,
        recv_window=settings.recv_window_ms,
        timeout=settings.request_timeout_s,
    )

    try:
        if args.command == "status":
            raw = client.get_order(args.symbol, order_id=args.order_id)
            print_result(OrderResult(raw))
            return
        if args.command == "cancel":
            raw = client.cancel_order(args.symbol, args.order_id)
            print_result(OrderResult(raw))
            return
        if args.command == "open-orders":
            raw = client.get_open_orders(symbol=args.symbol)
            print(f"\n{len(raw)} open order(s):")
            for o in raw:
                print(f"  orderId={o.get('orderId')} symbol={o.get('symbol')} side={o.get('side')} "
                      f"type={o.get('type')} status={o.get('status')} qty={o.get('origQty')}")
            print()
            return
        if args.command == "cancel-all":
            confirm_or_exit(
                f"Cancel ALL open orders for {args.symbol}? [y/N] ", dry_run=False, skip=args.yes
            )
            raw = client.cancel_all_open_orders(args.symbol)
            print(f"\nCancelled orders for {args.symbol}: {raw}\n")
            return
        if args.command == "balance":
            raw = client.account_balance()
            print("\n=== FUTURES WALLET BALANCE ===")
            for asset in raw:
                if Decimal(asset.get("balance", "0")) != 0:
                    print(f"  {asset.get('asset')}: {asset.get('balance')}")
            print()
            return

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

        exchange_cache = ExchangeInfoCache(client, ttl_seconds=settings.exchange_info_ttl_s)
        validated = apply_exchange_filters(exchange_cache, validated, settings.enforce_exchange_filters)

        extra = {}
        if args.command == "twap":
            extra = {"Slices": args.slices, "Interval (s)": args.interval}
        print_summary(args.command.upper(), validated, extra)

        if args.dry_run:
            print("(dry run — no request was sent)")
            return

        confirm_or_exit(
            "Proceed and send this order to Binance Futures Demo Trading? [y/N] ",
            dry_run=args.dry_run, skip=args.yes,
        )

        service = OrderService(client)
        risk = RiskManager(max_notional_usdt=settings.max_order_notional_usdt)

        reference_price = validated.get("price")
        if reference_price is None and settings.max_order_notional_usdt is not None:
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
        logger.error("Command failed: %s", exc)
        print(f"\nFAILED: {exc}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
