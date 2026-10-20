"""Regenerate the offline evaluation fixtures under evaluation_data/.

These corpora are synthetic fixtures, not real GitHub pull requests: every case
is labelled "offline-fixture" so the real-PR readiness gates stay closed. They
exist so the evaluation harness, the controlled experiments and the prompt
evolution proof can be replayed deterministically in CI.

Run: python scripts/generate_evaluation_fixtures.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pragent.evolution_proof import write_jsonl  # noqa: E402


CONTROLLED_PATH = os.path.join(ROOT, "evaluation_data", "pr_diff_100.jsonl")
PROMPT_EVOLUTION_PATH = os.path.join(
    ROOT, "evaluation_data", "prompt_evolution_130.jsonl"
)

# rule_id -> (added line, severity, cwe). Lines are chosen so that each one
# matches exactly one deterministic rule and no other.
LOCAL_RULE_LINES = {
    "SEC-EVAL": ("result = eval(user_input)", "critical", "CWE-95"),
    "SEC-SUBPROCESS-SHELL": ("subprocess.run(command, shell=True)", "high", "CWE-78"),
    "SEC-HARDCODED-SECRET": ('api_key = "production-secret"', "high", "CWE-798"),
    "SEC-SQL-CONCAT": (
        'cursor.execute(f"SELECT * FROM users WHERE id={user_id}")', "high", "CWE-89",
    ),
    "REL-EMPTY-EXCEPT": ("except Exception: pass", "medium", "CWE-703"),
    "REL-DEBUG-PRINT": ("print(result)", "low", "CWE-532"),
}

CONTEXT_RULE_LINES = {
    "SEC-PATH-TRAVERSAL": (
        "payload = open(base / user_path)", "high", "CWE-22",
    ),
    "SEC-YAML-LOAD": ("config = yaml.load(stream)", "high", "CWE-502"),
    "SEC-WEAK-HASH": ("digest = hashlib.md5(payload)", "medium", "CWE-328"),
    "SEC-INSECURE-TEMPFILE": ("spool = tempfile.mktemp()", "medium", "CWE-377"),
    "SEC-WEAK-RANDOM": ("nonce = random.random()", "medium", "CWE-330"),
    "REL-UNBOUNDED-RETRY": ("while True:", "medium", "CWE-835"),
    "SEC-ASSERT-AUTH": ("assert user.is_admin", "medium", "CWE-617"),
    "SEC-INSECURE-COOKIE": (
        'response.set_cookie("sid", value, secure=False)', "medium", "CWE-614",
    ),
}

CLEAN_LINES = [
    "total = price * quantity",
    'value = config.get("timeout", 30)',
    "user = repository.find(user_id)",
    "items = sorted(batch)",
    'return {"status": "ok"}',
    "cursor.execute(query, (user_id,))",
]


def _diff(path: str, line: str) -> str:
    return "--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n-old\n+%s\n" % (path, path, line)


def _case(
    case_id: str, repository: str, number: int, split: str, path: str,
    line: str, rule_id: str = "", severity: str = "", cwe: str = "",
) -> dict:
    expected = []
    if rule_id:
        expected.append({
            "path": path, "start_line": 1, "end_line": 1,
            "rule_id": rule_id, "cwe": cwe, "severity": severity,
            "should_comment": True,
        })
    return {
        "id": case_id,
        "repository": repository,
        "pull_request": number,
        "split": split,
        "source": {"kind": "offline-fixture"},
        "diff": _diff(path, line),
        "expected_findings": expected,
        "repair_validation": {
            "risk_pattern": "" if not rule_id else _risk_pattern(rule_id),
            "auto_fixable": False,
        },
        "after_files": {path: line + "\n"},
    }


def _risk_pattern(rule_id: str) -> str:
    from pragent.review_rules import ContextRuleReviewer
    from pragent.reviewer import LocalRuleReviewer

    for item in LocalRuleReviewer.RULES:
        if item[0] == rule_id:
            return item[2].pattern
    for item in ContextRuleReviewer.RULES:
        if item[0] == rule_id:
            return item[2].pattern
    return ""


def controlled_cases() -> list:
    """100 cases from 10 repositories: 40 labelled defects, 60 clean."""
    risk_repositories = ["fixture/repo-01", "fixture/repo-02",
                         "fixture/repo-09", "fixture/repo-10"]
    clean_repositories = ["fixture/repo-%02d" % index for index in range(3, 9)]
    cases = []
    rules = sorted(LOCAL_RULE_LINES)
    counter = 0
    for repository in risk_repositories:
        split = "holdout" if repository in risk_repositories[2:] else "validation"
        for _ in range(10):
            rule_id = rules[counter % len(rules)]
            line, severity, cwe = LOCAL_RULE_LINES[rule_id]
            counter += 1
            cases.append(_case(
                "controlled-%03d" % len(cases), repository, len(cases) + 1, split,
                "app.py", line, rule_id, severity, cwe,
            ))
    for repository in clean_repositories:
        for _ in range(10):
            line = CLEAN_LINES[len(cases) % len(CLEAN_LINES)]
            cases.append(_case(
                "controlled-%03d" % len(cases), repository, len(cases) + 1,
                "validation", "app.py", line,
            ))
    return cases


def prompt_evolution_cases() -> list:
    """130 cases: 32 validation defects the default prompt misses on purpose.

    The default prompt carries no focus rules, so it only reports the local rule
    set. The 32 context-rule defects are therefore false negatives until
    feedback names those rules and the proposal adds them.
    """
    validation_repositories = ["evolve/repo-%02d" % index for index in range(1, 9)]
    holdout_repositories = ["evolve/repo-%02d" % index for index in range(9, 11)]
    context_rules = sorted(CONTEXT_RULE_LINES)
    local_rules = sorted(LOCAL_RULE_LINES)

    cases = []
    for index in range(104):
        repository = validation_repositories[index % len(validation_repositories)]
        if index < 32:
            rule_id = context_rules[index % len(context_rules)]
            line, severity, cwe = CONTEXT_RULE_LINES[rule_id]
        elif index < 64:
            rule_id = local_rules[index % len(local_rules)]
            line, severity, cwe = LOCAL_RULE_LINES[rule_id]
        else:
            rule_id, severity, cwe = "", "", ""
            line = CLEAN_LINES[index % len(CLEAN_LINES)]
        cases.append(_case(
            "evolve-%03d" % len(cases), repository, len(cases) + 1, "validation",
            "service.py", line, rule_id, severity, cwe,
        ))
    for index in range(26):
        repository = holdout_repositories[index % len(holdout_repositories)]
        # The holdout also carries one defect per context rule so the candidate
        # has something real to gain there; it feeds no feedback because only
        # the validation split is harvested.
        if index < len(context_rules):
            rule_id = context_rules[index]
            line, severity, cwe = CONTEXT_RULE_LINES[rule_id]
        elif index < 13:
            rule_id = local_rules[index % len(local_rules)]
            line, severity, cwe = LOCAL_RULE_LINES[rule_id]
        else:
            rule_id, severity, cwe = "", "", ""
            line = CLEAN_LINES[index % len(CLEAN_LINES)]
        cases.append(_case(
            "evolve-%03d" % len(cases), repository, len(cases) + 1, "holdout",
            "service.py", line, rule_id, severity, cwe,
        ))
    return cases


def main() -> None:
    controlled = controlled_cases()
    evolution = prompt_evolution_cases()
    write_jsonl(controlled, CONTROLLED_PATH)
    write_jsonl(evolution, PROMPT_EVOLUTION_PATH)
    print("wrote %d cases to %s" % (len(controlled), CONTROLLED_PATH))
    print("wrote %d cases to %s" % (len(evolution), PROMPT_EVOLUTION_PATH))


if __name__ == "__main__":
    main()
