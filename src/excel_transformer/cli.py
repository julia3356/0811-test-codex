import argparse
from pathlib import Path
from typing import List, Optional

from .config import load_config
from .transform import print_terminal, transform_rows, write_csv, write_xlsx


def _parse_rows_arg(rows: Optional[str]) -> Optional[List[int]]:
    if not rows:
        return None
    result: List[int] = []
    for part in rows.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            result.extend(list(range(start, end + 1)))
        else:
            result.append(int(part))
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="excel-transform",
        description=(
            "根据 config.conf 的字段映射与输出模板，读取 Excel 并输出为 终端/CSV/XLSX。"
        ),
    )
    parser.add_argument("excel", help="输入 Excel 文件路径 (.xlsx)")
    parser.add_argument(
        "-c", "--config", default="config.conf", help="配置文件路径，默认 config.conf"
    )
    parser.add_argument("-s", "--sheet", default=None, help="工作表名，默认第一个")
    parser.add_argument(
        "--header-row", type=int, default=1, help="表头所在行（从1开始），默认1"
    )
    parser.add_argument(
        "--row",
        type=int,
        help="只处理指定行（数据行号，从1开始，不含表头）",
    )
    parser.add_argument(
        "--rows",
        type=str,
        help="处理多行，逗号分隔或区间，如 1,3,5-10（不含表头）",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="输出文件名（固定写入 ./output/ 目录；若未提供且选择 csv/xlsx，将使用输入文件名并补全扩展名）",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["terminal", "csv", "xlsx"],
        default="terminal",
        help="输出格式：terminal/csv/xlsx，默认 terminal",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="终端输出时美化 JSON（缩进显示）",
    )

    args = parser.parse_args(argv)

    # Ensure the input file is an Excel .xlsx file for reading
    if not str(args.excel).lower().endswith(".xlsx"):
        parser.error(f"输入文件必须为 .xlsx（Excel），收到：{args.excel}")

    cfg = load_config(args.config)
    row_numbers = None
    if args.row is not None:
        row_numbers = [int(args.row)]
    elif args.rows:
        row_numbers = _parse_rows_arg(args.rows)

    rows = transform_rows(
        excel_path=args.excel,
        display_to_internal=cfg.display_to_internal,
        out_groups=cfg.out_groups,
        sheet_name=args.sheet,
        header_row=args.header_row,
        row_numbers=row_numbers,
    )

    if args.format == "terminal":
        print_terminal(rows, pretty=args.pretty)
    else:
        out_dir = Path("./output")
        out_dir.mkdir(parents=True, exist_ok=True)

        # Decide output name: prefer provided name; else derive from input excel name
        if args.output:
            name = Path(args.output).name
        else:
            base = Path(args.excel).stem
            name = base
        if args.format == "csv" and not name.lower().endswith(".csv"):
            name = f"{name}.csv"
        if args.format == "xlsx" and not name.lower().endswith(".xlsx"):
            name = f"{name}.xlsx"
        out_path = str(out_dir / name)

        if args.format == "csv":
            write_csv(out_path, rows)
        else:
            write_xlsx(out_path, rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
