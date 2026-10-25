"""The approval queue shared by the conversion engine's drafting agents (Section 11.1, Level 1).

Agents write drafts to engines/conversion/drafts/ as `pending`. The operator
edits a draft if needed and approves it (the checks run again on the text as
it stands), or rejects it with a reason that goes to rules/corrections.md
(Section 12.1). A human sends approved drafts from their own tool and marks
them sent, which records an outbound touch on the lead.

Each draft's front matter names its agent and the playbook section its rules
come from, so one queue serves every drafting agent. Track records toward
Level 2 are kept per agent (Section 11.2).
"""

from __future__ import annotations

import csv
import hashlib
import re
import tomllib
from datetime import datetime
from pathlib import Path

from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import Ledger, iso, parse_ts
from ...core.workspace import Workspace
from .checks import check_text

PLAYBOOK = "engines/conversion/playbook.toml"
DRAFTS = "engines/conversion/drafts"
STATUSES = ("pending", "approved", "rejected", "sent")
PROMOTION_STREAK = 20   # Section 11.2 default: consecutive approvals without substantive edits
PROMOTION_DAYS = 14     # ... across at least two weeks


def body_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()[:16]


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Write the templates first.")
    return tomllib.loads(path.read_text())


def must_include(playbook: dict, section: str) -> list[str]:
    return playbook.get(section, {}).get("must_include", [])


def situation(meta: dict) -> str:
    """Why the draft exists: a cold-lead reason, or awaiting a first response."""
    return meta.get("situation") or meta.get("leak", "")


