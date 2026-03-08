---
name: code-review
description: Review the kid-mind codebase for compliance with AGENTS.md coding standards. Use this skill whenever the user asks to review code quality, check coding standards, audit the codebase, enforce AGENTS.md rules, check for consistency, or says things like "review the code", "check code quality", "are we following our standards?", "lint everything", or "run a code review". Also use when the user has made changes and wants to verify they comply with project conventions before committing.
---

# Code Review

Review the kid-mind codebase against the coding standards defined in `AGENTS.md`.

The review has two phases: an automated script that catches programmatically detectable violations, and a manual review pass for rules that require judgment.

## Phase 1: Automated checks

Run the review script first — it handles the mechanical checks:

```bash
uv run python .claude/skills/code-review/scripts/review.py
```

To review a single file:
```bash
uv run python .claude/skills/code-review/scripts/review.py --path src/kid_mind/tools.py
```

To auto-fix what ruff can handle:
```bash
uv run python .claude/skills/code-review/scripts/review.py --fix
```

The script checks:
- `from __future__ import annotations` presence (src/kid_mind/ files)
- Logging patterns (module-level logger, no print() in app code)
- Type hint conventions (PEP 604 unions, lowercase generics)
- Error handling (no bare except, narrow catches)
- pathlib usage (no os.path in app code)
- HTTP timeouts (all requests.get/post must have timeout=)
- Hardcoded URLs outside config.py
- Ruff lint violations
- Ruff format compliance

Report the script output to the user. If there are errors, those are the priority to fix.

## Phase 2: Manual review

After the automated checks, do a manual pass over the codebase. Read `AGENTS.md` first (it's the source of truth), then review each file for rules the script can't catch:

### What to look for

Read `AGENTS.md` before every review — it may have been updated. Focus on these judgment-based rules:

1. **Function size and focus** — Are functions small and single-responsibility? Flag functions over ~40 lines that do multiple things.

2. **Self-documenting code** — Are names expressive enough that comments aren't needed? Flag unnecessary inline comments on obvious code.

3. **Docstring quality** — Do complex public functions have Google-style docstrings? Are they accurate (no "JSON format" for dicts, no "or error" language)?

4. **Lazy imports** — Are heavy dependencies (docling, sentence-transformers, chromadb) lazy-imported in functions that use them, not at module top?

5. **Constants** — Are magic values (URLs, paths, thresholds) defined as module-level constants?

6. **Error handling judgment** — Are try/except blocks truly necessary? Is there a clear recovery path, or are they just suppressing errors?

7. **HTTP client patterns** — Do HTTP calls have retry logic with backoff? Rate-limiting delays between requests?

8. **Code organization** — Is application code in src/kid_mind/? Skill scripts in .claude/skills/? CLI runners at project root?

9. **Consistency** — Do similar modules follow the same patterns? (e.g., all tool functions return str, all use the same logging style)

### Review scope

- **Primary**: `src/kid_mind/*.py` — these files must strictly follow AGENTS.md
- **Secondary**: `chunk_kids_cli.py`, `streamlit_app.py`, `agent_cli.py` — project root scripts, should follow conventions
- **Tertiary**: `.claude/skills/*/scripts/*.py` — skill scripts, lighter standards but should still be clean
- **Shell scripts**: `.claude/skills/ssh/scripts/*.sh`, `.claude/skills/streamlit-app/scripts/*.sh` — not covered by the automated review script (Python only). Review manually for: `set -eu`/`set -euo pipefail`, proper quoting, `.env` sourcing patterns, and deployment guardrail compliance (`.env` exclusion, `data/` protection).
- **Skip**: `tests/`, `.venv/`, third-party code

### Output format

Present findings as a concise table or list, grouped by severity:

1. **Errors** — violations that must be fixed (bare except, missing future annotations, ruff errors)
2. **Warnings** — should be fixed (os.path usage, missing timeouts, Optional[] syntax)
3. **Suggestions** — could improve but not required (long functions, magic values, docstring gaps)

For each finding, include the file:line reference and a brief explanation. If the fix is obvious, state it. If it requires judgment, explain the tradeoff.

After listing findings, offer to fix the errors and warnings automatically where possible.
