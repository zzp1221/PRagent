"""Execution leases so one worker owns a task at a time."""
import socket
import threading
import uuid
from typing import Optional


class TaskLease:
    """Hold the database lease on one task and keep renewing it while work runs.

    The lease is the cross-process mutex: a second worker that receives a
    duplicate delivery cannot take the task while the first one holds it. A
    heartbeat renews the deadline so a long review is not mistaken for a dead
    worker; if the process dies the heartbeat stops and the lease expires.
    """

    def __init__(self, store, task_id: str, lease_seconds: int = 60, owner: str = ""):
        self.store = store
        self.task_id = task_id
        self.lease_seconds = max(1, int(lease_seconds))
        self.owner = owner or "%s-%s" % (socket.gethostname(), uuid.uuid4().hex[:8])
        self.token: Optional[int] = None
        self.lost = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def held(self) -> bool:
        return self.token is not None

    def _interval(self) -> float:
        return max(0.05, self.lease_seconds / 3.0)

    def acquire(self) -> bool:
        if self.token is not None:
            return True
        self.token = self.store.acquire_task_lease(
            self.task_id, self.owner, self.lease_seconds
        )
        if self.token is None:
            return False
        self._thread = threading.Thread(
            target=self._heartbeat, name="pragent-lease", daemon=True,
        )
        self._thread.start()
        return True

    def _heartbeat(self) -> None:
        while not self._stop.wait(self._interval()):
            try:
                renewed = self.store.renew_task_lease(
                    self.task_id, self.owner, self.token, self.lease_seconds,
                )
            except Exception:
                # A transient database error is not proof of lost ownership.
                continue
            if not renewed:
                # Someone else holds the task now; stop pretending we do.
                self.lost = True
                return

    def release(self) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval()))
            self._thread = None
        if self.token is None:
            return False
        token, self.token = self.token, None
        try:
            return self.store.release_task_lease(self.task_id, self.owner, token)
        except Exception:
            return False

    def __enter__(self) -> "TaskLease":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()
