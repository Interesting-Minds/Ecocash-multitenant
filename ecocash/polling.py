"""Poll EcoCash's Transaction Lookup endpoint until a transaction resolves.

EcoCash's charge response is not the final word on a transaction — the end
user still has to confirm on their phone. The only reliable way to know
whether money actually moved is to poll the status endpoint until it
reaches a terminal status.

Usage:

    poller = PaymentPoller(client.status)
    result = poller.poll_until_terminal(
        end_user_id=payment.end_user_id,
        client_correlator=payment.client_correlator,
    )
    print(result.status)
"""

import time
from dataclasses import dataclass

from .api.status import TransactionStatusAPI
from .logging import get_logger
from .models import TransactionStatusRequest, TransactionStatusResponse

logger = get_logger("ecocash.polling")

# Statuses EcoCash returns while a transaction is still resolving.
# Anything else (SUCCESS, FAILED, CANCELLED, USERCANCELLED, ...) is treated
# as terminal. Adjust this set if EcoCash's sandbox surfaces other
# in-flight status strings.
PENDING_STATUSES = {"PENDING", "INITIATED", "PROCESSING", "SUBMITTED"}


class PollTimeoutError(Exception):
    """Raised when a transaction never reaches a terminal status in time."""


@dataclass
class PaymentPoller:
    """Polls the Transaction Lookup endpoint until a terminal status,
    backing off exponentially between attempts."""

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
