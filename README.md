# Coding Space

A minimal starter repository scaffold for iterative development. Use this as a clean base to add application code under `src/`, tests under `tests/`, and automation via `scripts/` and CI workflows.

## Project Structure
- `src/` application modules and entry points
- `tests/` unit/integration tests mirroring `src/`
- `scripts/` automation (setup, lint, build, release)
- `assets/` static files, sample data, schemas
- `.github/workflows/` CI pipelines

Example
```
src/feature_a/
tests/feature_a/test_basic.py
scripts/dev/seed.sh
.github/workflows/ci.yml
.github/workflows/nightly-audit.yml
output/              # CLI 默认输出目录（运行后生成）
```

## Quickstart
- Clone: `git clone <repo> && cd coding-space`
- Choose your stack and install deps:
  - Node: `npm install`
  - Python: `python -m venv .venv && source .venv/bin/activate && pip install -U pip`
- Run (pick what matches your stack):
  - Node: `npm run dev` or `npm run build && npm start`
- Python: `python -m src.app` (after creating `src/app.py`)
- Optional Make targets: `make build`, `make test`, `make lint`, `make fmt`, `make fmt-check`.

## Excel Transformer (Python)
This repo includes a small Excel-to-structured-output CLI under `src/excel_transformer`.

- Generate sample Excel for local testing:
  - `.venv/bin/python scripts/generate_sample_xlsx.py`

- Basic usage (terminal output):
  - `.venv/bin/python -m src.excel_transformer.cli tests/data/sample.xlsx -c scripts/example_config.conf -f terminal`
  - Pretty JSON: add `--pretty` to beautify terminal output
    - `.venv/bin/python -m src.excel_transformer.cli tests/data/sample.xlsx -c scripts/example_config.conf -f terminal --pretty`

- CSV/XLSX output to `./output/` directory (grouped by default):
  - Output directory is fixed to `./output/` (auto-created).
  - If `-o/--output` is omitted, the file name defaults to the input Excel file name with the correct extension.
  - Examples:
    - CSV with default name: `.venv/bin/python -m src.excel_transformer.cli tests/data/sample.xlsx -c scripts/example_config.conf -f csv`
      - Produces `output/sample.csv`
    - CSV with custom name: `.venv/bin/python -m src.excel_transformer.cli tests/data/sample.xlsx -c scripts/example_config.conf -f csv -o result.csv`
      - Produces `output/result.csv`
    - XLSX with name without extension: `.venv/bin/python -m src.excel_transformer.cli tests/data/sample.xlsx -c scripts/example_config.conf -f xlsx -o result`
      - Produces `output/result.xlsx`
  - Grouped columns (default):
    - Each `[out]` object becomes one column; the cell value is that group's JSON (compact by default)
    - Column names come only from `"__label__"` in each group; if missing, auto `group1/group2/...`
    - One source row -> one output row. Fields inside a group are not expanded into multiple columns.
  - Row selection
    - Single row: `--row 2`
    - Multiple rows: `--row 2,3,9` or ranges `--row 2-5,9`

Notes
- The `-f/--format` options are: `terminal`, `csv`, `xlsx`.
- The input must be an `.xlsx` file; non-`.xlsx` inputs are rejected.
 - Terminal output supports `--pretty` for indented JSON.
 - CSV/XLSX default to compact JSON for structured fields (single-line, no indentation). Use `--pretty-json` to output pretty, multi-line JSON in cells/fields. `--compact-json` is also available but enabled by default.
 - Column order in CSV/XLSX preserves the `[out]` group/field order from config.

## Testing
- JavaScript/TypeScript: `npm test` (coverage: `npm test -- --coverage`)
- Python: `pytest -q` (coverage: `pytest --cov=src`)
- Place tests under `tests/<module>/...` or `**/*.test.ts` and keep them fast, isolated, and deterministic.

## Commands
- `make test` runs tests with coverage.
- `make lint` runs Ruff for static checks.
- `make fmt` formats code with Black.
- `make fmt-check` verifies formatting without changing files.
- `make build` builds a source and wheel distribution via `python -m build`.

## Git via SSH
- Check remote: `git remote -v`
- Set SSH remote: `git remote set-url origin git@github.com:<user>/<repo>.git`
- Test SSH auth: `ssh -T git@github.com` (ensure your SSH key is added to GitHub)
- Push: `git push origin <branch>`

## Pre-commit Hooks
- Install tooling: `pip install -e .[dev] && pip install pre-commit` (or just dev extras)
- Install hooks: `pre-commit install`
- Run on all files once: `pre-commit run --all-files`
- Commit bypass (not recommended): `git commit -m "msg" --no-verify`

Hooks configured
- Ruff (with auto-fix)
- Black
- Pytest (runs quick test suite)

## Diff Coverage Gate
- CI enforces diff coverage ≥ 80% vs `origin/main` and fails below the threshold.
- Local reproduction:
  - `pytest --cov=src --cov-report=xml -q`
  - `diff-cover coverage.xml --compare-branch origin/main --fail-under 80`

## CI & Reports
- Workflows
  - `CI` (push/PR to `main`/`master`): runs tests with coverage and publishes non-blocking reports.
  - `Nightly Security Audit`: daily pip-audit; also triggerable via workflow dispatch.
- Coverage (diff-based)
  - Generates `coverage.xml` and a diff coverage report comparing to `origin/main`.
  - Artifact: `diff-cover` (file: `diff-cover.txt`). Not blocking merges.
- Dependency security audit
  - PR/Push: runs only when `pyproject.toml`, `requirements.txt`, or `uv.lock` change; non-blocking.
  - Nightly: always runs, non-blocking.
  - Artifacts: `pip-audit` (PR/Push) and `nightly-pip-audit` (Nightly), each containing `pip-audit.json`.
- Local reproduction
  - Tests with coverage: `pytest --cov=src --cov-report=xml -q`
  - Diff coverage (requires `diff-cover`): `diff-cover coverage.xml --compare-branch origin/main > diff-cover.txt`

## Contributing
- Read the contributor guide in `AGENTS.md` for style, tooling, commit/PR rules, and security practices.
- Prefer small, focused PRs with clear descriptions and tests for new behavior.

## License
Specify a license (e.g., MIT) in `LICENSE`.
