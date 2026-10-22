import json
import os
import tempfile
import unittest

from pragent.budget import ReviewBudget
from pragent.config import Settings
from pragent.runtime import RuntimeBudgetExceeded
from pragent.service import ReviewService
from pragent.telemetry import ExecutionLedger
from agentic_fake import FakeAgenticClient


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
WORKERS = {"security", "correctness-reliability"}
UNEVIDENCED = {
    "rule_id": "FORGED-HIGH", "severity": "high", "title": "Unsafe eval",
    "explanation": "Added line evaluates untrusted input.", "path": "a.py", "line": 1,
    "evidence": "eval(data)", "fix": "Use ast.literal_eval", "test": "test_eval",
    "confidence": 0.9,
}


class RecordingClient(FakeAgenticClient):
    """Records the tools and instructions each role was actually offered."""

    def __init__(self, findings=None, risk_level="normal"):
        self.calls = []
        self.findings = list(findings or [])
        self.risk_level = risk_level

    def complete_json(self, role, system, user, ledger=None, max_tokens=None):
        managed = json.loads(user)
        task = json.loads(managed["task"])
        self.calls.append({
            "role": role, "phase": str(task.get("phase", "")),
            "tools": len(managed.get("available_tools") or []),
            "instruction": str(task.get("instruction", "")),
        })
        if role in WORKERS:
            if ledger:
                ledger.record_model(
                    role, self.provider, self.model,
                    {"prompt_tokens": 10, "completion_tokens": 5}, 1,
                )
            return {"action": "final", "findings": list(self.findings)}
        result = super().complete_json(role, system, user, ledger, max_tokens)
        if role == "lead" and task.get("phase") == "delegate":
            result = dict(result)
            result["risk_level"] = self.risk_level
        return result


