"""Lead and outcome ledger.

One SQLite file per client (data/ledger.db). Lead history is a list of events
that can be added to but never edited or deleted: SQLite triggers reject any
UPDATE or DELETE on `lead_events`, and the same holds for `action_keys`, which
the runner uses to make sure an action never runs twice.

Outcomes through Commit (Section 7) are events too: `won`, `lost` with a reason,
or `reopened`. The latest one wins.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .pii import scrub
from .workspace import FUNNEL

EVENT_KINDS = ("inquired", "touch_in", "touch_out", "stage", "outcome")
OUTCOMES = ("won", "lost", "reopened")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id     TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    source      TEXT NOT NULL,
    ref         TEXT NOT NULL,
    channel     TEXT,
    segment     TEXT,
    value       REAL,
    touches_out_reported INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lead_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     TEXT NOT NULL REFERENCES leads(lead_id),
    kind        TEXT NOT NULL,
    at          TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT '',
    value       TEXT NOT NULL DEFAULT '',
    detail      TEXT,
    source      TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (lead_id, kind, at, stage, value)
);
CREATE TABLE IF NOT EXISTS action_keys (
    key         TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    result      TEXT
);
CREATE TRIGGER IF NOT EXISTS lead_events_no_update BEFORE UPDATE ON lead_events
BEGIN SELECT RAISE(ABORT, 'lead_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS lead_events_no_delete BEFORE DELETE ON lead_events
BEGIN SELECT RAISE(ABORT, 'lead_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS action_keys_no_delete BEFORE DELETE ON action_keys
BEGIN SELECT RAISE(ABORT, 'action_keys is append-only'); END;
CREATE TRIGGER IF NOT EXISTS action_keys_finish_only BEFORE UPDATE ON action_keys
WHEN OLD.status != 'started'
BEGIN SELECT RAISE(ABORT, 'a finished action key cannot change'); END;
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_ts(value: str | None) -> datetime | None:
    """Parse ISO-ish timestamps from exports. Naive values are taken as UTC."""
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Unrecognized timestamp: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LeadState:
    """A lead's position as of a point in time, derived from its events."""

    lead_id: str
    ref: str
    source: str
    channel: str | None
    segment: str | None
    value: float | None
    inquired_at: datetime | None = None
    first_response_at: datetime | None = None
    last_in: datetime | None = None
    last_out: datetime | None = None
    touches_out: int = 0
    stages: dict[str, datetime] = field(default_factory=dict)
    outcome: str | None = None  # won | lost | None (open)
    outcome_at: datetime | None = None
    lost_reason: str | None = None

    @property
    def furthest_stage(self) -> str | None:
        reached = [s for s in FUNNEL if s in self.stages]
        return reached[-1] if reached else ("inquire" if self.inquired_at else None)

    @property
    def last_activity(self) -> datetime | None:
        times = [t for t in (self.inquired_at, self.last_in, self.last_out, *self.stages.values()) if t]
        return max(times) if times else None

    def reached(self, stage: str) -> bool:
        if self.outcome == "won" and FUNNEL.index(stage) <= FUNNEL.index("commit"):
            return True
        f = self.furthest_stage
        return f is not None and FUNNEL.index(f) >= FUNNEL.index(stage)


