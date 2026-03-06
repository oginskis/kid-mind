# Coding Standards (for Agents)

> These standards apply to **all** Python code in the project: `src/kid_mind/`, `tests/`, `chunk_kids_cli.py`, and `.claude/skills/*/scripts/`.

**MANDATORY**: After any codebase changes, update both `CLAUDE.md` and this file (`AGENTS.md`) to keep them in sync with the codebase. This includes new files, renamed modules, changed conventions, new dependencies, or removed features.

## Contents
- Python Style
- Import Conventions
- Error Handling
- Logging
- Type Hints
- Docstrings
- Data Modeling
- HTTP Clients
- Code Organization
- Ruff Linter
- Good vs Bad Practices
- Pre-Push Checklist

## Python Style

- Target Python 3.10+.
- Favor self-documenting code: expressive names and small functions over inline comments.
- Avoid inline comments; if the code needs a comment, consider renaming or restructuring first.
- **Exception**: core top-level orchestration functions (e.g., `process_pdf`, `main`) may use step-by-step inline comments to explain the pipeline flow and *why* each step exists.
- Keep functions focused on a single responsibility.
- Use constants for magic values; define them at module level.

## Import Conventions

- Organize imports in standard order: standard library, third-party, local.
- Remove unused imports before committing.
- Consolidate related imports; prefer `from x import a, b` over multiple `import` lines when importing several names from the same module.
- Use lazy imports for heavy dependencies (e.g., Docling, sentence-transformers) that slow startup.

## Error Handling

- Fail fast: let exceptions bubble up unless a clear, necessary recovery path exists.
- Do NOT add try/except blocks unless absolutely necessary.
- Never swallow exceptions with bare `except:` or broad `except Exception` that hide root causes.
- When catching exceptions, handle narrowly (specific exception types) and always log context.
- For pipeline scripts processing multiple items, catch per-item exceptions to avoid aborting the entire batch, but always log the failure with full context.

## Logging

- Use the standard library `logging` module.
- Create loggers at module level: `log = logging.getLogger(__name__)`.
- Never create/instantiate loggers inside classes or functions.
- Keep log messages concise and actionable.
- Never log secrets, credentials, or raw tokens.
- Use appropriate log levels:
  - `debug`: internal flow details useful only during development.
  - `info`: progress milestones (start/finish of major operations, counts).
  - `warning`: degraded but recoverable situations.
  - `error`: failures that skip items or degrade results.
- Avoid excessive status-only logging ("Starting...", "Finished...").

## Type Hints

- Use PEP 604 union syntax: `str | None` instead of `Optional[str]`.
- Use `from __future__ import annotations` for forward references.
- Type all function signatures (parameters and return types).
- Use `list[str]`, `dict[str, int]` (lowercase) instead of `List[str]`, `Dict[str, int]`.

## Docstrings

- Use a one-line docstring for simple functions and `__init__` methods.
- Use multi-line Google-style docstrings for complex public functions:
  ```python
  def process(path: Path, limit: int = 0) -> list[dict]:
      """Process KID PDFs and return structured chunks.

      Args:
          path: Directory containing PDF files.
          limit: Max files to process (0 = unlimited).

      Returns:
          List of chunk dicts with keys: id, section, text, metadata.
      """
  ```
- Do NOT mention "JSON format" in return descriptions for functions returning dicts (it's implicit).
- Do NOT document that functions can fail ("or error") — that's always possible.
- Mark optional parameters explicitly: `limit: Max files (optional, defaults to 0)`.

## Data Modeling

- Use `pydantic.BaseModel` with `Field` for structured data that needs validation or serialization.
- Use plain dicts for internal data passing between functions in the same module.
- Use `@dataclass` only for simple value objects that don't need validation.

## HTTP Clients

- Use `requests` for simple HTTP downloads (skill scripts).
- Use `httpx` for async or more complex HTTP patterns (future API clients).
- Always set explicit timeouts on HTTP calls.
- Always validate responses: check status codes, content type, response size.
- Implement retry logic with exponential backoff for transient failures.
- Use rate-limiting delays between requests to external services.

## Code Organization

- Application code lives in `src/kid_mind/` (standard src layout, importable package).
- Skill scripts live in `.claude/skills/<skill>/scripts/`.
- Run application modules via: `uv run python -m kid_mind.<module>`.
- Define constants at the top of each module (paths, URLs, settings).
- Use `argparse` for CLI interfaces; follow the existing pattern (`-p`/`--provider`, `-m`/`--max`).
- Use lazy initialization for expensive resources (ML models, converters).
- Data outputs go under `data/`.

## Ruff Linter

**Configuration** lives in `pyproject.toml` under `[tool.ruff]`. Always check it before running.

```bash
# Check for linting errors (all project code)
uv run ruff check src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/

# Auto-fix where possible
uv run ruff check src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/ --fix

# Format code
uv run ruff format src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/

# Verify no errors remain
uv run ruff check src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/
```

## Good vs Bad Practices

**Good:**
- Use `from __future__ import annotations` in every module.
- Expressive variable/function names that make code self-documenting.
- Small, focused functions with single responsibility.
- Fail fast on invalid input; validate at system boundaries.
- Lazy-load heavy dependencies (ML models, Docling converters).
- Reuse client instances and expensive objects (initialize once, use many times).
- Filter empty/None values from dicts before storage: `{k: v for k, v in d.items() if v}`.
- Use `Path` objects for file paths, not strings.

**Bad:**
- Broad `try/except` blocks that suppress exceptions or hide root causes.
- Inline comments instead of improving code readability.
- Adding comments to code you didn't change or that is already clear.
- Excessive logging ("Starting...", "Finished...", status-only messages).
- Embedding credentials or secrets in code or logs.
- Using `os.path` when `pathlib.Path` is available.
- Adding type annotations, docstrings, or refactoring to code you didn't modify.
- Over-engineering: feature flags, backwards-compatibility shims, or abstractions for one-time operations.

## Pre-Push Checklist

Before pushing code:

1. **Ruff lint**: `uv run ruff check src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/ --fix`
2. **Ruff format**: `uv run ruff format src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/`
3. **Verify**: `uv run ruff check src/ tests/ chunk_kids_cli.py .claude/skills/kid-collector/scripts/` (no errors)
4. **Tests**: `uv run python -m pytest tests/ -v`
5. **Imports**: Verify no unused imports remain
6. **Docs**: Update `CLAUDE.md` and `AGENTS.md` if project structure or conventions changed
