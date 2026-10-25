"""Content engine (Section 9.1): one insight becomes several assets, but only once it has resonated.

A Level 1 job. The agent doesn't write the posts. It writes a brief per
insight for whoever does, whether that's the operator, the founder or a writing
model. The brief carries:

- what customers keep saying, in their words (for language only)
- the approved facts that may be claimed for that segment
- angles to try, and one section per channel with the operator's format guidance
- a tracking tag, so inquiries can be traced back to the content

Only insight records the operator has confirmed, with enough evidence behind
them, get a brief. That is the spec's "only after the insight has shown it
resonates". Each insight gets a fresh brief at most every `refresh_days`.

The writer fills in the channel sections, then `mefw content approve` checks
every written asset. Claims must come from approved facts usable for the
segment. Banned phrases, sensitive-data requests and missing required text are
blocked. A quotation that looks like a customer's words is also blocked unless
the operator confirms they have that person's permission, because the engine
never invents testimonials. Publishing is done by a human, who records it with
`mefw content published`. `mefw content results` then counts the inquiries
that came in carrying each brief's tag, and how far they got.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from ...core.client_report import CLIENT_READY, _client_quote, _field
from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import Ledger, iso, parse_ts
from ...core.workspace import Workspace
from ..conversion.checks import Issue, check_text

AGENT = "content-brief-writer"
PLAYBOOK = "engines/content/playbook.toml"
BRIEFS = "engines/content/briefs"
RESULTS = "engines/content/results.md"
WRITE_HERE = "_Write here._"
DEFAULTS = {"min_evidence": 5, "refresh_days": 60, "tag_prefix": "mefw"}
QUOTE = re.compile(r"[\"“]([^\"”]{25,})[\"”]")  # a quotation long enough to be someone's words


def settings(ws: Workspace) -> dict:
    return {**DEFAULTS, **ws.config.content}


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Set up the channels and their guidance first.")
    pb = tomllib.loads(path.read_text()).get("content", {})
    if not pb.get("channels"):
        raise ValueError(f"{PLAYBOOK} has no [content.channels.<name>] sections")
    return pb


def _evidence_count(text: str) -> int:
    """The most signals behind the insight on any one day: the record's Evidence line or its evidence log."""
    best = 0
    m = re.search(r"(\d+)\s+signals?", _field(text, "Evidence"))
    if m:
        best = int(m.group(1))
    log = text.split("## Evidence log", 1)[1] if "## Evidence log" in text else ""
    for line in log.splitlines():
        if line.startswith("- "):
            more = re.search(r"and (\d+) more", line)
            best = max(best, len(re.findall(r"`[^`]+`", line)) + (int(more.group(1)) if more else 0))
    return best


def _segment_key(ws: Workspace, label: str) -> str:
    for name in ws.segment_names():
        if ws.segment_label(name) == label:
            return name
    return "all"


def all_briefs(ws: Workspace) -> list[tuple[Path, dict, str]]:
    d = ws.path(BRIEFS)
    return [(p, *load(p)) for p in sorted(d.glob("C-*.md"))] if d.exists() else []


