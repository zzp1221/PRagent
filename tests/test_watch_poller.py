import threading
import time
import unittest

from pragent.watchdog import WatchPoller


def pull(number, sha, diff_url="https://api.example/diff", issue_url="https://api.example/issue"):
    return {
        "number": number, "head": {"sha": sha},
        "diff_url": diff_url, "issue_url": issue_url,
    }


class FakeStore:
    def __init__(self, watches=None):
        self.watches = list(watches or [])
        self.claimed = set()
        self.checks = []

    def list_all_watches(self, limit=500):
        return list(self.watches)

    def find_review_commit(self, tenant_id, repository, head_sha):
        if (tenant_id, repository, head_sha) in self.claimed:
            return {"task_id": "already-there", "head_sha": head_sha}
        return None

    def update_watch_check(
        self, tenant_id, repository, last_sha="", last_task_id="", error="",
    ):
        self.checks.append({
            "tenant_id": tenant_id, "repository": repository,
            "last_sha": last_sha, "last_task_id": last_task_id, "error": error,
        })


class FakeClient:
    def __init__(self, pulls=None, errors=None):
        self.pulls = pulls or {}
        self.errors = errors or {}
        self.calls = []

    def list_open_pull_requests(self, repository, limit=30):
        self.calls.append(repository)
        if repository in self.errors:
            raise RuntimeError(self.errors[repository])
        return list(self.pulls.get(repository, []))


class FakeService:
    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.submitted = []
        self.duplicate_shas = set()

    def runtime_github_client(self):
        return self.client

    def submit_polled_review(
        self, tenant_id, repository, pull_request, head_sha, diff_url, issue_url="",
    ):
        if (tenant_id, repository, head_sha) in self.duplicate_shas:
            return {"duplicate": True, "task_id": "raced"}
        self.submitted.append({
            "tenant_id": tenant_id, "repository": repository,
            "pull_request": pull_request, "head_sha": head_sha,
            "diff_url": diff_url, "issue_url": issue_url,
        })
        return {"task_id": "task-%d" % len(self.submitted), "state": "PENDING"}


def watch(repository="org/repo", mode="poll", last_sha="", tenant="default"):
    return {
        "tenant_id": tenant, "repository": repository, "mode": mode,
        "enabled": 1, "last_sha": last_sha, "last_task_id": "",
    }


class WatchPollerTests(unittest.TestCase):
    def build(self, watches, pulls=None, errors=None):
        store = FakeStore(watches)
        client = FakeClient(pulls, errors)
        service = FakeService(store, client)
        poller = WatchPoller(service, interval_seconds=180, interval_getter=lambda: 180)
        return poller, store, client, service

    def test_new_pull_request_is_submitted_and_recorded(self):
        poller, store, _, service = self.build(
            [watch()], {"org/repo": [pull(7, "sha-new")]},
        )
        summary = poller.tick()
        self.assertEqual(1, summary["submitted"])
        self.assertEqual("sha-new", service.submitted[0]["head_sha"])
        self.assertEqual(7, service.submitted[0]["pull_request"])
        self.assertEqual("sha-new", store.checks[0]["last_sha"])
        self.assertEqual("task-1", store.checks[0]["last_task_id"])

    def test_unchanged_head_is_skipped_without_touching_github_results(self):
        poller, store, _, service = self.build(
            [watch(last_sha="sha-old")], {"org/repo": [pull(7, "sha-old")]},
        )
        summary = poller.tick()
        self.assertEqual(0, summary["submitted"])
        self.assertEqual([], service.submitted)
        self.assertEqual([], store.checks)

    def test_commit_already_reviewed_is_counted_as_duplicate(self):
        store = FakeStore([watch()])
        store.claimed.add(("default", "org/repo", "sha-new"))
        client = FakeClient({"org/repo": [pull(7, "sha-new")]})
        service = FakeService(store, client)
        poller = WatchPoller(service, interval_seconds=180)
        summary = poller.tick()
        self.assertEqual(1, summary["duplicates"])
        self.assertEqual(0, summary["submitted"])
        self.assertEqual([], service.submitted)

    def test_service_level_duplicate_is_also_counted(self):
        poller, _, _, service = self.build(
            [watch()], {"org/repo": [pull(7, "sha-new")]},
        )
        service.duplicate_shas.add(("default", "org/repo", "sha-new"))
        summary = poller.tick()
        self.assertEqual(1, summary["duplicates"])
        self.assertEqual(0, summary["submitted"])

    def test_one_failing_repository_does_not_stop_the_others(self):
        poller, store, _, service = self.build(
            [watch("org/broken"), watch("org/ok")],
            {"org/ok": [pull(1, "sha-ok")]},
            {"org/broken": "HTTP 500"},
        )
        summary = poller.tick()
        self.assertEqual(1, summary["failed"])
        self.assertEqual(1, summary["submitted"])
        self.assertEqual("org/ok", service.submitted[0]["repository"])
        failure = [c for c in store.checks if c["error"]]
        self.assertEqual("org/broken", failure[0]["repository"])
        self.assertIn("HTTP 500", failure[0]["error"])

    def test_webhook_only_watches_are_not_polled(self):
        poller, _, client, _ = self.build(
            [watch(mode="webhook")], {"org/repo": [pull(7, "sha-new")]},
        )
        summary = poller.tick()
        self.assertEqual(0, summary["submitted"])
        self.assertEqual([], client.calls)

    def test_both_mode_is_polled(self):
        poller, _, client, _ = self.build(
            [watch(mode="both")], {"org/repo": [pull(7, "sha-new")]},
        )
        poller.tick()
        self.assertEqual(["org/repo"], client.calls)

    def test_multiple_new_pulls_are_all_submitted(self):
        poller, store, _, service = self.build(
            [watch()], {"org/repo": [pull(1, "sha-a"), pull(2, "sha-b")]},
        )
        summary = poller.tick()
        self.assertEqual(2, summary["submitted"])
        self.assertEqual(["sha-a", "sha-b"], [s["head_sha"] for s in service.submitted])
        self.assertEqual("sha-b", store.checks[0]["last_sha"])

    def test_pulls_without_a_usable_diff_url_are_ignored(self):
        poller, _, _, service = self.build(
            [watch()], {"org/repo": [{"number": 7, "head": {"sha": "sha-new"}}]},
        )
        summary = poller.tick()
        self.assertEqual(0, summary["submitted"])
        self.assertEqual([], service.submitted)

    def test_a_whole_round_error_is_contained_and_reported(self):
        store = FakeStore([watch()])
        service = FakeService(store, FakeClient())

        def explode(limit=500):
            raise RuntimeError("database is locked")

        store.list_all_watches = explode
        poller = WatchPoller(service, interval_seconds=180)
        with self.assertRaises(RuntimeError):
            poller.tick()

    def test_interval_prefers_the_live_getter_then_the_fallback(self):
        poller, _, _, _ = self.build([], {})
        self.assertEqual(180, poller.interval_seconds())
        self.assertEqual(45, WatchPoller(FakeService(FakeStore(), FakeClient()), 90,
                                        interval_getter=lambda: 45).interval_seconds())
        self.assertEqual(90, WatchPoller(FakeService(FakeStore(), FakeClient()), 90).interval_seconds())

    def test_stop_event_ends_the_run_loop(self):
        poller, _, _, _ = self.build([], {})
        poller.start()
        self.assertTrue(poller.is_alive() or poller.stopped)
        poller.stop()
        poller.join(timeout=5)
        self.assertFalse(poller.is_alive())
        self.assertTrue(poller.stopped)


if __name__ == "__main__":
    unittest.main()
