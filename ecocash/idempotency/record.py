from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class PaymentState(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class IdempotencyRecord:
    source_reference: str
    tenant_id: str
    phone: str
    amount: float
    currency: str
    reason: str
    state: PaymentState = PaymentState.PENDING
    attempts: int = 0
    ecocash_reference: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response_payload: Optional[dict] = None

    def is_terminal(self) -> bool:
        return self.state in (PaymentState.SUCCESS, PaymentState.FAILED)

    def mark_success(self, ecocash_reference: str, payload: dict) -> None:
        self.state = PaymentState.SUCCESS
        self.ecocash_reference = ecocash_reference
        self.response_payload = payload
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str) -> None:
        self.state = PaymentState.FAILED
        self.error_message = error
        self.updated_at = datetime.now(timezone.utc)

    def mark_timed_out(self) -> None:
        self.state = PaymentState.TIMED_OUT
        self.updated_at = datetime.now(timezone.utc)

    def increment_attempt(self) -> None:
        self.attempts += 1
        self.updated_at = datetime.now(timezone.utc)
