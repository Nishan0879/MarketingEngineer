"""First-response drafts for new inquiries nobody has answered yet (Section 9.3).

A Level 1 job: the agent drafts, a human releases. Speed to first response is
the conversion engine's first metric, so this agent works the newest part of
the funnel: open leads with no reply from us that haven't gone cold yet. Once
a lead passes the cold line it belongs to the re-engagement drafter instead.

Each draft fills the operator's [first_response] template and answers the
questions the lead asked, but only from approved facts tagged with that topic
(`topics = [...]` in profile/approved-facts.toml). A question with no usable
fact is never guessed at: the draft gets a visible `{answer needed: <topic>}`
line, which blocks approval until the operator writes the answer (Section 9.3,
"routes to a human instead of guessing"). Review, approval and sending go
through the shared queue in queue.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ...core.facts import Fact, load_facts
from ...core.ledger import Ledger, LeadState, iso, parse_ts
from ...core.workspace import Workspace
from . import cold_audit, queue
from .checks import Issue, check_text, render
from .reengage import draft_id, escalation, signals_by_lead

AGENT = "first-response-drafter"
SECTION = "first_response"
SITUATION = "awaiting_first_response"
ANSWERS = "{answers}"
QUOTE_MAX = 300


@dataclass
class Candidate:
    state: LeadState
    segment: str
    messages: list[dict] = field(default_factory=list)


@dataclass
class Topic:
    key: str
    label: str
    keywords: list[str]

    def asked_in(self, text: str) -> bool:
        return any(re.search(rf"\b{re.escape(k)}", text, re.I) for k in self.keywords)


def topics(playbook: dict) -> list[Topic]:
    raw = playbook.get(SECTION, {}).get("topics", {})
    return [Topic(k, v.get("label", k), list(v.get("keywords", []))) for k, v in raw.items()]


def template_for(playbook: dict, segment: str) -> dict | None:
    entry = playbook.get(SECTION, {})
    seg = entry.get("by_segment", {}).get(segment, {})
    subject, body = seg.get("subject", entry.get("subject")), seg.get("body", entry.get("body"))
    return {"subject": subject, "body": body} if subject and body else None


def candidates(ws: Workspace, ledger: Ledger, as_of: datetime) -> tuple[list[Candidate], list[dict]]:
    """Open inquiries with no reply from us yet, longest waiting first, and the ones skipped with why."""
    out, skipped = [], []
    by_lead = signals_by_lead(ledger, as_of)
    for s in ledger.states(as_of):
        if s.outcome or not s.inquired_at or s.first_response_at or s.touches_out:
            continue
        if s.reached("meet"):
            continue  # they booked without a reply; the meeting itself is the next touch
        segment = ws.segment_for(s.segment)
        seg = ws.config.segments.get(segment)
        cfg = cold_audit.Settings.from_config(ws.config.conversion, seg.cold_audit if seg else None)
        if s.last_activity < as_of - timedelta(days=cfg.cold_after_days):
            continue  # gone cold: the re-engagement drafter's job now
        if s.opted_out:
            skipped.append({"ref": s.ref, "why": "opted out"})
            continue
        messages = [m for m in by_lead.get(s.lead_id, []) if m["kind"] != "lost_reason"]
        flagged = escalation(messages)
        if flagged:
            skipped.append({"ref": s.ref, "why": "needs a human (Section 11.5)", "receipt": flagged["ref"]})
            continue
        out.append(Candidate(s, segment, messages))
    out.sort(key=lambda c: c.state.inquired_at)
    return out, skipped


def answer(asked: list[Topic], facts: dict[str, Fact], segment: str, today, already_used: set[str]
           ) -> tuple[str, list[str], list[Topic], dict[str, str]]:
    """Answers for the asked topics from usable facts. Returns (text, facts used, unanswered, why unusable)."""
    used: list[str] = []
    unanswered: list[Topic] = []
    unusable: dict[str, str] = {}
    sentences: list[str] = []
    for t in asked:
        tagged = [f for f in facts.values() if t.key in f.topics]
        usable = [f for f in tagged if f.problem(today, segment) is None]
        for f in tagged:
            if f not in usable:
                unusable[f.key] = f.problem(today, segment)
        if not usable:
            unanswered.append(t)
            continue
        for f in usable:
            if f.key not in used and f.key not in already_used:
                used.append(f.key)
                sentences.append(f.text)
    lines = [" ".join(sentences)] if sentences else []
    lines += [f"{{answer needed: {t.label}}}" for t in unanswered]
    return "\n\n".join(lines), used, unanswered, unusable


def _quote(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX].rsplit(" ", 1)[0] + "…"


def make_draft(ws: Workspace, c: Candidate, as_of: datetime) -> dict:
    """Write one pending draft. Returns its front matter, including any blocking issues."""
    playbook = queue.load_playbook(ws)
    tpl = template_for(playbook, c.segment)
    if tpl is None:
        return {"skipped": f"no [first_response] template ({c.segment})"}
    today = as_of.date()
    facts = load_facts(ws)
    asked_text = " ".join(m["text"] for m in c.messages)
    asked = [t for t in topics(playbook) if t.asked_in(asked_text)]

    subject, used_s, issues_s = render(tpl["subject"], facts, c.segment, today)
    marker = "\x00answers\x00"
    body, used_b, issues_b = render(tpl["body"].replace(ANSWERS, marker), facts, c.segment, today)
    answers, used_a, unanswered, unusable = answer(asked, facts, c.segment, today, set(used_s + used_b))
    body = re.sub(r"\n{3,}", "\n\n", body.replace(marker, answers)).strip()
    text = f"{subject}\n\n{body}"
    issues: list[Issue] = issues_s + issues_b + check_text(
        ws, text, facts, c.segment, today, queue.must_include(playbook, SECTION))

    s = c.state
    meta = {
        "id": draft_id("F", as_of, s.ref), "status": "pending", "agent": AGENT, "playbook_section": SECTION,
        "lead": s.ref, "lead_id": s.lead_id, "segment": c.segment, "situation": SITUATION,
        "channel": s.channel or "", "created": iso(as_of), "inquired": iso(s.inquired_at),
        "facts": sorted(set(used_s + used_b + used_a)), "topics_asked": [t.key for t in asked],
        "unanswered": [t.key for t in unanswered], "body_hash": queue.body_hash(text),
        "blocking_issues": list(dict.fromkeys(f"{i.check}: {i.message}" for i in issues if i.blocking)),
    }
    hours = (as_of - s.inquired_at).total_seconds() / 3600
    waited = f"{hours:.0f} hours" if hours < 48 else f"{hours / 24:.0f} days"
    why = [
        f"- Lead `{s.ref}` in the lead-tracking tool ({ws.segment_label(c.segment)}, "
        f"{s.channel or 'unknown channel'})",
        f"- No reply from us yet; they've waited {waited}",
        f"- Asked about: {', '.join(t.label for t in asked) or 'nothing the playbook lists as a topic'}",
        f"- Facts used: {', '.join(meta['facts']) or 'none'}",
    ]
    if unanswered:
        why.append(f"- **No approved fact for: {', '.join(t.label for t in unanswered)}.** Write that answer "
                   "yourself in place of the `{answer needed: ...}` line, or add an approved fact. "
                   "A price, number or promise still has to come from an approved fact.")
    for key, problem in unusable.items():
        why.append(f"- Not used: {problem}")
    latest = [m for m in c.messages if m["text"].strip()][-1:]
    if latest:
        why.append(f"- Latest message or note on this lead ({latest[0]['ref']}):\n\n"
                   f"  > {_quote(latest[0]['text'])}")
    md = (f"## Message\n\nSubject: {subject}\n\n{body}\n\n## Why this lead\n" + "\n".join(why)
          + "\n\n## Checks\n" + queue.checks_md(meta) + queue.footer_md(meta["id"]))
    queue.write_draft(ws, meta, md)
    return meta


def track_record(ws: Workspace) -> dict:
    return queue.track_record(ws, AGENT)


def key_for(c: Candidate) -> str:
    """One first response per lead."""
    return f"first-response:{c.state.lead_id}"


def waiting(ws: Workspace, as_of: datetime) -> dict | None:
    """Pending or approved first responses, and how long the oldest lead has waited, for the cockpit."""
    open_ = [m for _, m, _ in queue.existing_drafts(ws, AGENT) if m["status"] in ("pending", "approved")]
    if not open_:
        return None
    oldest = min(parse_ts(m["inquired"]) for m in open_)
    return {"count": len(open_), "oldest_hours": (as_of - oldest).total_seconds() / 3600}


def has_template(playbook: dict, c: Candidate) -> bool:
    return template_for(playbook, c.segment) is not None


def template_label(c: Candidate) -> str:
    return f"first_response ({c.segment})"


key = key_for
