"""Claude Code skills for the operator: slash commands such as /mefw-today that run the CLI for you.

The skills ship in `mefw/claude_skills/`. `install` copies them into a `.claude/skills/` folder, either a client
workspace's (Claude Code picks them up when it's opened there) or the operator's own `~/.claude/skills/`.
Only folders named `mefw-*` are ours, so other skills in the same folder are never touched.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

PREFIX = "mefw-"


def shipped() -> dict[str, str]:
    """Each shipped skill's name and its SKILL.md text."""
    out = {}
    for d in sorted(resources.files("mefw").joinpath("claude_skills").iterdir(), key=lambda p: p.name):
        if d.is_dir() and d.name.startswith(PREFIX):
            out[d.name] = d.joinpath("SKILL.md").read_text()
    return out


def description(text: str) -> str:
    for line in text.splitlines()[1:]:
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
        if line.strip() == "---":
            break
    return ""


def install(dest: Path) -> list[tuple[str, str]]:
    """Write every shipped skill into dest (a `.claude/skills` folder). Returns (name, new|updated|unchanged|removed).

    A `mefw-*` skill that's no longer shipped is removed, so a renamed skill doesn't linger.
    """
    dest.mkdir(parents=True, exist_ok=True)
    skills = shipped()
    result = []
    for name, text in skills.items():
        path = dest / name / "SKILL.md"
        if not path.exists():
            state = "new"
        elif path.read_text() == text:
            state = "unchanged"
        else:
            state = "updated"
        if state != "unchanged":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        result.append((name, state))
    for old in sorted(dest.glob(f"{PREFIX}*")):
        if old.is_dir() and old.name not in skills:
            shutil.rmtree(old)
            result.append((old.name, "removed"))
    return result
