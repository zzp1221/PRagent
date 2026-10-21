import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from pragent.api import ApiHandler
from pragent.config import Settings
from pragent.onboarding import (
    OnboardingService, mask_secret, probe_github_cli,
)
from pragent.service import DEPLOYMENT_SCOPE, ReviewService
from pragent.watchdog import WatchPoller


def make_settings(db_path, public_base_url="http://127.0.0.1:8080"):
    return Settings(
        host="127.0.0.1", port=0, db_path=db_path, max_diff_bytes=200000,
        max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="",
        llm_model="", github_webhook_secret="", github_token="",
        auto_post_review=False, watch_poll_enabled=False,
        public_base_url=public_base_url,
    )


class SecretMaskTests(unittest.TestCase):
    def test_mask_keeps_a_recognisable_prefix_only(self):
        self.assertEqual("", mask_secret(""))
        self.assertEqual("****", mask_secret("abc"))
        self.assertEqual("gho_****", mask_secret("gho_1234567890abcdef"))
        self.assertNotIn("1234567890", mask_secret("gho_1234567890abcdef"))


class GithubCliProbeTests(unittest.TestCase):
    def _completed(self, returncode, stdout="", stderr=""):
        return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)

    def test_missing_cli_is_a_normal_result(self):
        with mock.patch("pragent.onboarding.shutil.which", return_value=None):
            report = probe_github_cli()
        self.assertFalse(report["found"])
        self.assertIn("GitHub CLI", report["reason"])

    def test_logged_out_cli_explains_how_to_fix(self):
        with mock.patch("pragent.onboarding.shutil.which", return_value="gh"), \
             mock.patch("pragent.onboarding._run_gh", return_value=self._completed(
                 1, "", "You are not logged into any GitHub hosts.")):
            report = probe_github_cli()
        self.assertFalse(report["found"])
        self.assertIn("未登录", report["reason"])

    def test_successful_probe_parses_account_and_scopes(self):
        status = self._completed(0, (
            "github.com\n"
            "  \u2713 Logged in to github.com account octocat (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n"
        ))
        token = self._completed(0, "gho_abcdefghijklmnop\n")
        with mock.patch("pragent.onboarding.shutil.which", return_value="gh"), \
             mock.patch("pragent.onboarding._run_gh", side_effect=[status, token]):
            report = probe_github_cli()
        self.assertTrue(report["found"])
        self.assertEqual("octocat", report["account"])
        self.assertEqual(["gist", "read:org", "repo", "workflow"], report["scopes"])
        self.assertEqual("gho_abcdefghijklmnop", report["token"])
        self.assertEqual("gho_****", report["token_masked"])
        self.assertFalse(report["missing_repo_scope"])

    def test_read_only_scope_is_reported_as_insufficient(self):
        status = self._completed(0, (
            "  \u2713 Logged in to github.com account octocat (keyring)\n"
            "  - Token scopes: 'gist', 'read:org'\n"
        ))
        token = self._completed(0, "gho_abcdefghijklmnop\n")
        with mock.patch("pragent.onboarding.shutil.which", return_value="gh"), \
             mock.patch("pragent.onboarding._run_gh", side_effect=[status, token]):
            report = probe_github_cli()
        self.assertTrue(report["missing_repo_scope"])


class OnboardingServiceTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.settings = make_settings(self.path)
        self.service = ReviewService(self.settings)
        self.onboarding = OnboardingService(self.service)

    def tearDown(self):
        self.service.queue.close()
        os.unlink(self.path)

    def test_initial_status_reports_an_unconfigured_deployment(self):
        status = self.onboarding.status("default")
        self.assertFalse(status["llm"]["configured"])
        self.assertFalse(status["github"]["has_token"])
        self.assertEqual([], status["watches"])
        self.assertFalse(status["webhook"]["available"])
        self.assertIn("HTTPS", status["webhook"]["reason"])

    def test_loopback_https_url_is_rejected_for_a_different_reason(self):
        service = ReviewService(make_settings(self.path, "https://127.0.0.1"))
        try:
            status = OnboardingService(service).status("default")
            self.assertFalse(status["webhook"]["available"])
            self.assertIn("回环", status["webhook"]["reason"])
        finally:
            service.queue.close()

    def test_public_base_url_enables_the_webhook_branch(self):
        service = ReviewService(make_settings(self.path, "https://agent.example.com"))
        try:
            status = OnboardingService(service).status("default")
            self.assertTrue(status["webhook"]["available"])
            self.assertEqual(
                "https://agent.example.com/webhooks/github", status["webhook"]["endpoint"],
            )
        finally:
            service.queue.close()

    def test_save_llm_rejects_missing_fields(self):
        with self.assertRaises(ValueError) as caught:
            self.onboarding.save_llm("", "m", "k")
        self.assertIn("URL", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            self.onboarding.save_llm("https://api.example.com", "", "k")
        self.assertIn("模型", str(caught.exception))

    def test_save_llm_rejects_a_non_http_url(self):
        with self.assertRaises(ValueError) as caught:
            self.onboarding.save_llm("api.example.com/v1", "m", "k")
        self.assertIn("http", str(caught.exception))

    def test_save_llm_reports_provider_failure_without_storing_anything(self):
        failing = mock.Mock()
        failing.complete_json.side_effect = RuntimeError("custom API returned HTTP 401")
        with mock.patch("pragent.onboarding.JsonChatClient", return_value=failing):
            with self.assertRaises(ValueError) as caught:
                self.onboarding.save_llm("https://api.example.com", "m", "sk-bad")
        self.assertIn("401", str(caught.exception))
        self.assertFalse(self.onboarding.status("default")["llm"]["configured"])

    def test_save_llm_applies_immediately_and_masks_the_key(self):
        working = mock.Mock()
        working.complete_json.return_value = {"ok": True}
        with mock.patch("pragent.onboarding.JsonChatClient", return_value=working):
            result = self.onboarding.save_llm(
                "https://api.example.com/v1/", "demo-model", "sk-very-secret",
            )
        self.assertTrue(result["configured"])
        self.assertEqual("demo-model", result["model"])
        self.assertEqual("https://api.example.com/v1", result["base_url"])
        status = self.onboarding.status("default")
        self.assertTrue(status["llm"]["configured"])
        self.assertEqual("sk-v****", status["llm"]["api_key_masked"])
        self.assertNotIn("sk-very-secret", json.dumps(status))

    def test_save_github_token_verifies_before_storing(self):
        with mock.patch("pragent.onboarding.GitHubClient") as client:
            client.return_value.get_authenticated_user.return_value = {"login": "octocat"}
            saved = self.onboarding.save_github_token("ghp_example", "manual")
        self.assertEqual("octocat", saved["account"])
        self.assertEqual("ghp_****", saved["token_masked"])
        self.assertTrue(self.onboarding.status("default")["github"]["has_token"])

    def test_invalid_github_token_is_not_stored(self):
        with mock.patch("pragent.onboarding.GitHubClient") as client:
            client.return_value.get_authenticated_user.side_effect = RuntimeError("HTTP 401")
            with self.assertRaises(ValueError):
                self.onboarding.save_github_token("bad", "manual")
        self.assertFalse(self.onboarding.status("default")["github"]["has_token"])

    def test_watches_replace_the_whole_set_and_grant_access(self):
        self.onboarding.save_watches("default", [
            {"repository": "org/a", "mode": "poll"},
            {"repository": "org/b", "mode": "both"},
        ])
        current = {w["repository"]: w for w in self.onboarding.status("default")["watches"]}
        self.assertEqual({"org/a", "org/b"}, set(current))
        self.assertTrue(self.service.store.repository_allowed("default", "org/a"))

        self.onboarding.save_watches("default", [{"repository": "org/a", "mode": "webhook"}])
        current = {w["repository"]: w for w in self.onboarding.status("default")["watches"]}
        self.assertEqual({"org/a"}, set(current))
        self.assertEqual("webhook", current["org/a"]["mode"])
        # Dropping a subscription keeps the grant, so manual reviews still work.
        self.assertTrue(self.service.store.repository_allowed("default", "org/b"))

    def test_watches_reject_unknown_modes(self):
        with self.assertRaises(ValueError):
            self.onboarding.save_watches("default", [{"repository": "org/a", "mode": "realtime"}])

    def test_rotate_webhook_secret_returns_it_once_and_becomes_effective(self):
        rotated = self.onboarding.rotate_webhook_secret()
        self.assertEqual(64, len(rotated["secret"]))
        self.assertTrue(rotated["endpoint"].endswith("/webhooks/github"))
        self.assertEqual(rotated["secret"], self.onboarding.webhook_secret())
        status = self.onboarding.status("default")
        self.assertTrue(status["webhook"]["has_secret"])
        self.assertNotIn(rotated["secret"], json.dumps(status))

    def test_watch_interval_falls_back_when_garbage_is_stored(self):
        self.assertEqual(180, self.onboarding.watch_interval_seconds())
        self.service.store.set_runtime_setting(
            DEPLOYMENT_SCOPE, "watch.interval_seconds", "not-a-number",
        )
        self.assertEqual(180, self.onboarding.watch_interval_seconds())
        self.service.store.set_runtime_setting(
            DEPLOYMENT_SCOPE, "watch.interval_seconds", "60",
        )
        self.assertEqual(60, self.onboarding.watch_interval_seconds())


class OnboardingHttpTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.service = ReviewService(make_settings(self.path))
        self.onboarding = OnboardingService(self.service)
        handler = type("TestApiHandler", (ApiHandler,), {
            "service": self.service,
            "settings": self.service.settings,
            "onboarding": self.onboarding,
            "poller": None,
        })
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.queue.close()
        os.unlink(self.path)

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_status_endpoint_returns_the_wizard_summary(self):
        status, body = self.call("GET", "/v1/onboarding/status")
        self.assertEqual(200, status)
        self.assertIn("llm", body)
        self.assertIn("github", body)
        self.assertIn("webhook", body)
        self.assertIn("watches", body)

    def test_probe_endpoint_never_returns_the_token(self):
        report = {
            "found": True, "account": "octocat",
            "scopes": ["repo"], "token": "gho_supersecret",
            "token_masked": "gho_****", "reason": "", "missing_repo_scope": False,
        }
        with mock.patch("pragent.api.probe_github_cli", return_value=report):
            status, body = self.call("POST", "/v1/onboarding/probe-gh")
        self.assertEqual(200, status)
        self.assertEqual("octocat", body["account"])
        self.assertNotIn("token", body)
        self.assertNotIn("gho_supersecret", json.dumps(body))

    def test_probe_endpoint_returns_200_when_detection_fails(self):
        report = {
            "found": False, "account": "", "scopes": [], "token": "",
            "token_masked": "", "reason": "未检测到 GitHub CLI，请手动填写访问令牌",
            "missing_repo_scope": False,
        }
        with mock.patch("pragent.api.probe_github_cli", return_value=report):
            status, body = self.call("POST", "/v1/onboarding/probe-gh")
        self.assertEqual(200, status)
        self.assertFalse(body["found"])
        self.assertIn("手动填写", body["reason"])

    def test_llm_endpoint_rejects_incomplete_input_with_400(self):
        status, body = self.call("POST", "/v1/onboarding/llm", {"url": "", "model": "", "api_key": ""})
        self.assertEqual(400, status)
        self.assertIn("缺少必填项", body["error"])

    def test_watches_endpoint_persists_the_selection(self):
        status, body = self.call("POST", "/v1/onboarding/watches", {
            "watches": [{"repository": "org/a", "mode": "poll", "enabled": True}],
        })
        self.assertEqual(200, status)
        self.assertEqual(1, len(body["watches"]))
        status, body = self.call("GET", "/v1/onboarding/status")
        self.assertEqual(["org/a"], [w["repository"] for w in body["watches"]])

    def test_webhook_secret_endpoint_rotates_and_hides_the_value_in_status(self):
        status, body = self.call("POST", "/v1/onboarding/webhook-secret", {})
        self.assertEqual(201, status)
        secret = body["secret"]
        self.assertEqual(64, len(secret))
        status, status_body = self.call("GET", "/v1/onboarding/status")
        self.assertNotIn(secret, json.dumps(status_body))


if __name__ == "__main__":
    unittest.main()
