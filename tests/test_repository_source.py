import os
import tempfile
import threading
import unittest

from pragent.diff_parser import parse_unified_diff
from pragent.repository_source import LocalTree, PinnedFiles, coerce_source
from pragent.repository_tools import RepositoryToolSuite
from pragent.telemetry import ExecutionLedger


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
PY_SOURCE = "def helper(value):\n    return eval(value)\n\n\ndef caller():\n    return helper('x')\n"


class LocalTreeTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name
        self._write("pkg/module.py", PY_SOURCE)
        self._write("node_modules/vendored.js", "eval(x)")
        self._write(".git/config", "[core]")
        self._write("README.md", "# demo\n")

    def tearDown(self):
        self._temp.cleanup()

    def _write(self, relative, content):
        target = os.path.join(self.root, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_list_files_skips_vendored_and_vcs_directories(self):
        files = LocalTree(self.root).list_files()
        self.assertIn("pkg/module.py", files)
        self.assertIn("README.md", files)
        self.assertNotIn("node_modules/vendored.js", files)
        self.assertNotIn(".git/config", files)

    def test_resolve_rejects_paths_outside_the_tree(self):
        tree = LocalTree(self.root)
        with self.assertRaises(ValueError):
            tree.resolve("../escape.py")
        self.assertTrue(tree.resolve("pkg/module.py").startswith(self.root))

    def test_read_text_returns_file_content(self):
        self.assertEqual(PY_SOURCE, LocalTree(self.root).read_text("pkg/module.py"))

    def test_describe_avoids_walking_the_tree(self):
        described = LocalTree(self.root).describe()
        self.assertEqual("local-tree", described["source_kind"])
        self.assertIsNone(described["file_count"])


class PinnedFilesTests(unittest.TestCase):
    def setUp(self):
        self.source = PinnedFiles({"src/app.py": PY_SOURCE, "README.md": "# demo\n"})

    def test_read_text_serves_the_snapshot(self):
        self.assertEqual(PY_SOURCE, self.source.read_text("src/app.py"))

    def test_read_text_normalizes_windows_and_leading_separators(self):
        self.assertEqual(PY_SOURCE, self.source.read_text("\\src\\app.py"))
        self.assertEqual(PY_SOURCE, self.source.read_text("/src/app.py"))

    def test_read_text_rejects_files_outside_the_snapshot(self):
        with self.assertRaises(ValueError):
            self.source.read_text("secrets.env")

    def test_resolve_stays_inside_the_materialized_tree(self):
        path = self.source.resolve("src/app.py")
        self.assertTrue(os.path.isfile(path))
        with self.assertRaises(ValueError):
            self.source.resolve("../../etc/passwd")

    def test_materialization_is_shared_between_callers(self):
        self.assertEqual(self.source.local_path(), self.source.local_path())
        self.assertTrue(os.path.isdir(self.source.local_path()))

    def test_describe_reports_the_snapshot_size(self):
        described = self.source.describe()
        self.assertEqual("pinned-files", described["source_kind"])
        self.assertEqual(2, described["file_count"])

    def test_concurrent_reads_are_safe(self):
        errors = []

        def worker():
            try:
                for _ in range(50):
                    self.assertEqual(PY_SOURCE, self.source.read_text("src/app.py"))
                    self.source.list_files()
            except Exception as exc:  # pragma: no cover - only on failure
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for item in threads:
            item.start()
        for item in threads:
            item.join()
        self.assertEqual([], errors)


class CoerceSourceTests(unittest.TestCase):
    def test_empty_values_become_none(self):
        self.assertIsNone(coerce_source(""))
        self.assertIsNone(coerce_source(None))
        self.assertIsNone(coerce_source(os.path.join(tempfile.gettempdir(), "pragent-missing")))

    def test_directory_strings_become_a_local_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsInstance(coerce_source(temp), LocalTree)

    def test_existing_sources_pass_through(self):
        source = PinnedFiles({"a.py": "x = 1\n"})
        self.assertIs(source, coerce_source(source))


class ToolSuiteSourceTests(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_unified_diff(DIFF)

    def test_suite_without_a_source_registers_only_diff_tools(self):
        from pragent.agentic_core import ROLE_PERMISSIONS

        suite = RepositoryToolSuite("", DIFF, self.parsed)
        self.assertFalse(suite.repository_available)
        # security may reach eight source-backed tools; none of them survive,
        # and the two diff-local tools it is allowed stay.
        self.assertEqual(
            ["changed_line", "search_diff"],
            suite.registry("security", ROLE_PERMISSIONS["security"]).names(),
        )

    def test_suite_without_a_source_keeps_the_lead_diff_tool(self):
        from pragent.agentic_core import ROLE_PERMISSIONS

        suite = RepositoryToolSuite("", DIFF, self.parsed)
        # The lead's allow-list never included changed_line, so it keeps one.
        self.assertEqual(
            ["search_diff"],
            suite.registry("lead", ROLE_PERMISSIONS["lead"]).names(),
        )

    def test_directory_input_keeps_every_role_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            suite = RepositoryToolSuite(temp, DIFF, self.parsed)
            self.assertTrue(suite.repository_available)
            self.assertIn("read_file", suite.registry("security").names())

    def test_pinned_files_restore_the_tools_that_needed_a_checkout(self):
        suite = RepositoryToolSuite(
            PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed,
        )
        self.assertTrue(suite.repository_available)
        names = suite.registry("security").names()
        for expected in ("read_file", "symbol", "ast_analyze", "search_repository"):
            self.assertIn(expected, names)

    def test_pinned_files_serve_symbol_and_ast_lookups(self):
        suite = RepositoryToolSuite(
            PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed,
        )
        registry = suite.registry("security")
        symbol = registry.invoke("symbol", {"name": "helper"})
        self.assertEqual(
            [{"path": "a.py", "line": 1, "kind": "FunctionDef"}],
            symbol["output"]["definitions"],
        )
        analyzed = registry.invoke("ast_analyze", {"path": "a.py"})
        self.assertTrue(analyzed["output"]["valid"])
        self.assertEqual(
            [{"symbol": "eval", "line": 2}], analyzed["output"]["dangerous_calls"],
        )

    def test_pinned_files_cannot_read_outside_the_snapshot(self):
        suite = RepositoryToolSuite(PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed)
        with self.assertRaises(ValueError):
            suite.registry("security").invoke("read_file", {"path": "b.py"})

    def test_git_context_reports_unavailable_instead_of_raising(self):
        suite = RepositoryToolSuite(PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed)
        value = suite.registry("security").invoke(
            "git_context", {"path": "a.py", "line": 1},
        )
        self.assertFalse(value["output"]["available"])

    def test_pinned_files_materialize_for_the_test_runner(self):
        suite = RepositoryToolSuite(PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed)
        self.assertTrue(os.path.isfile(os.path.join(suite.root, "a.py")))

    def test_ledger_records_a_successful_tool_call_without_a_checkout(self):
        from pragent.gates import FindingGate
        from pragent.models import Finding, Severity

        ledger = ExecutionLedger("agentic")
        suite = RepositoryToolSuite(PinnedFiles({"a.py": PY_SOURCE}), DIFF, self.parsed, ledger)
        value = suite.registry("security").invoke("ast_analyze", {"path": "a.py"})
        self.assertTrue(ledger.has_evidence(value["evidence_id"], "ast_analyze"))
        finding = Finding(
            rule_id="SEC-EVAL", severity=Severity.HIGH, title="Unsafe eval",
            explanation="helper() evaluates untrusted input.", path="a.py", line=1,
            evidence="eval(data)", fix="Use ast.literal_eval", test="test_eval",
            confidence=0.9,
            evidence_refs=[{"evidence_id": value["evidence_id"], "tool": "ast_analyze"}],
        )
        result = FindingGate().apply([finding], self.parsed, ledger)
        self.assertEqual([], result.rejected)


if __name__ == "__main__":
    unittest.main()
