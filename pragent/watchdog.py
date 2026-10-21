"""Background poller that turns new pull request commits into reviews.

Polling exists because a single-machine install has no public address, so
GitHub cannot deliver webhooks to it. A poller only needs outbound HTTPS, which
the same token already permits, and it cannot miss an event the way a webhook
can when the process is down.
"""
import threading
from typing import Any, Callable, Dict, Optional

from .github import GitHubClient


class WatchPoller(threading.Thread):
    def __init__(
        self,
        service,
        interval_seconds: int = 180,
        client_factory: Optional[Callable[[], GitHubClient]] = None,
        interval_getter: Optional[Callable[[], int]] = None,
        max_pull_requests: int = 30,
    ):
        super().__init__(name="pragent-watch-poller", daemon=True)
        self.service = service
        self._fallback_interval = max(1, int(interval_seconds))
        self._client_factory = client_factory
        self._interval_getter = interval_getter
        self._max_pull_requests = max(1, int(max_pull_requests))
        self._stop_event = threading.Event()
        self.last_summary: Dict[str, int] = {}
        self.last_error = ""
        self.ticks = 0

    # --- lifecycle ----------------------------------------------------------

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.last_summary = self.tick()
                self.last_error = ""
            except Exception as exc:  # never let the thread die on one bad round
                self.last_error = str(exc)
            self.ticks += 1
            self._stop_event.wait(self.interval_seconds())

    def interval_seconds(self) -> int:
        for getter in (self._interval_getter, getattr(self.service, "watch_interval_seconds", None)):
            if not callable(getter):
                continue
            try:
                return max(1, int(getter()))
            except Exception:
                continue
        return self._fallback_interval

    def client(self) -> GitHubClient:
        if self._client_factory is not None:
            return self._client_factory()
        return self.service.runtime_github_client()

    # --- one round ----------------------------------------------------------

    def tick(self) -> Dict[str, int]:
        summary = {"watches": 0, "submitted": 0, "duplicates": 0, "failed": 0}
        for row in self.service.store.list_all_watches():
            summary["watches"] += 1
            try:
                outcome = self._poll_watch(row)
            except Exception as exc:
                # One unreachable repository must not stop the others.
                summary["failed"] += 1
                self._record(
                    row, str(row.get("last_sha") or ""),
                    str(row.get("last_task_id") or ""), str(exc)[:500],
                )
                continue
            summary["submitted"] += outcome["submitted"]
            summary["duplicates"] += outcome["duplicates"]
        return summary

    def _poll_watch(self, row: Dict[str, Any]) -> Dict[str, int]:
        tenant_id = str(row.get("tenant_id") or "default")
        repository = str(row.get("repository") or "")
        outcome = {"submitted": 0, "duplicates": 0}
        if not repository or str(row.get("mode") or "poll") == "webhook":
            return outcome
        pulls = self.client().list_open_pull_requests(
            repository, self._max_pull_requests,
        )
        last_sha = str(row.get("last_sha") or "")
        last_task_id = str(row.get("last_task_id") or "")
        latest_sha = last_sha
        latest_task = last_task_id
        for pull in pulls:
            head = str(((pull.get("head") or {}).get("sha")) or "")
            number = pull.get("number")
            diff_url = pull.get("diff_url")
            if not head or head == last_sha:
                continue
            if not isinstance(number, int) or not diff_url:
                continue
            if self.service.store.find_review_commit(tenant_id, repository, head):
                outcome["duplicates"] += 1
                latest_sha = head
                continue
            result = self.service.submit_polled_review(
                tenant_id, repository, number, head, str(diff_url),
                str(pull.get("issue_url") or ""),
            )
            if result.get("duplicate"):
                outcome["duplicates"] += 1
            else:
                outcome["submitted"] += 1
                latest_task = str(result.get("task_id") or "")
            latest_sha = head
        if latest_sha != last_sha or latest_task != last_task_id:
            self._record(row, latest_sha, latest_task, "")
        return outcome

    def _record(
        self, row: Dict[str, Any], last_sha: str, last_task_id: str, error: str,
    ) -> None:
        self.service.store.update_watch_check(
            str(row.get("tenant_id") or "default"),
            str(row.get("repository") or ""),
            last_sha, last_task_id, error,
        )
