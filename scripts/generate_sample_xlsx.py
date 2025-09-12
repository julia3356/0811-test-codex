"""
Generate tests/data/sample.xlsx for local verification.
Requires: pip install openpyxl
"""
from pathlib import Path

from openpyxl import Workbook


def main() -> None:
    out_dir = Path("tests/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sample.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["原始记录", "计分", "原始记录-问题", "问题的积分", "标准回答", "猜测回答"])
    ws.append(["记录A", 1, "问题A", 5, "标准答A", "猜测答A"])
    ws.append(["记录B", 2, "问题B", 8, "标准答B", "猜测答B"])
    ws.append(["记录C", 3, "问题C", 2, "标准答C", "猜测答C"])
    wb.save(str(out_path))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

