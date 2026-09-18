from unittest.mock import patch

import pytest

from ecocash import (
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    EcoCashAPIError,
    EcoCashClient,
    EcoCashNetworkError,
    InMemoryIdempotencyStore,
    PaymentRequest,
    PaymentState,
    RetryConfig,
    TenantConfig,
)
from ecocash.resilience.circuit_breaker import _registry

FAKE_SUCCESS = {
    "status": "SUCCESS",
    "message": "Payment initiated",
    "ecocashTransactionReference": "ECO-TEST-001",
}

CONFIG = TenantConfig(
    api_key="test-key",
    merchant_code="TEST01",
    environment="sandbox",
)


def make_client(store=None, retry_config=None, cb_config=None):
    _registry.clear()
    return EcoCashClient(
        CONFIG,
        idempotency_store=store or InMemoryIdempotencyStore(),
        retry_config=retry_config or RetryConfig(max_attempts=3, base_delay=0, jitter=False),
        circuit_breaker_config=cb_config
        or CircuitBreakerConfig(failure_threshold=3, recovery_timeout=999),
        enable_idempotency=True,
    )


def make_request(ref="ref-001"):
    return PaymentRequest(
        customer_msisdn="0771234567",
        amount=10.00,
        reason="Test",
        source_reference=ref,
    )


# Test 1: successful payment persists to store


def test_successful_payment_persisted():
    store = InMemoryIdempotencyStore()
    client = make_client(store=store)

    with patch.object(client._http, "post", return_value=FAKE_SUCCESS):
        resp = client.c2b.charge(make_request())

    assert resp.status == "SUCCESS"
    assert resp.ecocash_transaction_reference == "ECO-TEST-001"

    record = store.get("TEST01", "ref-001")
    assert record.state == PaymentState.SUCCESS
    assert record.ecocash_reference == "ECO-TEST-001"
    assert record.attempts == 1


# Test 2: idempotency second call returns cached, no HTTP
def test_idempotency_returns_cached_on_second_call():
    store = InMemoryIdempotencyStore()
    client = make_client(store=store)

    with patch.object(client._http, "post", return_value=FAKE_SUCCESS) as mock_post:
        client.c2b.charge(make_request())
        resp2 = client.c2b.charge(make_request())

    mock_post.assert_called_once()
    assert resp2.status == "SUCCESS"
    assert resp2.ecocash_transaction_reference == "ECO-TEST-001"
    assert "idempotency" in resp2.message.lower() or resp2.message


# Test 3: retry on network error then succeeds


def test_retries_on_network_error_then_succeeds():
    store = InMemoryIdempotencyStore()
    client = make_client(store=store)

    call_count = 0

    def flaky_post(path, payload):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise EcoCashNetworkError("connection reset")
        return FAKE_SUCCESS

    with patch.object(client._http, "post", side_effect=flaky_post):
        resp = client.c2b.charge(make_request())

    assert resp.status == "SUCCESS"
    assert call_count == 3

    record = store.get("TEST01", "ref-001")
    assert record.state == PaymentState.SUCCESS
    assert record.attempts == 3


# Test 4: all retries exhausted, FAILED in store
def test_all_retries_exhausted_marks_failed():
    store = InMemoryIdempotencyStore()
    client = make_client(
        store=store,
        retry_config=RetryConfig(max_attempts=2, base_delay=0, jitter=False),
    )

    with (
        patch.object(client._http, "post", side_effect=EcoCashNetworkError("down")),
        pytest.raises(EcoCashNetworkError),
    ):
        client.c2b.charge(make_request())

    record = store.get("TEST01", "ref-001")
    assert record.state == PaymentState.FAILED
    assert record.attempts == 2


# Test 5: circuit breaker opens after threshold


def test_circuit_breaker_opens_after_failures():
    store = InMemoryIdempotencyStore()
    cb_config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=999)
    client = make_client(
        store=store,
        retry_config=RetryConfig(max_attempts=1, base_delay=0, jitter=False),
        cb_config=cb_config,
    )

    with patch.object(client._http, "post", side_effect=EcoCashNetworkError("down")):
        with pytest.raises(EcoCashNetworkError):
            client.c2b.charge(make_request("ref-001"))
        with pytest.raises(EcoCashNetworkError):
            client.c2b.charge(make_request("ref-002"))

        # Circuit should now be OPEN fast-fail without HTTP call
        with pytest.raises(CircuitBreakerOpenError):
            client.c2b.charge(make_request("ref-003"))


# Test 6: non-retryable 400 does not retry


def test_non_retryable_api_error_does_not_retry():
    store = InMemoryIdempotencyStore()
    client = make_client(store=store)

    call_count = 0

    def bad_request(path, payload):
        nonlocal call_count
        call_count += 1
        raise EcoCashAPIError("bad request", status_code=400)

    with (
        patch.object(client._http, "post", side_effect=bad_request),
        pytest.raises(EcoCashAPIError),
    ):
        client.c2b.charge(make_request())

    assert call_count == 1


# Test 7: PENDING record reuses same reference


def test_pending_record_reuses_reference():
    store = InMemoryIdempotencyStore()
    client = make_client(store=store)

    # Inject a PENDING record simulates a stalled prior attempt
    from ecocash.idempotency.record import IdempotencyRecord, PaymentState

    pending = IdempotencyRecord(
        source_reference="ref-stalled",
        tenant_id="TEST01",
        phone="263771234567",
        amount=10.00,
        currency="USD",
        reason="Test",
        state=PaymentState.PENDING,
        attempts=1,
    )
    store.save(pending)

    with patch.object(client._http, "post", return_value=FAKE_SUCCESS):
        resp = client.c2b.charge(make_request("ref-stalled"))

    assert resp.status == "SUCCESS"
    record = store.get("TEST01", "ref-stalled")
    assert record.state == PaymentState.SUCCESS
    assert record.attempts == 2
