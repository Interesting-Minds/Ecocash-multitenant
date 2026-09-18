import uuid
from dataclasses import dataclass, field


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
    currency: str | None = None
    client_name: str | None = None


@dataclass
class PaymentResponse:
    source_reference: str
    ecocash_transaction_reference: str | None
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
    currency: str | None = None
    client_name: str | None = None


@dataclass
class RefundResponse:
    refund_correlator: str
    ecocash_transaction_reference: str | None
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
    ecocash_transaction_reference: str | None
    status: str
    amount: float | None
    currency: str | None
    message: str
    raw: dict = field(default_factory=dict)
