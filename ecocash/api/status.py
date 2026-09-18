from ..http import EcoCashHTTPClient
from ..logging import get_logger
from ..models import TenantConfig, TransactionStatusRequest, TransactionStatusResponse
from ..utils import normalize_phone

PATHS = {
    "sandbox": "/v1/transaction/c2b/status/sandbox",
    "live": "/v1/transaction/c2b/status/live",
}


class TransactionStatusAPI:
    def __init__(self, config: TenantConfig, http: EcoCashHTTPClient):
        self.config = config
        self.http = http
        self.logger = get_logger(f"ecocash.status.{config.merchant_code}")

    def lookup(self, request: TransactionStatusRequest) -> TransactionStatusResponse:
        phone = normalize_phone(request.source_mobile_number)

        payload = {
            "sourceMobileNumber": phone,
            "sourceReference": request.source_reference,
        }

        self.logger.info(
            "Transaction lookup: ref=%s",
            request.source_reference,
        )

        path = PATHS[self.config.environment]
        data = self.http.post(path, payload)

        resp = TransactionStatusResponse(
            source_reference=request.source_reference,
            ecocash_transaction_reference=data.get("ecocashTransactionReference"),
            status=data.get("status", "UNKNOWN"),
            amount=data.get("amount"),
            currency=data.get("currency"),
            message=data.get("message", ""),
            raw=data,
        )

        self.logger.info(
            "Lookup result: ref=%s status=%s",
            resp.source_reference,
            resp.status,
        )
        return resp
