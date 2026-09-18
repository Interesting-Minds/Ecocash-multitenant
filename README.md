# ecocash-python

A clean, multitenant Python library for the EcoCash Open API built for production use in multi-merchant platforms.

**Features at a glance:**
- Multitenant — per-tenant credentials, isolated circuit breakers
- Idempotency store — no double charges on network failures
- Retry with exponential backoff + full jitter
- Per-tenant circuit breaker
- Structured logging with PII masking
- Pluggable storage backends (SQLite / Redis / custom)

---

## How idempotency works

Every C2B payment gets a `source_reference` (UUID). Before hitting EcoCash, the library checks the store:

```
charge() called
     │
     ▼
Check idempotency store
     │
     ├─ SUCCESS record found → return cached response (no HTTP call)
     │
     ├─ PENDING record found → prior attempt stalled, reuse same
     │                         reference, proceed to EcoCash
     │
     └─ No record → create PENDING record, proceed
              │
              ▼
         Circuit breaker check
              │
              ├─ OPEN → raise CircuitBreakerOpenError immediately
              │
              └─ CLOSED/HALF-OPEN → attempt HTTP call
                       │
                       ├─ Success → mark SUCCESS in store, return
                       │
                       ├─ Transient error → retry with backoff
                       │                    (up to max_attempts)
                       │
                       └─ Terminal failure → mark FAILED in store, raise
```

This means a network blip between your server and EcoCash **cannot cause a double charge**. The same `source_reference` is always reused on retry, and EcoCash's own API deduplicates on that key.

---

## Installation

```bash
pip install requests
pip install -e .
```

Once published to PyPI:

```bash
pip install ecocash-python
```

For Redis backend:

```bash
pip install redis
```

---

## Quick start

```python
from ecocash import EcoCashClient, TenantConfig, PaymentRequest

config = TenantConfig(
    api_key="your-api-key",
    merchant_code="MERCHANT001",
    environment="sandbox",   # or "live"
    currency="USD",
)

with EcoCashClient(config) as client:
    payment = client.c2b.charge(PaymentRequest(
        customer_msisdn="0771234567",
        amount=25.00,
        reason="Invoice INV-001",
    ))
    print(payment.status)                          # SUCCESS
    print(payment.ecocash_transaction_reference)   # ECO-XXXXXXX
```

Calling `charge()` again with the same `source_reference` returns the cached response immediately no second HTTP request, no second charge.

---

## Multitenancy

Each tenant gets their own `TenantConfig`. In a multitenant app, look up the tenant's credentials at request time:

```python
def get_ecocash_client(tenant) -> EcoCashClient:
    config = TenantConfig(
        api_key=tenant.ecocash_api_key,
        merchant_code=tenant.ecocash_merchant_code,
        environment=tenant.ecocash_environment,
        currency=tenant.default_currency,
    )
    return EcoCashClient(config, idempotency_store=your_shared_store)
```

Circuit breakers are tracked per `merchant_code` in a global registry, so each tenant's failure state is isolated.

---

## Idempotency backends

### SQLite (default — zero config)

```python
from ecocash import EcoCashClient, TenantConfig, SQLiteIdempotencyStore

store = SQLiteIdempotencyStore(db_path="payments.db")
client = EcoCashClient(config, idempotency_store=store)
```

Good for single-server deployments. Thread-safe. Persists across restarts.

### Redis (distributed / multi-process)

```python
import redis
from ecocash import EcoCashClient, RedisIdempotencyStore

r = redis.Redis(host="localhost", port=6379, db=0)
store = RedisIdempotencyStore(r, ttl_seconds=86_400)
client = EcoCashClient(config, idempotency_store=store)
```

Good for multi-worker deployments (Gunicorn, Celery). TTL auto-expires old records.

### In-memory (testing only)

```python
from ecocash import EcoCashClient, InMemoryIdempotencyStore

client = EcoCashClient(config, idempotency_store=InMemoryIdempotencyStore())
```