def write_draft(ws: Workspace, meta: dict, md: str) -> Path:
    path = ws.path(f"{DRAFTS}/{meta['id']}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, md))
    return path


def checks_md(meta: dict) -> str:
    return ("".join(f"- ❌ {x}\n" for x in meta["blocking_issues"])
            or "- ✅ facts, claims, banned language, sensitive data, required text\n")


def footer_md(draft_id: str) -> str:
    return (f"\n_Edit the message above if needed, then `mefw drafts approve {draft_id}` or "
            f"`mefw drafts reject {draft_id} --reason \"...\"`. Send it from your own tool; nothing is sent "
            "from here._\n")


def existing_drafts(ws: Workspace, agent: str | None = None) -> list[tuple[Path, dict, str]]:
    d = ws.path(DRAFTS)
    if not d.exists():
        return []
    out = [(p, *load(p)) for p in sorted(d.glob("*.md"))]
    return [x for x in out if agent is None or x[1].get("agent") == agent]


def open_draft_for(ws: Workspace, lead_id: str) -> dict | None:
    """A pending or approved draft for this lead from any agent. One message in flight per lead."""
    for _, meta, _ in existing_drafts(ws):
        if meta["lead_id"] == lead_id and meta["status"] in ("pending", "approved"):
            return meta
    return None


def message_text(body: str) -> str:
    m = re.search(r"## Message\n(.*?)\n## Why this lead", body, re.S)
    text = (m.group(1) if m else body).strip()
    return re.sub(r"^Subject:\s*", "", text, count=1)


def find(ws: Workspace, draft_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in existing_drafts(ws):
        if meta["id"].lower() == draft_id.lower():
            return p, meta, body
    raise KeyError(f"No draft {draft_id}")


def approve(ws: Workspace, draft_id: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "pending":
        raise ValueError(f"{draft_id} is {meta['status']}; only a pending draft can be approved")
    text = message_text(body)
    required = must_include(load_playbook(ws), meta.get("playbook_section", "reengage"))
    issues = [i for i in check_text(ws, text, load_facts(ws), meta["segment"], at.date(), required) if i.blocking]
    if issues:
        raise ValueError("Can't approve; the message as written fails checks:\n" +
                         "\n".join(f"  - {i.check}: {i.message}" for i in issues))
    meta.update(status="approved", approved_by=by, approved_at=iso(at),
                edited=body_hash(text) != meta["body_hash"], blocking_issues=[])
    path.write_text(dump(meta, body))
    return meta


def reject(ws: Workspace, draft_id: str, reason: str, by: str, at: datetime) -> dict:
    """Reject a draft. The reason becomes a correction the agent reads next time (Section 12.1)."""
    if not reason.strip():
        raise ValueError("A rejection needs a reason; it becomes a correction")
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "pending":
        raise ValueError(f"{draft_id} is {meta['status']}; only a pending draft can be rejected")
    meta.update(status="rejected", rejected_by=by, rejected_at=iso(at), reject_reason=reason.strip())
    path.write_text(dump(meta, body))
    corrections = ws.path("rules/corrections.md")
    reason_cell = reason.strip().replace("|", "\\|").replace("\n", " ")
    with open(corrections, "a", encoding="utf-8") as f:
        f.write(f"| {at.date().isoformat()} | {meta['agent']} | Rejected {meta['id']} ({situation(meta)}, "
                f"{meta['segment']}) | {reason_cell} |\n")
    return meta


def mark_sent(ws: Workspace, ledger: Ledger, draft_id: str, by: str, at: datetime) -> dict:
    """Record that a human sent the approved draft; it counts as an outbound touch on the lead."""
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "approved":
        raise ValueError(f"{draft_id} is {meta['status']}; only an approved draft can be marked sent")
    states = {s.lead_id: s for s in ledger.states(at)}
    if states.get(meta["lead_id"]) and states[meta["lead_id"]].opted_out:
        raise ValueError(f"{meta['lead']} has opted out since this was drafted. Don't send it.")
    ledger.add_event(meta["lead_id"], "touch_out", at, source=f"draft:{meta['id']}")
    meta.update(status="sent", sent_by=by, sent_at=iso(at))
    path.write_text(dump(meta, body))
    return meta


def export_approved(ws: Workspace, at: datetime) -> Path | None:
    """A CSV of approved, unsent drafts for loading into the client's own sending tool."""
    rows = []
    for _, meta, body in existing_drafts(ws):
        if meta["status"] == "approved":
            text = message_text(body)
            subject, _, msg = text.partition("\n")
            rows.append({"Draft ID": meta["id"], "Lead ID": meta["lead"], "Channel": meta.get("channel", ""),
                         "Subject": subject.strip(), "Message": msg.strip()})
    if not rows:
        return None
    path = ws.path(f"{DRAFTS}/export-{at:%Y-%m-%d}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def track_record(ws: Workspace, agent: str) -> dict:
    """Progress toward Level 2 by the Section 11.2 default: 20 consecutive unedited approvals over 2+ weeks."""
    decided = []
    for _, meta, _ in existing_drafts(ws, agent):
        if meta["status"] in ("approved", "sent"):
            decided.append((meta["approved_at"], "clean" if not meta.get("edited") else "edited"))
        elif meta["status"] == "rejected":
            decided.append((meta["rejected_at"], "rejected"))
    decided.sort()
    streak = []
    for at, kind in decided:
        streak = streak + [at] if kind == "clean" else []
    span = (parse_ts(streak[-1]) - parse_ts(streak[0])).days if len(streak) > 1 else 0
    return {
        "decided": len(decided), "approved_unedited": sum(1 for _, k in decided if k == "clean"),
        "edited": sum(1 for _, k in decided if k == "edited"),
        "rejected": sum(1 for _, k in decided if k == "rejected"),
        "streak": len(streak), "streak_days": span,
        "meets_threshold": len(streak) >= PROMOTION_STREAK and span >= PROMOTION_DAYS,
    }


def summary_counts(ws: Workspace, agent: str | None = None) -> dict:
    counts = {k: 0 for k in STATUSES}
    for _, meta, _ in existing_drafts(ws, agent):
        counts[meta["status"]] += 1
    return counts
