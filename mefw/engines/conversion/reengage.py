"""Re-engagement drafts for leads that went cold for reasons on our side (Section 9.3).

A Level 1 job: the agent drafts, a human releases. For each lead the cold audit
marks as ours to fix, it fills the operator's playbook template for that leak
(engines/conversion/playbook.toml) with approved facts, runs the checks, and
writes a draft to engines/conversion/drafts/ with status `pending`.

Leads are skipped, never drafted, when they opted out, already committed or
declined, or wrote something a human should handle (Section 11.5). The operator
approves (after editing the file if needed), or rejects with a reason that goes
to rules/corrections.md. Approval reruns the checks on the text as it stands.
Whether the operator changed the text is recorded, because that is the track
record promotion to Level 2 is judged on (Section 11.2).
"""

from __future__ import annotations

import csv
import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import Ledger, LeadState, iso, parse_ts
from ...core.workspace import Workspace
from . import cold_audit
from .checks import ESCALATE, Issue, check_text, render

AGENT = "re-engagement-drafter"
PLAYBOOK = "engines/conversion/playbook.toml"
DRAFTS = "engines/conversion/drafts"
STATUSES = ("pending", "approved", "rejected", "sent")
PROMOTION_STREAK = 20   # Section 11.2 default: consecutive approvals without substantive edits
PROMOTION_DAYS = 14     # ... across at least two weeks


@dataclass
class Candidate:
    state: LeadState
    segment: str
    leak: str


def _body_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()[:16]


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Write the re-engagement templates first.")
    return tomllib.loads(path.read_text())


def template_for(playbook: dict, leak: str, segment: str) -> dict | None:
    entry = playbook.get("reengage", {}).get(leak)
    if not entry:
        return None
    seg = entry.get("by_segment", {}).get(segment, {})
    subject, body = seg.get("subject", entry.get("subject")), seg.get("body", entry.get("body"))
    return {"subject": subject, "body": body} if subject and body else None


def candidates(ws: Workspace, ledger: Ledger, as_of: datetime) -> tuple[list[Candidate], list[dict]]:
    """Leads cold for reasons on our side, and the ones skipped with why."""
    out, skipped = [], []
    signals_by_lead: dict[str, list[dict]] = {}
    for s in ledger.signals(as_of):
        if s["lead_id"]:
            signals_by_lead.setdefault(s["lead_id"], []).append(s)
    for s in ledger.states(as_of):
        segment = ws.segment_for(s.segment)
        seg = ws.config.segments.get(segment)
        cfg = cold_audit.Settings.from_config(ws.config.conversion, seg.cold_audit if seg else None)
        if s.outcome or s.reached("commit") or not s.last_activity:
            continue
        if s.last_activity > as_of - timedelta(days=cfg.cold_after_days):
            continue
        if s.last_activity < as_of - timedelta(days=cfg.lookback_days):
            continue
        leak = cold_audit.classify(s, cfg)
        if leak not in cold_audit.FIXABLE:
            continue
        if s.opted_out:
            skipped.append({"ref": s.ref, "why": "opted out"})
            continue
        flagged = [x for x in signals_by_lead.get(s.lead_id, []) if ESCALATE.search(x["text"])]
        if flagged:
            skipped.append({"ref": s.ref, "why": "needs a human (Section 11.5)", "receipt": flagged[-1]["ref"]})
            continue
        out.append(Candidate(s, segment, leak))
    out.sort(key=lambda c: (-(c.state.value or 0), -c.state.last_activity.timestamp()))
    return out, skipped


def existing_drafts(ws: Workspace) -> list[tuple[Path, dict, str]]:
    d = ws.path(DRAFTS)
    if not d.exists():
        return []
    return [(p, *load(p)) for p in sorted(d.glob("D-*.md"))]


def open_draft_for(ws: Workspace, lead_id: str) -> dict | None:
    for _, meta, _ in existing_drafts(ws):
        if meta["lead_id"] == lead_id and meta["status"] in ("pending", "approved"):
            return meta
    return None


