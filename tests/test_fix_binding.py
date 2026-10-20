import io
import json
import os
import tempfile
import unittest
import zipfile

from pragent.config import Settings
from pragent.models import Finding, ReviewReport, Severity, TaskState, TraceEvent
from pragent.patching import VerifiedPatchFixer
from pragent.service import ReviewService
from pragent.verifier import RepairVerifier
from agentic_fake import enable_agentic_service


APP_SOURCE = "x = 1\ny = 2\n"
PATCH = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 x = 1
-y = 2
+y = 3
"""
DIFF = "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 3\n"


class FakeFixModel:
    def __init__(self, patch=PATCH):
        self.patch = patch
        self.calls = []

    def complete_json(self, role, _system, user, ledger=None, max_tokens=None):
        self.calls.append(json.loads(user))
        return {
            "patch": self.patch,
            "behavioral_claims": ["y is now 3"],
            "related_tests": ["test_app"],
        }


def _archive(source=APP_SOURCE):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("repo/app.py", source)
    return buffer.getvalue()


class FakeFixGitHub:
    def __init__(self, head_sha="reviewed-sha", files=None):
        self.head_sha = head_sha
        self.files = files or {"app.py": APP_SOURCE}
        self.read_refs = []
        self.archive_refs = []
        self.commits = []
        self.drafts = []
        self.pull_requests = []

    def get_pull_request(self, repository, number):
        self.pull_requests.append((repository, number))
        return {
            "head": {
                "ref": "feature", "sha": self.head_sha,
                "repo": {"full_name": "org/repo"},
            },
            "base": {"ref": "main"},
        }

    def get_file(self, repository, path, ref):
        self.read_refs.append(ref)
        return {"decoded_content": self.files[path]}

    def download_archive(self, repository, ref):
        self.archive_refs.append(ref)
        return _archive(self.files["app.py"])

    def create_atomic_commit(self, repository, branch, parent_sha, files, message):
        self.commits.append({"branch": branch, "parent_sha": parent_sha, "files": dict(files)})
        return {"sha": "commit-sha"}

    def create_draft_pull_request(self, repository, title, head, base, body):
        self.drafts.append({"head": head, "base": base, "title": title})
        return {"number": 12, "html_url": "https://example.test/draft"}


def _report(gate_passed=True):
    finding = Finding(
        rule_id="BUG-WRONG-DEFAULT", severity=Severity.HIGH,
        title="Wrong default", explanation="y should be 3", path="app.py", line=2,
        evidence="y = 2", fix="set y to 3", test="test_app", confidence=0.9,
    )
    finding.gate = {"passed": gate_passed}
    return ReviewReport(
        repository="org/repo", pull_request=7, summary="one finding", risk="high",
        findings=[finding],
    ).to_dict()


def _verifier(command="python -m compileall -q ."):
    return RepairVerifier(command, 120)


class FixBindingTests(unittest.TestCase):
    def test_stale_review_is_refused_before_reading_anything(self):
        client = FakeFixGitHub(head_sha="new-sha")
        fixer = VerifiedPatchFixer(FakeFixModel(), _verifier())

        result = fixer.create_fix_commits(
            client, "org/repo", 7, _report(), expected_sha="old-sha",
        )

        self.assertEqual("stale", result["status"])
        self.assertEqual("old-sha", result["reviewed_sha"])
        self.assertEqual("new-sha", result["current_sha"])
        self.assertEqual([], client.read_refs)
        self.assertEqual([], client.commits)
        self.assertEqual([], client.drafts)

    def test_files_and_archive_come_from_the_same_immutable_commit(self):
        client = FakeFixGitHub(head_sha="reviewed-sha")
        fixer = VerifiedPatchFixer(FakeFixModel(), _verifier())

        result = fixer.create_fix_commits(
            client, "org/repo", 7, _report(), expected_sha="reviewed-sha",
        )

        self.assertEqual("verified-draft", result["status"])
        self.assertEqual(["reviewed-sha"], client.read_refs)
        self.assertEqual(["reviewed-sha"], client.archive_refs)
        self.assertEqual("reviewed-sha", client.commits[0]["parent_sha"])

    def test_verified_patch_is_published_only_as_a_draft(self):
        client = FakeFixGitHub()
        fixer = VerifiedPatchFixer(FakeFixModel(), _verifier())

        result = fixer.create_fix_commits(
            client, "org/repo", 7, _report(), expected_sha="reviewed-sha",
        )

        self.assertTrue(result["verification"]["comparison"]["passed"])
        self.assertTrue(result["verification"]["comparison"]["test_evidence_present"])
        self.assertEqual(1, len(client.drafts))
        self.assertEqual("main", client.drafts[0]["base"])
        self.assertEqual("y = 3", client.commits[0]["files"]["app.py"].splitlines()[1])

    def test_missing_test_command_never_creates_a_draft(self):
        client = FakeFixGitHub()
        fixer = VerifiedPatchFixer(FakeFixModel(), _verifier(command=""))

        result = fixer.create_fix_commits(
            client, "org/repo", 7, _report(), expected_sha="reviewed-sha",
        )

        self.assertEqual("suggestion-only", result["status"])
        self.assertEqual([], client.drafts)
        self.assertEqual([], client.archive_refs)

    def test_blocked_gate_findings_are_not_patched(self):
        client = FakeFixGitHub()
        model = FakeFixModel()
        fixer = VerifiedPatchFixer(model, _verifier())

        result = fixer.create_fix_commits(
            client, "org/repo", 7, _report(gate_passed=False), expected_sha="reviewed-sha",
        )

        self.assertEqual("suggestion-only", result["status"])
        self.assertEqual([], model.calls)
        self.assertEqual([], client.drafts)


class CreateFixServiceTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

    def tearDown(self):
        os.unlink(self.path)

    def test_create_fix_forwards_the_reviewed_commit(self):
        settings = Settings(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
        )
        service = enable_agentic_service(ReviewService(settings))
        task_id = service._create_task(
            "org/repo", DIFF, 7, "api", extra={"head_sha": "reviewed-sha"},
        )
        service.store.succeed(
            task_id, ReviewReport("org/repo", 7, "summary", "low"),
            TraceEvent(1, TaskState.SUCCESS, "done", "2026-01-01T00:00:00+00:00"),
        )
        captured = {}

        class StubFixer:
            def create_fix_commits(self, client, repository, pull_request, report,
                                   expected_sha=""):
                captured.update({
                    "repository": repository, "pull_request": pull_request,
                    "expected_sha": expected_sha,
                })
                return {"status": "stale", "commits": [], "branch": None}

        service.fixer = StubFixer()
        service.github_client_for_installation = lambda installation_id=None: object()

        result = service.create_fix(task_id)

        self.assertEqual("reviewed-sha", captured["expected_sha"])
        self.assertEqual("org/repo", captured["repository"])
        self.assertEqual(7, captured["pull_request"])
        self.assertEqual("stale", result["status"])
        service.queue.close()


if __name__ == "__main__":
    unittest.main()
