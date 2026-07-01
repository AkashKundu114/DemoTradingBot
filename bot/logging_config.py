from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler


class RedactSecretsFilter(logging.Filter):

    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        redacted = msg
        for secret in self._secrets:
            if secret and secret in redacted:
                redacted = redacted.replace(secret, "***REDACTED***")
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


class JSONFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _build_formatter(log_format: str) -> logging.Formatter:
    if log_format == "json":
        return JSONFormatter()
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logging(
    log_file: str = "logs/trading_bot.log",
    level: int = logging.INFO,
    secrets: list[str] | None = None,
    log_format: str = "text",
) -> logging.Logger:
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    fmt = _build_formatter(log_format)

    logger = logging.getLogger("trading_bot")
    logger.setLevel(level)
    logger.handlers.clear()

    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.WARNING)
    if secrets:
        redactor = RedactSecretsFilter(secrets)
        file_handler.addFilter(redactor)
        console_handler.addFilter(redactor)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
