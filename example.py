from ecocash import (
    EcoCashAPIError,
    EcoCashClient,
    EcoCashValidationError,
    PaymentRequest,
    RefundRequest,
    TenantConfig,
    TransactionStatusRequest,
)

config = TenantConfig(
    username="sbx_6cfb7c9c9582",
    password="c2J4XzZjZmI3YzljOTU4Mjo4Y1l2a1pGOHN0blNuZVdQdUxuIQ==",
    merchant_code="001535",
    merchant_pin="1234",
    merchant_number="788732685",
    terminal_id="UAT00003",
    merchant_name="UAT STORE 3",
    super_merchant_name="ECOCASH",
    location="Harare",
    country_code="ZW",
    environment="sandbox",
    currency="USD",
)

TEST_MSISDN = "0779587612"  # your whitelisted sandbox test number

with EcoCashClient(config) as client:

    # Charge (tranType=MER)
    try:
        payment = client.c2b.charge(
            PaymentRequest(
                end_user_id=TEST_MSISDN,
                amount=25.00,
                description="Invoice INV-001",
            )
        )
    except EcoCashValidationError as e:
        print(f"Validation: {e} (field={e.field})")
        raise SystemExit(1)
    except EcoCashAPIError as e:
        print(f"API error {e.status_code}: {e}")
        raise SystemExit(1)

    print(payment.status, payment.transaction_id)

    # Transaction status (GET lookup)
    status = client.status.lookup(
        TransactionStatusRequest(
            end_user_id=TEST_MSISDN,
            client_correlator=payment.client_correlator,
        )
    )
    print(status.status, status.amount)

    # Refund (tranType=REF) — use RefundRequest(tran_type="REV") for a
    # merchant-initiated reversal instead.
    if status.status == "SUCCESS":
        refund = client.refund.refund(
            RefundRequest(
                original_ecocash_reference=payment.transaction_id,
                end_user_id=TEST_MSISDN,
                amount=25.00,
                description="Customer request",
            )
        )
        print(refund.status)
