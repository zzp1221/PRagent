"""One hard budget shared by every role in a single review.

Per-role budgets cannot bound a review: the lead runs several phases, workers
can be retried and revised, and the critic adds another call. This object reads
the execution ledger, which already records every model call, so the ceiling
covers all roles, retries and rework without duplicating accounting.
"""
import threading
import time
from typing import Any, Dict

from .runtime import RuntimeBudgetExceeded


class ReviewBudget:
    def __init__(
        self, ledger, token_budget: int = 0, time_budget_seconds: int = 0,
        max_model_calls: int = 0,
    ):
        self.ledger = ledger
        self.token_budget = max(0, int(token_budget or 0))
        self.time_budget_seconds = max(0, int(time_budget_seconds or 0))
        self.max_model_calls = max(0, int(max_model_calls or 0))
        self.started = time.monotonic()
        self._lock = threading.Lock()

    def _calls(self) -> list:
        return list(self.ledger.model_calls)

    def used_tokens(self) -> int:
        with self._lock:
            return sum(
                item.input_tokens + item.output_tokens for item in self._calls()
            )

    def model_calls(self) -> int:
        with self._lock:
            return len(self._calls())

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining_tokens(self) -> int:
        """Tokens still allowed, or 0 when no token ceiling is configured."""
        if not self.token_budget:
            return 0
        return max(0, self.token_budget - self.used_tokens())

    def exhausted(self) -> str:
        """Return a human-readable reason when the review must stop."""
        if self.max_model_calls and self.model_calls() >= self.max_model_calls:
            return "model calls %d/%d" % (self.model_calls(), self.max_model_calls)
        if self.token_budget and self.used_tokens() >= self.token_budget:
            return "tokens %d/%d" % (self.used_tokens(), self.token_budget)
        if self.time_budget_seconds and self.elapsed() >= self.time_budget_seconds:
            return "seconds %.1f/%d" % (self.elapsed(), self.time_budget_seconds)
        return ""

    def check(self, role: str = "") -> None:
        reason = self.exhausted()
        if not reason:
            return
        self.ledger.trace(
            role or "review", "review_budget_exhausted", reason=reason,
            **self.snapshot(),
        )
        raise RuntimeBudgetExceeded(
            "review budget exhausted%s: %s" % (
                " for %s" % role if role else "", reason,
            )
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "token_budget": self.token_budget,
            "time_budget_seconds": self.time_budget_seconds,
            "max_model_calls": self.max_model_calls,
            "tokens_used": self.used_tokens(),
            "model_calls": self.model_calls(),
            "elapsed_seconds": round(self.elapsed(), 3),
            "exhausted": self.exhausted(),
        }