def find(ws: Workspace, brief_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in all_briefs(ws):
        if meta["id"].lower() == brief_id.lower():
            return p, meta, body
    raise KeyError(f"No brief {brief_id}")


def candidates(ws: Workspace, as_of: datetime, ledger: Ledger | None = None) -> tuple[list[dict], list[str]]:
    """Confirmed insights with enough evidence and no recent brief; plus why others were passed over."""
    cfg = settings(ws)
    said = {s["ref"]: s["text"] for s in ledger.signals(as_of)} if ledger else {}
    recent = {m["insight"] for _, m, _ in all_briefs(ws)
              if parse_ts(m["created"]) > as_of - timedelta(days=int(cfg["refresh_days"]))}
    out, passed = [], []
    d = ws.path("customer-truth/insights")
    for path in sorted(d.glob("*.md")) if d.exists() else []:
        text = path.read_text()
        status = _field(text, "Status").lower()
        if status not in CLIENT_READY or "Draft wording" in _field(text, "Statement"):
            continue
        n = _evidence_count(text)
        if n < int(cfg["min_evidence"]):
            passed.append(f"{path.stem} ({n} signals; needs {cfg['min_evidence']})")
            continue
        if path.stem in recent:
            continue
        title = re.search(r"^## Insight: (.+)$", text, re.M)
        quotes = [_client_quote(_field(text, "Customer language"))]
        # More of their words: the signals the evidence log points at, newest first.
        log = text.split("## Evidence log", 1)[-1]
        for ref in reversed(re.findall(r"`([^`]+)`", log)):
            if ref in said:
                words = re.sub(r"\s+", " ", said[ref]).strip()
                quotes.append(f'"{words[:160]}{"…" if len(words) > 160 else ""}"')
        segment_label = _field(text, "Segment")
        out.append({
            "insight": path.stem, "title": title.group(1).strip() if title else path.stem,
            "statement": _field(text, "Statement"), "confidence": _field(text, "Confidence") or "low",
            "segment_label": segment_label, "segment": _segment_key(ws, segment_label), "evidence": n,
            "quotes": [q for q in dict.fromkeys(quotes) if q][:4],
        })
    return out, passed


def tag_for(ws: Workspace, insight: str) -> str:
    return f"{settings(ws)['tag_prefix']}-{re.sub(r'[^a-z0-9]+', '-', insight.lower()).strip('-')}"


def make_brief(ws: Workspace, c: dict, as_of: datetime) -> dict:
    pb = load_playbook(ws)
    today = as_of.date()
    facts = {k: f for k, f in load_facts(ws).items() if f.problem(today, c["segment"]) is None}
    tag = tag_for(ws, c["insight"])
    brief_id = f"C-{as_of:%Y%m%d}-{c['insight']}"
    meta = {"id": brief_id, "status": "brief", "agent": AGENT, "insight": c["insight"], "segment": c["segment"],
            "tag": tag, "created": iso(as_of), "channels": list(pb["channels"]), "facts": sorted(facts),
            "published": []}
    L = [f"## Brief: {c['title']}", "",
         f"- **Insight:** {c['statement']} _(confidence {c['confidence']}, {c['evidence']} signals; "
         f"`customer-truth/insights/{c['insight']}.md`)_",
         f"- **Audience:** {c['segment_label']}",
         "- **Their words** (use the language; don't quote anyone publicly without their permission):"]
    L += [f"  - {q}" for q in c["quotes"]] or ["  - none recorded"]
    L.append("- **Facts you may claim** (nothing else: no prices, numbers or promises that aren't here):")
    L += [f"  - `{k}`: {f.text}" for k, f in sorted(facts.items())] or ["  - none approved for this segment yet"]
    L.append("- **Angles to try:**")
    L += [f"  - **{name}:** {text}" for name, text in pb.get("angles", {}).items()] or ["  - your call"]
    L.append(f"- **Tracking:** add `utm_campaign={tag}` to every link, so inquiries from this content carry "
             f"`{tag}` in the lead tool's campaign field.")
    L += ["", "## Assets", "",
          "Write in the sections you want to publish. Leave the rest as they are; they're skipped.", ""]
    for name, ch in pb["channels"].items():
        L += [f"### {ch.get('label', name)}", "", f"_Guidance: {ch.get('guidance', 'Keep it short and specific.')}_",
              "", WRITE_HERE, ""]
    L += ["## Checks", "", f"_Run `mefw content approve {brief_id}` once the assets are written._", ""]
    path = ws.path(f"{BRIEFS}/{brief_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, "\n".join(L)))
    return meta


def assets(ws: Workspace, body: str) -> dict[str, str]:
    """The written channel sections, keyed by channel name; unwritten ones are left out."""
    pb = load_playbook(ws)
    labels = {ch.get("label", name): name for name, ch in pb["channels"].items()}
    section = body.split("## Assets", 1)[-1].split("\n## Checks", 1)[0]
    out = {}
    for m in re.finditer(r"^### ([^\n]+)\n(.*?)(?=^### |\Z)", section, re.S | re.M):
        text = "\n".join(ln for ln in m.group(2).strip().splitlines()
                         if not ln.startswith("_Guidance:") and ln.strip() != WRITE_HERE).strip()
        if text and m.group(1).strip() in labels:
            out[labels[m.group(1).strip()]] = text
    return out


def check_asset(ws: Workspace, text: str, segment: str, today, quote_permission: bool) -> list[Issue]:
    pb = load_playbook(ws)
    issues = [i for i in check_text(ws, text, load_facts(ws), segment, today, pb.get("must_include", []))
              if i.blocking]
    if not quote_permission:
        for q in QUOTE.findall(text):
            issues.append(Issue("testimonial", f"quotes someone (\"{q[:40]}...\"). Only publish a customer's "
                                               "words with their permission; then approve with --quote-permission"))
    return issues


def approve(ws: Workspace, brief_id: str, by: str, at: datetime, quote_permission: bool = False) -> dict:
    path, meta, body = find(ws, brief_id)
    if meta["status"] not in ("brief", "approved"):
        raise ValueError(f"{brief_id} is {meta['status']}")
    written = assets(ws, body)
    if not written:
        raise ValueError(f"Nothing written in {brief_id} yet. Fill in at least one channel under ## Assets.")
    problems = {ch: check_asset(ws, text, meta["segment"], at.date(), quote_permission) for ch, text in written.items()}
    lines = [f"  - {ch}: {i.check}: {i.message}" for ch, issues in problems.items() for i in issues]
    if lines:
        raise ValueError("Can't approve; these assets fail checks:\n" + "\n".join(lines))
    meta.update(status="approved", approved_by=by, approved_at=iso(at), approved_assets=sorted(written),
                quote_permission=quote_permission)
    body = body.split("\n## Checks", 1)[0] + (
        f"\n## Checks\n\n- ✅ {', '.join(sorted(written))}: facts, claims, banned language, sensitive data, "
        f"required text{', quotes (permission confirmed)' if quote_permission else ', no quotations'}\n"
        f"- Approved by {by} on {at.date().isoformat()}. Publish them yourself, then "
        f"`mefw content published {meta['id']} --channel <name> --url <link>`.\n")
    path.write_text(dump(meta, body))
    return meta


def published(ws: Workspace, brief_id: str, channel: str, url: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, brief_id)
    if meta["status"] not in ("approved", "published"):
        raise ValueError(f"{brief_id} is {meta['status']}; approve it before publishing")
    if channel not in meta.get("approved_assets", []):
        raise ValueError(f"No approved {channel} asset in {brief_id}; approved: {', '.join(meta['approved_assets'])}")
    meta["published"] = [*meta.get("published", []), {"channel": channel, "url": url, "at": iso(at), "by": by}]
    meta["status"] = "published"
    path.write_text(dump(meta, body))
    return meta


def results(ws: Workspace, ledger: Ledger, as_of: datetime) -> list[dict]:
    """Inquiries that carry each published brief's tag, and how far they got, against the rest of the segment."""
    states = ledger.states(as_of)
    rows = []
    for _, meta, _ in all_briefs(ws):
        if not meta.get("published"):
            continue
        since = min(parse_ts(p["at"]) for p in meta["published"])
        tagged = [s for s in states if (s.campaign or "").lower() == meta["tag"].lower() and s.inquired_at >= since]
        seg = meta["segment"]
        others = [s for s in states if s.inquired_at >= since and (s.campaign or "").lower() != meta["tag"].lower()
                  and (seg == "all" or ws.segment_for(s.segment) == seg)]

        def rate(group, stage):
            return (sum(1 for s in group if s.reached(stage)) / len(group)) if group else None
        rows.append({
            "id": meta["id"], "insight": meta["insight"], "tag": meta["tag"], "segment": ws.segment_label(seg),
            "since": iso(since), "channels": sorted({p["channel"] for p in meta["published"]}),
            "inquiries": len(tagged), "meetings": sum(1 for s in tagged if s.reached("meet")),
            "won": sum(1 for s in tagged if s.outcome == "won"),
            "meet_rate": rate(tagged, "meet"), "others_meet_rate": rate(others, "meet"), "others": len(others),
        })
    return rows


def render_results(rows: list[dict], as_of: datetime) -> str:
    L = [f"# Content results, {as_of.date().isoformat()}", "",
         "Inquiries that came in carrying a brief's tag since it was first published. A rate from a handful of "
         "inquiries is a direction, not proof (Section 13.2).", ""]
    if not rows:
        L.append("Nothing published yet.")
        return "\n".join(L) + "\n"
    L += ["| Brief | Segment | Channels | Inquiries | Meetings | Won | Meeting rate | Rest of segment |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mr = f"{r['meet_rate']:.0%}" if r["meet_rate"] is not None else "–"
        orr = f"{r['others_meet_rate']:.0%} of {r['others']}" if r["others_meet_rate"] is not None else "–"
        L.append(f"| {r['id']} | {r['segment']} | {', '.join(r['channels'])} | {r['inquiries']} | {r['meetings']} | "
                 f"{r['won']} | {mr} | {orr} |")
    return "\n".join(L) + "\n"
