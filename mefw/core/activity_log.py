"""Append-only, hash-chained activity log (Sections 8.1 and 11.6).

Every entry carries the hash of the entry before it, so editing or deleting
history breaks the chain and `verify()` reports where. The writer only ever
opens the file in append mode, and takes an exclusive lock so two agents can't
interleave writes.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import LogTampered

GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ActivityLog:
    def __init__(self, path: Path, client_id: str):
        self.path = path
        self.client_id = client_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(
        self,
        agent: str,
        action: str,
        result: str,
        inputs: dict | None = None,
        output: dict | None = None,
    ) -> dict:
        with open(self.path, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                last = None
                for line in f:
                    if line.strip():
                        last = line
                prev = json.loads(last) if last else None
                entry = {
                    "seq": (prev["seq"] + 1) if prev else 1,
                    "ts": _now(),
                    "client": self.client_id,
                    "agent": agent,
                    "action": action,
                    "result": result,
                    "inputs": inputs or {},
                    "output": output or {},
                    "prev_hash": prev["hash"] if prev else GENESIS,
                }
                entry["hash"] = _hash(entry)
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return entry

    def entries(self) -> list[dict]:
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def verify(self) -> int:
        """Check the whole chain. Returns the entry count or raises LogTampered."""
        prev_hash, seq = GENESIS, 0
        for i, e in enumerate(self.entries(), start=1):
            if e.get("prev_hash") != prev_hash or e.get("seq") != seq + 1:
                raise LogTampered(f"Chain broken at line {i} (seq {e.get('seq')})")
            if _hash(e) != e.get("hash"):
                raise LogTampered(f"Entry at line {i} (seq {e.get('seq')}) was edited")
            if e.get("client") != self.client_id:
                raise LogTampered(f"Entry at line {i} belongs to another client")
            prev_hash, seq = e["hash"], e["seq"]
        return seq

    def render_markdown(self, out: Path) -> None:
        """Human-readable copy at logs/agent-activity.md. The JSONL is the record."""
        lines = [
            "# Agent activity",
            "",
            "Generated from `agent-activity.jsonl`; do not edit by hand.",
            "",
            "| # | Time (UTC) | Agent | Action | Result | Detail |",
            "|---|---|---|---|---|---|",
        ]
        for e in self.entries():
            detail = e["output"].get("summary") or e["output"].get("reason") or ""
            detail = str(detail).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {e['seq']} | {e['ts']} | {e['agent']} | {e['action']} | {e['result']} | {detail} |"
            )
        out.write_text("\n".join(lines) + "\n")
