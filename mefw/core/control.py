"""Kill switch (Section 11.3).

The operator can pause a whole client, one engine, or one agent. State lives in
control/pause.json so it can be flipped by hand, from the CLI, or by the runner
itself when an agent keeps failing. The runner checks it before every action.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import Paused

SCOPES = ("client", "engine", "agent")


def _empty() -> dict:
    return {"client": None, "engines": {}, "agents": {}}


class Control:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return _empty()
        try:
            data = json.loads(self.path.read_text() or "{}")
        except json.JSONDecodeError:
            # A corrupt control file must fail closed: treat everything as paused.
            return {"client": {"reason": "control/pause.json is unreadable", "by": "system"},
                    "engines": {}, "agents": {}}
        base = _empty()
        base.update(data)
        return base

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.path)

    def pause(self, scope: str, name: str | None, reason: str, by: str) -> None:
        data = self.load()
        flag = {"reason": reason, "by": by,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if scope == "client":
            data["client"] = flag
        elif scope == "engine":
            data["engines"][name] = flag
        elif scope == "agent":
            data["agents"][name] = flag
        else:
            raise ValueError(f"scope must be one of {SCOPES}")
        self._save(data)

    def resume(self, scope: str, name: str | None) -> None:
        data = self.load()
        if scope == "client":
            data["client"] = None
        elif scope == "engine":
            data["engines"].pop(name, None)
        elif scope == "agent":
            data["agents"].pop(name, None)
        else:
            raise ValueError(f"scope must be one of {SCOPES}")
        self._save(data)

    def check(self, engine: str, agent: str) -> None:
        """Raise Paused if the client, this engine or this agent is paused."""
        data = self.load()
        for label, flag in (
            ("client", data.get("client")),
            (f"engine '{engine}'", data["engines"].get(engine)),
            (f"agent '{agent}'", data["agents"].get(agent)),
        ):
            if flag:
                raise Paused(f"{label} is paused by {flag.get('by')}: {flag.get('reason')}")
