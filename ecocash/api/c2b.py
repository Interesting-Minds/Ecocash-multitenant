from ..exceptions import EcoCashError, EcoCashTimeoutError
from ..http import EcoCashHTTPClient
from ..idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
    PaymentState,
)
from ..logging import get_logger
from ..models import PaymentRequest, PaymentResponse, TenantConfig
from ..resilience import (
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    RetryConfig,
    get_circuit_breaker,
    with_retry,
)
from ..utils import normalize_end_user_id, validate_amount, validate_currency

# Per developers.ecocash.co.zw sandbox docs: API 1 — Charge Request
PATHS = {
    "sandbox": "/payment/v1/transactions/amount/",
    "live": "/payment/v1/transactions/amount/",
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
        self.circuit_breaker = get_circuit_breaker(config.merchant_code, circuit_breaker_config)
        self.logger = get_logger(f"ecocash.c2b.{config.merchant_code}")

    def charge(self, request: PaymentRequest) -> PaymentResponse:
        currency = request.currency or self.config.currency
        end_user_id = normalize_end_user_id(request.end_user_id)
        validate_amount(request.amount)
        validate_currency(currency)

        # Idempotency check — keyed on clientCorrelator, same as EcoCash's
        # own dedup key.
        record = None
        if self.store:
            record = self.store.get(self.config.merchant_code, request.client_correlator)

            if record and record.state == PaymentState.SUCCESS:
                self.logger.info(
                    "Idempotency hit (SUCCESS): correlator=%s ecocash_ref=%s — returning cached",
                    request.client_correlator,
                    record.ecocash_reference,
                )
                return self._record_to_response(record)

            if record and record.state == PaymentState.PENDING:
                self.logger.warning(
                    "Idempotency hit (PENDING): correlator=%s attempts=%d — "
                    "prior attempt in-flight or stalled, proceeding with status check",
                    request.client_correlator,
                    record.attempts,
                )

            if record is None:
                record = IdempotencyRecord(
                    source_reference=request.client_correlator,
                    tenant_id=self.config.merchant_code,
                    phone=end_user_id,
                    amount=request.amount,
                    currency=currency,
                    reason=request.description,
                )
                self.store.save(record)
                self.logger.debug("Idempotency record created: correlator=%s", request.client_correlator)

        # Build payload per the real API's Charge Request schema
        payload = {
            "clientCorrelator": request.client_correlator,
            "notifyUrl": request.notify_url,
            "referenceCode": request.reference_code,
            "tranType": "MER",
            "endUserId": end_user_id,
            "remarks": request.remarks,
            "transactionOperationStatus": "Charged",
            "paymentAmount": {
                "charginginformation": {
                    "amount": request.amount,
                    "currency": currency,
                    "description": request.description,
                },
                "chargeMetaData": {
                    "channel": request.channel,
                },
            },
            "merchantCode": self.config.merchant_code,
            "merchantPin": self.config.merchant_pin,
            "merchantNumber": self.config.merchant_number,
            "countryCode": self.config.country_code,
            "terminalID": self.config.terminal_id,
            "location": self.config.location,
            "superMerchantName": self.config.super_merchant_name,
            "merchantName": self.config.merchant_name,
        }

        path = PATHS[self.config.environment]

        self.logger.info(
            "Initiating charge: correlator=%s amount=%s %s endUserId=%s",
            request.client_correlator,
            request.amount,
            currency,
            end_user_id[:4] + "***",
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
                        "Retry %d for correlator=%s: %s", n, request.client_correlator, exc
                    ),
                )
            )
        except CircuitBreakerOpenError as exc:
            self.logger.error("Circuit breaker OPEN: correlator=%s — %s", request.client_correlator, exc)
            if record:
                record.mark_failed(str(exc))
                self.store.update(record)
            raise
        except EcoCashTimeoutError:
            self.logger.error(
                "Timed out after retries: correlator=%s — marking TIMED_OUT",
                request.client_correlator,
            )
            if record:
                record.mark_timed_out()
                self.store.update(record)
            raise
        except EcoCashError as exc:
            self.logger.error("Charge failed: correlator=%s — %s", request.client_correlator, exc)
            if record:
                record.mark_failed(str(exc))
                self.store.update(record)
            raise

        # Persist success
        transaction_id = data.get("transactionId")
        if record:
            record.mark_success(transaction_id, data)
            self.store.update(record)

        resp = PaymentResponse(
            client_correlator=data.get("clientCorrelator", request.client_correlator),
            transaction_id=transaction_id,
            status=data.get("status", "UNKNOWN"),
            status_code=data.get("statusCode"),
            status_message=data.get("statusMessage", ""),
            amount=data.get("amount"),
            currency=data.get("currency"),
            end_user_id=data.get("endUserId"),
            merchant_code=data.get("merchantCode"),
            timestamp=data.get("timestamp"),
            raw=data,
        )

        self.logger.info(
            "Charge result: correlator=%s status=%s transaction_id=%s attempts=%s",
            resp.client_correlator,
            resp.status,
            resp.transaction_id,
            record.attempts if record else "n/a",
        )
        return resp

    @staticmethod
    def _record_to_response(record: IdempotencyRecord) -> PaymentResponse:
        raw = record.response_payload or {}
        return PaymentResponse(
            client_correlator=record.source_reference,
            transaction_id=record.ecocash_reference,
            status=PaymentState.SUCCESS.value,
            status_code=raw.get("statusCode"),
            status_message=raw.get("statusMessage", "Returned from idempotency store"),
            amount=raw.get("amount"),
            currency=raw.get("currency"),
            end_user_id=raw.get("endUserId"),
            merchant_code=raw.get("merchantCode"),
            timestamp=raw.get("timestamp"),
            raw=raw,
        )
