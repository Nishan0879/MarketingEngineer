"""Approved facts (Section 11.4, rule 1): the only business information an agent may claim.

Facts live in profile/approved-facts.toml, one table per fact:

    [facts.membership_price]
    text = "Hot desk membership is $250 a month."
    segments = ["members"]          # optional; omit for all segments
    approved_by = "Owner name"
    approved_on = "2026-10-20"
    expires_on = "2027-01-31"       # optional; an expired fact can't be used

Agents refer to facts by key. A fact without approval details, or past its
expiry date, doesn't count.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date

from .workspace import Workspace

FACTS_PATH = "profile/approved-facts.toml"


@dataclass
class Fact:
    key: str
    text: str
    approved_by: str
    approved_on: str
    expires_on: str | None = None
    segments: list[str] = field(default_factory=list)

    def problem(self, today: date, segment: str | None = None) -> str | None:
        """Why this fact can't be used right now, or None if it can."""
        if not self.text.strip():
            return f"fact '{self.key}' has no text"
        if not (self.approved_by and self.approved_on):
            return f"fact '{self.key}' has no approval recorded"
        if self.expires_on and date.fromisoformat(self.expires_on) < today:
            return f"fact '{self.key}' expired on {self.expires_on}"
        if segment and self.segments and segment not in self.segments:
            return f"fact '{self.key}' isn't approved for segment '{segment}'"
        return None


def load_facts(ws: Workspace) -> dict[str, Fact]:
    path = ws.path(FACTS_PATH)
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text()).get("facts", {})
    return {
        key: Fact(key=key, text=str(f.get("text", "")), approved_by=str(f.get("approved_by", "")),
                  approved_on=str(f.get("approved_on", "")),
                  expires_on=str(f["expires_on"]) if f.get("expires_on") else None,
                  segments=list(f.get("segments", [])))
        for key, f in raw.items()
    }
