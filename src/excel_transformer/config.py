import json
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

    The text can contain whitespace between objects.
    """
    items: List[Dict[str, Any]] = []
    text = _strip_json_comments(blob).strip()
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] != "{":
            raise ValueError("Expected '{' starting a JSON object in [out] section")
        depth = 0
        start = i
        while i < n:
            ch = text[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif ch == '"':
                # Skip string contents safely
                i += 1
                while i < n:
                    if text[i] == '\\':
                        i += 2
                        continue
                    if text[i] == '"':
                        i += 1
                        break
                    i += 1
                continue
            i += 1
        obj_raw = text[start:i]
        obj = json.loads(obj_raw)
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
            j = json.loads(_strip_json_comments(blob))
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

