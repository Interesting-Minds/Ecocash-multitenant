import base64

import requests
from requests import Response, Session

from .exceptions import (
    EcoCashAPIError,
    EcoCashAuthError,
    EcoCashNetworkError,
    EcoCashTimeoutError,
)
from .logging import get_logger, mask_dict
from .models import TenantConfig

# The API docs (developers.ecocash.co.zw) only publish the sandbox base URL
# and path prefix. The "live" values below follow the same convention EcoCash
# uses elsewhere (dropping the /sandbox/ segment) but are NOT confirmed
# against production docs — verify with EcoCash / production docs before
# going live.
BASE_URLS = {
    "sandbox": "https://developers.ecocash.co.zw/sandbox",
    "live": "https://developers.ecocash.co.zw/live",
}


class EcoCashHTTPClient:
    def __init__(self, config: TenantConfig):
        self.config = config
        self.base_url = BASE_URLS[config.environment]
        self.logger = get_logger(f"ecocash.http.{config.merchant_code}")
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = requests.Session()
            credentials = f"{self.config.username}:{self.config.password}".encode("utf-8")
            encoded = base64.b64encode(credentials).decode("ascii")
            self._session.headers.update(
                {
                    "Authorization": f"Basic {encoded}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
        return self._session

    def post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        self.logger.debug("POST %s payload=%s", url, mask_dict(payload))
        try:
            response: Response = self.session.post(url, json=payload, timeout=self.config.timeout)
        except requests.Timeout:
            self.logger.error("Request timed out: %s", url)
            raise EcoCashTimeoutError(f"Request to {url} timed out")
        except requests.ConnectionError as exc:
            self.logger.error("Network error: %s", str(exc))
            raise EcoCashNetworkError(f"Network error: {exc}") from exc

        return self._handle_response(response)

    def get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        self.logger.debug("GET %s", url)
        try:
            response: Response = self.session.get(url, timeout=self.config.timeout)
        except requests.Timeout:
            self.logger.error("Request timed out: %s", url)
            raise EcoCashTimeoutError(f"Request to {url} timed out")
        except requests.ConnectionError as exc:
            self.logger.error("Network error: %s", str(exc))
            raise EcoCashNetworkError(f"Network error: {exc}") from exc

        return self._handle_response(response)

    def _handle_response(self, response: Response) -> dict:
        self.logger.debug(
            "Response status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        if response.status_code == 401:
            raise EcoCashAuthError("Unauthorized — check your Basic Auth credentials", status_code=401)
        if response.status_code == 403:
            raise EcoCashAuthError("Forbidden", status_code=403)

        try:
            data = response.json()
        except ValueError as exc:
            raise EcoCashAPIError(
                f"Non-JSON response: {response.text[:200]}",
                status_code=response.status_code,
            ) from exc

        if not response.ok:
            msg = (
                data.get("statusMessage")
                or data.get("message")
                or data.get("error")
                or "API error"
            )
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
