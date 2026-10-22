"""Repository-level factual tools exposed to LLM agents through strict schemas."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import shlex
import time
from typing import Any, Dict, List, Optional, Set

from .diff_parser import ParsedDiff
from .repository_source import SKIP_DIRS, RepositorySource, coerce_source
from .runtime import AgentTool, ToolRegistry
from .telemetry import ExecutionLedger


# Tools that need no repository content at all: they answer from the diff.
SOURCE_FREE_TOOLS = {"search_diff", "changed_line"}
CONFIG_NAMES = {
    "package.json", "package-lock.json", "requirements.txt", "pyproject.toml",
    "poetry.lock", "Pipfile", "Dockerfile", "docker-compose.yml", ".github",
    "CODEOWNERS", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
}


def _evidence(tool: str, payload: Any) -> Dict[str, Any]:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "evidence_id": "%s:%s" % (
            tool, hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
        ),
        "tool": tool,
        "output": payload,
    }


class RepositoryToolSuite:
    def __init__(
        self, source=None, diff: str = "", parsed: Optional[ParsedDiff] = None,
        ledger: Optional[ExecutionLedger] = None,
        test_command: str = "",
    ):
        """``source`` accepts a RepositorySource, a directory path, or nothing.

        A directory string keeps working so existing callers and tests do not
        have to know about the new interface.
        """
        self.source: Optional[RepositorySource] = coerce_source(source)
        self.diff = diff
        self.parsed = parsed
        self.ledger = ledger
        self.test_command = test_command

    @property
    def repository_available(self) -> bool:
        return self.source is not None

    @property
    def root(self) -> str:
        """Local directory backing this review, or "" when it has none yet.

        Kept as a property because callers used to read the attribute; a
        materialized source only builds its directory on first use.
        """
        return self.source.local_path() if self.source is not None else ""

    def _remember_evidence(
        self, tool: str, value: Any, arguments: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record the evidence id a tool produced so the gate can verify citations."""
        if self.ledger is None or not isinstance(value, dict):
            return
        evidence_id = value.get("evidence_id")
        if not evidence_id:
            return
        subject = ""
        if isinstance(arguments, dict):
            path = arguments.get("path")
            if isinstance(path, str) and path:
                subject = path
        self.ledger.record_evidence(str(evidence_id), tool, subject)

    def _safe_path(self, relative: str) -> str:
        if self.source is None:
            raise ValueError("repository source is unavailable for this review")
        return self.source.resolve(relative)

    def _read_text(self, relative: str) -> str:
        if self.source is None:
            raise ValueError("repository source is unavailable for this review")
        return self.source.read_text(relative)

    def _files(self) -> List[str]:
        return self.source.list_files() if self.source is not None else []

    def list_repository(self, limit: int = 500) -> dict:
        files = list(self._files())[:max(1, min(int(limit), 2000))]
        return _evidence("list_repository", {
            "available": self.repository_available, "files": files,
            "truncated": len(files) >= min(int(limit), 2000),
        })

    def search_repository(self, query: str, limit: int = 50) -> dict:
        query = str(query).strip()
        if not query:
            raise ValueError("query is required")
        hits = []
        for relative in self._files():
            try:
                content = self._read_text(relative)
            except (OSError, ValueError):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append({"path": relative, "line": number, "content": line.rstrip()[:500]})
                    if len(hits) >= max(1, min(int(limit), 200)):
                        return _evidence("search_repository", hits)
        return _evidence("search_repository", hits)

    def search_diff(self, query: str, limit: int = 50) -> dict:
        query = str(query).strip().lower()
        if not query:
            raise ValueError("query is required")
        hits = [
            {"diff_line": number, "content": line[:500]}
            for number, line in enumerate(self.diff.splitlines(), 1)
            if query in line.lower()
        ][:max(1, min(int(limit), 200))]
        return _evidence("search_diff", hits)

    def read_file(self, path: str, start_line: int = 1, end_line: int = 240) -> dict:
        start = max(1, int(start_line))
        end = min(max(start, int(end_line)), start + 499)
        lines = self._read_text(path).splitlines(keepends=True)
        payload = {
            "path": str(path), "start_line": start, "end_line": min(end, len(lines)),
            "content": "".join(lines[start - 1:end])[:40_000],
        }
        return _evidence("read_file", payload)

    def changed_line(self, path: str, line: int) -> dict:
        match = next((
            item for item in self.parsed.added_lines
            if item.path == str(path) and item.line == int(line)
        ), None)
        payload = (
            {"found": True, "path": match.path, "line": match.line, "content": match.content}
            if match else {"found": False, "path": path, "line": line}
        )
        return _evidence("changed_line", payload)

    def symbol(self, name: str) -> dict:
        name = str(name).strip()
        if not name:
            raise ValueError("symbol name is required")
        definitions, callers, callees = [], [], []
        for relative in self._files():
            if not relative.endswith(".py"):
                continue
            try:
                source = self._read_text(relative)
                tree = ast.parse(source, filename=relative)
            except (OSError, ValueError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                    definitions.append({"path": relative, "line": node.lineno, "kind": type(node).__name__})
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call):
                                called = (
                                    child.func.id if isinstance(child.func, ast.Name)
                                    else child.func.attr if isinstance(child.func, ast.Attribute) else ""
                                )
                                if called:
                                    callees.append({"path": relative, "line": child.lineno, "symbol": called})
                if isinstance(node, ast.Call):
                    called = (
                        node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                    if called == name:
                        callers.append({"path": relative, "line": node.lineno})
            if len(definitions) + len(callers) > 300:
                break
        return _evidence("symbol", {
            "symbol": name, "definitions": definitions[:100],
            "callers": callers[:100], "callees": callees[:100],
        })

    def locate_tests(self, path: str = "", symbol: str = "") -> dict:
        tokens = {str(symbol).lower()} if symbol else set()
        if path:
            stem = Path(str(path)).stem.lower()
            tokens.update({stem, "test_" + stem})
        candidates = []
        for relative in self._files():
            lowered = relative.lower()
            if "test" not in lowered and "spec" not in lowered:
                continue
            score = sum(token and token in lowered for token in tokens)
            if score or not tokens:
                candidates.append({"path": relative, "relevance": score})
        candidates.sort(key=lambda item: (-item["relevance"], item["path"]))
        return _evidence("locate_tests", candidates[:100])

    def read_project_controls(self) -> dict:
        selected = []
        for relative in self._files():
            parts = set(relative.split("/"))
            if Path(relative).name in CONFIG_NAMES or parts.intersection({".github", "config", "permissions"}):
                try:
                    content = self._read_text(relative)[:20_000]
                except (OSError, ValueError):
                    continue
                selected.append({"path": relative, "content": content})
                if len(selected) >= 40:
                    break
        return _evidence("read_project_controls", selected)

    def ast_analyze(self, path: str) -> dict:
        source = self._read_text(path)
        if str(path).endswith(".py"):
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                return _evidence("ast_analyze", {
                    "path": path, "valid": False, "error": str(exc),
                })
            nodes = {}
            dangerous = []
            for node in ast.walk(tree):
                kind = type(node).__name__
                nodes[kind] = nodes.get(kind, 0) + 1
                if isinstance(node, ast.Call):
                    called = (
                        node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                    if called in {"eval", "exec", "system", "Popen", "run", "loads"}:
                        dangerous.append({"symbol": called, "line": node.lineno})
            return _evidence("ast_analyze", {
                "path": path, "valid": True, "node_counts": nodes,
                "dangerous_calls": dangerous,
            })
        return _evidence("ast_analyze", {
            "path": path, "valid": None,
            "note": "Tree-sitter is not installed; non-Python AST analysis is unavailable.",
        })

    def git_context(self, path: str, line: int = 1) -> dict:
        # History needs a real checkout; a fetched file set has no .git.
        if self.source is None or self.source.kind != "local-tree":
            return _evidence("git_context", {"available": False, "path": path})
        root = self.root
        if not os.path.isdir(os.path.join(root, ".git")) or not shutil.which("git"):
            return _evidence("git_context", {"available": False, "path": path})
        commands = [
            ["git", "log", "-n", "8", "--format=%h%x09%ad%x09%s", "--date=short", "--", str(path)],
            ["git", "blame", "-L", "%d,%d" % (max(1, int(line) - 3), max(1, int(line) + 3)), "--", str(path)],
        ]
        outputs = []
        for command in commands:
            result = subprocess.run(
                command, cwd=self.root, capture_output=True, text=True,
                timeout=20, check=False,
            )
            outputs.append({
                "command": command[1], "returncode": result.returncode,
                "output": (result.stdout + result.stderr)[-12_000:],
            })
        return _evidence("git_context", {"available": True, "path": path, "results": outputs})

    def run_scanners(self) -> dict:
        """Run installed, fixed-command analyzers. User input never becomes a command."""
        if self.source is None:
            return _evidence("run_scanners", {"available": False, "runs": []})
        specs = [
            ("semgrep", ["semgrep", "scan", "--config", "auto", "--json", "--quiet", "."]),
            ("bandit", ["bandit", "-r", ".", "-f", "json", "-q"]),
            ("eslint", ["eslint", ".", "--format", "json"]),
            ("mypy", ["mypy", ".", "--no-error-summary"]),
            ("pyright", ["pyright", "--outputjson"]),
        ]
        runs = []
        for name, command in specs:
            if not shutil.which(command[0]):
                runs.append({"name": name, "available": False})
                continue
            try:
                result = subprocess.run(
                    command, cwd=self.root, capture_output=True, text=True,
                    timeout=90, check=False,
                    env={key: value for key, value in os.environ.items() if key in {
                        "PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TMP", "TEMP"
                    }},
                )
                runs.append({
                    "name": name, "available": True, "returncode": result.returncode,
                    "output": (result.stdout + result.stderr)[-50_000:],
                })
            except subprocess.TimeoutExpired:
                runs.append({"name": name, "available": True, "timed_out": True})
        return _evidence("run_scanners", {"available": True, "runs": runs})

    def run_repository_checks(self, kind: str = "compile") -> dict:
        """Run fixed checks in an isolated repository copy with a restricted environment."""
        kind = str(kind).strip().lower()
        if kind not in {"compile", "tests"}:
            raise ValueError("kind must be compile or tests")
        if self.source is None:
            return _evidence("test", {"available": False, "kind": kind})
        if kind == "tests" and not self.test_command:
            return _evidence("test", {
                "available": False, "kind": kind,
                "reason": "no administrator-configured test command",
            })
        with tempfile.TemporaryDirectory(prefix="pragent-review-check-") as temp:
            checkout = os.path.join(temp, "checkout")
            shutil.copytree(
                self.root, checkout,
                ignore=shutil.ignore_patterns(*SKIP_DIRS),
            )
            command = (
                [sys.executable, "-m", "compileall", "-q", "."]
                if kind == "compile" else
                shlex.split(self.test_command, posix=os.name != "nt")
            )
            env = {
                key: value for key, value in os.environ.items()
                if key in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TMP", "TEMP"}
            }
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                result = subprocess.run(
                    command, cwd=checkout, env=env, capture_output=True, text=True,
                    timeout=120, check=False,
                )
                payload = {
                    "available": True, "kind": kind,
                    "isolation": "temporary-copy+restricted-environment",
                    "network_disabled": False,
                    "returncode": result.returncode,
                    "passed": result.returncode == 0,
                    "output": (result.stdout + result.stderr)[-40_000:],
                }
            except subprocess.TimeoutExpired:
                payload = {
                    "available": True, "kind": kind,
                    "isolation": "temporary-copy+restricted-environment",
                    "network_disabled": False, "passed": False, "timed_out": True,
                }
        return _evidence("test", payload)

    def registry(self, role: str, allowed: Optional[Set[str]] = None) -> ToolRegistry:
        specs = {
            "list_repository": (
                "List repository files.",
                {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 2000}}, "additionalProperties": False},
                self.list_repository,
            ),
            "search_repository": (
                "Full repository text search.",
                {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["query"], "additionalProperties": False},
                self.search_repository,
            ),
            "search_diff": (
                "Search the unified diff.",
                {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["query"], "additionalProperties": False},
                self.search_diff,
            ),
            "read_file": (
                "Read a bounded range from a repository file.",
                {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False},
                self.read_file,
            ),
            "changed_line": (
                "Read one added line from the diff.",
                {"type": "object", "properties": {"path": {"type": "string"}, "line": {"type": "integer", "minimum": 1}}, "required": ["path", "line"], "additionalProperties": False},
                self.changed_line,
            ),
            "symbol": (
                "Find a symbol definition, callers and callees.",
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False},
                self.symbol,
            ),
            "locate_tests": (
                "Locate tests related to a path or symbol.",
                {"type": "object", "properties": {"path": {"type": "string"}, "symbol": {"type": "string"}}, "additionalProperties": False},
                self.locate_tests,
            ),
            "read_project_controls": (
                "Read dependency, configuration and permission files.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                self.read_project_controls,
            ),
            "ast_analyze": (
                "Parse source and return AST facts.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
                self.ast_analyze,
            ),
            "git_context": (
                "Read nearby Git history and blame context.",
                {"type": "object", "properties": {"path": {"type": "string"}, "line": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False},
                self.git_context,
            ),
            "run_scanners": (
                "Run installed Semgrep, Bandit, ESLint and type checkers with fixed arguments.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                self.run_scanners,
            ),
            "run_repository_checks": (
                "Compile or run the administrator-configured tests in an isolated checkout copy.",
                {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"], "additionalProperties": False},
                self.run_repository_checks,
            ),
        }
        selected = set(specs) if allowed is None else set(allowed).intersection(specs)
        if self.source is None:
            # Without repository content only the diff-local tools can answer.
            # Registering the rest would just invite calls that must fail.
            selected = selected.intersection(SOURCE_FREE_TOOLS)
        tools = []
        for name in sorted(selected):
            description, schema, handler = specs[name]

            def wrapped(_handler=handler, _name=name, **arguments):
                started = time.monotonic()
                try:
                    value = _handler(**arguments)
                    if self.ledger:
                        self.ledger.record_tool(
                            role, _name, arguments, True,
                            int((time.monotonic() - started) * 1000), value,
                        )
                        self._remember_evidence(_name, value, arguments)
                    return value
                except Exception as exc:
                    if self.ledger:
                        self.ledger.record_tool(
                            role, _name, arguments, False,
                            int((time.monotonic() - started) * 1000), error=str(exc),
                        )
                    raise
            tools.append(AgentTool(name, description, schema, wrapped))
        return ToolRegistry(tools)
