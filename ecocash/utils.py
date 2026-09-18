import re

from .exceptions import EcoCashValidationError

_PHONE_RE = re.compile(r"^(263)(77|78|71|73)\d{7}$")


def normalize_phone(phone: str) -> str:
    phone = re.sub(r"\s+|-", "", phone)
    if phone.startswith("0"):
        phone = "263" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]
    if not _PHONE_RE.match(phone):
        raise EcoCashValidationError(f"Invalid Zimbabwe mobile number: {phone}", field="phone")
    return phone


def validate_amount(amount: float) -> None:
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise EcoCashValidationError("Amount must be a positive number", field="amount")


def validate_currency(currency: str) -> None:
    allowed = {"USD", "ZWL", "ZiG"}
    if currency.upper() not in allowed:
        raise EcoCashValidationError(f"Currency must be one of {allowed}", field="currency")
