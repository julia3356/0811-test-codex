# Repository Guidelines

## Project Structure & Module Organization
- `src/` application code (packages or modules per feature).
- `tests/` unit/integration tests mirroring `src/` paths.
- `scripts/` utility scripts for CI and local dev.
- `assets/` (or `public/`) static files, schemas, sample data.
- `.github/workflows/` CI pipelines; keep jobs fast and deterministic.

Example:
```
/ src/feature_a/...
/ tests/feature_a/test_scenarios.py
/ scripts/dev/seed.sh
```

## Build, Test, and Development Commands
- Build: `make build` (add a Makefile target); for Node use `npm run build`, for Python packaging use `python -m build`.
- Test: `pytest -q` (Python) or `npm test` (JS/TS). Enable coverage: `pytest --cov=src` or `npm test -- --coverage`.
- Run locally: `make dev` (hot reload) or stack-specific (`npm run dev`, `python -m src.app`). Document app entry in README.

## Coding Style & Naming Conventions
- Indentation: 2 spaces (JS/TS), 4 spaces (Python).
- Names: snake_case (files/functions Python), camelCase (JS vars), PascalCase (classes), kebab-case (CLI, folders where applicable).
- Formatters/Linters: Prettier + ESLint (JS/TS), Black + Ruff (Python). Example: `ruff check . && black --check .` or `npm run lint && npm run fmt:check`.

## Testing Guidelines
- Frameworks: pytest (Python), Jest/Vitest (JS/TS).
- Test files: `tests/<module>/test_*.py` or `**/*.test.ts`.
- Coverage: target ≥ 90% for changed code. Fail CI on drops; upload reports as artifacts.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
- PRs: clear description, linked issue, reproduction/steps, screenshots for UI, and tests for new logic. Keep PRs focused (< ~300 LOC net where feasible).
- CI must pass; include migration notes and rollback steps when relevant.

## Security & Configuration
- Never commit secrets. Use `.env` (ignored) and provide `.env.example`.
- Validate inputs at boundaries; add schema checks for external data.
- Restrict dependencies; pin versions and run `npm audit` / `pip-audit` in CI.

## Agent-Specific Instructions
- Prefer small, targeted patches; don’t modify unrelated files.
- Use `rg` to search, keep diffs minimal, and mirror `src/`→`tests/` structure.
- When adding tools/config, document commands in README and wire into CI.