### Custom backend

Implement `IdempotencyStore` to plug in PostgreSQL, DynamoDB, or anything else:

```python
from ecocash import IdempotencyStore, IdempotencyRecord
from typing import Optional

class PostgresIdempotencyStore(IdempotencyStore):
    def get(self, tenant_id: str, source_reference: str) -> Optional[IdempotencyRecord]:
        ...
    def save(self, record: IdempotencyRecord) -> None:
        ...
    def update(self, record: IdempotencyRecord) -> None:
        ...
```

---

## Retry configuration

```python
from ecocash import EcoCashClient, RetryConfig

client = EcoCashClient(
    config,
    retry_config=RetryConfig(
        max_attempts=3,       # total attempts (including first)
        base_delay=1.0,       # seconds before first retry
        max_delay=30.0,       # cap on delay
        backoff_factor=2.0,   # exponential multiplier
        jitter=True,          # full jitter — prevents thundering herd
    ),
)
```

Retried errors: network errors, timeouts, HTTP 408/429/500/502/503/504.  
Never retried: HTTP 400/401/403/422 (your fault, not transient).

---

## Circuit breaker

The circuit breaker prevents a flaky or down EcoCash API from cascading into your whole platform.

```python
from ecocash import EcoCashClient, CircuitBreakerConfig

client = EcoCashClient(
    config,
    circuit_breaker_config=CircuitBreakerConfig(
        failure_threshold=5,    # consecutive failures before opening
        recovery_timeout=60.0,  # seconds before probing again
        success_threshold=2,    # consecutive successes to close again
    ),
)
```

States:

| State | Behaviour |
|---|---|
| `CLOSED` | Normal all requests go through |
| `OPEN` | Fast-fail raises `CircuitBreakerOpenError` immediately |
| `HALF_OPEN` | Probe — one request allowed; success closes, failure re-opens |

Circuit breakers are per `merchant_code`. One tenant's failures do not affect others.

---

## Error handling

```python
from ecocash import (
    EcoCashValidationError,
    EcoCashAuthError,
    EcoCashAPIError,
    EcoCashTimeoutError,
    EcoCashNetworkError,
    CircuitBreakerOpenError,
)

try:
    payment = client.c2b.charge(request)

except EcoCashValidationError as e:
    # bad phone number, negative amount, unknown currency
    print(f"Input error: {e} (field={e.field})")

except CircuitBreakerOpenError as e:
    # EcoCash is down — don't even try
    print(f"EcoCash unavailable, retry after {e.retry_after:.0f}s")

except EcoCashAuthError:
    # wrong API key
    ...

except EcoCashAPIError as e:
    # EcoCash returned an error response
    print(f"API error {e.status_code}: {e}")
    print(e.response)   # raw dict

except EcoCashTimeoutError:
    # timed out after all retries
    ...

except EcoCashNetworkError:
    # network unreachable after all retries
    ...
```

**Exception hierarchy:**

```
EcoCashError
├── EcoCashAPIError
│   └── EcoCashAuthError
├── EcoCashValidationError
├── EcoCashTimeoutError
├── EcoCashNetworkError
└── CircuitBreakerOpenError
```

---

## Payment states

```python
from ecocash import PaymentState, InMemoryIdempotencyStore

store = InMemoryIdempotencyStore()
client = EcoCashClient(config, idempotency_store=store)

client.c2b.charge(request)

record = store.get(config.merchant_code, request.source_reference)
print(record.state)     # PaymentState.SUCCESS
print(record.attempts)  # 1
print(record.ecocash_reference)
```

| State | Meaning |
|---|---|
| `PENDING` | Created, not yet resolved |
| `SUCCESS` | EcoCash confirmed safe to fulfil |
| `FAILED` | Terminal error do not retry with same reference |
| `TIMED_OUT` | Timed out after all retries — check status endpoint |

---

