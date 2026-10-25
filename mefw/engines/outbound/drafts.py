"""Outbound signal engine, send and learn (Section 9.2). A Level 1 job: it drafts, a human sends.

Each draft is tied to one trigger. The operator's template for that trigger
type (`[outbound.events.<type>]`) may use `{company}`, `{detail}` (the
trigger as it was reported) and `{fact:key}`, and nothing else. That's the "no
fake personalization" rule: the only personal touch is the real reason to get
in touch now. Approval blocks a message that no longer mentions the trigger,
stock flattery that pretends to know the reader, unapproved claims, banned
language, sensitive-data requests and missing required text (opt-out wording,
a postal address, whatever the channel and region need).

Who to contact is the operator's call, made in their own tool. No names or
addresses are kept here. Sending is by hand and capped at `daily_send_limit`
a day. An opt-out suppresses the company at once, withdraws its open drafts
and blocks marking anything else sent to it.

Learn: each sent draft records what came back (replied, qualified, meeting,
not interested, opted out, bounced). The report counts qualified replies and
meetings by trigger type and by score band, not messages sent.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import iso, parse_ts
from ...core.workspace import Workspace
from ..conversion.checks import Issue, check_text, render
from ..conversion.queue import body_hash
from . import signals

AGENT = "outbound-drafter"
DRAFTS = "engines/outbound/drafts"
OPEN = ("pending", "approved")
IN_FLIGHT = datetime(9999, 1, 1, tzinfo=timezone.utc)  # a draft not yet sent or dropped blocks another
OUTCOMES = ("replied", "qualified", "meeting", "not_interested", "opted_out", "bounced", "no_reply")
REPLIED = ("replied", "qualified", "meeting", "not_interested", "opted_out")
QUALIFIED = ("qualified", "meeting")
# Lines that pretend to know the reader. The trigger is the only personal touch allowed.
FAKE = re.compile(
    r"\b(?:i'?ve been following|big fan of (?:you|your)|(?:love|loved|admire) what you(?:'re| are) doing|"
    r"loved your (?:recent )?post|came across your profile|hope this finds you well|as a fellow)\b",
    re.I,
)


def all_drafts(ws: Workspace) -> list[tuple[Path, dict, str]]:
    d = ws.path(DRAFTS)
    return [(p, *load(p)) for p in sorted(d.glob("O-*.md"))] if d.exists() else []


def find(ws: Workspace, draft_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in all_drafts(ws):
        if meta["id"].lower() == draft_id.lower():
            return p, meta, body
    raise KeyError(f"No outbound draft {draft_id}")


def contacted(ws: Workspace, in_flight: bool = True) -> dict[str, datetime]:
    """When each account was last contacted; with in_flight, an open draft counts as contact from now on."""
    out: dict[str, datetime] = {}
    for _, m, _ in all_drafts(ws):
        when = parse_ts(m["sent_at"]) if m["status"] == "sent" else \
            (IN_FLIGHT if in_flight and m["status"] in OPEN else None)
        if when and (m["account_key"] not in out or when > out[m["account_key"]]):
            out[m["account_key"]] = when
    return out


def candidates(ws: Workspace, as_of: datetime) -> tuple[list[dict], dict]:
    return signals.score(ws, as_of, contacted(ws))


def message_text(body: str) -> str:
    return body.split("## Message", 1)[-1].split("\n## ", 1)[0].strip()


def check(ws: Workspace, pb: dict, text: str, account: str, detail: str, today) -> list[Issue]:
    issues = []
    if not detail:
        issues.append(Issue("personalization", "the trigger has no detail to say why now; find the reason first"))
    elif detail.lower() not in text.lower():
        issues.append(Issue("personalization", "no longer mentions the trigger; every message must say the real "
                                               "reason for getting in touch now"))
    m = FAKE.search(text)
    if m:
        issues.append(Issue("personalization", f"\"{m.group(0)}\" pretends to know the reader; use the trigger"))
    ours = text  # the company's name, the trigger as reported and required text aren't our claims
    for theirs in sorted({account, detail, *pb["must_include"]}, key=len, reverse=True):
        if theirs:
            ours = re.sub(re.escape(theirs), " ", ours, flags=re.I)
    issues += [i for i in check_text(ws, ours, load_facts(ws), None, today, []) if i.blocking]
    for required in pb["must_include"]:
        if required.lower() not in text.lower():
            issues.append(Issue("compliance", f"missing required text: \"{required}\""))
    return issues


def make_draft(ws: Workspace, a: dict, as_of: datetime) -> dict:
    pb = signals.load_playbook(ws)
    t = a["trigger"]
    ev = pb["events"][t["event"]]
    if not (ev.get("subject") and ev.get("body")):
        return {"skipped": f"no template for '{t['event']}' in [outbound.events.{t['event']}]"}
    today = as_of.date()
    fill = lambda s: s.replace("{company}", a["account"]).replace("{detail}", t["detail"])  # noqa: E731
    facts = load_facts(ws)
    subject, used_s, issues_s = render(fill(ev["subject"]), facts, None, today)
    body, used_b, issues_b = render(fill(ev["body"]), facts, None, today)
    text = f"{subject}\n\n{body}"
    issues = issues_s + issues_b + check(ws, pb, text, a["account"], t["detail"], today)
    if "{detail}" not in ev["body"] and "{detail}" not in ev["subject"]:
        issues.append(Issue("personalization", f"the {t['event']} template doesn't use {{detail}}"))
    draft_id = f"O-{as_of:%Y%m%d}-{a['account_key']}"
    meta = {"id": draft_id, "status": "pending", "agent": AGENT, "account": a["account"],
            "account_key": a["account_key"], "account_ref": a.get("account_ref", ""), "event": t["event"],
            "trigger": t["id"], "detail": t["detail"], "score": a["score"], "created": iso(as_of),
            "facts": sorted(set(used_s + used_b)), "body_hash": body_hash(text),
            "blocking_issues": list(dict.fromkeys(f"{i.check}: {i.message}" for i in issues)), "outcomes": []}
    trig = "\n".join(f"- {x['at'][:10]}: {pb['events'][x['event']].get('label', x['event'])}: {x['detail'] or '–'}"
                     + (f" ({x['source']})" if x["source"] else "") for x in a["triggers"])
    md = f"""## Message

