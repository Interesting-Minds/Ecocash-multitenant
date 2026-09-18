from ..http import EcoCashHTTPClient
from ..models import TenantConfig, PaymentRequest, PaymentResponse
from ..utils import normalize_phone, validate_amount, validate_currency
from ..logging import get_logger
from ..idempotency import (
    IdempotencyStore,
    IdempotencyRecord,
    PaymentState,
)
from ..resilience import (
    RetryConfig,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    with_retry,
    get_circuit_breaker,
)
from ..exceptions import EcoCashError, EcoCashTimeoutError

PATHS = {
    "sandbox": "/v2/payment/instant/c2b/sandbox",
    "live": "/v2/payment/instant/c2b/live",
}


class C2BAPI:
    def __init__(
        self,
        config: TenantConfig,
        http: EcoCashHTTPClient,
        idempotency_store: IdempotencyStore = None,
        retry_config: RetryConfig = None,
        circuit_breaker_config: CircuitBreakerConfig = None,
    ):
        self.config = config
        self.http = http
        self.store = idempotency_store
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker = get_circuit_breaker(
            config.merchant_code, circuit_breaker_config
        )
        self.logger = get_logger(f"ecocash.c2b.{config.merchant_code}")

    def charge(self, request: PaymentRequest) -> PaymentResponse:
        currency = request.currency or self.config.currency
        phone = normalize_phone(request.customer_msisdn)
        validate_amount(request.amount)
        validate_currency(currency)

        # ── Idempotency check ────────────────────────────────────────────────
        record = None
        if self.store:
            record = self.store.get(self.config.merchant_code, request.source_reference)

            if record and record.state == PaymentState.SUCCESS:
                self.logger.info(
                    "Idempotency hit (SUCCESS): ref=%s ecocash_ref=%s — returning cached",
                    request.source_reference,
                    record.ecocash_reference,
                )
                return self._record_to_response(record)

            if record and record.state == PaymentState.PENDING:
                self.logger.warning(
                    "Idempotency hit (PENDING): ref=%s attempts=%d — "
                    "prior attempt in-flight or stalled, proceeding with status check",
                    request.source_reference,
                    record.attempts,
                )

            if record is None:
                record = IdempotencyRecord(
                    source_reference=request.source_reference,
                    tenant_id=self.config.merchant_code,
                    phone=phone,
                    amount=request.amount,
                    currency=currency,
                    reason=request.reason,
                )
                self.store.save(record)
                self.logger.debug("Idempotency record created: ref=%s", request.source_reference)

        # ── Build payload ────────────────────────────────────────────────────
        payload = {
            "customerMsisdn": phone,
            "amount": str(request.amount),
            "reason": request.reason,
            "currency": currency,
            "sourceReference": request.source_reference,
        }
        if request.client_name:
            payload["clientName"] = request.client_name

        path = PATHS[self.config.environment]

        # ── Circuit breaker + retry ──────────────────────────────────────────
        self.logger.info(
            "Initiating C2B: ref=%s amount=%s %s phone=%s",
            request.source_reference, request.amount, currency, phone[:6] + "***",
        )

        def _attempt():
            if record:
                record.increment_attempt()
                self.store.update(record)
            return self.http.post(path, payload)

        try:
            data = self.circuit_breaker.call(
                lambda: with_retry(
                    _attempt,
                    self.retry_config,
                    on_retry=lambda n, exc: self.logger.warning(
                        "Retry %d for ref=%s: %s", n, request.source_reference, exc
                    ),
                )
            )
        except CircuitBreakerOpenError as exc:
            self.logger.error("Circuit breaker OPEN: ref=%s — %s", request.source_reference, exc)
            if record:
                record.mark_failed(str(exc))
                self.store.update(record)
            raise
        except EcoCashTimeoutError as exc:
            self.logger.error(
                "Timed out after retries: ref=%s — marking TIMED_OUT", request.source_reference
            )
            if record:
                record.mark_timed_out()
                self.store.update(record)
            raise
        except EcoCashError as exc:
            self.logger.error("Payment failed: ref=%s — %s", request.source_reference, exc)
            if record:
                record.mark_failed(str(exc))
                self.store.update(record)
            raise

        # ── Persist success ──────────────────────────────────────────────────
        ecocash_ref = data.get("ecocashTransactionReference")
        if record:
            record.mark_success(ecocash_ref, data)
            self.store.update(record)

        resp = PaymentResponse(
            source_reference=request.source_reference,
            ecocash_transaction_reference=ecocash_ref,
            status=data.get("status", "UNKNOWN"),
            message=data.get("message", ""),
            raw=data,
        )

        self.logger.info(
            "C2B success: ref=%s status=%s ecocash_ref=%s attempts=%s",
            resp.source_reference,
            resp.status,
            resp.ecocash_transaction_reference,
            record.attempts if record else "n/a",
        )
        return resp

    @staticmethod
    def _record_to_response(record: IdempotencyRecord) -> PaymentResponse:
        raw = record.response_payload or {}
        return PaymentResponse(
            source_reference=record.source_reference,
            ecocash_transaction_reference=record.ecocash_reference,
            status=PaymentState.SUCCESS.value,
            message=raw.get("message", "Returned from idempotency store"),
            raw=raw,
        )
