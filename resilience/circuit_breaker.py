import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..exceptions import EcoCashError
from ..logging import get_logger

logger = get_logger("ecocash.resilience.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"  # normal operation
    OPEN = "OPEN"  # fast-failing not calling EcoCash
    HALF_OPEN = "HALF_OPEN"  # probe -> one request allowed through


class CircuitBreakerOpenError(EcoCashError):
    def __init__(self, tenant_id: str, retry_after: float):
        super().__init__(
            f"Circuit breaker OPEN for tenant '{tenant_id}'. " f"Retry after {retry_after:.1f}s."
        )
        self.tenant_id = tenant_id
        self.retry_after = retry_after


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # consecutive failures before opening
    recovery_timeout: float = 60.0  # seconds to wait before half-open probe
    success_threshold: int = 2  # consecutive successes to close again


class CircuitBreaker:
    def __init__(self, tenant_id: str, config: CircuitBreakerConfig = None):
        self.tenant_id = tenant_id
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._resolve_state()

    def _resolve_state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.config.recovery_timeout:
                logger.info(
                    "Circuit HALF-OPEN for tenant '%s' (elapsed=%.1fs)",
                    self.tenant_id,
                    elapsed,
                )
                self._state = CircuitState.HALF_OPEN
        return self._state

    def call(self, fn: Callable):
        with self._lock:
            state = self._resolve_state()
            if state == CircuitState.OPEN:
                retry_after = self.config.recovery_timeout - (time.monotonic() - self._opened_at)
                raise CircuitBreakerOpenError(self.tenant_id, max(retry_after, 0))

        try:
            result = fn()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            raise

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    logger.info("Circuit CLOSED for tenant '%s'", self.tenant_id)

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            self._success_count = 0
            if (
                self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
                and self._failure_count >= self.config.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.error(
                    "Circuit OPEN for tenant '%s' after %d failures. Last: %s",
                    self.tenant_id,
                    self._failure_count,
                    exc,
                )

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
        logger.info("Circuit manually RESET for tenant '%s'", self.tenant_id)


# Global registry one circuit breaker per tenant, shared across client instances
_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(tenant_id: str, config: CircuitBreakerConfig = None) -> CircuitBreaker:
    with _registry_lock:
        if tenant_id not in _registry:
            _registry[tenant_id] = CircuitBreaker(tenant_id, config)
        return _registry[tenant_id]
