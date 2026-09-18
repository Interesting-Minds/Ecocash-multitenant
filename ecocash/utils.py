import re

from .exceptions import EcoCashValidationError

_NETWORK_PREFIXES = ("77", "78", "71", "73")
_LOCAL_RE = re.compile(r"^(77|78|71|73)\d{7}$")


def normalize_end_user_id(phone: str) -> str:
    """Normalize a Zimbabwe mobile number to the ``endUserId`` format used
    throughout the EcoCash Instant Payment API examples: local subscriber
    number with no leading 0, no country code, no '+' (e.g. "773047653").

    Note: the API's own sandbox playground form shows endUserId accepted
    with a '+263' prefix too, so the API may tolerate other formats — this
    normalizes to the one used in EcoCash's own request/response examples.
    """
    phone = re.sub(r"\s+|-", "", phone)
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("263"):
        phone = phone[3:]
    elif phone.startswith("0"):
        phone = phone[1:]
    if not _LOCAL_RE.match(phone):
        raise EcoCashValidationError(f"Invalid Zimbabwe mobile number: {phone}", field="end_user_id")
    return phone


# Backwards-compatible alias
normalize_phone = normalize_end_user_id


def validate_amount(amount: float) -> None:
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise EcoCashValidationError("Amount must be a positive number", field="amount")


def validate_currency(currency: str) -> None:
    allowed = {"USD", "ZWL", "ZiG"}
    if currency.upper() not in allowed:
        raise EcoCashValidationError(f"Currency must be one of {allowed}", field="currency")
