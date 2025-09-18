import json
import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


COMMENT_RE = re.compile(r"//.*$")
TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_json_comments(s: str) -> str:
    """Remove // comments and trailing commas for JSON-like snippets."""
    # Remove line comments
    s = "\n".join(COMMENT_RE.sub("", line) for line in s.splitlines())
    # Remove trailing commas before } or ]
    while True:
        new_s = TRAILING_COMMA_RE.sub(r"\1", s)
        if new_s == s:
            break
        s = new_s
    return s


def _parse_multiple_json_objects(blob: str) -> List[Dict[str, Any]]:
    """Parse one or more top-level JSON objects concatenated in text.

    Extensions supported for [out]:
    - Optional label lines directly above an object, like:
        Label:
        { ... }
      This will be injected into the object as {"__label__": "Label", ...}.

    JSON may include // comments and trailing commas (handled earlier).
    """
    items: List[Dict[str, Any]] = []
    text = _strip_json_comments(blob)
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        # Find the next object start '{'
        if text[i] != "{":
            # Allow an optional single-line label ending with ':' before the object
            # Capture the line up to ':' and then expect '{' after optional whitespace/newline.
            # Move to the next non-space
            label_start = i
            # Read to line end
            while i < n and text[i] != '\n' and text[i] != '{':
                i += 1
            # If we stopped at '{' on same line, backtrack to find ':'
            line = text[label_start:i]
            label_val: str | None = None
            if ':' in line:
                # Take content before ':'
                label_candidate = line.split(':', 1)[0].strip()
                if label_candidate:
                    label_val = label_candidate
            # Now skip to next '{'
            while i < n and text[i] != '{':
                i += 1
            if i >= n:
                break
            # From here, i points to '{' and label_val holds an optional label
        # Parse JSON object from i (which is '{')
        depth = 0
        start = i
        i += 1
        while i < n:
            ch = text[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                if depth == 0:
                    i += 1
                    break
                depth -= 1
            elif ch in ('"', "'"):
                # Skip string contents safely for both double/single quoted strings
                quote = ch
                i += 1
                while i < n:
                    if text[i] == '\\':
                        i += 2
                        continue
                    if text[i] == quote:
                        i += 1
                        break
                    i += 1
                continue
            i += 1
        obj_raw = text[start:i]
        # Prefer JSON parsing; fallback to Python literal_eval to support single quotes
        try:
            obj = json.loads(obj_raw)
        except Exception:
            obj = ast.literal_eval(obj_raw)  # type: ignore[assignment]
        # Alias common typo: __lable__ -> __label__
        if isinstance(obj, dict) and "__lable__" in obj and "__label__" not in obj:
            obj["__label__"] = obj.get("__lable__")
        # Attempt to find a label on the immediate previous non-empty line
        # If not already injected by earlier step
        # Look backwards from start to previous line
        if '__label__' not in obj:
            j = start - 1
            # Skip whitespace backwards
            while j >= 0 and text[j].isspace():
                # stop at newline but keep going to find previous line start
                j -= 1
            # Find line start
            line_end = j
            while j >= 0 and text[j] != '\n':
                j -= 1
            line_start = j + 1
            prev_line = text[line_start:line_end + 1]
            pl = prev_line.strip()
            if pl.endswith(':') and pl[:-1].strip():
                obj['__label__'] = pl[:-1].strip()
        items.append(obj)
    return items


@dataclass
class Config:
    # Map from display column name (e.g., 中文列名) to internal key (e.g., "record")
    display_to_internal: Dict[str, str]
    # Out groups: each is a mapping that describes an output record
    out_groups: List[Dict[str, Any]]


def load_config(path: str) -> Config:
    """Load config.conf with sections [map] and [out].

    [map] contains one JSON object. [out] contains one or more JSON objects.
    JSON may include // comments and trailing commas.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split by sections
    section_re = re.compile(r"^\s*\[(map|out)\]\s*$", re.MULTILINE)
    sections: List[Tuple[str, int, int]] = []
    matches = list(section_re.finditer(content))
    for idx, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        sections.append((name, start, end))

    display_to_internal: Dict[str, str] = {}
    out_groups: List[Dict[str, Any]] = []

    for name, start, end in sections:
        blob = content[start:end].strip()
        if not blob:
            continue
        if name == "map":
            cleaned = _strip_json_comments(blob)
            try:
                j = json.loads(cleaned)
            except Exception:
                j = ast.literal_eval(cleaned)
            if not isinstance(j, dict):
                raise ValueError("[map] must be a single JSON object")
            display_to_internal = {str(k): str(v) for k, v in j.items()}
        elif name == "out":
            out_groups.extend(_parse_multiple_json_objects(blob))

    if not display_to_internal:
        raise ValueError("Missing or empty [map] section in config")
    if not out_groups:
        raise ValueError("Missing or empty [out] section in config")

    return Config(display_to_internal=display_to_internal, out_groups=out_groups)
