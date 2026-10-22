import os
import shutil
import tempfile
import unittest
from urllib.parse import unquote

from agentic_fake import FakeAgenticClient
from pragent.config import Settings
from pragent.diff_parser import parse_unified_diff
from pragent.github import GitHubClient
from pragent.repository_source import PinnedFiles
from pragent.service import ReviewService


DIFF = (
    "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
    "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-old\n+value = 1\n"
)


class RecordingGitHub(GitHubClient):
    """Captures the request each fetch makes and serves canned file bodies."""

    def __init__(self, files=None, errors=()):
        super().__init__("fake-token")
        self.files = dict(files or {})
        self.errors = set(errors)
        self.requests = []

    def _request(self, method, url, payload=None, accept="", raw=False):
        self.requests.append({
            "method": method, "url": url, "accept": accept, "raw": raw,
        })
        key = unquote(url.split("/contents/", 1)[1].split("?", 1)[0])
        if key in self.errors:
            raise RuntimeError("GitHub API GET returned HTTP 500")
        if key not in self.files:
            raise RuntimeError("GitHub API GET returned HTTP 404")
        return self.files[key].encode("utf-8")


class FetchFileTests(unittest.TestCase):
    def test_fetch_file_requests_raw_content_at_the_given_ref(self):
        client = RecordingGitHub({"pkg/app.py": "x = 1\n"})
        body = client.fetch_file("org/repo", "pkg/app.py", "abc123")

        self.assertEqual("x = 1\n", body)
        request = client.requests[0]
        self.assertEqual(
            "https://api.github.com/repos/org/repo/contents/pkg/app.py?ref=abc123",
            request["url"],
        )
        self.assertEqual("application/vnd.github.raw", request["accept"])
        self.assertTrue(request["raw"])

    def test_fetch_file_omits_the_ref_when_it_is_empty(self):
        client = RecordingGitHub({"app.py": "x = 1\n"})
        client.fetch_file("org/repo", "app.py")

        self.assertEqual(
            "https://api.github.com/repos/org/repo/contents/app.py",
            client.requests[0]["url"],
        )

    def test_fetch_file_escapes_path_segments_but_keeps_separators(self):
        client = RecordingGitHub({"dir/my file.py": "y = 2\n"})
        client.fetch_file("org/repo", "/dir/my file.py", "sha")

        url = client.requests[0]["url"]
        self.assertIn("contents/dir/my%20file.py", url)
        self.assertNotIn(" ", url)


