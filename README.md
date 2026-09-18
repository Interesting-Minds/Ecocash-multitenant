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
