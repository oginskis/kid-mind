#!/usr/bin/env python3
"""Automated code review against AGENTS.md coding standards.

Checks programmatically enforceable rules across the kid-mind codebase.
Outputs findings grouped by category with file:line references.

Usage:
    uv run python .claude/skills/code-review/scripts/review.py
    uv run python .claude/skills/code-review/scripts/review.py --path src/kid_mind/tools.py
    uv run python .claude/skills/code-review/scripts/review.py --fix  # auto-fix what's possible
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# Files to review (excludes .venv, __pycache__, etc.)
SRC_DIRS = [
    PROJECT_ROOT / "src" / "kid_mind",
    PROJECT_ROOT / "tests",
]
ROOT_SCRIPTS = list(PROJECT_ROOT.glob("*.py"))
SKILL_SCRIPTS = list((PROJECT_ROOT / ".claude" / "skills").rglob("scripts/*.py"))


def _collect_files(specific_path: str | None = None) -> list[Path]:
    """Collect all Python files to review."""
    if specific_path:
        p = Path(specific_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return [p] if p.exists() else []

    files = []
    for d in SRC_DIRS:
        if d.exists():
            files.extend(sorted(d.rglob("*.py")))
    files.extend(sorted(ROOT_SCRIPTS))
    files.extend(sorted(SKILL_SCRIPTS))
    # Exclude __pycache__
    return [f for f in files if "__pycache__" not in str(f)]


class Finding:
    """A single code review finding."""

    def __init__(self, path: Path, line: int, category: str, message: str, severity: str = "warning"):
        self.path = path
        self.line = line
        self.category = category
        self.message = message
        self.severity = severity  # "error", "warning", "info"

    @property
    def relative_path(self) -> str:
        try:
            return str(self.path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(self.path)

    def __str__(self) -> str:
        icon = {"error": "E", "warning": "W", "info": "I"}[self.severity]
        return f"  [{icon}] {self.relative_path}:{self.line} — {self.message}"


def check_future_annotations(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check for `from __future__ import annotations`."""
    findings = []
    # Only check src/kid_mind/ files (AGENTS.md scope)
    if "src/kid_mind" not in str(path) and "chunk_kids_cli" not in str(path):
        return findings

    has_future = any(
        isinstance(node, ast.ImportFrom) and node.module == "__future__" and any(a.name == "annotations" for a in node.names)
        for node in ast.iter_child_nodes(tree)
    )
    if not has_future:
        findings.append(Finding(path, 1, "imports", "Missing `from __future__ import annotations`", "error"))
    return findings


