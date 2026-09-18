from ecocash import (
    EcoCashAPIError,
    EcoCashClient,
    EcoCashValidationError,
    PaymentRequest,
    PollTimeoutError,
    RefundRequest,
    TenantConfig,
)

config = TenantConfig(
    username="sbx_6cfb7c9c9582",
    password="8cYvkZF8stnSneWPuLn!",
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

TEST_MSISDN = "0778587612"  # your whitelisted sandbox test number

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

    # The charge response above is not final — the end user still has to
    # confirm on their phone. Poll the status endpoint with exponential
    # backoff until the transaction reaches a terminal status.
    try:
        status = client.wait_for_completion(
            end_user_id=TEST_MSISDN,
            client_correlator=payment.client_correlator,
            interval_seconds=3.0,      # first retry after ~3s
            backoff_factor=1.5,        # then 4.5s, 6.75s, ...
            max_interval_seconds=15.0,  # capped at 15s between polls
            timeout_seconds=120.0,     # give up after 2 minutes
        )
    except PollTimeoutError as e:
        print(f"Still pending after polling: {e}")
        raise SystemExit(1)

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