## API reference

### C2B payment

```python
from ecocash import PaymentRequest

resp = client.c2b.charge(PaymentRequest(
    customer_msisdn="0771234567",
    amount=50.00,
    reason="Order #1042",
    source_reference="uuid",    # optional — auto-generated if omitted
    currency="USD",             # optional — falls back to TenantConfig default
    client_name="test Store",   # optional
))
```

### Transaction status

```python
from ecocash import TransactionStatusRequest

status = client.status.lookup(TransactionStatusRequest(
    source_mobile_number="0771234567",
    source_reference="your-uuid",
))
print(status.status, status.amount)
```

### Refund

```python
from ecocash import RefundRequest

refund = client.refund.refund(RefundRequest(
    original_transaction_reference="ECO-XXXXXXX",
    source_mobile_number="0771234567",
    amount=25.00,
    reason="Customer request",
))
```

---

## Logging

Structured logs with automatic PII masking. Phone numbers and API keys are masked in all output.

```
[2026-01-01 10:00:00] [INFO]  [ecocash.c2b.MERCHANT001] Initiating C2B: ref=abc-123 amount=25.0 USD phone=263771***
[2026-01-01 10:00:01] [INFO]  [ecocash.c2b.MERCHANT001] C2B success: ref=abc-123 status=SUCCESS ecocash_ref=ECO-001 attempts=1
[2026-01-01 10:00:05] [WARN]  [ecocash.resilience.retry] Attempt 1/3 failed: connection reset — retrying in 0.74s
[2026-01-01 10:00:06] [ERROR] [ecocash.resilience.circuit_breaker] Circuit OPEN for tenant 'MERCHANT001' after 5 failures
```

Integrate with your existing config:

```python
import logging

logging.getLogger("ecocash").setLevel(logging.INFO)
logging.getLogger("ecocash.http").setLevel(logging.DEBUG)  # raw HTTP payloads

# Django
LOGGING = {
    "loggers": {
        "ecocash": {"handlers": ["console"], "level": "INFO"}
    }
}
```

---

## Phone number formats

All common Zimbabwean formats are accepted and normalised to `263XXXXXXXXX`:

```python
"0771234567"      # → 263771234567
"263771234567"    # → 263771234567
"+263771234567"   # → 263771234567
```

Supported prefixes: `077`, `078`, `071`, `073`.

---

## Environments

| Environment | Endpoints used |
|---|---|
| `sandbox` | `/v2/payment/instant/c2b/sandbox` · `/v2/refund/instant/c2b/sandbox` · `/v1/transaction/c2b/status/sandbox` |
| `live` | `/v2/payment/instant/c2b/live` · `/v2/refund/instant/c2b/live` · `/v1/transaction/c2b/status/live` |

Get API credentials from [developers.ecocash.co.zw](https://developers.ecocash.co.zw) after merchant approval.

---

## Project structure

```
ecocash/
├── __init__.py             # Public API surface
├── client.py               # EcoCashClient — main entrypoint
├── http.py                 # HTTP session, auth headers, response handling
├── models.py               # TenantConfig + request/response dataclasses
├── exceptions.py           # Typed exception hierarchy
├── utils.py                # Phone normalization, validation
├── logging/
│   └── logger.py           # Structured logging with PII masking
├── idempotency/
│   ├── record.py           # IdempotencyRecord + PaymentState
│   └── store.py            # SQLite, Redis, InMemory backends
├── resilience/
│   ├── retry.py            # Exponential backoff with jitter
│   └── circuit_breaker.py  # Per-tenant circuit breaker
└── api/
    ├── c2b.py              # C2B payments (idempotency + retry + CB wired here)
    ├── refund.py           # Refunds
    └── status.py           # Transaction status lookup
```

---

## Requirements

- Python 3.10+
- `requests >= 2.31.0`
- `redis` (optional — only for `RedisIdempotencyStore`)

---

## License

MIT
