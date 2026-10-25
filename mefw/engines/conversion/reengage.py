"""Re-engagement drafts for leads that went cold for reasons on our side (Section 9.3).

A Level 1 job: the agent drafts, a human releases. For each lead the cold audit
marks as ours to fix, it fills the operator's playbook template for that leak
(engines/conversion/playbook.toml) with approved facts, runs the checks, and
writes a draft to engines/conversion/drafts/ with status `pending`.

Leads are skipped, never drafted, when they opted out, already committed or
declined, or wrote something a human should handle (Section 11.5). Review, approval
and sending go through the shared queue in queue.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ...core.facts import load_facts
from ...core.ledger import Ledger, LeadState, iso
from ...core.workspace import Workspace
from . import cold_audit, queue
from .checks import ESCALATE, Issue, check_text, render
# Queue operations, re-exported for callers that work with re-engagement drafts.
from .queue import (DRAFTS, PROMOTION_DAYS, PROMOTION_STREAK, approve, existing_drafts,  # noqa: F401
                    export_approved, find, load_playbook, mark_sent, message_text, open_draft_for, reject,
                    summary_counts)

AGENT = "re-engagement-drafter"
SECTION = "reengage"


@dataclass
class Candidate:
    state: LeadState
    segment: str
    leak: str


def template_for(playbook: dict, leak: str, segment: str) -> dict | None:
    entry = playbook.get(SECTION, {}).get(leak)
    if not entry:
        return None
    seg = entry.get("by_segment", {}).get(segment, {})
    subject, body = seg.get("subject", entry.get("subject")), seg.get("body", entry.get("body"))
    return {"subject": subject, "body": body} if subject and body else None


def signals_by_lead(ledger: Ledger, as_of: datetime) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in ledger.signals(as_of):
        if s["lead_id"]:
            out.setdefault(s["lead_id"], []).append(s)
    return out


def escalation(signals: list[dict]) -> dict | None:
    """The latest message from this lead that a human should handle (Section 11.5), if any."""
    flagged = [x for x in signals if ESCALATE.search(x["text"])]
    return flagged[-1] if flagged else None


def candidates(ws: Workspace, ledger: Ledger, as_of: datetime) -> tuple[list[Candidate], list[dict]]:
    """Leads cold for reasons on our side, and the ones skipped with why."""
    out, skipped = [], []
    by_lead = signals_by_lead(ledger, as_of)
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
        flagged = escalation(by_lead.get(s.lead_id, []))
        if flagged:
            skipped.append({"ref": s.ref, "why": "needs a human (Section 11.5)", "receipt": flagged["ref"]})
            continue
        out.append(Candidate(s, segment, leak))
    out.sort(key=lambda c: (-(c.state.value or 0), -c.state.last_activity.timestamp()))
    return out, skipped


def draft_id(prefix: str, as_of: datetime, ref: str) -> str:
    return f"{prefix}-{as_of:%Y%m%d}-{re.sub(r'[^A-Za-z0-9]+', '-', ref)}"


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
        ws, text, facts, c.segment, today, queue.must_include(playbook, SECTION))

    s = c.state
    meta = {
        "id": draft_id("D", as_of, s.ref), "status": "pending", "agent": AGENT, "playbook_section": SECTION,
        "lead": s.ref, "lead_id": s.lead_id, "segment": c.segment, "leak": c.leak, "channel": s.channel or "",
        "created": iso(as_of), "facts": sorted(set(used_s + used_b)),
        "body_hash": queue.body_hash(text),
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
""" + queue.checks_md(meta) + queue.footer_md(meta["id"])
    queue.write_draft(ws, meta, md)
    return meta


def track_record(ws: Workspace) -> dict:
    return queue.track_record(ws, AGENT)


def today_key(c: Candidate) -> str:
    """One draft per lead per cold spell: a new spell starts when the lead's last activity changes."""
    return f"reengage:{c.state.lead_id}:{c.leak}:{c.state.last_activity.date().isoformat()}"


def has_template(playbook: dict, c: Candidate) -> bool:
    return template_for(playbook, c.leak, c.segment) is not None


def template_label(c: Candidate) -> str:
    return f"{c.leak} ({c.segment})"


key = today_key
