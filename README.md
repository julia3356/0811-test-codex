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
    - Bracket range: `--row [2,10]` (inclusive)

Notes
- The `-f/--format` options are: `terminal`, `csv`, `xlsx`.
- The input must be an `.xlsx` file; non-`.xlsx` inputs are rejected.
 - Terminal output supports `--pretty` for indented JSON.
 - CSV/XLSX default to compact JSON for structured fields (single-line, no indentation). Use `--pretty-json` to output pretty, multi-line JSON in cells/fields. `--compact-json` is also available but enabled by default.
 - Column order in CSV/XLSX preserves the `[out]` group/field order from config.

## WF Batch Runner (Python)
批量读取 Excel/CSV，逐行调用工作流接口，并把结果写回 Excel/CSV。

- 模块：`src/wf_batch_runner/cli.py`
- 依赖：`pandas`, `requests`, `openpyxl`

用法
- 基本（固定列导出，保持向后兼容）：
  - `.venv/bin/python -m src.wf_batch_runner.cli -i input.xlsx -o out.xlsx --token app-xxxx`
  - 也支持 CSV：`-i data.csv -o result.csv`

- 终端友好输出（逐行跑时镜像关键字段）：
  - 加 `--tee 1`

- 控制是否美化输出：
  - `--pretty 1|0`（默认 1）。美化包括：
    - Markdown 包裹的 JSON 自动提取 + 缩进
    - 常见转义字符（\n、\t、\r、\"、\\）人类可读化

- 配置驱动导出列（推荐）：
  - 通过 `--config assets/mapping.json` 指定 JSON 配置，描述如何从响应主体中选择字段并映射为输出列。
  - 根对象结构：
    ```json
    {
      "task_id": "...",
      "workflow_run_id": "...",
      "data": {
        "workflow_id": "...",
        "status": "succeeded",
        "outputs": { /* 工作流节点返回 */ }
      },
      "error": null
    }
    ```

配置文件格式（JSON）
```json
{
  "request": {
    "inputs": {
      "input": { "from": "input" },
      "check": { "from": "check", "as": "json_string" },
      "meta": { "const": "batch" }
    },
    "user": { "from": "user", "default": "cli-runner" },
    "response_mode": { "const": "blocking" }
  },
  "base": "data.outputs",
  "include_all": false,
  "columns": [
    { "name": "llm_out", "path": "llm_out" },
    { "name": "judge.schema_ok", "path": "llm_judge.schema_ok" },
    { "name": "judge.score", "path": "llm_judge.score" },
    { "name": "raw_error", "path": "$.error" }
  ]
}
```

说明
- `path` 以 `$.` 开头：从根对象取值；否则相对 `base`。
- 当 `include_all: true` 时，会将 `base` 下嵌套对象扁平化为点号连接的列名并附加到结果（不会覆盖 `columns` 已定义列）。
- 当 `include_all: true` 与 `columns` 同时使用时，若某个 `base` 下的键已通过 `columns` 指定了映射（例如 `{ "name": "V-0922", "path": "output_1" }`），则自动展开时会跳过该键，避免在输出中同时出现自定义列名与原始键名（如同时出现 `V-0922` 与 `output_1`）。
- 不提供 `--config` 时，导出默认固定列（兼容旧版本）。
- `request`：将输入文件的列映射到 Dify 请求的 `inputs`、`user` 与 `response_mode`。
  - `inputs` 值支持：
    - 字符串：视为列名；
    - 对象：`{"from": "col", "as": "json|json_string|string"}` 或 `{"const": any}`；
    - `json` 会解析单元格为 JSON 结构；`json_string` 会将其序列化为紧凑 JSON 字符串；
  - `user` 支持字符串列名或对象定义（同上），为空时回退 `cli-runner`；
  - `response_mode` 可设为 `blocking` 或 `streaming`（字符串），或对象定义。

示例
- 示例文件：`assets/mapping.json`
- 执行：
  - `.venv/bin/python -m src.wf_batch_runner.cli -i tests/data/sample.xlsx -o output/batch.xlsx --token app-xxxx --config assets/mapping.json --pretty 1`

输出
- `-o/--out` 指定的 Excel/CSV 文件，列顺序遵循配置中的 `columns`，若有 `include_all: true` 则追加自动展开列。

调试模式（Debug）增强
- 仅打印将要发送的请求，不实际调用：`--debug 1`
- 指定行调试：`--row N`（1-based，仅处理该行；未指定时默认第 1 行）
- 自动打印可直接复制的 `curl` 命令（包含真实 Token），格式示例：
  ```bash
  curl -X POST 'http://localhost/v1/workflows/run' \
    -H 'Authorization: Bearer app-xxxx' \
    -H 'Content-Type: application/json' \
    --data-binary @- <<'JSON'
  { ... 请求 JSON ... }
  JSON
  ```

容错与长批量优化（fast-append）
- 开启：`--fast-append 1`
- 行为：
  - 若发现 `-o` 文件已存在，则跳过已包含的行数，从未处理行继续；
  - 写入策略：
    - CSV：逐行追加（首行写表头），每行请求成功后立即写入，然后再发起下一次请求；
    - Excel（.xlsx/.xls）：为保证正确性，采用“合并既有数据并重写”的方式（每行仍会立即落盘），性能略低于 CSV；
  - Debug 模式下（`--debug 1`）不写入输出文件。
- 局限：
  - 若使用 `include_all: true`（自动展开动态列），fast-append 模式以“既有表头或首行产生的表头”为准，后续行出现的新列会被忽略（不会新增到表头）。如需完整列集合，建议关闭 fast-append 或固定列集合。

去重示例（含 include_all）
```jsonc
{
  "request": { /* 省略 */ },
  "base": "data.outputs",
  "include_all": true,
  "columns": [
    { "name": "V-0922", "path": "output_1" }
  ]
}
```
说明：当响应中存在 `data.outputs.output_1` 时，输出表只包含列 `V-0922`，其值取自 `output_1`；不会再额外生成名为 `output_1` 的列。

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
