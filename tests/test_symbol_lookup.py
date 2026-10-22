import unittest

from pragent.diff_parser import parse_unified_diff
from pragent.repository_source import PinnedFiles
from pragent.repository_tools import RepositoryToolSuite


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+value = 1\n"


def suite_for(files):
    parsed = parse_unified_diff(DIFF)
    return RepositoryToolSuite(PinnedFiles(files), DIFF, parsed)


class PythonSymbolTests(unittest.TestCase):
    def test_python_definitions_are_marked_exact(self):
        suite = suite_for({"app/helpers.py": "def shared():\n    return 1\n"})

        value = suite.symbol("shared")

        self.assertEqual(
            [{"path": "app/helpers.py", "line": 1, "kind": "FunctionDef",
              "confidence": "exact"}],
            value["output"]["definitions"],
        )
        self.assertEqual(1, value["output"]["summary"]["exact_definitions"])
        self.assertEqual(0, value["output"]["summary"]["heuristic_definitions"])

    def test_caller_scope_separates_local_imported_and_unknown(self):
        suite = suite_for({
            "app/main.py": (
                "from app.helpers import shared\n"
                "\n"
                "def use_imported():\n"
                "    return shared()\n"
                "\n"
                "def shared():\n"
                "    return 0\n"
            ),
            "app/helpers.py": "def shared():\n    return 1\n",
            "app/consumer.py": (
                "from app.helpers import shared\n"
                "\n"
                "def run():\n"
                "    return shared()\n"
            ),
            "app/orphan.py": "def use_orphan():\n    return shared()\n",
        })

        value = suite.symbol("shared")
        scopes = {
            item["path"]: item["scope"] for item in value["output"]["callers"]
        }

        self.assertEqual("local", scopes["app/main.py"])
        self.assertEqual("imported", scopes["app/consumer.py"])
        self.assertEqual("unresolved", scopes["app/orphan.py"])
        self.assertEqual(1, value["output"]["summary"]["unresolved_callers"])

    def test_same_name_in_two_files_stays_two_definitions(self):
        suite = suite_for({
            "a.py": "def helper():\n    return 1\n",
            "b.py": "def helper():\n    return 2\n",
            "c.py": "def run():\n    return helper()\n",
        })

        value = suite.symbol("helper")
        paths = [item["path"] for item in value["output"]["definitions"]]

        self.assertEqual(["a.py", "b.py"], paths)
        self.assertEqual(2, value["output"]["summary"]["exact_definitions"])

    def test_callees_describe_the_matched_definition_body(self):
        suite = suite_for({
            "a.py": "def helper():\n    return sanitize(1)\n",
        })

        value = suite.symbol("helper")

        self.assertEqual(
            [{"path": "a.py", "line": 2, "symbol": "sanitize"}],
            value["output"]["callees"],
        )


class JavaScriptSymbolTests(unittest.TestCase):
    def test_function_declaration_is_found_heuristically(self):
        suite = suite_for({
            "web/util.ts": (
                "export function format(value: string) {\n"
                "  return value.trim();\n"
                "}\n"
            ),
        })

        value = suite.symbol("format")

        self.assertEqual(
            [{"path": "web/util.ts", "line": 1, "kind": "declaration",
              "confidence": "heuristic"}],
            value["output"]["definitions"],
        )
        self.assertEqual(1, value["output"]["summary"]["heuristic_definitions"])

    def test_arrow_binding_is_a_definition_and_its_use_is_a_caller(self):
        suite = suite_for({
            "web/util.js": (
                "const helper = (x) => x;\n"
                "\n"
                "function run() {\n"
                "  return helper(1);\n"
                "}\n"
            ),
        })

        value = suite.symbol("helper")

        self.assertEqual(1, len(value["output"]["definitions"]))
        self.assertEqual(
            [{"path": "web/util.js", "line": 4, "scope": "unresolved"}],
            value["output"]["callers"],
        )

    def test_a_longer_name_is_not_mistaken_for_the_short_one(self):
        suite = suite_for({
            "web/util.ts": "export const formatCompact = (v: string) => v;\n",
        })

        value = suite.symbol("format")

        self.assertEqual([], value["output"]["definitions"])
        self.assertEqual([], value["output"]["callers"])

    def test_python_files_are_not_scanned_by_the_text_channel(self):
        suite = suite_for({"a.py": "def helper():\n    return 1\n"})

        value = suite.symbol("helper")

        # If both channels ran, this would appear twice.
        self.assertEqual(1, len(value["output"]["definitions"]))


class GoSymbolTests(unittest.TestCase):
    def test_method_with_receiver_is_found(self):
        suite = suite_for({
            "svc/handler.go": (
                "func (s *Server) Handle(w http.ResponseWriter) {\n"
                "\treturn\n"
                "}\n"
            ),
        })

        value = suite.symbol("Handle")

        self.assertEqual(
            [{"path": "svc/handler.go", "line": 1, "kind": "declaration",
              "confidence": "heuristic"}],
            value["output"]["definitions"],
        )


class SymbolOutputTests(unittest.TestCase):
    def test_unsupported_languages_are_skipped_entirely(self):
        suite = suite_for({"docs/notes.md": "# helper\nhelper()\n"})

        value = suite.symbol("helper")

        self.assertEqual([], value["output"]["definitions"])
        self.assertEqual([], value["output"]["callers"])

    def test_very_long_lines_are_trimmed_before_matching(self):
        suite = suite_for({"web/bundle.js": "const helper = " + "x" * 3000 + ";\n"})

        value = suite.symbol("helper")

        # The definition sits at the start of the line, so it still matches and
        # the trailing bulk never reaches the pattern engine.
        self.assertEqual(1, len(value["output"]["definitions"]))
        self.assertEqual([], value["output"]["callers"])

    def test_empty_name_is_rejected(self):
        suite = suite_for({"a.py": "x = 1\n"})

        with self.assertRaises(ValueError):
            suite.symbol("   ")


if __name__ == "__main__":
    unittest.main()
