## Coding principles
These are intentionally opinionated to keep the codebase coherent.

- **Follow existing patterns over personal preference**
  - Mirror the style of similar tools already in the repo.
  - If you think a pattern should change, discuss it first instead of introducing inconsistencies.

- **Formatting & linting**
  - Use the repo’s configured tools (e.g., `black`, `isort`, `ruff`/`flake8`, `mypy`/`pyright`).
  - Do **not** change their configuration casually.
  - Code should be warning-free in the configured linter and type-checker.

- **Typing**
  - Use type hints everywhere (PEP 484/PEP 561 style).
  - Use duck typing whenever possible, following the patterns of the repo.
  - Avoid `Any` unless truly unavoidable; if used, keep it localized and documented.
  - Avoid `from __future__ import annotations`

- **Function and module size**
  - Aim for functions ≤ ~50 lines where feasible.
  - If a function starts doing multiple conceptual things, split it.
  - Keep modules focused; if a file grows unwieldy, break it into smaller modules within the same package.

- **Control flow & clarity**
  - Avoid deeply nested conditionals; prefer early returns and helper functions.
  - Avoid overly clever one-liners and deeply nested comprehensions.
  - Avoid code duplication. If you need to repeat the same logic in multiple places, extract a helper.

- **Error handling**
  - Don’t swallow exceptions silently.
  - Avoid bare `except:`; catch specific exception types.
  - If you must catch `Exception`, log/annotate and re-raise or wrap in a custom exception type.
  - Prefer raising explicit exceptions over returning sentinel values like `None`/`False` on failure.

- **I/O and side effects**
  - Use `pathlib.Path` instead of bare path strings where possible.
  - Keep filesystem and network I/O at the edges; keep core logic pure/side-effect-light when possible.
  - For concurrency:
    - Prefer `asyncio` where the rest of the codebase already does.
    - Otherwise, stick to synchronous code until there’s a demonstrated performance need.

- **Performance**
  - Measure before optimizing. Don’t prematurely introduce async, multiprocessing, or complex caching.
  - When performance matters:
    - Use streaming I/O for large files.
    - Avoid holding entire large datasets in memory if unnecessary.
    - Consider generators/iterators for pipelines.

- **Imports and dependencies**
  - Group imports (standard library, third-party, local) according to the repo’s formatting rules.
  - Avoid introducing heavy dependencies unless justified; prefer using existing shared utilities.
  - When solving for a helper/utility, check if the existing package `raccoontools` have something you can use: https://github.com/brenordv/pypi-raccoon-tools
  - If adding a new dependency:
    - Justify it in the PR.
    - Add it to the appropriate dependency file and lockfile.

- **Shared utilities**
  - Before writing a new helper, check `shared/` (and existing tools/agents) to see if something similar exists.
  - If you add something to `shared/`, keep it:
    - Generic
    - Small
    - Well-documented and tested

- **Style & docs**
  - Follow PEP 8 (plus the repo’s conventions).
  - Use docstrings for public functions/classes (consistent style: Google/NumPy/ReST, as used elsewhere in the repo).
  - Prefer clear, intention-revealing names over abbreviations.

## Testing
- **Test framework**
  - Use the existing test framework (likely `pytest`).
  - Don’t introduce a new framework without discussion.

- **Where tests go**
  - Mirror source layout:
    - `src/tools/cat/` → `tests/tools/test_cat.py` or `tests/tools/cat/test_*.py`
    - `src/ai_tools/agents/foo/` → `tests/ai_tools/agents/test_foo.py`
    - `src/shared/xyz.py` → `tests/shared/test_xyz.py`

- **What to test**
  - Happy paths (common usage scenarios).
  - Important edge cases, but within reason.
  - Error conditions where behavior is user-visible (e.g., invalid input, missing files).

- **How to test**
  - Keep tests fast and deterministic.
  - Use fixtures for expensive setups.
  - Prefer black-box tests at the tool/agent boundary; only test internals directly when it provides clear benefit.

- **CI**
  - Make sure tests pass locally before pushing.
  - If CI has additional steps (lint, type-check), run them locally when possible.

## Other

1. **YAGNI**
   - Don’t build abstractions or features until they’re needed.
   - Start simple; it’s easier to generalize later than to simplify something overengineered.

2. **Be nice**
   - Be respectful in issues, PRs, and code review.
   - Leave the code a little clearer than you found it.
   - When in doubt, add a short comment to help the next person.

3. **Ask questions**
   - If something in this document or in the codebase is unclear, open an issue or ask in the relevant channel.
   - Consistency and clarity are more important than being “right” in isolation.
