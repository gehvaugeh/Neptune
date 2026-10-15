"""
Minimal frontmatter parser/writer for Neptune notebook PTY bindings.

Only a small, closed subset of YAML is supported (nested maps + scalar values),
which is sufficient because Neptune itself is the only writer. If parsing fails
for any reason, `parse_frontmatter` returns `(None, text)` so that legacy
notebooks (no frontmatter) keep importing unchanged.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def parse_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Split an optional leading `---` frontmatter block from the document body.

    Returns `(parsed_or_None, body)`:
      * `parsed` is the parsed mapping (only when a `neptune:` key is present),
        otherwise `None`.
      * `body` is the remaining document (frontmatter stripped) — equal to
        `text` when there is no (valid) frontmatter.
    """
    if not text:
        return None, text

    lines = text.splitlines(keepends=True)

    # Frontmatter must start on the very first line.
    if not lines or lines[0].strip() != "---":
        return None, text

    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        return None, text

    header = "".join(lines[1:close_idx])
    body = "".join(lines[close_idx + 1:])

    try:
        parsed = _parse_yaml_subset(header)
    except Exception:
        return None, text

    if not isinstance(parsed, dict) or "neptune" not in parsed:
        return None, text

    return parsed, body


def _parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Parse a minimal YAML subset: nested mappings of scalars. No lists."""
    root: Dict[str, Any] = {}
    # Stack of (indent, dict)
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            # Not a mapping line — abort the whole parse for safety.
            raise FrontmatterParseError(f"unsupported line: {raw!r}")
        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()

        # Pop stacks deeper or equal than current indent.
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n")
        return inner
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


class FrontmatterParseError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def build_frontmatter(ptys: Dict[str, Any]) -> str:
    """
    Build the frontmatter block for a mapping of `name -> config`.

    Config shape:
      {'type': 'local'}
      {'type': 'remote', 'host': ..., 'user': ..., 'port': ..., 'key': ...}
    """
    if not ptys:
        return ""

    out = ["---", "neptune:", "  version: 1", "  ptys:"]
    for name in sorted(ptys.keys()):
        cfg = ptys.get(name) or {}
        out.append(f"    {name}:")
        ptype = cfg.get("type") or "local"
        out.append(f"      type: {ptype}")
        if ptype == "remote":
            for field in ("host", "user", "port", "key"):
                val = cfg.get(field)
                if val is not None and val != "":
                    out.append(f"      {field}: {_format_scalar(val)}")
    out.append("---")
    return "\n".join(out) + "\n"


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    # Quote when the value could be ambiguous for our parser.
    if text == "" or text.strip() != text or ":" in text or text[0] in ("'", '"', "#", "&", "*", "!", "|", ">", "%", "@", "`", "-", "?", "["):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def ptys_from_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract the `neptune.ptys` mapping from a parsed frontmatter dict."""
    if not isinstance(parsed, dict):
        return None
    neptune = parsed.get("neptune")
    if not isinstance(neptune, dict):
        return None
    ptys = neptune.get("ptys")
    return ptys if isinstance(ptys, dict) else None
