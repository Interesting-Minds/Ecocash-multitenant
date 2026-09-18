from ..http import EcoCashHTTPClient
from ..models import TenantConfig, RefundRequest, RefundResponse
from ..utils import normalize_phone, validate_amount, validate_currency
from ..logging import get_logger

PATHS = {
    "sandbox": "/v2/refund/instant/c2b/sandbox",
    "live": "/v2/refund/instant/c2b/live",
}


class RefundAPI:
    def __init__(self, config: TenantConfig, http: EcoCashHTTPClient):
        self.config = config
        self.http = http
        self.logger = get_logger(f"ecocash.refund.{config.merchant_code}")

    def refund(self, request: RefundRequest) -> RefundResponse:
        currency = request.currency or self.config.currency
        phone = normalize_phone(request.source_mobile_number)
        validate_amount(request.amount)
        validate_currency(currency)

        payload = {
            "originalEcocashTransactionReference": request.original_transaction_reference,
            "sourceMobileNumber": phone,
            "amount": str(request.amount),
            "reasonForRefund": request.reason,
            "currency": currency,
            "refundCorrelator": request.refund_correlator,
        }
        if request.client_name:
            payload["clientName"] = request.client_name

        self.logger.info(
            "Initiating refund: correlator=%s original_ref=%s amount=%s",
            request.refund_correlator,
            request.original_transaction_reference,
            request.amount,
        )

        path = PATHS[self.config.environment]
        data = self.http.post(path, payload)

        resp = RefundResponse(
            refund_correlator=request.refund_correlator,
            ecocash_transaction_reference=data.get("ecocashTransactionReference"),
            status=data.get("status", "UNKNOWN"),
            message=data.get("message", ""),
            raw=data,
        )

        self.logger.info(
            "Refund result: correlator=%s status=%s",
            resp.refund_correlator,
            resp.status,
        )
        return resp
