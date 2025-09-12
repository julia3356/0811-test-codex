from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from openpyxl import load_workbook, Workbook


def _build_internal_to_display(mapper: Mapping[str, str]) -> Dict[str, str]:
    return {v: k for k, v in mapper.items()}


def _coerce_literal(val: Any) -> Any:
    # Try to coerce strings that look like numbers
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            try:
                return int(s)
            except Exception:
                return val
        try:
            return float(s)
        except Exception:
            return val
    return val


def _eval_condition(expr: str, context: Mapping[str, Any]) -> bool:
    # Very small evaluator supporting comparisons like a==b, a!=b, a>b, etc.
    ops = ["==", "!=", ">=", "<=", ">", "<"]
    for op in ops:
        if op in expr:
            left, right = expr.split(op, 1)
            left, right = left.strip(), right.strip()
            lv = context.get(left)
            rv: Any
            # Strip quotes around right if present
            if (right.startswith("'") and right.endswith("'")) or (
                right.startswith('"') and right.endswith('"')
            ):
                rv = right[1:-1]
            else:
                rv = _coerce_literal(right)
            lv = _coerce_literal(lv)
            try:
                if op == "==":
                    return lv == rv
                if op == "!=":
                    return lv != rv
                if op == ">=":
                    return lv >= rv  # type: ignore[operator]
                if op == "<=":
                    return lv <= rv  # type: ignore[operator]
                if op == ">":
                    return lv > rv  # type: ignore[operator]
                if op == "<":
                    return lv < rv  # type: ignore[operator]
            except Exception:
                return False
    # Fallback: unknown expression -> False
    return False


def _cell_value_by_display(headers: List[str], row_values: List[Any], display_name: str) -> Any:
    try:
        idx = headers.index(display_name)
    except ValueError:
        return ""
    if idx < 0 or idx >= len(row_values):
        return ""
    return row_values[idx]


def _value_by_internal(
    headers: List[str], row_values: List[Any], internal_to_display: Mapping[str, str], internal_key: str
) -> Any:
    display = internal_to_display.get(internal_key)
    if not display:
        return ""
    return _cell_value_by_display(headers, row_values, display)


def _resolve_field(
    field_key: str,
    spec: Any,
    headers: List[str],
    row_values: List[Any],
    internal_to_display: Mapping[str, str],
    context_by_internal: Mapping[str, Any],
) -> Tuple[str, Any]:
    """Resolve one field of an out-group.

    - If spec is a string: treat it as output key, and take value from the column named by field_key.
    - If spec is an object with {name, value, ex?}: compute value with optional conditional override.
    """
    # Case 1: direct mapping
    if isinstance(spec, str):
        output_key = spec
        value = _cell_value_by_display(headers, row_values, field_key)
        return output_key, value

    if isinstance(spec, dict):
        name = spec.get("name")
        value_ref = spec.get("value")
        ex = spec.get("ex")
        # Evaluate ex condition to override value_ref
        if ex:
            # normalize to list of one rule or many
            rules = ex if isinstance(ex, list) else [ex]
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                condition = rule.get("if")
                if condition and _eval_condition(str(condition), context_by_internal):
                    # Prefer explicit 'value' in rule; else accept a key matching name
                    override = rule.get("value")
                    if not override and name:
                        override = rule.get(name)
                    if override:
                        value_ref = override
                        break
        # Pull the value from the row by internal key reference
        output_key = name if name else str(field_key)
        if isinstance(value_ref, str):
            value = _value_by_internal(headers, row_values, internal_to_display, value_ref)
        else:
            value = value_ref
        return output_key, value

    # Fallback: emit as string
    return str(field_key), str(spec)


def transform_rows(
    excel_path: str,
    display_to_internal: Mapping[str, str],
    out_groups: Sequence[Mapping[str, Any]],
    sheet_name: Optional[str] = None,
    header_row: int = 1,
    row_numbers: Optional[Sequence[int]] = None,  # 1-based, excluding header row
) -> List[Dict[str, Any]]:
    """Transform rows according to config into a list of output dicts.

    For each source row, each out-group produces one output record.
    """
    wb = load_workbook(excel_path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    # Read headers from header_row
    headers: List[str] = []
    for cell in ws[header_row]:
        headers.append(str(cell.value) if cell.value is not None else "")

    internal_to_display = _build_internal_to_display(display_to_internal)

    results: List[Dict[str, Any]] = []

    # Build iterable of row indices to process (1-based including header in ws indexing)
    start_row_idx = header_row + 1
    end_row_idx = ws.max_row
    indices = range(start_row_idx, end_row_idx + 1)
    if row_numbers:
        # Convert to worksheet row indexes
        indices = [header_row + n for n in row_numbers]

    for r in indices:
        row_cells = ws[r]
        row_values = [c.value for c in row_cells]
        # Context by internal keys for condition evaluation
        context = {internal: _value_by_internal(headers, row_values, internal_to_display, internal)
                   for internal in internal_to_display.keys()}

        for group in out_groups:
            out: Dict[str, Any] = {}
            for key, spec in group.items():
                out_key, out_val = _resolve_field(
                    field_key=str(key),
                    spec=spec,
                    headers=headers,
                    row_values=row_values,
                    internal_to_display=internal_to_display,
                    context_by_internal=context,
                )
                out[out_key] = out_val
            results.append(out)

    return results


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    import csv

    # Union of keys preserves insertion but we will sort for stability
    fieldnames: List[str] = sorted({k for r in rows for k in r.keys()})
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def write_xlsx(path: str, rows: List[Dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "output"
    headers = sorted({k for r in rows for k in r.keys()})
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    wb.save(path)


def print_terminal(rows: List[Dict[str, Any]]) -> None:
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))