Subject: {subject}

{body}

## Why this company, why now
{trig}
- Score {a['score']}: fit {a['fit']} ({', '.join(a['fit_why']) or 'no ICP set'}), reason {a['reason']}, right now {a['now']}
- In your tool: {a.get('account_ref') or 'not linked'}

## Who to contact
Pick the right person in your own tool. No names or contact details are kept here.

## Checks
""" + ("".join(f"- ❌ {x}\n" for x in meta["blocking_issues"]) or
       "- ✅ tied to the trigger, no fake personalization, facts, claims, banned language, sensitive data, "
       "required text\n") + (
        f"\n_Edit the message if needed, then `mefw outbound approve {draft_id}` or "
        f"`mefw outbound reject {draft_id} --reason \"...\"`. Send it from your own tool, then "
        f"`mefw outbound sent {draft_id}`._\n")
    path = ws.path(f"{DRAFTS}/{draft_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, md))
    return meta


def approve(ws: Workspace, draft_id: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "pending":
        raise ValueError(f"{draft_id} is {meta['status']}")
    if meta["account_key"] in signals.suppressed(ws):
        raise ValueError(f"{meta['account']} is suppressed; don't contact them")
    pb = signals.load_playbook(ws)
    text = message_text(body).removeprefix("Subject:").strip()
    issues = check(ws, pb, text, meta["account"], meta["detail"], at.date())
    if issues:
        raise ValueError("Can't approve; the message fails checks:\n" +
                         "\n".join(f"  - {i.check}: {i.message}" for i in issues))
    edited = body_hash(text) != meta["body_hash"]
    meta.update(status="approved", approved_by=by, approved_at=iso(at), edited=edited, blocking_issues=[])
    path.write_text(dump(meta, body))
    return meta


def reject(ws: Workspace, draft_id: str, reason: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] not in OPEN:
        raise ValueError(f"{draft_id} is {meta['status']}")
    if not reason.strip():
        raise ValueError("Say why; rejections teach the scoring and the templates")
    meta.update(status="rejected", rejected_by=by, rejected_at=iso(at), reason=reason.strip())
    path.write_text(dump(meta, body))
    return meta


def sent_today(ws: Workspace, at: datetime) -> int:
    return sum(1 for _, m, _ in all_drafts(ws) if m["status"] == "sent" and parse_ts(m["sent_at"]).date() == at.date())


def mark_sent(ws: Workspace, draft_id: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "approved":
        raise ValueError(f"{draft_id} is {meta['status']}; only an approved draft can be marked sent")
    if meta["account_key"] in signals.suppressed(ws):
        raise ValueError(f"{meta['account']} was suppressed after this was drafted. Don't send it.")
    limit = int(signals.load_playbook(ws)["daily_send_limit"])
    if sent_today(ws, at) >= limit:
        raise ValueError(f"Already {limit} sent today (daily_send_limit). Send the rest tomorrow.")
    meta.update(status="sent", sent_by=by, sent_at=iso(at))
    path.write_text(dump(meta, body))
    return meta


def record_outcome(ws: Workspace, draft_id: str, outcome: str, by: str, at: datetime) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"Outcome must be one of: {', '.join(OUTCOMES)}")
    path, meta, body = find(ws, draft_id)
    if meta["status"] != "sent":
        raise ValueError(f"{draft_id} is {meta['status']}; record outcomes on sent messages")
    meta["outcomes"] = [*meta.get("outcomes", []), {"outcome": outcome, "at": iso(at), "by": by}]
    path.write_text(dump(meta, body))
    if outcome == "opted_out":
        stop(ws, meta["account"], "opted out in reply to " + meta["id"], by, at)
    return meta


def stop(ws: Workspace, account: str, reason: str, by: str, at: datetime) -> list[str]:
    """Suppress a company and withdraw its open drafts. Returns the withdrawn draft IDs."""
    signals.suppress(ws, account, reason, by, at)
    key = signals.account_key(account)
    withdrawn = []
    for path, meta, body in all_drafts(ws):
        if meta["account_key"] == key and meta["status"] in OPEN:
            meta.update(status="withdrawn", withdrawn_at=iso(at), reason=reason)
            path.write_text(dump(meta, body))
            withdrawn.append(meta["id"])
    return withdrawn


def learn(ws: Workspace, as_of: datetime, days: int = 90) -> dict:
    """Qualified replies and meetings for messages sent in the last `days`, by trigger type and score band."""
    pb = signals.load_playbook(ws)
    sent = [m for _, m, _ in all_drafts(ws)
            if m["status"] == "sent" and as_of - timedelta(days=days) <= parse_ts(m["sent_at"]) <= as_of]

    def row(group: list[dict]) -> dict:
        got = lambda kinds: sum(1 for m in group if any(o["outcome"] in kinds for o in m.get("outcomes", [])))  # noqa: E731
        n = len(group)
        r = {"sent": n, "replied": got(REPLIED), "qualified": got(QUALIFIED), "meetings": got(("meeting",)),
             "opted_out": got(("opted_out",)), "bounced": got(("bounced",))}
        r["qualified_rate"] = r["qualified"] / n if n else None
        return r
    by_event = {pb["events"].get(e, {}).get("label", e): row([m for m in sent if m["event"] == e])
                for e in sorted({m["event"] for m in sent})}
    bands = {"7 and up": lambda s: s >= 7, "below 7": lambda s: s < 7}
    by_band = {b: row([m for m in sent if f(float(m["score"]))]) for b, f in bands.items()}
    return {"days": days, "total": row(sent), "by_event": by_event, "by_band": by_band}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def render_report(ws: Workspace, as_of: datetime, ranked: list[dict], dropped: dict, lrn: dict) -> str:
    L = [f"# Outbound signals, {as_of.date().isoformat()}", "",
         "Companies with a real reason to need you now, scored on fit × reason × right now (Section 9.2).", "",
         "## Worth contacting", ""]
    if ranked:
        L += ["| Company | Score | Trigger | When | Fit | Draft |", "|---|---|---|---|---|---|"]
        pb = signals.load_playbook(ws)
        for a in ranked[:20]:
            t = a["trigger"]
            L.append(f"| {a['account']} | {a['score']} | {pb['events'][t['event']].get('label', t['event'])}: "
                     f"{t['detail'] or '–'} | {t['at'][:10]} | {', '.join(a['fit_why']) or '–'} | "
                     f"{a.get('draft') or 'not yet'} |")
    else:
        L.append("Nobody right now. Import fresh triggers with `mefw outbound import <file>`.")
    if dropped:
        L += ["", "Left out: " + ", ".join(f"{n} {why}" for why, n in sorted(dropped.items())) + "."]
    t = lrn["total"]
    L += ["", f"## What came back (messages sent in the last {lrn['days']} days)", ""]
    if not t["sent"]:
        L.append("Nothing sent yet.")
    else:
        L += [f"{t['sent']} sent, {t['replied']} replied, {t['qualified']} qualified, {t['meetings']} meetings, "
              f"{t['opted_out']} opted out, {t['bounced']} bounced. Judge it on qualified replies and meetings, "
              "not on messages sent. A rate from a handful of messages is a direction, not proof.", "",
              "| Trigger | Sent | Replied | Qualified | Meetings | Qualified rate |", "|---|---|---|---|---|---|"]
        for name, r in lrn["by_event"].items():
            L.append(f"| {name} | {r['sent']} | {r['replied']} | {r['qualified']} | {r['meetings']} | "
                     f"{_pct(r['qualified_rate'])} |")
        L += ["", "| Score | Sent | Qualified | Meetings | Qualified rate |", "|---|---|---|---|---|"]
        for name, r in lrn["by_band"].items():
            L.append(f"| {name} | {r['sent']} | {r['qualified']} | {r['meetings']} | {_pct(r['qualified_rate'])} |")
    return "\n".join(L) + "\n"


def write_report(ws: Workspace, as_of: datetime) -> tuple[str, dict]:
    ranked, dropped = signals.score(ws, as_of, contacted(ws, in_flight=False))
    drafts = {m["account_key"]: m["id"] for _, m, _ in all_drafts(ws) if m["status"] in OPEN}
    for a in ranked:
        a["draft"] = drafts.get(a["account_key"])
    lrn = learn(ws, as_of)
    rel = f"engines/outbound/reports/{as_of.date().isoformat()}.md"
    path = ws.path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(ws, as_of, ranked, dropped, lrn))
    return rel, {"ranked": len(ranked), "dropped": dropped}
