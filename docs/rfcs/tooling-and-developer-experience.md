# RFC: Tooling and Developer Experience

Status: Proposed

Problem
- Consistent lint/format/typecheck workflows and pre-commit hooks reduce churn. Docs should specify the toolchain and commands, using `.venv`.

Evidence
- `pyproject.toml`, `requirements[-dev].txt`, and `Makefile` exist; exact lint/format/type settings not centralized in docs.

Options
1. Adopt ruff+black+mypy+isort; configure via `pyproject.toml`; add pre-commit.
2. Provide standard IDE settings and Make targets.

Recommendation
- Adopt (1) and (2). Document commands and ensure CI parity.

Impact
- Faster feedback and fewer style diffs.

Effort
- S.

Risks
- None.

Acceptance Criteria
- Docs list commands, pre-commit setup, and IDE guidance; CI runs the same tools.


