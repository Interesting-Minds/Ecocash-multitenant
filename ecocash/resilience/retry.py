import random
import time
from dataclasses import dataclass
from typing import Callable, Tuple, Type

from ..exceptions import (
    EcoCashError,
    EcoCashAPIError,
    EcoCashAuthError,
    EcoCashTimeoutError,
    EcoCashNetworkError,
)
from ..logging import get_logger

logger = get_logger("ecocash.resilience.retry")

# Errors that are safe to retry (transient)
RETRYABLE = (EcoCashTimeoutError, EcoCashNetworkError)

# Errors that must never be retried
NON_RETRYABLE = (EcoCashAuthError,)


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    jitter: bool = True


def _is_retryable_api_error(exc: EcoCashAPIError) -> bool:
    retryable_codes = {408, 429, 500, 502, 503, 504}
    return exc.status_code in retryable_codes


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    delay = min(config.base_delay * (config.backoff_factor**attempt), config.max_delay)
    if config.jitter:
        delay = random.uniform(0, delay)
    return delay


def with_retry(
    fn: Callable,
    config: RetryConfig,
    on_retry: Callable[[int, Exception], None] = None,
) -> any:
    last_exc = None
    for attempt in range(config.max_attempts):
        try:
            return fn()
        except NON_RETRYABLE as exc:
            logger.warning("Non-retryable error on attempt %d: %s", attempt + 1, exc)
            raise
        except EcoCashAPIError as exc:
            if not _is_retryable_api_error(exc):
                logger.warning(
                    "Non-retryable API error %s on attempt %d: %s",
                    exc.status_code,
                    attempt + 1,
                    exc,
                )
                raise
            last_exc = exc
        except RETRYABLE as exc:
            last_exc = exc
        except EcoCashError as exc:
            raise

        delay = _compute_delay(attempt, config)
        logger.warning(
            "Attempt %d/%d failed: %s — retrying in %.2fs",
            attempt + 1,
            config.max_attempts,
            last_exc,
            delay,
        )
        if on_retry:
            on_retry(attempt + 1, last_exc)
        time.sleep(delay)

    logger.error("All %d attempts exhausted: %s", config.max_attempts, last_exc)
    raise last_exc
