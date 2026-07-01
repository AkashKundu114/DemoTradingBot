from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import APIError, AuthenticationError, NetworkError

logger = logging.getLogger("trading_bot.client")


class BinanceFuturesClient:

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://demo.binance.com",
        recv_window: int = 5000,
        timeout: float = 10.0,
    ):
        if not api_key or not api_secret:
            raise AuthenticationError("API key and secret are required.")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout = timeout

        self.session = requests.Session()
        retry_policy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "DELETE"]),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry_policy))
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def _sign(self, params: dict) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    def _signed_request(self, method: str, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.recv_window
        params["signature"] = self._sign(params)

        url = f"{self.base_url}{path}"
        loggable_params = {k: v for k, v in params.items() if k != "signature"}
        logger.info("REQUEST %s %s params=%s", method, path, loggable_params)

        try:
            response = self.session.request(method, url, params=params, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            logger.error("NETWORK ERROR calling %s %s: %s", method, path, exc)
            raise NetworkError(f"Network error calling {path}: {exc}") from exc

        logger.info("RESPONSE %s %s status=%s body=%s", method, path, response.status_code, response.text)

        if response.status_code == 401 or response.status_code == 403:
            raise AuthenticationError(
                f"Authentication failed ({response.status_code}). Check your API key/secret and "
                f"that they were generated for the Futures Testnet, not mainnet."
            )
        if response.status_code >= 400:
            raise APIError(
                f"Binance API error {response.status_code}: {response.text}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise APIError(f"Binance returned a non-JSON response: {response.text[:300]}") from exc

    def _public_request(self, method: str, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.info("REQUEST %s %s params=%s", method, path, params or {})
        try:
            response = self.session.request(method, url, params=params, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise NetworkError(f"Network error calling {path}: {exc}") from exc
        logger.info("RESPONSE %s %s status=%s", method, path, response.status_code)
        if response.status_code >= 400:
            raise APIError(f"Binance API error {response.status_code}: {response.text}", status_code=response.status_code)
        return response.json()

    def ping(self) -> dict:
        return self._public_request("GET", "/fapi/v1/ping")

    def mark_price(self, symbol: str) -> dict:
        return self._public_request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})

    def place_order(self, **params) -> dict:
        return self._signed_request("POST", "/fapi/v1/order", params)

    def get_order(self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        params = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return self._signed_request("GET", "/fapi/v1/order", params)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._signed_request("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def account_balance(self) -> dict:
        return self._signed_request("GET", "/fapi/v2/balance", {})
