# src/wf_batch_runner/cli.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wf_batch_runner.cli
批量读取 Excel/CSV，逐行调用工作流接口，并把结果写回 Excel/CSV。
- 支持 --tee 将结果也友好地打印到终端（每列一行，便于人工快速查看）。
- 自动检测输入/输出文件类型（.xlsx/.xls/.csv）。
- 输入至少包含：input, check 两列；可选 user 列；列名可用参数重定义。
- check 列为原始 JSON 时会解析并序列化为“JSON 字符串”提交（满足你提到的转义要求）。
- 返回 llm_out/llm_judge 若为 Markdown 包裹的 JSON，会自动提取并美化。
"""
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests


def _is_nan(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _read_table(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suf == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"仅支持 .xlsx/.xls/.csv，当前：{path}")


def _write_table(df: pd.DataFrame, path: Path) -> None:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xls"):
        df.to_excel(path, index=False)
    elif suf == ".csv":
        df.to_csv(path, index=False)
    else:
        raise ValueError(f"输出仅支持 .xlsx/.xls/.csv，当前：{path}")


def _try_parse_json_maybe_markdown(text: str) -> Tuple[Optional[Any], Optional[str]]:
    """尝试把“Markdown 包裹的 JSON”提取为对象并美化；失败则返回原文"""
    if text is None:
        return None, None
    s = str(text).strip()

    # 直接当 JSON
    try:
        obj = json.loads(s)
        return obj, json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 提取 { ... }
    m = re.search(r"\{.*\}", s, flags=re.S | re.M)
    if m:
        inner = m.group(0)
        try:
            obj = json.loads(inner)
            return obj, json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return None, s


def _ensure_check_as_json_string(val: Any) -> str:
    """
    确保提交 payload 中的 inputs.check 为“JSON 字符串”。
    - 表中可能是 dict/list/JSON文本/普通文本；尽量解析为紧凑 JSON 字符串，否则按原文本提交。
    """
    if _is_nan(val):
        return ""

    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))

    s = str(val).strip()
    if s.startswith("{") or s.startswith("["):
        try:
            obj = json.loads(s)
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return s
    return s


def _pretty_json(val: Any) -> str:
    try:
        return json.dumps(val, ensure_ascii=False, indent=2)
    except Exception:
        return str(val)


def _get_row_value(row: pd.Series, col: Any) -> Any:
    """健壮地从行中取列值：
    - 优先精确匹配列名；
    - 其次尝试去除首尾空白后的列名；
    - 再次尝试不区分大小写 + 去空白匹配；
    找不到则返回 None。
    """
    if not isinstance(row, pd.Series):
        return None
    try:
        # 精确匹配
        if col in row.index:
            return row[col]
        # 去空白匹配
        col_s = str(col).strip()
        if col_s in row.index:
            return row[col_s]
        # 不区分大小写 + 去空白
        norm = {str(k).strip().lower(): k for k in row.index}
        key = col_s.lower()
        if key in norm:
            return row[norm[key]]
    except Exception:
        return None
    return None


@dataclass
class RunResult:
    task_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    workflow_id: Optional[str] = None
    status: Optional[str] = None
    llm_out: Optional[str] = None
    llm_judge: Optional[str] = None
    judge_usage: Optional[str] = None
    check_out: Optional[str] = None
    session: Optional[str] = None
    error: Optional[str] = None
    # ↓↓↓ 新增：从 llm_judge 结构中拆出的字段
    llm_judge_schema_ok: Optional[str] = None
    llm_judge_score: Optional[str] = None
    llm_judge_scores: Optional[str] = None
    llm_judge_diagnostics: Optional[str] = None
    # 原始 outputs 结构，供后续按配置抽取
    outputs_raw: Optional[Dict[str, Any]] = None

def _mask_token(tok: str, head: int = 6, tail: int = 4) -> str:
    """Mask token for logs: keep head and tail, mask middle.
    - If token is too short, keep first/last char and mask the middle.
    """
    if not tok:
        return ""
    t = str(tok)
    if len(t) <= head + tail:
        if len(t) <= 2:
            return t if len(t) <= 1 else (t[0] + "*")
        return t[0] + ("*" * (len(t) - 2)) + t[-1]
    return t[:head] + "..." + t[-tail:]


def _call_api(
    url: str,
    token: str,
    inputs_payload: Dict[str, Any],
    user_val: str,
    timeout: float,
    response_mode: str,
    pretty: bool,
    debug: bool = False,
) -> RunResult:
    # 规范化 token：兼容传入已含有前缀的情况（如 "Bearer xxx"）
    raw_token = (token or "").strip()
    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()

    headers = {"Authorization": f"Bearer {raw_token}", "Content-Type": "application/json"}
    payload = {
        "inputs": inputs_payload,
        "response_mode": response_mode or "blocking",
        "user": user_val or "cli-runner",
    }
    # 调试模式：打印请求预览与可直接执行的 curl 命令，不实际发起网络调用
    if debug:
        safe_token = _mask_token(raw_token)
        dbg_headers = {**headers, "Authorization": f"Bearer {safe_token}"}
        print("[DEBUG] Dify request preview:")
        print(f"URL: {url}")
        print(f"Headers: {json.dumps(dbg_headers, ensure_ascii=False)}")
        print("Body:")
        payload_pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        print(payload_pretty)
        # 直接可用的 curl 命令（使用真实 Token）
        print("\n[DEBUG] cURL（可直接复制执行）:")
        print(f"curl -X POST '{url}' \")
        print(f"  -H 'Authorization: Bearer {raw_token}' \")
        print("  -H 'Content-Type: application/json' \")
        print("  --data-binary @- <<'JSON'")
        print(payload_pretty)
        print("JSON")
        return RunResult(status="debug", outputs_raw={})
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return RunResult(error=f"HTTP error: {e}")
    except ValueError as e:
        return RunResult(error=f"Invalid JSON response: {e}")

    task_id = data.get("task_id")
    workflow_run_id = data.get("workflow_run_id")
    d = data.get("data") or {}
    status = d.get("status")
    workflow_id = d.get("workflow_id")

    if status != "succeeded":
        err_msg = d.get("error") or data.get("error") or f"status={status}"
        return RunResult(task_id=task_id, workflow_run_id=workflow_run_id, workflow_id=workflow_id, status=status, error=_pretty_json(err_msg))

    outputs = d.get("outputs") or {}
    if pretty:
        _, llm_out_pretty = _try_parse_json_maybe_markdown(outputs.get("llm_out", ""))
        llm_judge_obj, llm_judge_pretty = _try_parse_json_maybe_markdown(outputs.get("llm_judge", ""))
    else:
        llm_out_pretty = "" if outputs.get("llm_out") is None else str(outputs.get("llm_out"))
        lj = outputs.get("llm_judge")
        llm_judge_pretty = "" if lj is None else (json.dumps(lj, ensure_ascii=False, separators=(",", ":")) if isinstance(lj, (dict, list)) else str(lj))
        llm_judge_obj = lj if isinstance(lj, dict) else None

    schema_ok = score = scores_val = diagnostics_val = None
    if isinstance(llm_judge_obj, dict):
        schema_ok = llm_judge_obj.get("schema_ok")
        score = llm_judge_obj.get("score")
        scores_val = llm_judge_obj.get("scores")
        diagnostics_val = llm_judge_obj.get("diagnostics")

    schema_ok_s = "" if schema_ok is None else str(schema_ok)
    score_s = "" if score is None else str(score)
    scores_s = "" if scores_val is None else _pretty_json(scores_val)
    diagnostics_s = "" if diagnostics_val is None else _pretty_json(diagnostics_val)

    return RunResult(
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        workflow_id=workflow_id,
        status=status,
        llm_out=llm_out_pretty,
        llm_judge=llm_judge_pretty,
        judge_usage=(
            _pretty_json(outputs.get("judge_usage"))
            if pretty and outputs.get("judge_usage") is not None
            else (
                json.dumps(outputs.get("judge_usage"), ensure_ascii=False, separators=(",", ":"))
                if outputs.get("judge_usage") is not None and isinstance(outputs.get("judge_usage"), (dict, list))
                else ("" if outputs.get("judge_usage") is None else str(outputs.get("judge_usage")))
            )
        ),
        check_out=(
            _pretty_json(outputs.get("check"))
            if pretty and outputs.get("check") is not None
            else (
                json.dumps(outputs.get("check"), ensure_ascii=False, separators=(",", ":"))
                if outputs.get("check") is not None and isinstance(outputs.get("check"), (dict, list))
                else ("" if outputs.get("check") is None else str(outputs.get("check")))
            )
        ),
        session=(
            _pretty_json(outputs.get("session"))
            if pretty and outputs.get("session") is not None
            else (
                json.dumps(outputs.get("session"), ensure_ascii=False, separators=(",", ":"))
                if outputs.get("session") is not None and isinstance(outputs.get("session"), (dict, list))
                else ("" if outputs.get("session") is None else str(outputs.get("session")))
            )
        ),
        # ↓↓↓ 新增
        llm_judge_schema_ok=schema_ok_s,
        llm_judge_score=score_s,
        llm_judge_scores=scores_s,
        llm_judge_diagnostics=diagnostics_s,
        outputs_raw=outputs,
    )


def _tee_print(res: RunResult) -> None:
    mapping = [
        ("task_id", res.task_id),
        ("workflow_run_id", res.workflow_run_id),
        #("data.workflow_id", res.workflow_id),
        ("data.status", res.status),
        ("error", res.error),
        ("data.outputs.llm_out", res.llm_out),
        #("data.outputs.llm_judge", res.llm_judge),
        #("data.outputs.judge_usage", res.judge_usage),
        #("data.outputs.check", res.check_out),
        #("data.outputs.session", res.session),
        # ↓↓↓ 新增：按要求在 error 之后
        ("llm_judge.schema_ok", res.llm_judge_schema_ok),
        ("llm_judge.score", res.llm_judge_score),
        ("llm_judge.scores", res.llm_judge_scores),
        ("llm_judge.diagnostics", res.llm_judge_diagnostics),
    ]
    for k, v in mapping:
        print(f"{k}:\n{'' if v is None else v}\n")
    print("-" * 60)


def _load_json_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _get_by_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten_dict(v, key))
        else:
            out[key] = v
    return out


def _render_value(val: Any, pretty: bool) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, indent=2) if pretty else json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    s = str(val)
    if not pretty:
        return s
    # 尝试将 JSON 字符串美化
    try:
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            obj = json.loads(s)
            return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        pass
    # 处理常见转义序列
    s = s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").replace("\\\"", '"').replace("\\\\", "\\")
    return s


def _resolve_value_from_spec(spec: Any, row: pd.Series) -> Any:
    """根据 spec 与行记录解析一个值。
    支持：
    - 字符串：视为列名，返回对应单元格值（优先保持原始 dict/list），否则字符串
    - 对象：
        {"const": any} 固定常量
        {"from": "col", "as": "json|json_string|string"}
    """
    if isinstance(spec, dict):
        if "const" in spec:
            return spec.get("const")
        if "from" in spec:
            col = spec["from"]
            val = _get_row_value(row, col)
            if _is_nan(val):
                return spec.get("default", "")
            cast = spec.get("as")
            if cast == "json":
                if isinstance(val, (dict, list)):
                    return val
                s = str(val).strip()
                try:
                    return json.loads(s)
                except Exception:
                    return spec.get("default", s)
            if cast == "json_string":
                vs = _ensure_check_as_json_string(val)
                return spec.get("default", "") if vs == "" else vs
            # 默认 string
            if isinstance(val, (dict, list)):
                # 未指定 as 时，保留结构
                return val
            s = "" if val is None else str(val)
            return spec.get("default", "") if s == "" else s
        return None
    # 字符串列名
    if isinstance(spec, str):
        val = _get_row_value(row, spec)
        if _is_nan(val):
            return ""
        return val if isinstance(val, (dict, list)) else str(val)
    return spec


def _build_request_from_config(
    row: pd.Series,
    args: argparse.Namespace,
    conf: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str, str]:
    """从配置或参数构造 Dify 请求体中的 inputs 与 user、response_mode。
    返回: (inputs_payload, user_val, response_mode)
    """
    response_mode = "blocking"
    # 无配置：按旧逻辑
    if not conf or not isinstance(conf.get("request"), dict):
        input_text = "" if _is_nan(row.get(args.input_col)) else str(row.get(args.input_col))
        check_str = _ensure_check_as_json_string(row.get(args.check_col))
        user_val = "cli-runner"
        if args.user_col in row and not _is_nan(row.get(args.user_col)):
            user_val = str(row.get(args.user_col))
        return {"input": input_text, "check": check_str}, user_val, response_mode

    req = conf["request"]
    inputs_payload: Dict[str, Any] = {}

    # inputs 映射
    inputs_map = req.get("inputs", {})
    if isinstance(inputs_map, dict):
        for name, spec in inputs_map.items():
            inputs_payload[name] = _resolve_value_from_spec(spec, row)

    # user
    user_spec = req.get("user")
    if user_spec is None:
        # 退回到参数列
        if args.user_col in row and not _is_nan(row.get(args.user_col)):
            user_val = str(row.get(args.user_col))
        else:
            user_val = "cli-runner"
    else:
        # 支持 {from/const}
        if isinstance(user_spec, dict) or isinstance(user_spec, str):
            v = _resolve_value_from_spec(user_spec, row)
            user_val = "cli-runner" if v in (None, "") else str(v)
        else:
            user_val = "cli-runner"

    # response_mode 可选
    rm_spec = req.get("response_mode")
    if rm_spec is not None:
        if isinstance(rm_spec, dict) or isinstance(rm_spec, str):
            v = _resolve_value_from_spec(rm_spec, row)
            if isinstance(v, str) and v:
                response_mode = v
        elif isinstance(rm_spec, bool):
            response_mode = "streaming" if rm_spec else "blocking"

    return inputs_payload, user_val, response_mode


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="批量运行工作流并导出结果（Excel/CSV）")
    ap.add_argument("-i", "--in", dest="inp", required=True, help="输入 Excel/CSV 路径")
    ap.add_argument("-o", "--out", dest="outp", required=True, help="输出 Excel/CSV 路径（扩展名决定格式）")
    ap.add_argument("--url", default="http://localhost/v1/workflows/run", help="接口地址")
    ap.add_argument("--token", required=True, help="Bearer Token（如 app-xxxxxx）")
    ap.add_argument("--input-col", default="input", help="输入文本列名（默认 input）")
    ap.add_argument("--check-col", default="check", help="检查 JSON 列名（默认 check）")
    ap.add_argument("--user-col", default="user", help="用户列名（默认缺省为 cli-runner）")
    ap.add_argument("--timeout", type=float, default=180.0, help="HTTP 超时时间（秒，默认 180）")
    ap.add_argument("--max-rows", type=int, default=0, help="仅处理前 N 行（0=全部）")
    ap.add_argument("--tee", type=int, default=0, help="同时人类友好格式输出到终端（1 开启）")
    ap.add_argument("--config", type=str, default=None, help="JSON 配置文件，描述 outputs 的列映射")
    ap.add_argument("--pretty", type=int, default=1, help="是否美化输出（1=是，0=否）")
    ap.add_argument("--debug", type=int, default=0, help="调试模式：仅打印将发送的 Dify 请求，不实际调用，且忽略 -o 文件写入（1 开启）")
    ap.add_argument("--row", type=int, default=0, help="调试模式下指定行号（从 1 开始，仅处理该行）")
    ap.add_argument("--fast-append", type=int, default=0, help="容错与长批量优化：检测已存在的输出并跳过已处理行；CSV 采用逐行追加，Excel 采用合并重写（1 开启）")

    args = ap.parse_args(argv)

    in_path = Path(args.inp).expanduser().resolve()
    out_path = Path(args.outp).expanduser().resolve()
    df = _read_table(in_path)

    conf: Optional[Dict[str, Any]] = None
    if args.config:
        conf = _load_json_config(Path(args.config).expanduser().resolve())

    # 列检查：若未提供 request 配置，使用旧的固定列检查
    if not (conf and isinstance(conf.get("request"), dict)):
        for col in [args.input_col, args.check_col]:
            if col not in df.columns:
                raise KeyError(f"输入表缺少必须列: {col}")
    # user 列是否存在仅用于无配置时的回退逻辑，此处保留检查在 _build_request_from_config 内部完成

    results: List[Dict[str, Any]] = []
    total = len(df)
    limit = total if args.max_rows <= 0 else min(args.max_rows, total)

    use_fast = bool(args.fast_append)
    debug_mode = bool(args.debug)

    # fast-append 模式的断点续跑准备
    processed_count = 0
    out_columns: Optional[List[str]] = None
    prev_out_df: Optional[pd.DataFrame] = None
    warned_extra_cols = False
    if use_fast and not debug_mode:
        if out_path.exists():
            try:
                prev_out_df = _read_table(out_path)
                processed_count = len(prev_out_df)
                out_columns = list(prev_out_df.columns)
                if processed_count > 0:
                    print(f"↻ 检测到已存在输出，跳过前 {processed_count} 行并续跑……")
            except Exception as e:
                print(f"⚠️ fast-append 读取既有输出失败，将从头开始：{e}")
                prev_out_df = None
                processed_count = 0
                out_columns = None

    start_idx = processed_count if use_fast else 0
    # Debug 模式仅执行一行，支持 --row 指定（1-based）
    if debug_mode:
        target_idx = 0
        if args.row and args.row > 0:
            if args.row > total:
                print(f"❌ --row 超出范围：{args.row} > 总行数 {total}")
                return
            target_idx = args.row - 1
        else:
            print("ℹ️ Debug 未指定 --row，默认处理第 1 行。")
        start_idx = target_idx
        limit = target_idx + 1
    if start_idx >= limit:
        if not debug_mode:
            print(f"✅ 已完成：现有输出包含 {processed_count} 行（>= 目标 {limit} 行），无需继续。")
        return

    for idx in range(start_idx, limit):
        row = df.iloc[idx]
        inputs_payload, user_val, response_mode = _build_request_from_config(row, args, conf)

        # 将 response_mode 注入 _call_api 的 payload（通过 payload 默认 blocking；此处覆盖 headers/inputs）
        # 为避免修改 _call_api 签名过多，这里复用 _call_api 并在其内使用默认 blocking，后续如需 streaming 可扩展。
        # 目前兼容：若配置中指定了非 blocking，仅通过 payload.response_mode 传递即可。

        res = _call_api(
            args.url,
            args.token,
            inputs_payload,
            user_val,
            args.timeout,
            response_mode,
            bool(args.pretty),
            bool(args.debug),
        )
        if args.tee == 1:
            _tee_print(res)
        if conf:
            # 组合一个根对象，便于路径解析
            root_obj: Dict[str, Any] = {
                "task_id": res.task_id,
                "workflow_run_id": res.workflow_run_id,
                "data": {
                    "workflow_id": res.workflow_id,
                    "status": res.status,
                    "outputs": res.outputs_raw or {},
                },
                "error": res.error,
            }

            base = conf.get("base") or "data.outputs"
            include_all = bool(conf.get("include_all", False))
            cols_cfg = conf.get("columns") or []
            # 记录在 base 下已通过 columns 明确映射的相对路径（避免 include_all 重复添加同一路径为列名）
            mapped_under_base: set[str] = set()

            row_out: Dict[str, Any] = {
                "task_id": res.task_id or "",
                "workflow_run_id": res.workflow_run_id or "",
                "data.workflow_id": res.workflow_id or "",
                "data.status": res.status or "",
                "error": res.error or "",
            }

            # 配置列
            for col in cols_cfg:
                name = col.get("name")
                path = col.get("path")
                if not name or not path:
                    continue
                if path.startswith("$."):
                    v = _get_by_path(root_obj, path[2:])
                else:
                    rel = path if base == "" else f"{base}.{path}"
                    v = _get_by_path(root_obj, rel)
                    # 仅记录 base 下的相对路径 key（与 include_all 的扁平 key 一致）
                    mapped_under_base.add(path)
                row_out[name] = _render_value(v, bool(args.pretty))

            # 自动展开 outputs
            if include_all:
                base_obj = _get_by_path(root_obj, base)
                if isinstance(base_obj, dict):
                    flat = _flatten_dict(base_obj)
                    for k, v in flat.items():
                        # 不覆盖已配置列；且跳过已通过 columns 指定过的 base 相对路径
                        if k not in row_out and k not in mapped_under_base:
                            row_out[k] = _render_value(v, bool(args.pretty))

            if use_fast and not debug_mode:
                suf = out_path.suffix.lower()
                # 确定输出列：优先沿用既有文件列；否则以当前行的键顺序为列
                if out_columns is None:
                    out_columns = list(row_out.keys())

                # 处理潜在的“新列”（include_all 导致的动态列）
                if not warned_extra_cols:
                    extra = [k for k in row_out.keys() if k not in out_columns]
                    if extra:
                        print(f"⚠️ fast-append: 检测到未在表头中的新列，将被忽略：{', '.join(extra)}")
                        warned_extra_cols = True

                row_df = pd.DataFrame([{k: row_out.get(k, "") for k in out_columns}], columns=out_columns)
                if suf == ".csv":
                    # CSV：逐行追加（首行写表头）
                    mode = "a" if processed_count > 0 else "w"
                    header = False if processed_count > 0 else True
                    row_df.to_csv(out_path, mode=mode, header=header, index=False)
                    processed_count += 1
                else:
                    # Excel：合并既有数据并重写（保持容错与正确性）。
                    if prev_out_df is None:
                        prev_out_df = pd.DataFrame(columns=out_columns)
                    prev_out_df = pd.concat([prev_out_df, row_df], ignore_index=True)
                    _write_table(prev_out_df, out_path)
                    processed_count += 1
            else:
                results.append(row_out)
                # 增量写出：根据“当前已收集的结果”生成 DataFrame 并落盘
                if not debug_mode:
                    all_keys: List[str] = []
                    for r in results:
                        for k in r.keys():
                            if k not in all_keys:
                                all_keys.append(k)
                    _write_table(pd.DataFrame(results, columns=all_keys), out_path)
        else:
            # 兼容原有固定列
            row_fixed = {
                "task_id": res.task_id or "",
                "workflow_run_id": res.workflow_run_id or "",
                "data.workflow_id": res.workflow_id or "",
                "data.status": res.status or "",
                "data.outputs.llm_out": res.llm_out or "",
                "data.outputs.llm_judge": res.llm_judge or "",
                "data.outputs.judge_usage": res.judge_usage or "",
                "data.outputs.check": res.check_out or "",
                "data.outputs.session": res.session or "",
                "error": res.error or "",
                "llm_judge.schema_ok": res.llm_judge_schema_ok or "",
                "llm_judge.score": res.llm_judge_score or "",
                "llm_judge.scores": res.llm_judge_scores or "",
                "llm_judge.diagnostics": res.llm_judge_diagnostics or "",
            }
            # 增量写出：固定列顺序
            fixed_cols = [
                "task_id",
                "workflow_run_id",
                "data.workflow_id",
                "data.status",
                "data.outputs.llm_out",
                "data.outputs.llm_judge",
                "data.outputs.judge_usage",
                "data.outputs.check",
                "data.outputs.session",
                "error",
                "llm_judge.schema_ok",
                "llm_judge.score",
                "llm_judge.scores",
                "llm_judge.diagnostics",
            ]
            if use_fast and not debug_mode:
                suf = out_path.suffix.lower()
                # 既有列沿用；若不存在则使用固定列
                if out_columns is None:
                    out_columns = list(fixed_cols)
                row_df = pd.DataFrame([{k: row_fixed.get(k, "") for k in out_columns}], columns=out_columns)
                if suf == ".csv":
                    mode = "a" if processed_count > 0 else "w"
                    header = False if processed_count > 0 else True
                    row_df.to_csv(out_path, mode=mode, header=header, index=False)
                    processed_count += 1
                else:
                    if prev_out_df is None:
                        prev_out_df = pd.DataFrame(columns=out_columns)
                    prev_out_df = pd.concat([prev_out_df, row_df], ignore_index=True)
                    _write_table(prev_out_df, out_path)
                    processed_count += 1
            else:
                results.append(row_fixed)
                if not debug_mode:
                    _write_table(pd.DataFrame(results, columns=fixed_cols), out_path)

    # 调试模式：不写入输出文件，直接返回
    if debug_mode:
        print("ℹ️ Debug 模式：已打印请求预览，忽略 -o 输出写入。")
        return

    # 最终提示（非 debug 下，此时文件已在循环中逐步写出）
    if not debug_mode:
        print(f"✅ 完成：输出写入 {out_path}")


if __name__ == "__main__":
    main()