def make_draft(ws: Workspace, c: Candidate, as_of: datetime) -> dict:
    """Write one pending draft. Returns its front matter, including any blocking issues."""
    playbook = load_playbook(ws)
    tpl = template_for(playbook, c.leak, c.segment)
    if tpl is None:
        return {"skipped": f"no playbook template for '{c.leak}' ({c.segment})"}
    today = as_of.date()
    facts = load_facts(ws)
    subject, used_s, issues_s = render(tpl["subject"], facts, c.segment, today)
    body, used_b, issues_b = render(tpl["body"], facts, c.segment, today)
    text = f"{subject}\n\n{body}"
    issues: list[Issue] = issues_s + issues_b + check_text(
        ws, text, facts, c.segment, today, playbook.get("reengage", {}).get("must_include", []))

    s = c.state
    draft_id = f"D-{as_of:%Y%m%d}-{re.sub(r'[^A-Za-z0-9]+', '-', s.ref)}"
    meta = {
        "id": draft_id, "status": "pending", "agent": AGENT, "lead": s.ref, "lead_id": s.lead_id,
        "segment": c.segment, "leak": c.leak, "channel": s.channel or "",
        "created": iso(as_of), "facts": sorted(set(used_s + used_b)),
        "body_hash": _body_hash(text),
        "blocking_issues": list(dict.fromkeys(f"{i.check}: {i.message}" for i in issues if i.blocking)),
    }
    days_quiet = (as_of - s.last_activity).days
    md = f"""## Message

Subject: {subject}

{body}

## Why this lead
- Lead `{s.ref}` in the lead-tracking tool ({ws.segment_label(c.segment)}, {s.channel or 'unknown channel'})
- {cold_audit.LEAKS[c.leak]}; quiet for {days_quiet} days; furthest stage: {s.furthest_stage}
- Facts used: {", ".join(meta["facts"]) or "none"}

## Checks
""" + ("".join(f"- ❌ {x}\n" for x in meta["blocking_issues"]) or "- ✅ facts, claims, banned language, sensitive data, required text\n") + """
_Edit the message above if needed, then `mefw drafts approve {id}` or `mefw drafts reject {id} --reason "..."`. Send it from your own tool; nothing is sent from here._
""".replace("{id}", draft_id)
    path = ws.path(f"{DRAFTS}/{draft_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, md))
    return meta


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
    playbook = load_playbook(ws)
    issues = [i for i in check_text(ws, text, load_facts(ws), meta["segment"], at.date(),
                                     playbook.get("reengage", {}).get("must_include", [])) if i.blocking]
    if issues:
        raise ValueError("Can't approve; the message as written fails checks:\n" +
                         "\n".join(f"  - {i.check}: {i.message}" for i in issues))
    meta.update(status="approved", approved_by=by, approved_at=iso(at),
                edited=_body_hash(text) != meta["body_hash"], blocking_issues=[])
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
        f.write(f"| {at.date().isoformat()} | {AGENT} | Rejected {meta['id']} ({meta['leak']}, "
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


def track_record(ws: Workspace) -> dict:
    """Progress toward Level 2 by the Section 11.2 default: 20 consecutive unedited approvals over 2+ weeks."""
    decided = []
    for _, meta, _ in existing_drafts(ws):
        if meta["status"] in ("approved", "sent"):
            decided.append((meta["approved_at"], "clean" if not meta.get("edited") else "edited"))
        elif meta["status"] == "rejected":
            decided.append((meta["rejected_at"], "rejected"))
    decided.sort()
    streak = []
    for at, kind in decided:
        streak = streak + [at] if kind == "clean" else []
    span = (parse_ts(streak[-1]) - parse_ts(streak[0])).days if len(streak) > 1 else 0
    total = len(decided)
    clean = sum(1 for _, k in decided if k == "clean")
    return {
        "decided": total, "approved_unedited": clean,
        "edited": sum(1 for _, k in decided if k == "edited"),
        "rejected": sum(1 for _, k in decided if k == "rejected"),
        "streak": len(streak), "streak_days": span,
        "meets_threshold": len(streak) >= PROMOTION_STREAK and span >= PROMOTION_DAYS,
    }


def today_key(c: Candidate) -> str:
    """One draft per lead per cold spell: a new spell starts when the lead's last activity changes."""
    return f"reengage:{c.state.lead_id}:{c.leak}:{c.state.last_activity.date().isoformat()}"


def summary_counts(ws: Workspace) -> dict:
    counts = {k: 0 for k in STATUSES}
    for _, meta, _ in existing_drafts(ws):
        counts[meta["status"]] += 1
    return counts
