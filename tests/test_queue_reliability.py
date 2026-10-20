import os
import tempfile
import time
import unittest

from pragent.config import Settings
from pragent.harness import ReviewHarness
from pragent.models import ReviewReport, TaskState, TraceEvent
from pragent.reviewer import LocalRuleReviewer
from pragent.service import ReviewService
from pragent.store import TaskStore
from pragent.task_lease import LeaseLost, TaskLease
from pragent.task_queue import TaskQueue
from agentic_fake import enable_agentic_service


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
ISSUE_URL = "https://api.github.com/repos/org/repo/issues/7"


def _remove_database(path: str) -> None:
    """Delete a temporary database, retrying transient Windows handle contention.

    A lease heartbeat thread may still be finishing its last write when the test
    ends; on Windows that briefly blocks the unlink.
    """
    for _ in range(5):
        try:
            os.unlink(path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.unlink(path)


class TaskLeaseStoreTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.store = TaskStore(self.path)

    def tearDown(self):
        _remove_database(self.path)

    def _task(self, task_id="task-1"):
        self.store.create(task_id, "org/repo", 1, {"source": "test"})
        return task_id

    def test_second_worker_cannot_take_a_held_lease(self):
        task_id = self._task()
        self.assertEqual(1, self.store.acquire_task_lease(task_id, "worker-a", 60))
        self.assertIsNone(self.store.acquire_task_lease(task_id, "worker-b", 60))
        self.assertIsNotNone(self.store.acquire_task_lease(task_id, "worker-a", 60))

    def test_expired_lease_can_be_taken_with_a_new_fence(self):
        task_id = self._task()
        self.assertEqual(1, self.store.acquire_task_lease(task_id, "worker-a", 1))
        time.sleep(1.2)
        self.assertEqual(2, self.store.acquire_task_lease(task_id, "worker-b", 60))
        self.assertFalse(self.store.renew_task_lease(task_id, "worker-a", 1, 60))
        self.assertFalse(self.store.release_task_lease(task_id, "worker-a", 1))

    def test_finished_task_rejects_new_leases(self):
        task_id = self._task()
        self.store.fail(task_id, "boom", TraceEvent(1, TaskState.FAILED, "boom", "2026-01-01T00:00:00+00:00"))
        self.assertIsNone(self.store.acquire_task_lease(task_id, "worker-a", 60))

    def test_heartbeat_keeps_the_lease_through_a_long_task(self):
        task_id = self._task()
        lease = TaskLease(self.store, task_id, lease_seconds=1)
        self.assertTrue(lease.acquire())
        time.sleep(2.2)
        self.assertFalse(lease.lost)
        self.assertIsNone(self.store.acquire_task_lease(task_id, "worker-b", 60))
        self.assertTrue(lease.release())
        self.assertIsNotNone(self.store.acquire_task_lease(task_id, "worker-b", 60))


class QueuedDeliveryTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

    def tearDown(self):
        _remove_database(self.path)

    def _service(self):
        settings = Settings(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
        )
        return enable_agentic_service(ReviewService(settings))

    def _payload(self, service, pull_request=7):
        task_id = service._create_task("org/repo", DIFF, pull_request, "github-webhook")
        return {
            "task_id": task_id, "repository": "org/repo",
            "pull_request": pull_request, "github_issue_url": ISSUE_URL,
            "tenant_id": "default",
        }

    def test_duplicate_delivery_does_not_rerun_a_finished_task(self):
        service = self._service()
        payload = self._payload(service)
        service._process_queued(payload)
        task_id = payload["task_id"]
        first = service.store.get(task_id)
        self.assertEqual("SUCCESS", first["state"])
        steps = len(first["trace"])

        service._process_queued(payload)

        second = service.store.get(task_id)
        self.assertEqual("SUCCESS", second["state"])
        self.assertEqual(steps, len(second["trace"]))
        service.queue.close()

    def test_delivery_is_dropped_while_another_worker_holds_the_task(self):
        service = self._service()
        payload = self._payload(service)
        task_id = payload["task_id"]
        holder = TaskLease(service.store, task_id, 60, owner="other-worker")
        self.assertTrue(holder.acquire())

        service._process_queued(payload)

        self.assertEqual("PENDING", service.store.get(task_id)["state"])
        holder.release()
        service._process_queued(payload)
        self.assertEqual("SUCCESS", service.store.get(task_id)["state"])
        service.queue.close()


class FakeRedisClient:
    """Records the PEL claims a queue worker makes while a task runs."""

    def __init__(self, reclaim=()):
        self.claims = []
        self.acked = []
        self.added = []
        self.reclaim = list(reclaim)

    def xclaim(self, stream, group, consumer, min_idle_time, ids, idle=None):
        self.claims.append({"ids": list(ids), "idle": idle, "consumer": consumer})
        return []

    def xautoclaim(self, stream, group, consumer, min_idle_time, start_id, count):
        return ("0-0", list(self.reclaim), [])

    def xack(self, stream, group, redis_id):
        self.acked.append(redis_id)
        return 1

    def xadd(self, stream, fields):
        self.added.append(fields)
        return "1-0"

    def xrevrange(self, stream, count):
        return []


class PelHeartbeatTests(unittest.TestCase):
    def _queue(self, handler):
        return TaskQueue(handler, workers=1, lease_seconds=1)

    def test_long_delivery_keeps_resetting_the_pending_idle_time(self):
        queue = self._queue(lambda payload: time.sleep(1.0))
        queue._redis = FakeRedisClient()
        try:
            self.assertTrue(queue._deliver({"payload": {}, "attempt": 0}, "1-0"))
        finally:
            queue.close()
        self.assertGreaterEqual(len(queue._redis.claims), 2)
        self.assertTrue(all(item["idle"] == 0 for item in queue._redis.claims))
        self.assertEqual({"1-0"}, {item["ids"][0] for item in queue._redis.claims})

    def test_delivery_without_a_pending_id_does_not_claim(self):
        queue = self._queue(lambda payload: None)
        queue._redis = FakeRedisClient()
        try:
            self.assertTrue(queue._deliver({"payload": {}, "attempt": 0}))
        finally:
            queue.close()
        self.assertEqual([], queue._redis.claims)

    def test_unparseable_reclaimed_entry_is_parked_instead_of_looping(self):
        queue = self._queue(lambda payload: None)
        queue._redis = FakeRedisClient(reclaim=[("9-0", {"envelope": "{not json"})])
        try:
            queue._reclaim_stale()
        finally:
            queue.close()
        self.assertEqual(["9-0"], queue._redis.acked)
        self.assertEqual(1, len(queue._redis.added))

    def test_reclaimed_entry_is_delivered_and_acked(self):
        seen = []
        queue = self._queue(lambda payload: seen.append(payload))
        queue._redis = FakeRedisClient(reclaim=[
            ("7-0", {"envelope": '{"message_id": "m1", "attempt": 0, "payload": {"task_id": "m1"}}'}),
        ])
        try:
            queue._reclaim_stale()
        finally:
            queue.close()
        self.assertEqual([{"task_id": "m1"}], seen)
        self.assertEqual(["7-0"], queue._redis.acked)


class LeaseFencingTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.store = TaskStore(self.path)

    def tearDown(self):
        _remove_database(self.path)

    def _task(self, task_id="fence-1"):
        self.store.create(task_id, "org/repo", 1, {"source": "test"})
        return task_id

    @staticmethod
    def _event(state=TaskState.SUCCESS):
        return TraceEvent(1, state, "done", "2026-01-01T00:00:00+00:00")

    def test_stale_fence_cannot_overwrite_the_new_owner_result(self):
        task_id = self._task()
        token_a = self.store.acquire_task_lease(task_id, "worker-a", 1)
        time.sleep(1.2)
        token_b = self.store.acquire_task_lease(task_id, "worker-b", 60)
        self.assertEqual(2, token_b)

        self.assertFalse(self.store.succeed(
            task_id, ReviewReport("org/repo", 1, "stale result", "low"),
            self._event(), ("worker-a", token_a),
        ))
        self.assertTrue(self.store.succeed(
            task_id, ReviewReport("org/repo", 1, "current result", "low"),
            self._event(), ("worker-b", token_b),
        ))
        self.assertEqual("current result", self.store.get(task_id)["report"]["summary"])

    def test_transition_requires_the_current_fence(self):
        task_id = self._task()

        self.assertFalse(self.store.transition(
            task_id, self._event(TaskState.PLANNING), ("nobody", 1),
        ))
        self.assertEqual("PENDING", self.store.get(task_id)["state"])
        self.assertTrue(self.store.transition(
            task_id, self._event(TaskState.PLANNING),
        ))
        self.assertEqual("PLANNING", self.store.get(task_id)["state"])

    def test_writes_without_a_fence_are_unchanged(self):
        task_id = self._task()

        self.assertTrue(self.store.succeed(
            task_id, ReviewReport("org/repo", 1, "synchronous", "low"), self._event(),
        ))
        self.assertEqual("SUCCESS", self.store.get(task_id)["state"])

    def test_review_aborts_when_the_fence_no_longer_matches(self):
        task_id = self._task()
        harness = ReviewHarness(self.store, LocalRuleReviewer(), 8, 10)

        with self.assertRaises(LeaseLost):
            harness.run(task_id, "org/repo", 1, DIFF, "default", ("nobody", 1))

        self.assertEqual("PENDING", self.store.get(task_id)["state"])


def _webhook_payload(number=7):
    return {
        "action": "opened",
        "number": number,
        "installation": {"id": 1},
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "diff_url": "https://github.com/org/repo/pull/%d.diff" % number,
            "issue_url": "https://api.github.com/repos/org/repo/issues/%d" % number,
        },
    }


class WebhookDispatchTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

    def tearDown(self):
        _remove_database(self.path)

    def _service(self):
        settings = Settings(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
        )
        return enable_agentic_service(ReviewService(settings))

    def test_failed_submit_leaves_a_recoverable_task(self):
        service = self._service()

        def boom(payload, message_id=""):
            raise RuntimeError("queue is down")

        service.queue.submit = boom
        with self.assertRaises(RuntimeError):
            service.handle_github_pull_request(
                _webhook_payload(), "delivery-1", "digest", "default",
            )

        record = service.store.get_webhook("delivery-1")
        task_id = record["task_id"]
        self.assertTrue(task_id)
        task = service.store.get(task_id)
        self.assertEqual("PENDING", task["state"])
        self.assertNotIn("dispatched_at", task["input"])

        submitted = []
        service.queue.submit = lambda payload, message_id="": submitted.append(payload)
        self.assertEqual(
            [task_id], service.redispatch_pending(older_than_seconds=0)["redispatched"],
        )
        self.assertEqual([task_id], [item["task_id"] for item in submitted])
        self.assertEqual(
            "https://github.com/org/repo/pull/7.diff", submitted[0]["diff_url"],
        )
        service.queue.close()

    def test_duplicate_delivery_returns_the_existing_task(self):
        service = self._service()
        submitted = []
        service.queue.submit = lambda payload, message_id="": submitted.append(payload)

        first = service.handle_github_pull_request(
            _webhook_payload(), "delivery-2", "digest", "default",
        )
        second = service.handle_github_pull_request(
            _webhook_payload(), "delivery-2", "digest", "default",
        )

        self.assertEqual(first["task_id"], second["task_id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(1, len(submitted))
        service.queue.close()

    def test_retry_finishes_a_dispatch_that_never_recorded_a_task(self):
        service = self._service()
        submitted = []
        service.queue.submit = lambda payload, message_id="": submitted.append(payload)
        # A crash before the atomic write leaves the delivery without a task.
        service.store.claim_webhook("delivery-3", "default", "pull_request", "digest")

        result = service.handle_github_pull_request(
            _webhook_payload(), "delivery-3", "digest", "default",
        )

        self.assertFalse(result.get("duplicate"))
        self.assertTrue(result["task_id"])
        self.assertEqual([result["task_id"]], [item["task_id"] for item in submitted])
        service.queue.close()

    def test_redispatch_skips_tasks_that_already_reached_the_queue(self):
        from pragent.store import utc_now as _now

        service = self._service()
        submitted = []
        service.queue.submit = lambda payload, message_id="": submitted.append(payload)
        delivered = service._create_task("org/repo", DIFF, 7, "api")
        service.store.update_task_input(delivered, {"dispatched_at": _now()})
        stranded = service._create_task("org/repo", DIFF, 8, "api")

        result = service.redispatch_pending(older_than_seconds=0)

        self.assertEqual([stranded], result["redispatched"])
        self.assertEqual([stranded], [item["task_id"] for item in submitted])
        service.queue.close()


if __name__ == "__main__":
    unittest.main()
