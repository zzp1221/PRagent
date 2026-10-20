import unittest

from pragent.diff_parser import parse_unified_diff
from pragent.gates import FindingGate
from pragent.models import Finding, Severity
from pragent.repository_tools import RepositoryToolSuite
from pragent.telemetry import ExecutionLedger


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
LINE = "eval(data)"


def _finding(refs=(), severity=Severity.HIGH, rule_id="SEC-EVAL", line=1):
    return Finding(
        rule_id=rule_id, severity=severity, title="Unsafe eval",
        explanation="Added line evaluates untrusted input.", path="a.py", line=line,
        evidence=LINE, fix="Use ast.literal_eval", test="test_eval", confidence=0.9,
        evidence_refs=list(refs),
    )


def _rule_ref(rule_id="SEC-EVAL", line=1, path="a.py", content=LINE):
    import hashlib

    digest = hashlib.sha256(
        (rule_id + path + str(line) + content).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "evidence_id": "local-rule:%s" % digest, "tool": "local-rule-scanner",
        "rule_id": rule_id, "path": path, "line": line,
    }


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_unified_diff(DIFF)
        self.gate = FindingGate()

    def test_forged_strong_evidence_cannot_satisfy_the_high_risk_gate(self):
        ledger = ExecutionLedger("agentic")
        finding = _finding([
            {"evidence_id": "semgrep:deadbeefdeadbeef", "tool": "semgrep"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual([], result.accepted)
        self.assertEqual(1, result.checks["evidence"]["unverified_refs"])
        self.assertTrue(any(
            "AST/scanner/call-chain" in reason for reason in result.rejected[0]["reasons"]
        ))

    def test_evidence_from_a_real_tool_call_is_verified(self):
        ledger = ExecutionLedger("agentic")
        suite = RepositoryToolSuite("", DIFF, self.parsed, ledger)
        value = suite.registry("security").invoke("search_diff", {"query": "eval"})
        self.assertTrue(ledger.has_evidence(value["evidence_id"], "search_diff"))
        finding = _finding([
            {"evidence_id": value["evidence_id"], "tool": "search_diff"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual(0, result.checks["evidence"]["unverified_refs"])
        # A verified citation is not automatically strong evidence for high risk.
        self.assertEqual([], result.accepted)
        self.assertEqual(1, finding.gate["verified_evidence_count"])

    def test_tool_output_recorded_in_the_ledger_unblocks_the_gate(self):
        ledger = ExecutionLedger("agentic")
        ledger.record_evidence("ast_analyze:abc123", "ast_analyze")
        finding = _finding([
            {"evidence_id": "ast_analyze:abc123", "tool": "ast_analyze"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual(1, len(result.accepted))
        self.assertEqual(0, result.checks["evidence"]["unverified_refs"])
        self.assertEqual(1, result.accepted[0].gate["strong_evidence_count"])

    def test_evidence_cannot_borrow_a_tool_name(self):
        ledger = ExecutionLedger("agentic")
        finding = _finding([
            {"evidence_id": "local-rule:abc123", "tool": "semgrep"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual([], result.accepted)
        self.assertEqual(1, result.checks["evidence"]["unverified_refs"])

    def test_rule_evidence_is_recomputed_and_accepted(self):
        ledger = ExecutionLedger("agentic")
        finding = _finding([_rule_ref()], severity=Severity.MEDIUM)

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual(1, len(result.accepted))
        self.assertEqual(1, result.accepted[0].gate["verified_evidence_count"])

    def test_tampered_rule_evidence_is_rejected(self):
        ledger = ExecutionLedger("agentic")
        finding = _finding([_rule_ref(rule_id="SEC-OTHER")])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual([], result.accepted)
        self.assertEqual(1, result.checks["evidence"]["unverified_refs"])

    def test_rule_evidence_for_a_line_outside_the_diff_is_rejected(self):
        ledger = ExecutionLedger("agentic")
        finding = _finding([_rule_ref(line=99)], line=1)

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual([], result.accepted)

    def test_gate_without_a_ledger_keeps_prefix_checking_only(self):
        finding = _finding([
            {"evidence_id": "ast_analyze:abc123", "tool": "ast_analyze"},
        ])

        result = self.gate.apply([finding], self.parsed)

        self.assertEqual(1, len(result.accepted))

    def test_evidence_from_another_file_cannot_back_this_finding(self):
        ledger = ExecutionLedger("agentic")
        ledger.record_evidence("ast_analyze:abc123", "ast_analyze", "b.py")
        finding = _finding([
            {"evidence_id": "ast_analyze:abc123", "tool": "ast_analyze"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual([], result.accepted)
        self.assertEqual(1, result.checks["evidence"]["unverified_refs"])

    def test_evidence_scoped_to_the_same_file_is_accepted(self):
        ledger = ExecutionLedger("agentic")
        ledger.record_evidence("ast_analyze:abc123", "ast_analyze", "a.py")
        finding = _finding([
            {"evidence_id": "ast_analyze:abc123", "tool": "ast_analyze"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual(1, len(result.accepted))
        self.assertEqual(1, result.accepted[0].gate["strong_evidence_count"])

    def test_unscoped_tool_evidence_is_not_position_checked(self):
        ledger = ExecutionLedger("agentic")
        ledger.record_evidence("run_scanners:abc123", "run_scanners")
        finding = _finding([
            {"evidence_id": "run_scanners:abc123", "tool": "run_scanners"},
        ])

        result = self.gate.apply([finding], self.parsed, ledger)

        self.assertEqual(1, len(result.accepted))

    def test_tool_wrapper_records_the_file_scope_of_an_observation(self):
        ledger = ExecutionLedger("agentic")
        suite = RepositoryToolSuite("", DIFF, self.parsed, ledger)
        value = suite.registry("security").invoke(
            "changed_line", {"path": "a.py", "line": 1},
        )

        self.assertEqual("a.py", ledger.evidence_subject(value["evidence_id"]))
        self.assertTrue(ledger.has_evidence(value["evidence_id"], "changed_line"))

    def test_checkpoint_restore_preserves_recorded_evidence(self):
        ledger = ExecutionLedger("agentic")
        ledger.record_evidence("symbol:abc", "symbol")
        restored = ExecutionLedger("agentic")

        restored.restore(ledger.summary())

        self.assertTrue(restored.has_evidence("symbol:abc", "symbol"))


if __name__ == "__main__":
    unittest.main()
