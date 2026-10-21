import os
import tempfile
import unittest
from unittest import mock

from pragent.config import Settings
from pragent.service import ReviewService


def make_service(db_path):
    settings = Settings(
        host="127.0.0.1", port=0, db_path=db_path, max_diff_bytes=200000,
        max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="",
        llm_model="", github_webhook_secret="", github_token="",
        auto_post_review=False, watch_poll_enabled=False,
    )
    service = ReviewService(settings)
    # Only the presence of a client is checked before queueing; the review
    # itself is executed by the queue worker, which this test does not run.
    service.chat_client = mock.Mock()
    return service


class PolledReviewTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.service = make_service(self.path)
        self.submitted = []
        patcher = mock.patch.object(
            self.service.queue, "submit",
            side_effect=lambda payload, **kwargs: self.submitted.append(payload),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.service.queue.close()
        os.unlink(self.path)

    def test_polled_review_creates_a_pending_task_and_claims_the_commit(self):
        result = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
            "https://api.example/issues/12",
        )
        self.assertEqual("PENDING", result["state"])
        task = self.service.store.get(result["task_id"], "default")
        self.assertEqual("org/repo", task["repository"])
        self.assertEqual(12, task["pull_request"])
        self.assertEqual("github-poll", task["input"]["source"])
        self.assertTrue(task["input"]["diff_pending"])
        self.assertEqual("sha-1", task["input"]["head_sha"])
        self.assertEqual("https://api.example/diff/12", task["input"]["diff_url"])
        self.assertEqual(1, len(self.submitted))
        self.assertEqual(result["task_id"], self.submitted[0]["task_id"])
        self.assertEqual("https://api.example/diff/12", self.submitted[0]["diff_url"])

        claimed = self.service.store.find_review_commit("default", "org/repo", "sha-1")
        self.assertEqual(result["task_id"], claimed["task_id"])

    def test_the_same_commit_is_never_queued_twice(self):
        first = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
        )
        second = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
        )
        self.assertFalse(first.get("duplicate", False))
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(1, len(self.submitted))

    def test_a_new_commit_on_the_same_pull_request_is_reviewed_again(self):
        self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
        )
        second = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-2", "https://api.example/diff/12",
        )
        self.assertFalse(second.get("duplicate", False))
        self.assertEqual(2, len(self.submitted))

    def test_webhook_task_is_skipped_when_the_poller_already_claimed_it(self):
        polled = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
        )
        self.service.store.claim_webhook(
            "delivery-1", "default", "pull_request", "digest-1",
        )
        task_id = self.service._create_webhook_task(
            "delivery-1", "org/repo", 12, "default", {
                "diff_url": "https://api.example/diff/12", "head_sha": "sha-1",
            },
        )
        self.assertEqual("", task_id)
        self.assertEqual(1, len(self.submitted))
        self.assertEqual(
            polled["task_id"],
            self.service.store.find_review_commit("default", "org/repo", "sha-1")["task_id"],
        )
        # The delivery is closed out so GitHub retries stop.
        self.assertIsNotNone(self.service.store.get_webhook("delivery-1"))

    def test_webhook_task_is_created_when_the_commit_is_new(self):
        self.service.store.claim_webhook(
            "delivery-2", "default", "pull_request", "digest-2",
        )
        task_id = self.service._create_webhook_task(
            "delivery-2", "org/repo", 12, "default", {
                "diff_url": "https://api.example/diff/12", "head_sha": "sha-9",
            },
        )
        self.assertNotEqual("", task_id)
        self.assertEqual(
            task_id,
            self.service.store.find_review_commit("default", "org/repo", "sha-9")["task_id"],
        )

    def test_failed_task_creation_releases_the_claim(self):
        with mock.patch.object(
            self.service.store, "create", side_effect=RuntimeError("disk full"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.submit_polled_review(
                    "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
                )
        self.assertIsNone(
            self.service.store.find_review_commit("default", "org/repo", "sha-1"),
        )
        # The commit must be reviewable on the next round.
        retried = self.service.submit_polled_review(
            "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
        )
        self.assertFalse(retried.get("duplicate", False))

    def test_missing_model_refuses_to_queue_anything(self):
        self.service.chat_client = None
        with self.assertRaises(RuntimeError):
            self.service.submit_polled_review(
                "default", "org/repo", 12, "sha-1", "https://api.example/diff/12",
            )
        self.assertEqual([], self.submitted)


if __name__ == "__main__":
    unittest.main()
