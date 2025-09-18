import argparse
from pathlib import Path
from typing import List, Optional

from .config import load_config
import json
import ast
from .transform import (
    print_terminal,
    transform_rows,
    transform_rows_grouped,
    write_csv,
    write_xlsx,
)


def _split_top_level_commas(s: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in s:
        if ch == ',' and depth == 0:
            part = ''.join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        buf.append(ch)
    last = ''.join(buf).strip()
    if last:
        parts.append(last)
    return parts


def _parse_rows_arg(rows: Optional[str]) -> Optional[List[int]]:
    if not rows:
        return None
    result: List[int] = []
    s = rows.strip()
    # Split by top-level commas, so bracketed sections remain intact
    parts = _split_top_level_commas(s)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Bracket sub-expression: [a,b] range or explicit list
        if part.startswith("[") and part.endswith("]"):
            try:
                arr = json.loads(part)
            except Exception:
                arr = ast.literal_eval(part)
            if isinstance(arr, list):
                if len(arr) == 2 and all(isinstance(x, int) for x in arr):
                    a, b = arr
                    lo, hi = (a, b) if a <= b else (b, a)
                    result.extend(list(range(lo, hi + 1)))
                    continue
                result.extend(int(x) for x in arr)
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
        type=str,
        help="处理一行或多行：可为单个数字，或使用逗号/区间（如 2,3,9 或 2-5,9）",
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
    parser.add_argument(
        "--compact-json",
        action="store_true",
        help="CSV/XLSX 输出时将结构字段写为紧凑 JSON（无缩进、单行）。默认已启用。",
    )
    parser.add_argument(
        "--pretty-json",
        action="store_true",
        help="CSV/XLSX 输出时使用美化 JSON（多行缩进）。将覆盖默认紧凑模式。",
    )
    parser.add_argument(
        "--grouped",
        action="store_true",
        help=(
            "按组聚合为列：每个 [out] 对象作为一列，单元格为该组 JSON；"
            "可在组对象顶层使用 '__label__' 指定列名，未指定时按顺序命名 group1/group2/..."
        ),
    )

    args = parser.parse_args(argv)

    # Ensure the input file is an Excel .xlsx file for reading
    if not str(args.excel).lower().endswith(".xlsx"):
        parser.error(f"输入文件必须为 .xlsx（Excel），收到：{args.excel}")

    cfg = load_config(args.config)
    row_numbers = None
    if args.row:
        row_numbers = _parse_rows_arg(args.row)
    elif args.rows:
        row_numbers = _parse_rows_arg(args.rows)

    # For file outputs (csv/xlsx), always use grouped shape to ensure
    # one cell per [out] object and columns defined by __label__.
    if args.format in {"csv", "xlsx"}:
        rows = transform_rows_grouped(
            excel_path=args.excel,
            display_to_internal=cfg.display_to_internal,
            out_groups=cfg.out_groups,
            sheet_name=args.sheet,
            header_row=args.header_row,
            row_numbers=row_numbers,
        )
    else:
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

        compact = True
        if args.pretty_json:
            compact = False
        elif args.compact_json:
            compact = True

        if args.format == "csv":
            write_csv(out_path, rows, compact_json=compact)
        else:
            write_xlsx(out_path, rows, compact_json=compact)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
