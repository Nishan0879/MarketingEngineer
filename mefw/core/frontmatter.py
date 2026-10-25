"""Markdown files with TOML front matter between `+++` lines.

Used for records a person reads and edits (experiment briefs, message drafts)
that also carry fields the code relies on.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def _dump_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_dump_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # JSON string escapes are valid TOML basic strings


def dump(meta: dict, body: str) -> str:
    lines = ["+++"] + [f"{k} = {_dump_value(v)}" for k, v in meta.items() if v is not None] + ["+++", ""]
    return "\n".join(lines) + body.lstrip("\n")


def load(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n", text, re.S)
    if not m:
        raise ValueError(f"{path.name} has no +++ front matter")
    return tomllib.loads(m.group(1)), text[m.end():]
