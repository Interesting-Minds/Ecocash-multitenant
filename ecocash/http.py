import requests
from requests import Session, Response
from typing import Optional

from .models import TenantConfig
from .exceptions import (
    EcoCashAPIError,
    EcoCashAuthError,
    EcoCashNetworkError,
    EcoCashTimeoutError,
)
from .logging import get_logger, mask_dict

BASE_URLS = {
    "sandbox": "https://api.ecocash.co.zw",
    "live": "https://api.ecocash.co.zw",
}


class EcoCashHTTPClient:
    def __init__(self, config: TenantConfig):
        self.config = config
        self.base_url = BASE_URLS[config.environment]
        self.logger = get_logger(f"ecocash.http.{config.merchant_code}")
        self._session: Optional[Session] = None

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "X-API-KEY": self.config.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
        return self._session

    def post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        self.logger.debug("POST %s payload=%s", url, mask_dict(payload))
        try:
            response: Response = self.session.post(
                url, json=payload, timeout=self.config.timeout
            )
        except requests.Timeout:
            self.logger.error("Request timed out: %s", url)
            raise EcoCashTimeoutError(f"Request to {url} timed out")
        except requests.ConnectionError as e:
            self.logger.error("Network error: %s", str(e))
            raise EcoCashNetworkError(f"Network error: {e}")

        return self._handle_response(response)

    def _handle_response(self, response: Response) -> dict:
        self.logger.debug(
            "Response status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        if response.status_code == 401:
            raise EcoCashAuthError("Unauthorized — check your API key", status_code=401)
        if response.status_code == 403:
            raise EcoCashAuthError("Forbidden", status_code=403)

        try:
            data = response.json()
        except Exception:
            raise EcoCashAPIError(
                f"Non-JSON response: {response.text[:200]}",
                status_code=response.status_code,
            )

        if not response.ok:
            msg = data.get("message") or data.get("error") or "API error"
            raise EcoCashAPIError(msg, status_code=response.status_code, response=data)

        return data

    def close(self):
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
