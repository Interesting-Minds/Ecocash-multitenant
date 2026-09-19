from ..http import EcoCashHTTPClient
from ..logging import get_logger
from ..models import TenantConfig, TransactionStatusRequest, TransactionStatusResponse
from ..utils import normalize_end_user_id

# Per developers.ecocash.co.zw sandbox docs: API 2 — Transaction Lookup.
# GET /{endUserId}/transactions/amount/{clientCorrelator}
PATHS = {
    "sandbox": "/payment/v1/{end_user_id}/transactions/amount/{client_correlator}",
    "live": "/payment/v1/{end_user_id}/transactions/amount/{client_correlator}",
}


class TransactionStatusAPI:
    def __init__(self, config: TenantConfig, http: EcoCashHTTPClient):
        self.config = config
        self.http = http
        self.logger = get_logger(f"ecocash.status.{config.merchant_code}")

    def lookup(self, request: TransactionStatusRequest) -> TransactionStatusResponse:
        end_user_id = normalize_end_user_id(request.end_user_id)

        self.logger.info(
            "Transaction lookup: correlator=%s",
            request.client_correlator,
        )

        path = PATHS[self.config.environment].format(
            end_user_id=end_user_id,
            client_correlator=request.client_correlator,
        )
        data = self.http.get(path)

        resp = TransactionStatusResponse(
            client_correlator=data.get("clientCorrelator", request.client_correlator),
            transaction_id=data.get("transactionId"),
            status=data.get("status", "UNKNOWN"),
            status_code=data.get("statusCode"),
            end_user_id=data.get("endUserId"),
            amount=data.get("amount"),
            currency=data.get("currency"),
            merchant_code=data.get("merchantCode"),
            merchant_name=data.get("merchantName"),
            reference_code=data.get("referenceCode"),
            description=data.get("description"),
            timestamp=data.get("timestamp"),
            raw=data,
        )

        self.logger.info(
            "Lookup result: correlator=%s status=%s",
            resp.client_correlator,
            resp.status,
        )
        return resp
