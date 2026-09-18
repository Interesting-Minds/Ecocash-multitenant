from ecocash import (
    EcoCashClient,
    TenantConfig,
    PaymentRequest,
    RefundRequest,
    TransactionStatusRequest,
    EcoCashAPIError,
    EcoCashValidationError,
)

config = TenantConfig(
    api_key="your-api-key",
    merchant_code="MERCHANT001",
    environment="sandbox",
    currency="USD",
)

with EcoCashClient(config) as client:

    # C2B payment
    try:
        payment = client.c2b.charge(PaymentRequest(
            customer_msisdn="0771234567",
            amount=25.00,
            reason="Invoice INV-001",
        ))
        print(payment.status, payment.ecocash_transaction_reference)
    except EcoCashValidationError as e:
        print(f"Validation: {e} (field={e.field})")
    except EcoCashAPIError as e:
        print(f"API error {e.status_code}: {e}")

    # Transaction status
    status = client.status.lookup(TransactionStatusRequest(
        source_mobile_number="0771234567",
        source_reference=payment.source_reference,
    ))
    print(status.status, status.amount)

    # Refund
    if status.status == "SUCCESS":
        refund = client.refund.refund(RefundRequest(
            original_transaction_reference=payment.ecocash_transaction_reference,
            source_mobile_number="0771234567",
            amount=25.00,
            reason="Customer request",
        ))
        print(refund.status)