class ToolFirstWorkerClient(RecordingClient):
    """Asks for one repository lookup before answering, like a real worker."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations_seen = []

    def complete_json(self, role, system, user, ledger=None, max_tokens=None):
        if role not in WORKERS:
            return super().complete_json(role, system, user, ledger, max_tokens)
        managed = json.loads(user)
        task = json.loads(managed["task"])
        self.calls.append({
            "role": role, "phase": "",
            "tools": len(managed.get("available_tools") or []),
            "instruction": str(task.get("instruction", "")),
        })
        observations = managed.get("observations") or []
        self.observations_seen.append(len(observations))
        if ledger:
            ledger.record_model(
                role, self.provider, self.model,
                {"prompt_tokens": 10, "completion_tokens": 5}, 1,
            )
        if not observations:
            return {
                "action": "tool", "tool": "search_diff",
                "arguments": {"query": "eval"},
            }
        return {"action": "final", "findings": []}


class CriticLookupClient(RecordingClient):
    """Critic that insists on two verification lookups before deciding."""

    def complete_json(self, role, system, user, ledger=None, max_tokens=None):
        if role != "critic":
            return super().complete_json(role, system, user, ledger, max_tokens)
        managed = json.loads(user)
        task = json.loads(managed["task"])
        self.calls.append({
            "role": role, "phase": "critic",
            "tools": len(managed.get("available_tools") or []),
            "instruction": str(task.get("instruction", "")),
        })
        if ledger:
            ledger.record_model(
                role, self.provider, self.model,
                {"prompt_tokens": 10, "completion_tokens": 5}, 1,
            )
        observations = managed.get("observations") or []
        if len(observations) < 2:
            return {
                "action": "tool", "tool": "read_file",
                "arguments": {"path": "a.py", "start_line": 1, "end_line": 40},
            }
        return {
            "action": "final",
            "decisions": [
                {
                    "finding_index": index, "accepted": True, "objections": [],
                    "confidence_adjustment": 0.0,
                }
                for index, _ in enumerate(task["candidates"])
            ],
        }


class ReviewBudgetUnitTests(unittest.TestCase):
    def _ledger(self, calls=0):
        ledger = ExecutionLedger("agentic")
        for index in range(calls):
            ledger.record_model(
                "worker-%d" % index, "fake", "fake",
                {"prompt_tokens": 100, "completion_tokens": 20}, 1,
            )
        return ledger

    def test_token_ceiling_stops_the_review(self):
        budget = ReviewBudget(self._ledger(calls=1), token_budget=100)
        self.assertIn("tokens", budget.exhausted())
        with self.assertRaises(RuntimeBudgetExceeded):
            budget.check("critic")

    def test_call_ceiling_stops_the_review(self):
        budget = ReviewBudget(self._ledger(calls=2), max_model_calls=2)
        self.assertIn("model calls", budget.exhausted())

    def test_unset_ceilings_never_exhaust(self):
        budget = ReviewBudget(self._ledger(calls=50))
        self.assertEqual("", budget.exhausted())
        budget.check("lead")

    def test_snapshot_reports_usage(self):
        budget = ReviewBudget(self._ledger(calls=2), token_budget=1000, max_model_calls=12)
        snapshot = budget.snapshot()
        self.assertEqual(2, snapshot["model_calls"])
        self.assertEqual(240, snapshot["tokens_used"])
        self.assertEqual("", snapshot["exhausted"])
        self.assertEqual(1000, snapshot["token_budget"])


class DepthPolicyTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        os.rmdir(self.root)
        os.unlink(self.path)

    def _service(self, client=None, **overrides):
        settings = Settings(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
            **overrides,
        )
        service = ReviewService(settings)
        service.chat_client = client or RecordingClient()
        service.reviewer = service._build_agentic_reviewer()
        service.harness.reviewer = service.reviewer
        return service

    def _run(self, client, repository_root="", risk_level="normal"):
        client.risk_level = risk_level
        service = self._service(client=client)
        try:
            service.create_review(
                "org/repo", DIFF, 7, repository_root=(self.root if repository_root else ""),
            )
        finally:
            service.queue.close()
        return client.calls

    def test_worker_can_look_things_up_when_a_repository_is_available(self):
        calls = self._run(RecordingClient(), repository_root=True)
        worker_calls = [item for item in calls if item["role"] in WORKERS]
        self.assertTrue(worker_calls)
        self.assertTrue(all(item["tools"] > 0 for item in worker_calls))
        self.assertTrue(all(
            "at most one repository lookup" in item["instruction"]
            for item in worker_calls
        ))

    def test_worker_stays_single_step_without_a_repository(self):
        calls = self._run(RecordingClient(), repository_root=False)
        worker_calls = [item for item in calls if item["role"] in WORKERS]
        self.assertTrue(worker_calls)
        self.assertTrue(all(item["tools"] == 0 for item in worker_calls))
        self.assertTrue(all(
            "one-shot review with no tools" in item["instruction"]
            for item in worker_calls
        ))

    def test_worker_can_take_a_second_step_after_a_lookup(self):
        client = ToolFirstWorkerClient()
        calls = self._run(client, repository_root=True)
        worker_calls = [item for item in calls if item["role"] in WORKERS]
        # Two workers, each spending one lookup plus one final answer.
        self.assertEqual(4, len(worker_calls))
        self.assertEqual(2, client.observations_seen.count(0))
        self.assertEqual(2, client.observations_seen.count(1))

    def test_critic_gets_tools_for_an_unevidenced_high_risk_candidate(self):
        calls = self._run(
            RecordingClient(findings=[UNEVIDENCED]), repository_root=True,
        )
        critic_calls = [item for item in calls if item["role"] == "critic"]
        self.assertEqual(1, len(critic_calls))
        self.assertGreater(critic_calls[0]["tools"], 0)

    def test_critic_stays_blind_without_a_repository(self):
        calls = self._run(
            RecordingClient(findings=[UNEVIDENCED]), repository_root=False,
        )
        critic_calls = [item for item in calls if item["role"] == "critic"]
        self.assertEqual(1, len(critic_calls))
        self.assertEqual(0, critic_calls[0]["tools"])

    def test_critic_can_verify_twice_before_deciding(self):
        # Two proof-carrying lookups plus the decision is three steps; a two-step
        # ceiling raised "critic step budget exhausted" on a real 29-file PR.
        client = CriticLookupClient(findings=[UNEVIDENCED])
        calls = self._run(client, repository_root=True)
        critic_calls = [item for item in calls if item["role"] == "critic"]
        self.assertEqual(3, len(critic_calls))
        self.assertTrue(all(item["tools"] > 0 for item in critic_calls))


class ReviewBudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

    def tearDown(self):
        os.unlink(self.path)

    def _service(self, client=None, **overrides):
        settings = Settings(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
            **overrides,
        )
        service = ReviewService(settings)
        service.chat_client = client or RecordingClient()
        service.reviewer = service._build_agentic_reviewer()
        service.harness.reviewer = service.reviewer
        return service

    def test_exhausted_budget_fails_the_task(self):
        service = self._service(agent_review_token_budget=1)
        try:
            with self.assertRaises(RuntimeBudgetExceeded):
                service.create_review("org/repo", DIFF, 7)
            task = service.store.list_tasks(1)[0]
            self.assertEqual("FAILED", task["state"])
            self.assertIn("review budget exhausted", task["error"])
        finally:
            service.queue.close()

    def test_completed_review_reports_its_budget(self):
        service = self._service()
        try:
            result = service.create_review("org/repo", DIFF, 7)
        finally:
            service.queue.close()
        budget = result["report"]["execution"]["review_budget"]
        self.assertEqual(48000, budget["token_budget"])
        self.assertEqual(480, budget["time_budget_seconds"])
        self.assertEqual("", budget["exhausted"])
        self.assertGreater(budget["model_calls"], 0)
        self.assertGreater(budget["tokens_used"], 0)


if __name__ == "__main__":
    unittest.main()