def check_logging_pattern(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check logging follows AGENTS.md: module-level `log = logging.getLogger(__name__)`."""
    findings = []
    lines = source.splitlines()

    for i, line in enumerate(lines, 1):
        # Logger created inside function or class
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent > 0 and re.match(r"(log|logger)\s*=\s*logging\.getLogger", stripped):
            findings.append(Finding(path, i, "logging", "Logger created inside function/class — move to module level", "error"))

        # Bare print() in src/ files (should use logging)
        if "src/kid_mind" in str(path) and re.match(r"print\(", stripped):
            findings.append(Finding(path, i, "logging", "Use `log.info()` instead of `print()` in application code", "warning"))

    return findings


def check_type_hints(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check type hint conventions from AGENTS.md."""
    # Skip self — this file's regex patterns contain the strings we're looking for
    if path.name == "review.py" and "code-review" in str(path):
        return []
    findings = []
    lines = source.splitlines()

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        # Skip comments and string-heavy lines (regex patterns, log messages)
        if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
            continue

        # Optional[X] instead of X | None
        if "Optional[" in line and "from typing import" not in line and '"Optional[' not in line and "'Optional[" not in line:
            findings.append(Finding(path, i, "type-hints", "Use `X | None` instead of `Optional[X]` (PEP 604)", "warning"))

        # List[X] / Dict[X, Y] instead of list[x] / dict[x, y]
        if re.search(r"\bList\[", line) and "from typing" not in line and '"List[' not in line and "'List[" not in line:
            findings.append(Finding(path, i, "type-hints", "Use `list[...]` instead of `List[...]` (lowercase)", "warning"))
        if re.search(r"\bDict\[", line) and "from typing" not in line and '"Dict[' not in line and "'Dict[" not in line:
            findings.append(Finding(path, i, "type-hints", "Use `dict[...]` instead of `Dict[...]` (lowercase)", "warning"))
        if re.search(r"\bTuple\[", line) and "from typing" not in line and '"Tuple[' not in line and "'Tuple[" not in line:
            findings.append(Finding(path, i, "type-hints", "Use `tuple[...]` instead of `Tuple[...]` (lowercase)", "warning"))

    return findings


def check_error_handling(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check error handling patterns from AGENTS.md."""
    findings = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            # Bare except
            if node.type is None:
                findings.append(Finding(path, node.lineno, "error-handling", "Bare `except:` — catch specific exceptions", "error"))

    return findings


def check_os_path_usage(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check for os.path usage where pathlib.Path should be used."""
    findings = []
    lines = source.splitlines()

    for i, line in enumerate(lines, 1):
        if "os.path." in line and "# noqa" not in line:
            findings.append(Finding(path, i, "style", "Use `pathlib.Path` instead of `os.path`", "warning"))

    return findings


def check_http_timeouts(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check that HTTP calls have explicit timeouts."""
    findings = []
    lines = source.splitlines()

    for i, line in enumerate(lines, 1):
        # requests.get/post/put/delete without timeout=
        if re.search(r"requests\.(get|post|put|delete|head)\(", line):
            # Look at this line and next few for timeout=
            context = "\n".join(lines[i - 1 : min(i + 5, len(lines))])
            if "timeout" not in context:
                findings.append(Finding(path, i, "http", "HTTP request without explicit `timeout=`", "warning"))

    return findings


def check_magic_values(path: Path, source: str, tree: ast.Module) -> list[Finding]:
    """Check for hardcoded magic numbers/strings that should be constants."""
    findings = []
    lines = source.splitlines()

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        # Skip comments, imports, constants definitions (uppercase), and string assignments
        if stripped.startswith("#") or stripped.startswith("import ") or stripped.startswith("from "):
            continue

        # Hardcoded URLs in non-config files
        if "src/kid_mind" in str(path) and "config.py" not in str(path):
            urls = re.findall(r'["\']https?://[^"\']+["\']', line)
            for url in urls:
                if "localhost" not in url:
                    findings.append(Finding(path, i, "style", f"Hardcoded URL {url} — consider moving to config.py", "info"))

    return findings


def run_ruff(fix: bool = False) -> list[Finding]:
    """Run ruff linter and collect findings."""
    findings = []
    cmd = ["uv", "run", "ruff", "check", str(PROJECT_ROOT / "src"), "--output-format=json"]
    if fix:
        cmd.append("--fix")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        findings.append(Finding(PROJECT_ROOT / "pyproject.toml", 0, "ruff", "Could not run ruff", "error"))
        return findings

    if result.returncode != 0 and result.stdout:
        import json

        try:
            violations = json.loads(result.stdout)
        except json.JSONDecodeError:
            return findings

        for v in violations:
            p = Path(v.get("filename", ""))
            line = v.get("location", {}).get("row", 0)
            code = v.get("code", "")
            msg = v.get("message", "")
            findings.append(Finding(p, line, "ruff", f"[{code}] {msg}", "error"))

    return findings


def run_ruff_format_check() -> list[Finding]:
    """Check if code is formatted according to ruff."""
    findings = []
    try:
        result = subprocess.run(
            ["uv", "run", "ruff", "format", "--check", str(PROJECT_ROOT / "src")],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return findings

    if result.returncode != 0:
        # Parse which files need formatting
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("Would"):
                p = PROJECT_ROOT / line
                findings.append(Finding(p, 0, "formatting", "File needs `ruff format`", "warning"))

    return findings


def review(specific_path: str | None = None, fix: bool = False) -> list[Finding]:
    """Run all checks and return findings."""
    files = _collect_files(specific_path)
    all_findings: list[Finding] = []

    # AST-based checks
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            all_findings.append(Finding(path, 0, "parse", "Could not parse file", "error"))
            continue

        all_findings.extend(check_future_annotations(path, source, tree))
        all_findings.extend(check_logging_pattern(path, source, tree))
        all_findings.extend(check_type_hints(path, source, tree))
        all_findings.extend(check_error_handling(path, source, tree))
        all_findings.extend(check_os_path_usage(path, source, tree))
        all_findings.extend(check_http_timeouts(path, source, tree))
        all_findings.extend(check_magic_values(path, source, tree))

    # Ruff checks
    if not specific_path:
        all_findings.extend(run_ruff(fix=fix))
        all_findings.extend(run_ruff_format_check())

    return all_findings


def main() -> None:
    parser = argparse.ArgumentParser(description="Review code against AGENTS.md standards")
    parser.add_argument("--path", help="Review a specific file instead of the whole codebase")
    parser.add_argument("--fix", action="store_true", help="Auto-fix ruff violations where possible")
    args = parser.parse_args()

    findings = review(specific_path=args.path, fix=args.fix)

    if not findings:
        print("All checks passed. No issues found.")
        sys.exit(0)

    # Group by category
    by_category: dict[str, list[Finding]] = {}
    for f in findings:
        by_category.setdefault(f.category, []).append(f)

    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")

    print(f"Found {len(findings)} issue(s): {errors} error(s), {warnings} warning(s), {infos} info(s)")
    print()

    for category, items in sorted(by_category.items()):
        print(f"── {category} ({len(items)}) ──")
        for item in sorted(items, key=lambda x: (x.relative_path, x.line)):
            print(item)
        print()

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
