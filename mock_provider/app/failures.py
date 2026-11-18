"""Per-supplier failure modes, held in memory (they reset when the mock restarts).

Operations consult this before serving a supplier's data. The control interface (a later task) sets and
clears the modes; nothing in the public contract depends on it.
"""
import time
from dataclasses import dataclass

from app.errors import ApiError

UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"
RATE_LIMITED = "rate_limited"
MODES = (UNAVAILABLE, TIMEOUT, RATE_LIMITED)

DEFAULT_RETRY_AFTER = 2

# Failure mode -> SupplierWarning.code
WARNING_CODES = {
    UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    TIMEOUT: "PROVIDER_TIMEOUT",
    RATE_LIMITED: "RATE_LIMITED",
}


@dataclass(frozen=True)
class SupplierFailure:
    mode: str
    retry_after: int = DEFAULT_RETRY_AFTER


_failures: dict[str, SupplierFailure] = {}


def set_failure(provider_id: str, mode: str, retry_after: int = DEFAULT_RETRY_AFTER) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown failure mode: {mode}")
    _failures[provider_id] = SupplierFailure(mode, retry_after)


def clear_failure(provider_id: str) -> None:
    _failures.pop(provider_id, None)


def clear_all() -> None:
    _failures.clear()
    _latency_ms.clear()


# Artificial latency per supplier, in milliseconds.
MAX_LATENCY_MS = 60_000
_latency_ms: dict[str, int] = {}


def set_latency(provider_id: str, milliseconds: int) -> None:
    if milliseconds <= 0:
        _latency_ms.pop(provider_id, None)
    else:
        _latency_ms[provider_id] = min(milliseconds, MAX_LATENCY_MS)


def latencies() -> dict[str, int]:
    return dict(_latency_ms)


def failures() -> dict[str, SupplierFailure]:
    return dict(_failures)


def apply_latency(provider_ids: list[str]) -> None:
    """Delay the request by the slowest queried supplier (suppliers are queried in parallel)."""
    delay = max((_latency_ms.get(provider, 0) for provider in provider_ids), default=0)
    if delay:
        time.sleep(delay / 1000)


def get_failure(provider_id: str) -> SupplierFailure | None:
    return _failures.get(provider_id)


def failure_error(failure: SupplierFailure) -> ApiError:
    """The contract error returned when a request depends on a failing supplier."""
    if failure.mode == RATE_LIMITED:
        return ApiError(
            429,
            "RATE_LIMITED",
            "The provider rate limit was reached.",
            headers={"Retry-After": str(failure.retry_after)},
        )
    return ApiError(503, "PROVIDER_UNAVAILABLE", "The requested provider operation is temporarily unavailable.")
