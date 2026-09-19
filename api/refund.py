from ..http import EcoCashHTTPClient
from ..logging import get_logger
from ..models import RefundRequest, RefundResponse, TenantConfig
from ..utils import normalize_end_user_id, validate_amount, validate_currency

# Per developers.ecocash.co.zw sandbox docs: API 3 — Refund / Reversal.
# tranType REF = customer refund, REV = merchant reversal.
PATHS = {
    "sandbox": "/payment/v1/transactions/refund/",
    "live": "/payment/v1/transactions/refund/",
}


class RefundAPI:
    def __init__(self, config: TenantConfig, http: EcoCashHTTPClient):
        self.config = config
        self.http = http
        self.logger = get_logger(f"ecocash.refund.{config.merchant_code}")

    def refund(self, request: RefundRequest) -> RefundResponse:
        currency = request.currency or self.config.currency
        end_user_id = normalize_end_user_id(request.end_user_id)
        validate_amount(request.amount)
        validate_currency(currency)

        payload = {
            "clientCorrelator": request.client_correlator,
            "notifyUrl": request.notify_url,
            "referenceCode": request.reference_code,
            "tranType": request.tran_type,
            "originalEcocashReference": request.original_ecocash_reference,
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
                    "channel": "POS",
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

        self.logger.info(
            "Initiating %s: correlator=%s original_ref=%s amount=%s",
            "refund" if request.tran_type == "REF" else "reversal",
            request.client_correlator,
            request.original_ecocash_reference,
            request.amount,
        )

        path = PATHS[self.config.environment]
        data = self.http.post(path, payload)

        resp = RefundResponse(
            client_correlator=data.get("clientCorrelator", request.client_correlator),
            transaction_id=data.get("transactionId"),
            status=data.get("status", "UNKNOWN"),
            status_code=data.get("statusCode"),
            status_message=data.get("statusMessage", ""),
            original_reference=data.get("originalReference", request.original_ecocash_reference),
            amount=data.get("amount"),
            currency=data.get("currency"),
            timestamp=data.get("timestamp"),
            raw=data,
        )

        self.logger.info(
            "Refund/reversal result: correlator=%s status=%s",
            resp.client_correlator,
            resp.status,
        )
        return resp
