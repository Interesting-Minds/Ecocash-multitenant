from unittest.mock import patch

import pytest

from ecocash import (
    EcoCashClient,
    InMemoryIdempotencyStore,
    PollTimeoutError,
    RetryConfig,
    TenantConfig,
)
from ecocash.polling import PaymentPoller
from ecocash.resilience.circuit_breaker import _registry

CONFIG = TenantConfig(
    username="test-user",
    password="test-pass",
    merchant_code="TEST01",
    merchant_pin="1234",
    merchant_number="788732685",
    terminal_id="UAT00003",
    merchant_name="TEST STORE",
    environment="sandbox",
)


def make_client():
    _registry.clear()
    return EcoCashClient(
        CONFIG,
        idempotency_store=InMemoryIdempotencyStore(),
        retry_config=RetryConfig(max_attempts=1, base_delay=0, jitter=False),
        enable_idempotency=True,
    )


def status_payload(status, correlator="ref-001"):
    return {
        "clientCorrelator": correlator,
        "transactionId": "MP230422.1145.T0123456",
        "status": status,
        "statusCode": "200",
        "amount": 10.00,
        "currency": "USD",
        "endUserId": "771234567",
        "merchantCode": "TEST01",
        "timestamp": "2024-04-22T11:45:30Z",
    }


# Test 1: already terminal on first poll — no sleeping, no retries


def test_poll_resolves_immediately_when_terminal():
    client = make_client()

    with (
        patch.object(client._http, "get", return_value=status_payload("SUCCESS")),
        patch("ecocash.polling.time.sleep") as mock_sleep,
    ):
        resp = client.wait_for_completion(
            end_user_id="0771234567", client_correlator="ref-001"
        )

    assert resp.status == "SUCCESS"
    mock_sleep.assert_not_called()


# Test 2: PENDING then SUCCESS — verifies exponential backoff delays


def test_poll_backs_off_exponentially_then_succeeds():
    client = make_client()

    responses = [
        status_payload("PENDING"),
        status_payload("PENDING"),
        status_payload("PENDING"),
        status_payload("SUCCESS"),
    ]

    with (
        patch.object(client._http, "get", side_effect=responses),
        patch("ecocash.polling.time.sleep") as mock_sleep,
    ):
        resp = client.wait_for_completion(
            end_user_id="0771234567",
            client_correlator="ref-001",
            interval_seconds=2.0,
            backoff_factor=2.0,
            max_interval_seconds=10.0,
        )

    assert resp.status == "SUCCESS"
    # 3 pending polls -> 3 sleeps, doubling each time and capped at 10.0
    assert mock_sleep.call_args_list == [
        ((2.0,),),
        ((4.0,),),
        ((8.0,),),
    ]


# Test 3: backoff delay is capped at max_interval_seconds


def test_poll_backoff_caps_at_max_interval():
    client = make_client()

    responses = [status_payload("PENDING")] * 4 + [status_payload("SUCCESS")]

    with (
        patch.object(client._http, "get", side_effect=responses),
        patch("ecocash.polling.time.sleep") as mock_sleep,
    ):
        client.wait_for_completion(
            end_user_id="0771234567",
            client_correlator="ref-001",
            interval_seconds=5.0,
            backoff_factor=3.0,
            max_interval_seconds=12.0,
        )

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    # 5.0 -> 15.0 (capped to 12.0) -> 36.0 (capped to 12.0) -> ...
    assert delays == [5.0, 12.0, 12.0, 12.0]


# Test 4: never resolves -> PollTimeoutError, no infinite loop


def test_poll_raises_on_timeout():
    client = make_client()

    with (
        patch.object(client._http, "get", return_value=status_payload("PENDING")),
        patch("ecocash.polling.time.sleep"),
        patch(
            "ecocash.polling.time.monotonic",
            side_effect=[0, 1, 2, 121],  # last call exceeds a 120s deadline
        ),
    ):
        with pytest.raises(PollTimeoutError):
            client.wait_for_completion(
                end_user_id="0771234567",
                client_correlator="ref-001",
                timeout_seconds=120.0,
            )


# Test 5: PaymentPoller can be used directly, independent of EcoCashClient


def test_payment_poller_used_directly():
    client = make_client()
    poller = PaymentPoller(client.status, interval_seconds=1.0)

    with (
        patch.object(client._http, "get", return_value=status_payload("FAILED")),
        patch("ecocash.polling.time.sleep") as mock_sleep,
    ):
        resp = poller.poll_until_terminal(
            end_user_id="0771234567", client_correlator="ref-001"
        )

    assert resp.status == "FAILED"
    mock_sleep.assert_not_called()
