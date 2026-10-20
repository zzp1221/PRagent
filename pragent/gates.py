"""Deterministic finding and release gates shared by all run modes."""
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .diff_parser import ParsedDiff
from .models import Finding, Severity


@dataclass
class GateResult:
    accepted: List[Finding]
    rejected: List[Dict[str, Any]]
    checks: Dict[str, Any]


class FindingGate:
    STRONG_EVIDENCE_TOOLS = {
        "ast_analyze", "symbol", "git_context", "run_scanners",
        "semgrep", "bandit", "eslint", "typecheck", "test", "diff-ast-analyze",
    }
    # evidence ids carry their own prefix, which is not always the tool name.
    EVIDENCE_PREFIX_ALIASES = {
        "local-rule-scanner": "local-rule",
        "diff-ast-analyze": "diff-ast",
    }
    RULE_EVIDENCE_TOOL = "local-rule-scanner"
    # Tools whose call is bound to one file, so their evidence covers that file only.
    PATH_SCOPED_EVIDENCE_TOOLS = {
        "read_file", "ast_analyze", "git_context", "changed_line", "locate_tests",
    }

    def __init__(self, minimum_confidence: float = 0.55):
        self.minimum_confidence = minimum_confidence

    @staticmethod
    def _rule_matches(rule_id: str, content: str) -> bool:
        """Check that a deterministic rule actually fires on this line."""
        from .reviewer import LocalRuleReviewer

        for item in LocalRuleReviewer.RULES:
            if item[0] == rule_id:
                return bool(item[2].search(content))
        return False

    def _rule_evidence_matches(
        self, item: Dict[str, Any], finding: Finding,
        valid_locations: Dict[Tuple[str, int], str],
    ) -> bool:
        """Recompute deterministic rule evidence instead of trusting the claim.

        The inputs come from the finding and the diff, never from the reference
        itself, otherwise a caller could pick both sides of the comparison.
        """
        path, line = str(finding.path), int(finding.line)
        content = valid_locations.get((path, line))
        if content is None:
            return False
        rule_id = str(finding.rule_id)
        if not self._rule_matches(rule_id, content):
            return False
        expected = "local-rule:%s" % hashlib.sha256(
            (rule_id + path + str(line) + content).encode("utf-8")
        ).hexdigest()[:16]
        return str(item.get("evidence_id")) == expected

    @staticmethod
    def _path_key(value: str) -> str:
        return str(value).replace("\\", "/").lstrip("./")

    def _verified_refs(
        self, finding: Finding, valid_locations: Dict[Tuple[str, int], str],
        ledger: Optional[Any],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Keep only references this review can vouch for, and count the rest."""
        verified, unverified = [], 0
        for item in finding.evidence_refs:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id") or "")
            tool = str(item.get("tool") or "")
            if not evidence_id or not tool:
                continue
            prefix = self.EVIDENCE_PREFIX_ALIASES.get(tool, tool)
            if not evidence_id.startswith(prefix + ":"):
                # A citation cannot borrow a tool name it did not come from.
                unverified += 1
                continue
            if tool == self.RULE_EVIDENCE_TOOL:
                if not self._rule_evidence_matches(item, finding, valid_locations):
                    unverified += 1
                    continue
            elif ledger is not None:
                if not ledger.has_evidence(evidence_id, tool):
                    # No such tool observation exists in this review's ledger.
                    unverified += 1
                    continue
                if tool in self.PATH_SCOPED_EVIDENCE_TOOLS:
                    subject = ledger.evidence_subject(evidence_id)
                    if subject and self._path_key(subject) != self._path_key(finding.path):
                        # Evidence gathered from another file cannot back this one.
                        unverified += 1
                        continue
            verified.append(item)
        return verified, unverified

    def apply(
        self, findings: Iterable[Finding], parsed: ParsedDiff,
        ledger: Optional[Any] = None,
    ) -> GateResult:
        valid_locations = {(item.path, item.line): item.content for item in parsed.added_lines}
        accepted, rejected = [], []
        counters = {
            "format": 0, "evidence": 0, "confidence": 0, "release": 0, "unverified": 0,
        }
        for finding in findings:
            reasons = []
            location = (finding.path, finding.line)
            if (
                location not in valid_locations or not finding.rule_id.strip()
                or not finding.title.strip() or not finding.explanation.strip()
            ):
                reasons.append("format gate: invalid location or required field")
                counters["format"] += 1

            quoted = finding.evidence.strip()
            line = valid_locations.get(location, "").strip()
            exact_line = bool(quoted and quoted in line)
            valid_refs, unverified = self._verified_refs(
                finding, valid_locations, ledger,
            )
            counters["unverified"] += unverified
            strong_refs = [
                item for item in valid_refs
                if str(item.get("tool")) in self.STRONG_EVIDENCE_TOOLS
            ]
            if not exact_line and not valid_refs and not finding.call_chain:
                reasons.append("evidence gate: no matching code, call chain or tool evidence")
                counters["evidence"] += 1
            if finding.severity in {Severity.CRITICAL, Severity.HIGH} and not (
                strong_refs or finding.call_chain
            ):
                reasons.append(
                    "evidence gate: high-risk finding requires AST/scanner/call-chain evidence"
                )
                counters["evidence"] += 1
            if finding.confidence < self.minimum_confidence:
                reasons.append("confidence gate: score below %.2f" % self.minimum_confidence)
                counters["confidence"] += 1
            if finding.severity in {Severity.CRITICAL, Severity.HIGH} and (
                not finding.fix.strip() or not finding.test.strip()
            ):
                reasons.append("release gate: high-risk finding lacks fix or test guidance")
                counters["release"] += 1

            finding.gate = {
                "passed": not reasons, "reasons": reasons,
                "exact_location_evidence": exact_line,
                "strong_evidence_count": len(strong_refs),
                "verified_evidence_count": len(valid_refs),
                "unverified_evidence_count": unverified,
            }
            if reasons:
                rejected.append({
                    "rule_id": finding.rule_id, "path": finding.path,
                    "line": finding.line, "reasons": reasons,
                })
            else:
                accepted.append(finding)
        return GateResult(
            accepted, rejected,
            {
                "format": {"rejected": counters["format"]},
                "evidence": {
                    "rejected": counters["evidence"],
                    "unverified_refs": counters["unverified"],
                },
                "confidence": {
                    "minimum": self.minimum_confidence,
                    "rejected": counters["confidence"],
                },
                "release": {"rejected": counters["release"]},
                "accepted": len(accepted), "rejected": len(rejected),
            },
        )
