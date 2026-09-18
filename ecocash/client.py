from typing import Optional

from .api import C2BAPI, RefundAPI, TransactionStatusAPI
from .http import EcoCashHTTPClient
from .idempotency import IdempotencyStore, SQLiteIdempotencyStore
from .logging import get_logger
from .models import TenantConfig
from .resilience import CircuitBreakerConfig, RetryConfig


class EcoCashClient:
    def __init__(
        self,
        config: TenantConfig,
        idempotency_store: Optional[IdempotencyStore] = None,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        enable_idempotency: bool = True,
    ):
        self.config = config
        self.logger = get_logger(f"ecocash.client.{config.merchant_code}")
        self._http = EcoCashHTTPClient(config)

        if enable_idempotency and idempotency_store is None:
            idempotency_store = SQLiteIdempotencyStore()

        store = idempotency_store if enable_idempotency else None

        self.c2b = C2BAPI(
            config,
            self._http,
            idempotency_store=store,
            retry_config=retry_config,
            circuit_breaker_config=circuit_breaker_config,
        )
        self.refund = RefundAPI(config, self._http)
        self.status = TransactionStatusAPI(config, self._http)

        self.logger.info(
            "EcoCashClient ready: merchant=%s env=%s idempotency=%s",
            config.merchant_code,
            config.environment,
            "enabled" if store else "disabled",
        )

    def close(self):
        self._http.close()
        self.logger.info("EcoCashClient closed: merchant=%s", self.config.merchant_code)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
