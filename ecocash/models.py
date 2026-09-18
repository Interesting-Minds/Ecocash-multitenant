from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class TenantConfig:
    api_key: str
    merchant_code: str
    environment: str = "sandbox"
    currency: str = "USD"
    timeout: int = 30

    def __post_init__(self):
        if self.environment not in ("sandbox", "live"):
            raise ValueError("environment must be 'sandbox' or 'live'")


@dataclass
class PaymentRequest:
    customer_msisdn: str
    amount: float
    reason: str
    source_reference: str = field(default_factory=lambda: str(uuid.uuid4()))
    currency: Optional[str] = None
    client_name: Optional[str] = None


@dataclass
class PaymentResponse:
    source_reference: str
    ecocash_transaction_reference: Optional[str]
    status: str
    message: str
    raw: dict = field(default_factory=dict)


@dataclass
class RefundRequest:
    original_transaction_reference: str
    source_mobile_number: str
    amount: float
    reason: str
    refund_correlator: str = field(default_factory=lambda: str(uuid.uuid4()))
    currency: Optional[str] = None
    client_name: Optional[str] = None


@dataclass
class RefundResponse:
    refund_correlator: str
    ecocash_transaction_reference: Optional[str]
    status: str
    message: str
    raw: dict = field(default_factory=dict)


@dataclass
class TransactionStatusRequest:
    source_mobile_number: str
    source_reference: str


@dataclass
class TransactionStatusResponse:
    source_reference: str
    ecocash_transaction_reference: Optional[str]
    status: str
    amount: Optional[float]
    currency: Optional[str]
    message: str
    raw: dict = field(default_factory=dict)
