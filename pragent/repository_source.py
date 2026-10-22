"""Read-only views of the files a review is allowed to inspect.

The review pipeline used to hand every tool a local working tree, which only
exists when a caller passes ``repository_root`` to the API. Webhook and polled
reviews run on machines that never had a checkout, so ten of the twelve tools
degraded to errors or empty results. A ``RepositorySource`` is the seam that
lets the same tools read a small fetched file set instead of requiring a tree.
"""
import os
import tempfile
import threading
from typing import Dict, Iterable, List

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "dist", "build", ".venv", "venv"}
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 20_000


class RepositorySource:
    """Immutable, thread-safe view over the files one review may read."""

    kind = ""

    def list_files(self) -> List[str]:
        raise NotImplementedError

    def read_text(self, relative: str) -> str:
        raise NotImplementedError

    def resolve(self, relative: str) -> str:
        """Absolute filesystem path for a member, or raise when it is not one."""
        raise NotImplementedError

    def local_path(self) -> str:
        """Directory usable as a subprocess cwd, or "" when none exists."""
        return ""

    def describe(self) -> Dict[str, object]:
        return {"source_kind": self.kind, "file_count": len(self.list_files())}


class LocalTree(RepositorySource):
    """An existing working tree on this machine."""

    kind = "local-tree"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def describe(self) -> Dict[str, object]:
        # Counting a tree means walking it, which reviews already do on every
        # tool call. Report the kind without paying for an extra traversal.
        return {"source_kind": self.kind, "file_count": None}

    def list_files(self) -> List[str]:
        values: List[str] = []
        for current, dirs, files in os.walk(self.root):
            dirs[:] = [item for item in dirs if item not in SKIP_DIRS]
            for name in files:
                path = os.path.join(current, name)
                try:
                    if os.path.getsize(path) <= MAX_FILE_BYTES:
                        values.append(os.path.relpath(path, self.root).replace("\\", "/"))
                except OSError:
                    continue
                if len(values) >= MAX_FILES:
                    return values
        return values

    @staticmethod
    def _key(relative: str) -> str:
        return str(relative).replace("\\", "/").lstrip("/")

    def resolve(self, relative: str) -> str:
        target = os.path.abspath(os.path.join(self.root, self._key(relative)))
        if target != self.root and not target.startswith(self.root + os.sep):
            raise ValueError("path escapes repository root")
        return target

    def read_text(self, relative: str) -> str:
        with open(self.resolve(relative), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def local_path(self) -> str:
        return self.root


class PinnedFiles(RepositorySource):
    """A frozen set of file contents fetched for exactly one review.

    Reads are served from memory. Tools that need a real directory (scanners,
    compile/test runs, blame) trigger a one-time materialization into a
    temporary tree that lives as long as this object does.
    """

    kind = "pinned-files"

    def __init__(self, files: Dict[str, str]):
        self.files: Dict[str, str] = {
            str(path).replace("\\", "/").lstrip("/"): str(content)
            for path, content in (files or {}).items()
            if str(path).strip()
        }
        self._temp = None
        self._lock = threading.Lock()

    @staticmethod
    def _key(relative: str) -> str:
        return str(relative).replace("\\", "/").lstrip("/")

    def list_files(self) -> List[str]:
        return sorted(self.files)

    def read_text(self, relative: str) -> str:
        key = self._key(relative)
        if key not in self.files:
            raise ValueError(
                "file is not part of this review's snapshot: %s" % (key or "<empty>")
            )
        return self.files[key]

    def local_path(self) -> str:
        """Materialize once, then reuse the same directory for every caller."""
        with self._lock:
            if self._temp is not None:
                return self._temp.name
            temp = tempfile.TemporaryDirectory(prefix="pragent-source-")
            for relative, content in self.files.items():
                target = os.path.join(temp.name, *relative.split("/"))
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "w", encoding="utf-8", newline="") as handle:
                        handle.write(content)
                except OSError:
                    # A name that cannot be written (too long, reserved) simply
                    # does not appear in the materialized tree.
                    continue
            self._temp = temp
            return temp.name

    def resolve(self, relative: str) -> str:
        key = self._key(relative)
        if key not in self.files:
            raise ValueError(
                "file is not part of this review's snapshot: %s" % (key or "<empty>")
            )
        return os.path.join(self.local_path(), *key.split("/"))


def coerce_source(value) -> "RepositorySource | None":
    """Accept a source, a directory path, or nothing, and normalize once."""
    if isinstance(value, RepositorySource):
        return value
    if not value:
        return None
    candidate = os.path.abspath(str(value))
    return LocalTree(candidate) if os.path.isdir(candidate) else None
