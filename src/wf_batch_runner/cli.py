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
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "inputs": inputs_payload,
        "response_mode": response_mode or "blocking",
        "user": user_val or "cli-runner",
    }
    # 调试模式：仅打印将要发送的请求，不实际发起网络调用
    if debug:
        safe_token = "" if not token else (token[:6] + "..." + str(len(token)))
        dbg_headers = {**headers, "Authorization": f"Bearer {safe_token}"}
        print("[DEBUG] Dify request preview:")
        print(f"URL: {url}")
        print(f"Headers: {json.dumps(dbg_headers, ensure_ascii=False)}")
        print("Body:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
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
            val = None if col not in row else row[col]
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
        val = None if spec not in row else row[spec]
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

    for idx in range(limit):
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
                row_out[name] = _render_value(v, bool(args.pretty))

            # 自动展开 outputs
            if include_all:
                base_obj = _get_by_path(root_obj, base)
                if isinstance(base_obj, dict):
                    flat = _flatten_dict(base_obj)
                    for k, v in flat.items():
                        # 不覆盖已配置列
                        if k not in row_out:
                            row_out[k] = _render_value(v, bool(args.pretty))

            results.append(row_out)
        else:
            # 兼容原有固定列
            results.append({
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
            })

    # 调试模式：不写入输出文件，直接返回
    if bool(args.debug):
        print("ℹ️ Debug 模式：已打印请求预览，忽略 -o 输出写入。")
        return

    # 输出
    if conf:
        # 动态列：以第一行的键集合为主，后续缺失填空
        all_keys: List[str] = []
        for r in results:
            for k in r.keys():
                if k not in all_keys:
                    all_keys.append(k)
        out_df = pd.DataFrame(results, columns=all_keys)
    else:
        out_df = pd.DataFrame(results, columns=[
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
            # ↓↓↓ 新增：放在 error 后
            "llm_judge.schema_ok",
            "llm_judge.score",
            "llm_judge.scores",
            "llm_judge.diagnostics",
        ])
    _write_table(out_df, out_path)
    print(f"✅ 完成：输出写入 {out_path}")


if __name__ == "__main__":
    main()
