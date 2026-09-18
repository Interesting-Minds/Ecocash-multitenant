from .api import C2BAPI, RefundAPI, TransactionStatusAPI
from .http import EcoCashHTTPClient
from .idempotency import IdempotencyStore, SQLiteIdempotencyStore
from .logging import get_logger
from .models import TenantConfig, TransactionStatusResponse
from .polling import PaymentPoller
from .resilience import CircuitBreakerConfig, RetryConfig


class EcoCashClient:
    def __init__(
        self,
        config: TenantConfig,
        idempotency_store: IdempotencyStore | None = None,
        retry_config: RetryConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
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

    def wait_for_completion(
        self,
        end_user_id: str,
        client_correlator: str,
        interval_seconds: float = 3.0,
        timeout_seconds: float = 120.0,
        max_interval_seconds: float = 15.0,
        backoff_factor: float = 1.5,
    ) -> TransactionStatusResponse:
        """Poll the status endpoint with exponential backoff until the
        transaction reaches a terminal status (SUCCESS, FAILED, etc.), or
        raise PollTimeoutError if it doesn't resolve in time.

        Each retry's delay is `interval_seconds * backoff_factor` up to
        `max_interval_seconds`, until `timeout_seconds` elapses in total.
        """
        poller = PaymentPoller(
            self.status,
            interval_seconds=interval_seconds,
            timeout_seconds=timeout_seconds,
            max_interval_seconds=max_interval_seconds,
            backoff_factor=backoff_factor,
        )
        return poller.poll_until_terminal(end_user_id, client_correlator)

    def close(self):
        self._http.close()
        self.logger.info("EcoCashClient closed: merchant=%s", self.config.merchant_code)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