class Ledger:
    def __init__(self, path: Path, client_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client_id = client_id
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # Leads and events

    def upsert_lead(self, source: str, ref: str, channel=None, segment=None, value=None,
                    touches_out_reported: int | None = None) -> str:
        """Add a lead or refresh its attributes. touches_out_reported is the CRM's own
        count of outbound follow-ups, used when individual touches aren't exported."""
        lead_id = f"{source}:{ref}"
        self.db.execute(
            """INSERT INTO leads (lead_id, client_id, source, ref, channel, segment, value,
                                  touches_out_reported, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(lead_id) DO UPDATE SET
                 channel = COALESCE(excluded.channel, channel),
                 segment = COALESCE(excluded.segment, segment),
                 value   = COALESCE(excluded.value, value),
                 touches_out_reported = COALESCE(excluded.touches_out_reported, touches_out_reported)""",
            (lead_id, self.client_id, source, ref, channel, segment, value, touches_out_reported, now_iso()),
        )
        return lead_id

    def add_event(self, lead_id: str, kind: str, at: datetime, source: str,
                  stage: str = "", value: str = "", detail: str | None = None) -> bool:
        """Add an event. Returns False if the same event was already recorded."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"Unknown event kind {kind!r}")
        if kind == "stage" and stage not in FUNNEL:
            raise ValueError(f"Unknown funnel stage {stage!r}")
        if kind == "outcome" and value not in OUTCOMES:
            raise ValueError(f"Outcome must be one of {OUTCOMES}")
        cur = self.db.execute(
            """INSERT OR IGNORE INTO lead_events
               (lead_id, kind, at, stage, value, detail, source, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (lead_id, kind, iso(at), stage, value, scrub(detail), source, now_iso()),
        )
        return cur.rowcount == 1

    def record_outcome(self, lead_id: str, outcome: str, at: datetime, source: str,
                       reason: str | None = None) -> bool:
        if outcome == "lost" and not (reason and reason.strip()):
            raise ValueError("A lost outcome needs a reason (Section 7).")
        if not self.db.execute("SELECT 1 FROM leads WHERE lead_id = ?", (lead_id,)).fetchone():
            raise KeyError(f"No lead {lead_id}")
        return self.add_event(lead_id, "outcome", at, source, value=outcome, detail=reason)

    def find_lead(self, ref: str) -> str | None:
        rows = self.db.execute("SELECT lead_id FROM leads WHERE ref = ? OR lead_id = ?", (ref, ref)).fetchall()
        if len(rows) > 1:
            raise ValueError(f"Reference {ref!r} matches several leads; use source:ref")
        return rows[0][0] if rows else None

    def counts(self) -> dict:
        leads = self.db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        events = self.db.execute("SELECT COUNT(*) FROM lead_events").fetchone()[0]
        return {"leads": leads, "events": events}

    def states(self, as_of: datetime) -> list[LeadState]:
        leads, reported = {}, {}
        for r in self.db.execute(
            "SELECT lead_id, ref, source, channel, segment, value, touches_out_reported FROM leads"
        ):
            leads[r[0]] = LeadState(lead_id=r[0], ref=r[1], source=r[2], channel=r[3], segment=r[4], value=r[5])
            reported[r[0]] = r[6] or 0
        rows = self.db.execute(
            "SELECT lead_id, kind, at, stage, value, detail FROM lead_events WHERE at <= ? ORDER BY at, id",
            (iso(as_of),),
        )
        for lead_id, kind, at, stage, value, detail in rows:
            s = leads[lead_id]
            t = parse_ts(at)
            if kind == "inquired":
                s.inquired_at = min(filter(None, [s.inquired_at, t]))
            elif kind == "touch_in":
                s.last_in = t
            elif kind == "touch_out":
                s.touches_out += 1
                s.last_out = t
                if s.first_response_at is None:
                    s.first_response_at = t
            elif kind == "stage":
                s.stages.setdefault(stage, t)
            elif kind == "outcome":
                if value == "reopened":
                    s.outcome, s.outcome_at, s.lost_reason = None, None, None
                else:
                    s.outcome, s.outcome_at = value, t
                    s.lost_reason = detail if value == "lost" else None
        for lead_id, s in leads.items():
            s.touches_out = max(s.touches_out, reported[lead_id])
        return [s for s in leads.values() if s.inquired_at]

    # Action keys, used by the runner for dedupe

    def claim_action(self, key: str, agent: str, action: str) -> tuple[str, str | None] | None:
        """Claim a key before acting. Returns None if claimed, else (status, result) of the earlier claim."""
        try:
            self.db.execute(
                "INSERT INTO action_keys (key, agent, action, status, started_at) VALUES (?, ?, ?, 'started', ?)",
                (key, agent, action, now_iso()),
            )
            return None
        except sqlite3.IntegrityError:
            row = self.db.execute("SELECT status, result FROM action_keys WHERE key = ?", (key,)).fetchone()
            return row[0], row[1]

    def finish_action(self, key: str, status: str, result: dict | None = None) -> None:
        self.db.execute(
            "UPDATE action_keys SET status = ?, result = ? WHERE key = ?",
            (status, json.dumps(result or {}), key),
        )
