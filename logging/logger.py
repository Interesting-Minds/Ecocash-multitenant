import logging
import re
from typing import Any

SENSITIVE_KEYS = {"api_key", "apikey", "x-api-key", "pin", "password", "token", "bearer"}
SENSITIVE_SUBSTRINGS = ("pin", "password", "token", "apikey", "api_key")
PHONE_PATTERN = re.compile(r"(263\d{2})\d+(\d{3})")


def _is_sensitive_key(key: str) -> bool:
    key = key.lower()
    return key in SENSITIVE_KEYS or any(s in key for s in SENSITIVE_SUBSTRINGS)


def mask_value(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if _is_sensitive_key(key):
        return value[:4] + "***" + value[-2:] if len(value) > 6 else "***"
    return value


def mask_phone(phone: str) -> str:
    return PHONE_PATTERN.sub(r"\1***\2", phone)


def mask_dict(data: dict) -> dict:
    masked = {}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = mask_dict(v)
        elif isinstance(k, str) and _is_sensitive_key(k):
            masked[k] = mask_value(k, v)
        elif isinstance(v, str) and PHONE_PATTERN.search(v):
            masked[k] = mask_phone(v)
        else:
            masked[k] = v
    return masked


def get_logger(name: str = "ecocash", level: int = logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
