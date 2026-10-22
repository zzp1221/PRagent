import unittest

from pragent.report import to_markdown
from pragent.telemetry import ExecutionLedger


def degraded_report(execution_extra=None):
    return {
        "repository": "org/repo", "pull_request": 7, "risk": "medium",
        "reviewer": "agentic-reviewer", "summary": "Reviewed 3 file(s).",
        "run_mode": {"requested": "agentic", "effective": "agentic"},
        "execution": dict({
            "llm_calls": 5, "tool_calls": 2, "input_tokens": 100,
            "output_tokens": 50, "total_tokens": 150, "cost_usd": 0.0,
            "duration_ms": 1200,
        }, **(execution_extra or {})),
        "collaboration": {},
        "findings": [],
    }


class LedgerDegradedRolesTests(unittest.TestCase):
    def test_a_clean_review_reports_no_degraded_roles(self):
        ledger = ExecutionLedger("agentic")

        self.assertEqual([], ledger.summary()["degraded_roles"])

    def test_a_degraded_step_exhaustion_is_listed(self):
        ledger = ExecutionLedger("agentic")
        ledger.trace("critic", "budget_exhausted", budget="steps", degraded=True)

        self.assertEqual(["critic"], ledger.summary()["degraded_roles"])

    def test_a_plain_budget_exhaustion_is_not_a_degradation(self):
        # Token and time ceilings still fail the review; only steps degrade.
        ledger = ExecutionLedger("agentic")
        ledger.trace("critic", "budget_exhausted", budget="steps")

        self.assertEqual([], ledger.summary()["degraded_roles"])

    def test_multiple_degraded_roles_are_sorted(self):
        ledger = ExecutionLedger("agentic")
        ledger.trace("security", "budget_exhausted", degraded=True)
        ledger.trace("critic", "budget_exhausted", degraded=True)

        self.assertEqual(["critic", "security"], ledger.summary()["degraded_roles"])

    def test_the_field_survives_a_checkpoint_round_trip(self):
        ledger = ExecutionLedger("agentic")
        ledger.trace("critic", "budget_exhausted", degraded=True)
        summary = ledger.summary()

        restored = ExecutionLedger("agentic")
        restored.restore(summary)

        self.assertEqual(["critic"], restored.summary()["degraded_roles"])


class MarkdownDegradedTests(unittest.TestCase):
    def test_a_clean_report_does_not_mention_degradation(self):
        text = to_markdown(degraded_report())

        self.assertNotIn("Degraded roles", text)

    def test_a_degraded_report_states_which_role_was_partial(self):
        text = to_markdown(degraded_report({"degraded_roles": ["critic"]}))

        self.assertIn("Degraded roles: `critic`", text)
        self.assertIn("results are partial", text)

    def test_the_warning_sits_inside_the_execution_facts_block(self):
        text = to_markdown(degraded_report({"degraded_roles": ["critic", "security"]}))

        facts = text.split("## Execution facts", 1)[1].split("## ", 1)[0]
        self.assertIn("`critic, security`", facts)


if __name__ == "__main__":
    unittest.main()
