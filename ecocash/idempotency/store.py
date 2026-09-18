import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime

from .record import IdempotencyRecord, PaymentState

# Abstract base


class IdempotencyStore(ABC):
    @abstractmethod
    def get(self, tenant_id: str, source_reference: str) -> IdempotencyRecord | None: ...

    @abstractmethod
    def save(self, record: IdempotencyRecord) -> None: ...

    @abstractmethod
    def update(self, record: IdempotencyRecord) -> None: ...


# SQLite backend  (zero-dep, great for single-server)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ecocash_idempotency (
    source_reference    TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    phone               TEXT NOT NULL,
    amount              REAL NOT NULL,
    currency            TEXT NOT NULL,
    reason              TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'PENDING',
    attempts            INTEGER NOT NULL DEFAULT 0,
    ecocash_reference   TEXT,
    error_message       TEXT,
    response_payload    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_reference)
);
"""

_INSERT = """
INSERT INTO ecocash_idempotency
    (source_reference, tenant_id, phone, amount, currency, reason,
     state, attempts, ecocash_reference, error_message, response_payload,
     created_at, updated_at)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_UPDATE = """
UPDATE ecocash_idempotency
SET state=?, attempts=?, ecocash_reference=?, error_message=?,
    response_payload=?, updated_at=?
WHERE tenant_id=? AND source_reference=?;
"""

_SELECT = """
SELECT source_reference, tenant_id, phone, amount, currency, reason,
       state, attempts, ecocash_reference, error_message, response_payload,
       created_at, updated_at
FROM ecocash_idempotency
WHERE tenant_id=? AND source_reference=?;
"""


class SQLiteIdempotencyStore(IdempotencyStore):
    def __init__(self, db_path: str = "ecocash_idempotency.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def get(self, tenant_id: str, source_reference: str) -> IdempotencyRecord | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(_SELECT, (tenant_id, source_reference)).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def save(self, record: IdempotencyRecord) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                _INSERT,
                (
                    record.source_reference,
                    record.tenant_id,
                    record.phone,
                    record.amount,
                    record.currency,
                    record.reason,
                    record.state.value,
                    record.attempts,
                    record.ecocash_reference,
                    record.error_message,
                    json.dumps(record.response_payload) if record.response_payload else None,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def update(self, record: IdempotencyRecord) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                _UPDATE,
                (
                    record.state.value,
                    record.attempts,
                    record.ecocash_reference,
                    record.error_message,
                    json.dumps(record.response_payload) if record.response_payload else None,
                    record.updated_at.isoformat(),
                    record.tenant_id,
                    record.source_reference,
                ),
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
        payload_raw = row["response_payload"]
        return IdempotencyRecord(
            source_reference=row["source_reference"],
            tenant_id=row["tenant_id"],
            phone=row["phone"],
            amount=row["amount"],
            currency=row["currency"],
            reason=row["reason"],
            state=PaymentState(row["state"]),
            attempts=row["attempts"],
            ecocash_reference=row["ecocash_reference"],
            error_message=row["error_message"],
            response_payload=json.loads(payload_raw) if payload_raw else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


# Redis backend  (for distributed / multi-process deployments)


class RedisIdempotencyStore(IdempotencyStore):
    """
    Requires: pip install redis
    TTL defaults to 24 hours — enough to catch retries, short enough
    to not bloat Redis forever.
    """

    def __init__(self, redis_client, ttl_seconds: int = 86_400, key_prefix: str = "ecocash:idm"):
        self._r = redis_client
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _key(self, tenant_id: str, source_reference: str) -> str:
        return f"{self._prefix}:{tenant_id}:{source_reference}"

    def get(self, tenant_id: str, source_reference: str) -> IdempotencyRecord | None:
        raw = self._r.get(self._key(tenant_id, source_reference))
        if raw is None:
            return None
        data = json.loads(raw)
        payload_raw = data.get("response_payload")
        return IdempotencyRecord(
            source_reference=data["source_reference"],
            tenant_id=data["tenant_id"],
            phone=data["phone"],
            amount=data["amount"],
            currency=data["currency"],
            reason=data["reason"],
            state=PaymentState(data["state"]),
            attempts=data["attempts"],
            ecocash_reference=data.get("ecocash_reference"),
            error_message=data.get("error_message"),
            response_payload=payload_raw,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def save(self, record: IdempotencyRecord) -> None:
        self._r.setex(
            self._key(record.tenant_id, record.source_reference),
            self._ttl,
            self._serialize(record),
        )

    def update(self, record: IdempotencyRecord) -> None:
        key = self._key(record.tenant_id, record.source_reference)
        ttl = self._r.ttl(key)
        self._r.setex(key, ttl if ttl > 0 else self._ttl, self._serialize(record))

    @staticmethod
    def _serialize(record: IdempotencyRecord) -> str:
        return json.dumps(
            {
                "source_reference": record.source_reference,
                "tenant_id": record.tenant_id,
                "phone": record.phone,
                "amount": record.amount,
                "currency": record.currency,
                "reason": record.reason,
                "state": record.state.value,
                "attempts": record.attempts,
                "ecocash_reference": record.ecocash_reference,
                "error_message": record.error_message,
                "response_payload": record.response_payload,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }
        )


# In-memory backend  (testing / CI only not for production)


class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self):
        self._store: dict[tuple, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def get(self, tenant_id: str, source_reference: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._store.get((tenant_id, source_reference))

    def save(self, record: IdempotencyRecord) -> None:
        with self._lock:
            self._store[(record.tenant_id, record.source_reference)] = record

    def update(self, record: IdempotencyRecord) -> None:
        with self._lock:
            self._store[(record.tenant_id, record.source_reference)] = record
