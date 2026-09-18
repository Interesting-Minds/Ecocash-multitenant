"""Our own webhook layer, sitting on top of polling.

EcoCash's sandbox `notifyUrl` does not reliably call back (confirmed by the
sandbox's own "Poll until SUCCESS" test scenario existing at all — if the
webhook worked, that scenario wouldn't need to poll). So instead of trusting
EcoCash to notify *us*, we poll EcoCash's status endpoint ourselves and then
notify *our own* downstream consumers with a signed, EcoCash-shaped event.

Typical usage — fire-and-forget from a request handler:

    relay = WebhookRelay(status_api, secret="a-shared-secret")
    relay.notify_on_completion(
        end_user_id=payment.end_user_id,
        client_correlator=payment.client_correlator,
        notify_url="https://internal.example.com/hooks/ecocash",
        background=True,   # spawns a daemon thread and returns immediately
    )

Or, inside a Celery/RQ task (where blocking is fine and you get retries,
persistence, and visibility for free — the recommended production setup):

    @shared_task(bind=True, max_retries=5)
    def poll_and_notify(self, end_user_id, client_correlator, notify_url):
        relay = WebhookRelay(get_status_api(), secret=settings.ECOCASH_WEBHOOK_SECRET)
        relay.notify_on_completion(
            end_user_id, client_correlator, notify_url, background=False,
        )
"""

import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .api.status import TransactionStatusAPI
from .logging import get_logger
from .models import TransactionStatusRequest, TransactionStatusResponse

logger = get_logger("ecocash.webhooks")

# Statuses EcoCash returns while a transaction is still resolving.
# Anything else (SUCCESS, FAILED, CANCELLED, USERCANCELLED, ...) is treated
# as terminal. Adjust this set if EcoCash's sandbox surfaces other
# in-flight status strings.
PENDING_STATUSES = {"PENDING", "INITIATED", "PROCESSING", "SUBMITTED"}


class PollTimeoutError(Exception):
    """Raised when a transaction never reaches a terminal status in time."""


@dataclass
class PaymentPoller:
    """Polls the Transaction Lookup endpoint until a terminal status."""

    status_api: TransactionStatusAPI
    interval_seconds: float = 3.0
    timeout_seconds: float = 120.0
    max_interval_seconds: float = 15.0
    backoff_factor: float = 1.5

    def poll_until_terminal(
        self, end_user_id: str, client_correlator: str
    ) -> TransactionStatusResponse:
        deadline = time.monotonic() + self.timeout_seconds
        delay = self.interval_seconds
        attempt = 0

        while True:
            attempt += 1
            resp = self.status_api.lookup(
                TransactionStatusRequest(
                    end_user_id=end_user_id, client_correlator=client_correlator
                )
            )
            if resp.status.upper() not in PENDING_STATUSES:
                logger.info(
                    "Poll resolved: correlator=%s status=%s attempts=%d",
                    client_correlator,
                    resp.status,
                    attempt,
                )
                return resp

            if time.monotonic() >= deadline:
                raise PollTimeoutError(
                    f"correlator={client_correlator} still {resp.status} after "
                    f"{self.timeout_seconds}s ({attempt} polls)"
                )

            logger.debug(
                "Poll pending: correlator=%s status=%s attempt=%d — retrying in %.1fs",
                client_correlator,
                resp.status,
                attempt,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * self.backoff_factor, self.max_interval_seconds)


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 signature over the raw JSON body, hex-encoded."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Constant-time verification for use on the *receiving* end of a relayed webhook."""
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, signature)


@dataclass
class WebhookDeliveryResult:
    delivered: bool
    status_code: int | None = None
    attempts: int = 0
    error: str | None = None


def deliver_webhook(
    url: str,
    event_type: str,
    data: dict,
    secret: str | None = None,
    max_attempts: int = 5,
    timeout: float = 10.0,
) -> WebhookDeliveryResult:
    """POST a signed event to our own internal consumer, with retry."""
    event_id = str(uuid.uuid4())
    payload = {
        "id": event_id,
        "type": event_type,
        "created": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    body = json.dumps(payload, default=str).encode("utf-8")

    headers = {"Content-Type": "application/json", "X-Ecocash-Relay-Event": event_id}
    if secret:
        headers["X-Ecocash-Relay-Signature"] = sign_payload(secret, body)

    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=timeout)
            if resp.status_code < 300:
                logger.info(
                    "Webhook delivered: event=%s type=%s attempt=%d status=%d",
                    event_id,
                    event_type,
                    attempt,
                    resp.status_code,
                )
                return WebhookDeliveryResult(True, resp.status_code, attempt)
            logger.warning(
                "Webhook consumer returned %d (attempt %d/%d): event=%s",
                resp.status_code,
                attempt,
                max_attempts,
                event_id,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Webhook delivery error (attempt %d/%d): event=%s — %s",
                attempt,
                max_attempts,
                event_id,
                exc,
            )
            resp = None

        if attempt == max_attempts:
            return WebhookDeliveryResult(
                False,
                resp.status_code if resp is not None else None,
                attempt,
                error="max attempts exhausted",
            )
        time.sleep(delay)
        delay = min(delay * 2, 30.0)

    return WebhookDeliveryResult(False, None, max_attempts, error="unreachable")


@dataclass
class WebhookRelay:
    """Ties PaymentPoller + deliver_webhook together: poll EcoCash, then
    notify our own downstream consumer once the transaction resolves."""

    status_api: TransactionStatusAPI
    secret: str | None = None
    poll_interval_seconds: float = 3.0
    poll_timeout_seconds: float = 120.0
    delivery_max_attempts: int = 5

    def notify_on_completion(
        self,
        end_user_id: str,
        client_correlator: str,
        notify_url: str,
        background: bool = True,
    ) -> threading.Thread | WebhookDeliveryResult:
        """Poll until terminal, then deliver a webhook to notify_url.

        background=True (default): spawns a daemon thread and returns it
        immediately — fine for quick fire-and-forget use, but the process
        must stay alive and there's no retry across process restarts.

        background=False: blocks and returns the WebhookDeliveryResult —
        use this inside a Celery/RQ task, where the task queue gives you
        durability and retries for free. This is the recommended setup for
        anything that matters.
        """
        poller = PaymentPoller(
            self.status_api,
            interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.poll_timeout_seconds,
        )

        def _run() -> WebhookDeliveryResult:
            try:
                resp = poller.poll_until_terminal(end_user_id, client_correlator)
                event_type = (
                    "payment.succeeded" if resp.status.upper() == "SUCCESS" else "payment.failed"
                )
                data = {
                    "client_correlator": resp.client_correlator,
                    "transaction_id": resp.transaction_id,
                    "status": resp.status,
                    "status_code": resp.status_code,
                    "amount": resp.amount,
                    "currency": resp.currency,
                    "end_user_id": resp.end_user_id,
                    "merchant_code": resp.merchant_code,
                    "timestamp": resp.timestamp,
                }
            except PollTimeoutError as exc:
                logger.error("Poll timed out, relaying payment.timeout: %s", exc)
                event_type = "payment.timeout"
                data = {
                    "client_correlator": client_correlator,
                    "end_user_id": end_user_id,
                    "error": str(exc),
                }

            return deliver_webhook(
                notify_url,
                event_type,
                data,
                secret=self.secret,
                max_attempts=self.delivery_max_attempts,
            )

        if background:
            thread = threading.Thread(target=_run, daemon=True, name=f"ecocash-relay-{client_correlator}")
            thread.start()
            return thread

        return _run()
