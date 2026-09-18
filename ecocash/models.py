import uuid
from dataclasses import dataclass, field


@dataclass
class TenantConfig:
    """Per-tenant configuration.

    The EcoCash Instant Payment API authenticates with HTTP Basic Auth
    (username/password issued per sandbox/merchant account), not an API key.
    Several fields below (merchant_pin, merchant_number, terminal_id, ...)
    are sent on *every* charge/refund request per the API docs, so they live
    here rather than being repeated on each PaymentRequest.
    """

    username: str
    password: str
    merchant_code: str
    merchant_pin: str
    merchant_number: str
    terminal_id: str
    merchant_name: str
    super_merchant_name: str = "ECOCASH"
    location: str = "Harare"
    country_code: str = "ZW"
    environment: str = "sandbox"
    currency: str = "USD"
    timeout: int = 30

    def __post_init__(self):
        if self.environment not in ("sandbox", "live"):
            raise ValueError("environment must be 'sandbox' or 'live'")


@dataclass
class PaymentRequest:
    """A merchant-initiated charge (tranType=MER)."""

    end_user_id: str
    amount: float
    description: str
    client_correlator: str = field(default_factory=lambda: str(uuid.uuid4()))
    reference_code: str | None = None
    currency: str | None = None
    notify_url: str = ""
    remarks: str = "EcoCash Payment"
    channel: str = "POS"

    def __post_init__(self):
        if self.reference_code is None:
            self.reference_code = f"INV-{self.client_correlator[:8]}"


@dataclass
class PaymentResponse:
    client_correlator: str
    transaction_id: str | None
    status: str
    status_code: str | None
    status_message: str
    amount: float | None
    currency: str | None
    end_user_id: str | None
    merchant_code: str | None
    timestamp: str | None
    raw: dict = field(default_factory=dict)


@dataclass
class RefundRequest:
    """A refund (tranType=REF, customer-initiated) or reversal
    (tranType=REV, merchant-initiated) of a prior successful charge."""

    original_ecocash_reference: str
    end_user_id: str
    amount: float
    description: str
    client_correlator: str = field(default_factory=lambda: str(uuid.uuid4()))
    reference_code: str | None = None
    currency: str | None = None
    notify_url: str = ""
    remarks: str = "EcoCash Refund"
    tran_type: str = "REF"  # "REF" for refund, "REV" for reversal

    def __post_init__(self):
        if self.tran_type not in ("REF", "REV"):
            raise ValueError("tran_type must be 'REF' or 'REV'")
        if self.reference_code is None:
            self.reference_code = f"RFD-{self.client_correlator[:8]}"


@dataclass
class RefundResponse:
    client_correlator: str
    transaction_id: str | None
    status: str
    status_code: str | None
    status_message: str
    original_reference: str | None
    amount: float | None
    currency: str | None
    timestamp: str | None
    raw: dict = field(default_factory=dict)


@dataclass
class TransactionStatusRequest:
    end_user_id: str
    client_correlator: str


@dataclass
class TransactionStatusResponse:
    client_correlator: str
    transaction_id: str | None
    status: str
    status_code: str | None
    end_user_id: str | None
    amount: float | None
    currency: str | None
    merchant_code: str | None
    merchant_name: str | None
    reference_code: str | None
    description: str | None
    timestamp: str | None
    raw: dict = field(default_factory=dict)
