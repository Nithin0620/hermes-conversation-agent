import time
import logging
import os

logger = logging.getLogger(__name__)


class TokenBucket:
    """Sliding-window token bucket for Groq TPM rate limiting.

    Tracks token consumption in a sliding 60-second window and
    blocks the caller when the window is full.
    """

    def __init__(self, limit: int | None = None, window_s: float = 60.0):
        self._limit = limit or int(os.getenv("TPM_LIMIT", "12000"))
        self._window_s = window_s
        self._tokens: list[tuple[float, int]] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_s
        self._tokens = [(ts, t) for ts, t in self._tokens if ts > cutoff]

    def _used(self, now: float) -> int:
        self._prune(now)
        return sum(t for _, t in self._tokens)

    def wait(self, estimated: int = 3000) -> None:
        """Block until *estimated* tokens can be consumed without exceeding the limit."""
        while True:
            now = time.monotonic()
            used = self._used(now)
            available = self._limit - used
            if available >= estimated:
                return
            need = estimated - available
            self._prune(now)
            cumulative = 0
            for ts, t in sorted(self._tokens):
                cumulative += t
                if cumulative >= need:
                    sleep_for = (ts + self._window_s) - now
                    if sleep_for > 0:
                        logger.info("[TokenBucket] Waiting %.1fs to stay under TPM limit", sleep_for)
                        time.sleep(sleep_for)
                    break
            else:
                time.sleep(1)

    def record(self, tokens: int) -> None:
        now = time.monotonic()
        self._tokens.append((now, tokens))
        self._prune(now)


_bucket: TokenBucket | None = None


def get_bucket() -> TokenBucket:
    global _bucket
    if _bucket is None:
        _bucket = TokenBucket()
    return _bucket
