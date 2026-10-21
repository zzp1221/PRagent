import inspect
import os
import tempfile
import unittest

from pragent.postgres_store import PostgresTaskStore
from pragent.store import TaskStore


DUAL_STORE_METHODS = (
    "get_runtime_setting",
    "set_runtime_setting",
    "list_runtime_settings",
    "delete_runtime_setting",
    "upsert_watch",
    "list_watches",
    "update_watch_check",
    "delete_watch",
    "claim_review_commit",
    "find_review_commit",
    "latest_webhook_delivery",
    "list_all_watches",
    "release_review_commit",
)


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.store = TaskStore(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_setting_round_trip_and_overwrite(self):
        self.assertIsNone(self.store.get_runtime_setting("t1", "llm.model"))
        self.store.set_runtime_setting("t1", "llm.model", "deepseek-v4")
        self.assertEqual("deepseek-v4", self.store.get_runtime_setting("t1", "llm.model"))
        self.store.set_runtime_setting("t1", "llm.model", "gpt-5")
        self.assertEqual("gpt-5", self.store.get_runtime_setting("t1", "llm.model"))

    def test_settings_are_tenant_scoped(self):
        self.store.set_runtime_setting("t1", "llm.model", "a")
        self.store.set_runtime_setting("t2", "llm.model", "b")
        self.assertEqual("a", self.store.get_runtime_setting("t1", "llm.model"))
        self.assertEqual("b", self.store.get_runtime_setting("t2", "llm.model"))

    def test_list_and_delete_settings(self):
        self.store.set_runtime_setting("t1", "llm.model", "a")
        self.store.set_runtime_setting("t1", "github.token_source", "gh-cli")
        self.assertEqual(
            {"llm.model": "a", "github.token_source": "gh-cli"},
            self.store.list_runtime_settings("t1"),
        )
        self.store.delete_runtime_setting("t1", "llm.model")
        self.assertEqual({"github.token_source": "gh-cli"}, self.store.list_runtime_settings("t1"))

    def test_watch_lifecycle(self):
        self.assertEqual([], self.store.list_watches("t1"))
        self.store.upsert_watch("t1", "org/repo", mode="poll", enabled=True)
        self.store.upsert_watch("t1", "org/other", mode="both", enabled=False)
        watches = self.store.list_watches("t1")
        self.assertEqual(["org/other", "org/repo"], [w["repository"] for w in watches])
        self.assertEqual(0, watches[0]["enabled"])
        self.assertEqual("both", watches[0]["mode"])

        self.store.update_watch_check("t1", "org/repo", "sha-1", "task-1", "")
        stored = {w["repository"]: w for w in self.store.list_watches("t1")}
        self.assertEqual("sha-1", stored["org/repo"]["last_sha"])
        self.assertEqual("task-1", stored["org/repo"]["last_task_id"])
        self.assertIsNotNone(stored["org/repo"]["last_checked_at"])

        self.store.upsert_watch("t1", "org/repo", mode="webhook", enabled=False)
        stored = {w["repository"]: w for w in self.store.list_watches("t1")}
        self.assertEqual("webhook", stored["org/repo"]["mode"])
        self.assertEqual(0, stored["org/repo"]["enabled"])
        # Re-enabling must not erase the last reviewed commit.
        self.assertEqual("sha-1", stored["org/repo"]["last_sha"])

        self.store.delete_watch("t1", "org/repo")
        self.assertEqual(["org/other"], [w["repository"] for w in self.store.list_watches("t1")])

    def test_claim_review_commit_is_idempotent(self):
        self.assertTrue(self.store.claim_review_commit("t1", "org/repo", "sha-1", "task-1"))
        self.assertFalse(self.store.claim_review_commit("t1", "org/repo", "sha-1", "task-2"))
        record = self.store.find_review_commit("t1", "org/repo", "sha-1")
        self.assertEqual("task-1", record["task_id"])
        self.assertTrue(self.store.claim_review_commit("t1", "org/repo", "sha-2", "task-3"))

    def test_claim_review_commit_is_repository_scoped(self):
        self.assertTrue(self.store.claim_review_commit("t1", "org/a", "sha-1", "task-1"))
        self.assertTrue(self.store.claim_review_commit("t1", "org/b", "sha-1", "task-2"))
        self.assertTrue(self.store.claim_review_commit("t2", "org/a", "sha-1", "task-3"))

    def test_blank_sha_never_blocks_a_review(self):
        self.assertTrue(self.store.claim_review_commit("t1", "org/repo", "", "task-1"))
        self.assertTrue(self.store.claim_review_commit("t1", "org/repo", "", "task-2"))
        self.assertIsNone(self.store.find_review_commit("t1", "org/repo", ""))


class DualStoreParityTests(unittest.TestCase):
    def test_both_backends_expose_the_same_onboarding_surface(self):
        for name in DUAL_STORE_METHODS:
            self.assertIn(name, dir(TaskStore), "%s missing from TaskStore" % name)
            postgres = getattr(PostgresTaskStore, name, None)
            self.assertIsNotNone(postgres, "%s missing from PostgresTaskStore" % name)
            self.assertEqual(
                inspect.signature(getattr(TaskStore, name)),
                inspect.signature(postgres),
                "%s signature differs between backends" % name,
            )


if __name__ == "__main__":
    unittest.main()
