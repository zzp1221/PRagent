import os
import tempfile
import unittest

from pragent.config import Settings
from pragent.service import ReviewService


def settings_for(db_path, **overrides):
    options = {
        "host": "127.0.0.1", "port": 0, "db_path": db_path, "max_diff_bytes": 10000,
        "max_steps": 8, "timeout_seconds": 120, "llm_base_url": "", "llm_api_key": "",
        "llm_model": "", "github_webhook_secret": "", "github_token": "",
        "auto_post_review": False,
    }
    options.update(overrides)
    return Settings(**options)


class RuntimeTimeoutTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

    def test_default_timeout_is_lifted_above_the_review_budget(self):
        settings = settings_for(self.path)

        # review budget 60 * 8 = 480, plus the one-minute unwind allowance.
        self.assertEqual(540, settings.resolved_review_budget()["review_time_budget_seconds"] + 60)
        self.assertEqual(540, settings.resolved_runtime_timeout())

    def test_a_smaller_explicit_timeout_is_lifted(self):
        settings = settings_for(self.path, timeout_seconds=10)

        self.assertEqual(540, settings.resolved_runtime_timeout())

    def test_a_larger_explicit_timeout_is_kept(self):
        settings = settings_for(self.path, timeout_seconds=900)

        self.assertEqual(900, settings.resolved_runtime_timeout())

    def test_an_explicit_review_budget_changes_the_derived_timeout(self):
        # A small review budget only wins when the framework timeout is smaller.
        settings = settings_for(
            self.path, timeout_seconds=10, agent_review_time_budget_seconds=30,
        )

        self.assertEqual(90, settings.resolved_runtime_timeout())

    def test_a_larger_framework_timeout_still_wins_over_a_small_budget(self):
        settings = settings_for(
            self.path, timeout_seconds=120, agent_review_time_budget_seconds=30,
        )

        self.assertEqual(120, settings.resolved_runtime_timeout())

    def test_harness_gets_the_derived_value(self):
        settings = settings_for(self.path)
        service = ReviewService(settings)
        self.addCleanup(service.queue.close)

        self.assertEqual(540, service.harness.timeout_seconds)
        self.assertEqual(540, service.harness.runtime.timeout_seconds)


if __name__ == "__main__":
    unittest.main()
