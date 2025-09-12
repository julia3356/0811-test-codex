import sys
from pathlib import Path

import openpyxl

# Ensure repo root is on sys.path so `import src.excel_transformer.cli` works
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.excel_transformer.cli import main as cli_main  # noqa: E402


def _write_sample_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["原始记录", "计分", "原始记录-问题", "问题的积分", "标准回答", "猜测回答"])
    ws.append(["记录A", 1, "问题A", 5, "标准答A", "猜测答A"])
    ws.append(["记录B", 2, "问题B", 8, "标准答B", "猜测答B"])
    ws.append(["记录C", 3, "问题C", 2, "标准答C", "猜测答C"])
    wb.save(str(path))


def test_default_output_names_csv_and_xlsx(tmp_path, monkeypatch):
    # Arrange: create sample workbook under tmp dir
    excel_path = tmp_path / "sample.xlsx"
    _write_sample_xlsx(excel_path)

    # Use example config from repo
    cfg_path = REPO_ROOT / "scripts" / "example_config.conf"

    # Act: run in tmp cwd so outputs go to tmp_path/output
    monkeypatch.chdir(tmp_path)

    # CSV with default name (no -o)
    rc_csv = cli_main([str(excel_path), "-c", str(cfg_path), "-f", "csv"])
    assert rc_csv == 0
    assert (tmp_path / "output" / "sample.csv").exists()

    # XLSX with default name (no -o)
    rc_xlsx = cli_main([str(excel_path), "-c", str(cfg_path), "-f", "xlsx"]) 
    assert rc_xlsx == 0
    assert (tmp_path / "output" / "sample.xlsx").exists()


def test_custom_output_name_extension_completion(tmp_path, monkeypatch):
    excel_path = tmp_path / "sample.xlsx"
    _write_sample_xlsx(excel_path)
    cfg_path = REPO_ROOT / "scripts" / "example_config.conf"

    monkeypatch.chdir(tmp_path)

    # Provide name without extension; should complete to .xlsx
    rc = cli_main([str(excel_path), "-c", str(cfg_path), "-f", "xlsx", "-o", "result"])
    assert rc == 0
    assert (tmp_path / "output" / "result.xlsx").exists()