class ProviderTestCase(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.parsed = parse_unified_diff(DIFF)

    def _service(self, files=None, errors=(), **overrides):
        options = {
            "host": "127.0.0.1", "port": 0, "db_path": self.path,
            "max_diff_bytes": 200000, "max_steps": 8, "timeout_seconds": 10,
            "llm_base_url": "", "llm_api_key": "", "llm_model": "",
            "github_webhook_secret": "", "github_token": "fake-token",
            "auto_post_review": False, "watch_poll_enabled": False,
        }
        options.update(overrides)
        settings = Settings(**options)
        service = ReviewService(settings)
        self.github = RecordingGitHub(files, errors)
        service.github_client_for_installation = lambda installation_id=None: self.github
        return service


class RepositorySourceProviderTests(ProviderTestCase):
    def test_provider_returns_the_changed_files(self):
        service = self._service({"a.py": "eval(data)\n", "b.py": "value = 1\n"})

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertIsInstance(source, PinnedFiles)
        self.assertEqual(["a.py", "b.py"], source.list_files())
        self.assertIn("ref=sha-1", self.github.requests[0]["url"])

    def test_provider_skips_files_over_the_byte_ceiling(self):
        service = self._service(
            {"a.py": "x" * 500 + "\n", "b.py": "short\n"},
            repository_source_max_file_bytes=100,
        )

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertEqual(["b.py"], source.list_files())

    def test_provider_stops_when_the_total_ceiling_is_reached(self):
        service = self._service(
            {"a.py": "x" * 80 + "\n", "b.py": "y" * 80 + "\n"},
            repository_source_max_total_bytes=100,
        )

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertEqual(["a.py"], source.list_files())

    def test_provider_keeps_going_after_one_file_fails(self):
        service = self._service({"b.py": "value = 1\n"}, errors={"a.py"})

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertEqual(["b.py"], source.list_files())

    def test_provider_returns_none_when_every_file_fails(self):
        service = self._service({}, errors={"a.py", "b.py"})

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertIsNone(source)

    def test_provider_skips_binary_content(self):
        service = self._service({"a.py": "bin\x00ary\n", "b.py": "value = 1\n"})

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertEqual(["b.py"], source.list_files())

    def test_disabled_provider_never_touches_github(self):
        service = self._service(
            {"a.py": "eval(data)\n"}, repository_source_enabled=False,
        )

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertIsNone(source)
        self.assertEqual([], self.github.requests)

    def test_provider_respects_the_file_count_ceiling(self):
        service = self._service(
            {"a.py": "eval(data)\n", "b.py": "value = 1\n"},
            repository_source_max_files=1,
        )

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertEqual(["a.py"], source.list_files())


    def test_provider_refuses_to_fetch_without_a_commit_sha(self):
        service = self._service({"a.py": "eval(data)\n"})

        source = service._repository_source_provider(
            "default", "org/repo", {}, self.parsed,
        )

        self.assertIsNone(source)
        self.assertEqual([], self.github.requests)

    def test_provider_skips_the_fetch_without_a_credential(self):
        service = self._service({"a.py": "eval(data)\n"}, github_token="")

        source = service._repository_source_provider(
            "default", "org/repo", {"head_sha": "sha-1"}, self.parsed,
        )

        self.assertIsNone(source)
        self.assertEqual([], self.github.requests)


class ProviderWiringTests(ProviderTestCase):
    def _service_with_fake_model(self, files=None, **overrides):
        service = self._service(files=files, **overrides)
        service.chat_client = FakeAgenticClient()
        service.reviewer = service._build_agentic_reviewer()
        service.harness.reviewer = service.reviewer
        self.addCleanup(service.queue.close)
        return service

    def test_review_without_a_checkout_reports_a_pinned_snapshot(self):
        service = self._service_with_fake_model({"a.py": "eval(data)\n"})
        calls = []

        def provider(tenant_id, repository, task_input, parsed):
            calls.append((tenant_id, repository, list(parsed.files)))
            return PinnedFiles({"a.py": "def run():\n    return eval('x')\n"})

        service.reviewer.repository_source_provider = provider

        task_id = service._create_task("org/repo", DIFF, 7, "test")
        service.store.update_task_input(task_id, {"head_sha": "sha-1"})
        result = service._run_review(task_id, "org/repo", 7, DIFF, "default")
        context = result.to_dict()["execution"]["repository_context"]

        self.assertEqual("pinned-files", context["source_kind"])
        self.assertEqual(1, context["file_count"])
        self.assertTrue(context["available"])
        self.assertFalse(context["root_supplied"])
        self.assertEqual(1, len(calls))
        self.assertEqual(["a.py", "b.py"], calls[0][2])

    def test_a_local_root_wins_and_no_file_is_fetched(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        service = self._service_with_fake_model()
        calls = []
        service.reviewer.repository_source_provider = lambda *args: calls.append(args)

        result = service.create_review("org/repo", DIFF, 7, repository_root=root)
        context = result["report"]["execution"]["repository_context"]

        self.assertEqual("local-tree", context["source_kind"])
        self.assertTrue(context["root_supplied"])
        self.assertEqual([], calls)
        self.assertEqual([], self.github.requests)

    def test_a_failing_provider_degrades_to_no_source(self):
        service = self._service_with_fake_model()

        def provider(tenant_id, repository, task_input, parsed):
            raise RuntimeError("github is down")

        service.reviewer.repository_source_provider = provider

        task_id = service._create_task("org/repo", DIFF, 7, "test")
        service.store.update_task_input(task_id, {"head_sha": "sha-1"})
        result = service._run_review(task_id, "org/repo", 7, DIFF, "default")
        context = result.to_dict()["execution"]["repository_context"]

        self.assertFalse(context["available"])
        self.assertEqual("", context["source_kind"])


if __name__ == "__main__":
    unittest.main()
