# AGENTS

This repository accepts limited automated edits from trusted agents. The rules below are short and designed to minimize surprise for human maintainers.

Short contract for agents:

- **No littering**: NEVER create files at the repository root. Follow the strict organization rules below.
- Readability: Keep edits small and focused. If you must change >3 files, add a brief `docs/CHANGELOG.md` entry and update `docs/README.md` describing the changes.
- Docs: Put long-form documentation under `docs/` (see `docs/README.md`) and prefer `git mv` for renames. Preserve relative links inside moved files.
- Tests & Validation: If you change runnable code, run the project's tests or a quick smoke run where possible and include the result in your commit message.
- No secrets: Never add secrets, tokens, or credentials to the repository. If a secret is required, note the required env var in a `.env.example` update.
- Backwards compatible: Avoid breaking public APIs. If a change is large and may break things, create a draft PR and describe the migration steps in `docs/README.md`.
- Transparency: For any multi-file change add a one-paragraph summary to `docs/README.md` describing what moved/was added and how to verify.

If you are human: Follow these rules too; they make reviews faster and safer.

## File Organization Rules (MANDATORY)

The repository root must remain clean. **Only these files are allowed at root:**
- `README.md`, `AGENTS.md` (documentation)
- Configuration files: `.env.example`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, `requirements*.txt`
- Package metadata: `LICENSE`, `setup.py` (if needed)

**All other files MUST go in their proper directory:**

### Documentation (`docs/`)
- **Feature docs** → `docs/features/`
- **Implementation plans** → `docs/plans/`
- **Phase reports** → `docs/phases/`
- **Guides & tutorials** → `docs/guides/`
- **Bug fixes & patches** → `docs/fixes/`
- **Historical notes** → `docs/history/`
- **Overview docs** → `docs/overview/`

### Scripts (`scripts/`)
- **Database migrations** → `scripts/migrations/`
- **Diagnostic tools** → `scripts/diagnostics/`
- **Integration tests** → `scripts/tests/`
- **Verification scripts** → `scripts/verification/`
- **Deprecated code** → `scripts/deprecated/`
- **Utility scripts** → `scripts/` (root level if general purpose)

### Application Code (`app/`)
- All Python application code lives under `app/`
- Never create `.py` files at repository root (except `setup.py` if needed for packaging)

### Tests (`tests/`)
- Unit tests → `tests/unit/`
- Integration tests → `tests/integration/`

**Enforcement**: Before creating any file, ask yourself: "Is this a root-level config file?" If not, it belongs in a subdirectory. Check `scripts/README.md` and `docs/README.md` for the organization structure.

## Suggested moves

**Note**: Repository cleanup completed on 2025-10-08. The root directory is now clean with only essential files remaining. All documentation is in `docs/`, all scripts are in `scripts/`, and all application code is in `app/`.

**Historical context**: On 2025-10-02 a large reorganization moved many top-level Markdown docs into `docs/`. On 2025-10-08, all remaining scripts and utilities were organized into `scripts/` subdirectories. See `docs/CHANGELOG.md` for the full history.

If you need to create new files:

1. **Never create files at repository root** - use the organization rules above
2. Use `git mv <src> <dest>` if moving existing files (preserves history)
3. Add a one-line entry in `docs/README.md` or `docs/CHANGELOG.md` 
4. Add a verification command (e.g., `grep -r "keyword" newdir/`)
5. Run the project's quick sanity checks when possible

If you cannot run tests (no runtime available), still add the changelog entry and a short note explaining why tests were skipped.
