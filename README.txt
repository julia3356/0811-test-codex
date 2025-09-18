Excel 字段映射转换工具（uv 使用说明）

本工具从当前目录（.）读取配置与 Excel 文件，按映射与输出模板转换为终端、CSV 或 XLSX。

运行目录
- 在仓库根目录执行所有命令：`/home/work/coding-space`
- 默认从当前目录读取配置文件 `./config.conf` 与输入文件 `./*.xlsx`
- 可使用相对路径将输入/输出放在任意子目录

环境准备（uv）
- 安装并选择 Python 版本（可按需修改版本）：
  - `uv python install 3.11`

- 依赖安装（两种方式，二选一）
  1) 当前仓库暂无 `pyproject.toml`（使用 requirements.txt）
     - `uv pip install -r requirements.txt`
  2) 若后续改为 uv 项目管理（推荐）
     - `uv init`（如需创建项目元数据）
     - `uv add openpyxl`
     - `uv sync`

执行命令（从 . 目录读取文件）
- 终端打印（默认）：
  - `uv run python -m src.excel_transformer.cli ./tests/data/sample.xlsx -c ./config.conf`

- 输出 CSV（需指定输出路径）：
  - `uv run python -m src.excel_transformer.cli ./tests/data/sample.xlsx -c ./config.conf -f csv -o ./out.csv`

- 输出 XLSX（需指定输出路径）：
  - `uv run python -m src.excel_transformer.cli ./tests/data/sample.xlsx -c ./config.conf -f xlsx -o ./out.xlsx`

- 常用参数：
  - 指定工作表：`-s Sheet1`
  - 指定表头所在行：`--header-row 1`（默认 1）
  - 仅处理单行：`--row 2`（数据行，从 1 开始，不含表头）
  - 处理多行：`--rows 1,3,5-10`
  - 终端美化 JSON：`--pretty`
  - CSV/XLSX 默认为紧凑 JSON（结构字段单行、无缩进）；如需多行美化可加：`--pretty-json`

示例数据与配置
- 生成示例 Excel：
  - `uv run python scripts/generate_sample_xlsx.py`
  - 将在 `./tests/data/sample.xlsx` 生成样例

- 示例配置：`scripts/example_config.conf`
  - 复制到项目根目录使用：`cp scripts/example_config.conf ./config.conf`

依赖与文件放置建议
- `./config.conf`：配置文件，包含 [map] 与 [out] 段，默认从当前目录读取
- 输入文件：放在当前目录或子目录，例如 `./tests/data/sample.xlsx`
- 输出文件：建议放到 `./out/` 或当前目录，命令中通过 `-o` 指定

测试与质量（可选）
- 运行测试：
  - `uvx pytest -q`（需要网络以临时获取 pytest）
  - 或：`uv pip install pytest && uv run pytest -q`

常见问题
- 提示缺少 openpyxl：
  - `uv add openpyxl`（使用 uv 项目管理时）或 `uv pip install openpyxl`
- 找不到模块 `excel_transformer`：
  - 确认在仓库根目录运行，且使用模块方式：`python -m src.excel_transformer.cli`
