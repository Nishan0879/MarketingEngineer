"""The monthly client report (Section 18 week 4 "results review"; Section 22, what the client sees).

Separate from the internal cockpit. The cockpit is how the operator steers, so
it carries agent errors, lead IDs and decisions. The client report is what the
client reads, so it carries none of that. It covers:

- Results: the north star this month against last month.
- The funnel: inquiries, response speed and meetings.
- What customers are telling us: insight records the operator has confirmed.
- What we tested: experiments closed this month, and the ones running.
- Follow-up: messages sent, and cold leads that came back.
- What's next, and the data we need from the client.

Every number comes from the ledger with its sample size, and small samples are
labelled. Draft insights ("Draft wording; operator to confirm") are left out
until the operator confirms them.

The agent writes a draft to reports/YYYY-MM-client-report.md. The operator
reads and edits it, then approves it. Approval checks the text again and writes
a printable HTML copy to share. An approved report is never overwritten.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import experiments, metrics
from .frontmatter import dump, load
from .ledger import Ledger, LeadState, iso, parse_ts
from .pii import EMAIL, LONG_NUMBER, PHONE, scrub
from .workspace import Workspace
from ..engines.conversion import cold_audit, first_response, queue, reengage

AGENT = "client-reporter"
REPORTS = "reports"
CLIENT_READY = ("confirmed", "acted on")  # insight statuses the client may see
MIN_N = 10  # below this, a rate is shown but marked as a small sample
VERDICT_WORDS = {"keep": "keep it", "iterate": "refine it and test again", "kill": "stop it",
                 "inconclusive": "call it inconclusive for now"}


def month_bounds(month: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError(f"Month must look like 2026-10, not {month!r}")
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


def previous_month(month: str) -> str:
    start, _ = month_bounds(month)
    return (start - timedelta(days=1)).strftime("%Y-%m")


def default_month(as_of: datetime) -> str:
    """The last complete month before as_of."""
    return (as_of.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def month_label(month: str) -> str:
    return month_bounds(month)[0].strftime("%B %Y")


def _won(states: list[LeadState], start: datetime, end: datetime) -> list[LeadState]:
    return [s for s in states if s.outcome == "won" and s.outcome_at and start <= s.outcome_at < end]


def _north_star(won: list[LeadState], metric: str) -> float:
    return sum(s.value or 0 for s in won) if metric == "commit_value" else len(won)


def _value(v: metrics.Value, metric: str) -> dict:
    return {"text": v.fmt(metric), "n": v.n, "value": v.value, "small": 0 < v.n < MIN_N}


def _field(text: str, name: str) -> str:
    m = re.search(rf"^- \*\*{re.escape(name)}:\*\*[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def _client_quote(text: str) -> str:
    """Customer words without our internal source references, scrubbed again to be safe."""
    return scrub(re.sub(r"\s*\(`[^`]*`\)", "", text)).strip()


def insights(ws: Workspace) -> tuple[list[dict], list[str]]:
    """Confirmed insight records for the client, and the names of drafts left out."""
    d = ws.path("customer-truth/insights")
    shown, held = [], []
    for path in sorted(d.glob("*.md")) if d.exists() else []:
        text = path.read_text()
        status = _field(text, "Status").lower()
        if status not in CLIENT_READY or "Draft wording" in _field(text, "Statement"):
            if status not in ("retired",):
                held.append(path.stem)
            continue
        title = re.search(r"^## Insight: (.+)$", text, re.M)
        shown.append({
            "title": title.group(1).strip() if title else path.stem,
            "segment": _field(text, "Segment"), "statement": _field(text, "Statement"),
            "quote": _client_quote(_field(text, "Customer language")),
            "confidence": _field(text, "Confidence") or "low", "status": status,
        })
    return shown, held


def _came_back(s: LeadState, sent: datetime) -> bool:
    later = [t for t in (s.last_in, *s.stages.values()) if t and t > sent]
    return bool(later) or (s.outcome == "won" and s.outcome_at is not None and s.outcome_at > sent)


def build(ws: Workspace, ledger: Ledger, month: str, as_of: datetime) -> dict:
    start, end = month_bounds(month)
    if start >= as_of:
        raise ValueError(f"{month_label(month)} hasn't started yet")
    end_seen = min(end, as_of)
    pstart, pend = month_bounds(previous_month(month))
    states = ledger.states(as_of)
    seg_of = {s.lead_id: ws.segment_for(s.segment) for s in states}
    ns_cfg = ws.config.north_star
    ns_metric = ns_cfg.get("metric", "commits")
    data = {"client": ws.config.client_name or ws.client_id, "month": month, "label": month_label(month),
            "complete": end <= as_of, "as_of": iso(as_of)}

    won, won_before = _won(states, start, end_seen), _won(states, pstart, pend)
    by_seg = defaultdict(int)
    for s in won:
        by_seg[ws.segment_label(seg_of[s.lead_id])] += 1
    data["north_star"] = {"label": ns_cfg.get("label", "Commitments"), "metric": ns_metric,
                          "this": _north_star(won, ns_metric), "before": _north_star(won_before, ns_metric),
                          "by_segment": dict(by_seg)}

    funnel = []
    for seg in ws.segment_names():
        leads = [s for s in states if seg_of[s.lead_id] == seg]
        cycle = ws.cycle_days(seg)
        now, before = metrics.in_window(leads, start, end_seen), metrics.in_window(leads, pstart, pend)
        row = {"segment": ws.segment_label(seg), "inquiries": len(now), "inquiries_before": len(before)}
        for m in ("first_response_minutes", "responded_within_1h", "inquiry_to_meeting"):
            row[m] = _value(metrics.compute(m, now, as_of, cycle), m)
            row[m + "_before"] = _value(metrics.compute(m, before, as_of, cycle), m)
        funnel.append(row)
    data["funnel"] = funnel

    shown, held = insights(ws)
    data["insights"], data["held_insights"] = shown, held

    done, running, next_up = [], [], []
    for _, meta, body in experiments.all_briefs(ws):
        name = {"name": meta["name"], "segment": ws.segment_label(meta["segment"])}
        if meta["status"] == "completed" and start <= parse_ts(meta["completed_at"]) < end:
            done.append({**name, "verdict": meta.get("verdict"), "confidence": meta.get("confidence"),
                         "outcome": _field(body, "Outcome"), "lesson": _field(body, "Lesson")})
            if _field(body, "Next test"):
                next_up.append(_field(body, "Next test"))
        elif meta["status"] == "running":
            running.append({**name, "since": (meta.get("started_at") or "")[:10]})
        elif meta["status"] == "approved":
            next_up.append(f"{meta['name']} ({ws.segment_label(meta['segment'])})")
    data["tests"] = {"done": done, "running": running, "next": next_up}

    by_lead = {s.lead_id: s for s in states}
    sent = defaultdict(int)
    reengaged, came_back = 0, 0
    for _, meta, _ in queue.existing_drafts(ws):
        if meta["status"] != "sent" or not (start <= parse_ts(meta["sent_at"]) < end):
            continue
        sent[meta["agent"]] += 1
        if meta["agent"] == reengage.AGENT:
            reengaged += 1
            s = by_lead.get(meta["lead_id"])
            came_back += bool(s and _came_back(s, parse_ts(meta["sent_at"])))
    data["follow_up"] = {"first_responses": sent[first_response.AGENT], "reengaged": reengaged,
                         "came_back": came_back}

    audit = cold_audit.run_audit(ws, ledger, as_of)
    asks = []
    for d in audit["segments"].values():
        oc = d.get("outcome_coverage") or {}
        if oc.get("rate") is not None and oc["rate"] < 0.8:
            asks.append(f"{d['label']}: {oc['due'] - oc['with_outcome']} older leads have no won/lost result yet. "
                        "Marking them won or lost, with a reason, makes next month's numbers more reliable.")
    data["asks"] = asks
    data["headline"] = _headline(data)
    return data


def _headline(d: dict) -> str:
    ns = d["north_star"]
    fmt = (lambda v: f"{v:,.0f}") if ns["metric"] == "commit_value" else (lambda v: f"{v:g}")
    parts = [f"In {d['label']}{'' if d['complete'] else ' (so far)'}: {fmt(ns['this'])} "
             f"{ns['label'].lower()}, against {fmt(ns['before'])} the month before."]
    if d["insights"]:
        parts.append(f"What we learned: {d['insights'][0]['statement'].rstrip('.')}.")
    if d["tests"]["done"]:
        t = d["tests"]["done"][0]
        parts.append(f"We tested “{t['name']}” and decided to {VERDICT_WORDS.get(t['verdict'], t['verdict'])}"
                     + (f" ({t['outcome']})" if t["outcome"] else "") + ".")
    elif d["tests"]["running"]:
        parts.append(f"Running now: {', '.join(t['name'] for t in d['tests']['running'])}.")
    return " ".join(parts)


def _cell(v: dict) -> str:
    if v["value"] is None:
        return "not enough data yet"
    return f"{v['text']} (of {v['n']}{', small sample' if v['small'] else ''})"


def render(d: dict) -> str:
    L: list[str] = []
    w = L.append
    ns = d["north_star"]
    w(f"# {d['client']}: growth report for {d['label']}")
    w("")
    if not d["complete"]:
        w(f"_Month in progress; figures to {d['as_of'][:10]}._")
        w("")
    w(d["headline"])
    w("")

    w("## Results")
    w("")
    w(f"- **{ns['label']}:** {ns['this']:g} this month, {ns['before']:g} last month")
    for seg, n in sorted(ns["by_segment"].items()):
        w(f"  - {seg}: {n}")
    w("")

    w("## How inquiries were handled")
    w("")
    w("| | Inquiries | Typical time to first reply | Answered within an hour | Went on to a meeting |")
    w("|---|---|---|---|---|")
    for r in d["funnel"]:
        for when, sfx, n in (("this month", "", r["inquiries"]), ("last month", "_before", r["inquiries_before"])):
            w(f"| {r['segment']}, {when} | {n} | {_cell(r['first_response_minutes' + sfx])} | "
              f"{_cell(r['responded_within_1h' + sfx])} | {_cell(r['inquiry_to_meeting' + sfx])} |")
    w("")
    w("Numbers in brackets are how many inquiries each figure is based on. Meeting rates only count inquiries "
      "old enough to have booked one, so recent weeks fill in later.")
    w("")

    w("## What your customers are telling us")
    w("")
    if d["insights"]:
        for i in d["insights"]:
            w(f"- **{i['title']}.** {i['statement']}" + (f" In their words: {i['quote']}" if i["quote"] else "")
              + f" _(Confidence: {i['confidence']}.)_")
    else:
        w("- Nothing confirmed yet this month. We only report patterns once there's enough evidence behind them.")
    w("")

    w("## What we tested")
    w("")
    t = d["tests"]
    for x in t["done"]:
        w(f"- **{x['name']}** ({x['segment']}): we decided to {VERDICT_WORDS.get(x['verdict'], x['verdict'])}."
          + (f" {x['outcome'].rstrip('.')}." if x["outcome"] else "")
          + (f" Lesson: {x['lesson']}" if x["lesson"] else "") + f" _(Confidence: {x['confidence']}.)_")
    for x in t["running"]:
        w(f"- **{x['name']}** ({x['segment']}): running since {x['since']}; results once enough leads have come through.")
    if not t["done"] and not t["running"]:
        w("- No tests ran this month.")
    w("")

    f = d["follow_up"]
    if f["first_responses"] or f["reengaged"]:
        w("## Follow-up")
        w("")
        if f["first_responses"]:
            w(f"- {f['first_responses']} first repl{'ies' if f['first_responses'] != 1 else 'y'} to new inquiries, "
              "each checked against your approved facts")
        if f["reengaged"]:
            w(f"- {f['reengaged']} follow-up{'s' if f['reengaged'] != 1 else ''} to inquiries that had gone "
              f"quiet; {f['came_back']} of them {'have' if f['came_back'] != 1 else 'has'} replied, booked or "
              "signed since")
        w("")

    w("## Next month")
    w("")
    for x in t["next"]:
        w(f"- {x}")
    for x in t["running"]:
        w(f"- Keep measuring {x['name']}")
    if not t["next"] and not t["running"]:
        w("- We'll pick the next test from what this month showed and share it with you before it starts.")
    w("")

    if d["asks"]:
        w("## What would help from you")
        w("")
        for a in d["asks"]:
            w(f"- {a}")
        w("")
    w("_Figures come from your lead-tracking tool. Small samples are marked: read them as direction, not proof._")
    return "\n".join(L) + "\n"


def path_for(ws: Workspace, month: str) -> Path:
    return ws.path(f"{REPORTS}/{month}-client-report.md")


def write(ws: Workspace, d: dict, at: datetime) -> Path:
    """Write or refresh the draft. An approved report is never overwritten."""
    path = path_for(ws, d["month"])
    if path.exists() and load(path)[0].get("status") == "approved":
        raise ValueError(f"The {d['label']} report is already approved; it won't be overwritten")
    notes = []
    if d["held_insights"]:
        notes.append(f"Left out {len(d['held_insights'])} insight record(s) not yet confirmed: "
                     + ", ".join(d["held_insights"]) + ". Set Status to confirmed to include one.")
    meta = {"month": d["month"], "status": "draft", "agent": AGENT, "created": iso(at), "operator_notes": notes}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, render(d)))
    return path


CHECKS = [
    (re.compile(r"\{[^{}]+\}"), "an unfilled placeholder"),
    (re.compile(r"Draft wording|operator to confirm", re.I), "draft wording meant for the operator"),
    (re.compile(r"`[a-z_]+:[^`]+`|\bmefw\b"), "internal references (sources or commands)"),
]


def _contact_details(text: str) -> bool:
    """Emails, phone numbers or card-like numbers. Dates such as 2026-10-25 look like phone numbers; skip them."""
    phones = [m.group(0) for m in PHONE.finditer(text) if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0))]
    return bool(EMAIL.search(text) or LONG_NUMBER.search(text) or phones)


def approve(ws: Workspace, month: str, by: str, at: datetime) -> tuple[dict, Path]:
    path = path_for(ws, month)
    if not path.exists():
        raise FileNotFoundError(f"No report for {month}. Make it first: `mefw report make --month {month}`")
    meta, body = load(path)
    if meta["status"] == "approved":
        raise ValueError(f"The {month} report is already approved")
    problems = [why for rx, why in CHECKS if rx.search(body)]
    names = [n for n in (*ws.config.agents, "scheduler") if re.search(rf"\b{re.escape(n)}\b", body)]
    if names:
        problems.append("internal agent names (" + ", ".join(names) + ")")
    if _contact_details(body):
        problems.append("something that looks like personal contact details")
    if problems:
        raise ValueError("Can't approve; the report contains " + "; ".join(problems) + ". Edit it and try again.")
    meta.update(status="approved", approved_by=by, approved_at=iso(at))
    path.write_text(dump(meta, body))
    out = path.with_suffix(".html")
    out.write_text(to_html(body, f"{month_label(month)} growth report"))
    return meta, out


# A small Markdown subset: the one render() writes, plus whatever an operator adds in the same style.
def _inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<em>\1</em>", t)
    return t


def to_html(md: str, title: str) -> str:
    out, lst, table = [], [], []

    def flush():
        if lst:
            out.append("<ul>" + "".join(lst) + "</ul>")
            lst.clear()
        if table:
            head, *rows = table
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table>")
            table.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                table.append(cells)
            continue
        if line.lstrip().startswith("- "):
            if table:
                flush()
            cls = ' class="sub"' if line.startswith("  ") else ""
            lst.append(f"<li{cls}>{_inline(line.lstrip()[2:])}</li>")
            continue
        flush()
        if line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    flush()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font: 16px/1.55 Georgia, 'Times New Roman', serif; color: #1d1d1b; background: #fff; max-width: 46rem;
       margin: 2.5rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.7rem; line-height: 1.25; margin-bottom: 1rem; }}
h2 {{ font: 600 0.8rem/1.4 system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: #5b5b57;
     border-top: 1px solid #ddd; padding-top: 1.2rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; font: 0.85rem/1.4 system-ui, sans-serif; margin: .5rem 0; }}
th, td {{ text-align: left; padding: .45rem .5rem; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
th {{ color: #5b5b57; font-weight: 600; }}
li {{ margin: .3rem 0; }} li.sub {{ margin-left: 1.5rem; list-style: circle; }}
em {{ color: #5b5b57; }}
@media print {{ body {{ margin: 0; max-width: none; }} }}
</style></head><body>
{chr(10).join(out)}
</body></html>
"""
