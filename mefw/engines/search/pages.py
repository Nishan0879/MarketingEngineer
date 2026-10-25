"""Page and FAQ drafts for search (Section 9.5). A Level 1 job: it drafts, a human approves and publishes.

For each topic with a search opportunity or a buyer question no page answers,
the agent drafts an FAQ entry. The question is in the searcher's words, and
the answer comes only from approved facts tagged with that topic. A topic with
no such fact gets a blocking `{answer needed: <topic>}` line, so the engine
routes to a human instead of guessing. The draft says which page to improve,
or that a new one is needed, and leaves room for the business's own point of
view.

`mefw search approve` runs the same checks as other drafts (claims only from
approved facts, banned language, sensitive data, required text). It also
blocks keyword stuffing (a search query repeated over and over), review
gating (asking only happy customers for reviews) and quotations that look
like reviews or testimonials, unless the operator confirms permission. A
human publishes the change and records it with `mefw search published`.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import Ledger, iso, parse_ts
from ...core.pii import scrub
from ...core.workspace import Workspace
from ..content.briefs import QUOTE
from ..conversion.checks import Issue, check_text
from . import analysis, data

AGENT = "search-page-drafter"
DRAFTS = "engines/search/drafts"
QUESTION_WORDS = ("how", "what", "is", "are", "do", "does", "can", "where", "when", "why", "which", "who")
GATING = re.compile(
    r"\b(?:if you(?:'re| are| were)? (?:happy|satisfied|pleased)|only (?:happy|satisfied) (?:customers|members)|"
    r"(?:5|five)[- ]star reviews? only|leave (?:us )?a (?:good|great|positive) review|"
    r"(?:not happy|unhappy|had a problem)[^.]*\b(?:contact|email|tell) us (?:first|instead))",
    re.I,
)


def all_drafts(ws: Workspace) -> list[tuple[Path, dict, str]]:
    d = ws.path(DRAFTS)
    return [(p, *load(p)) for p in sorted(d.glob("S-*.md"))] if d.exists() else []


def find(ws: Workspace, draft_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in all_drafts(ws):
        if meta["id"].lower() == draft_id.lower():
            return p, meta, body
    raise KeyError(f"No search draft {draft_id}")


def candidates(ws: Workspace, ledger: Ledger, as_of: datetime) -> list[dict]:
    """One per topic: the opportunities and buyer questions it covers, best first; topics drafted lately left out."""
    pb = data.load_playbook(ws)
    snaps = data.snapshots(ws, as_of.date())
    ranked = analysis.opportunities(ws, pb, snaps[-1])[0] if snaps else []
    recent = {m["topic"] for _, m, _ in all_drafts(ws)
              if parse_ts(m["created"]) > as_of - timedelta(days=int(pb["refresh_days"]))}
    by_topic: dict[str, dict] = {}
    labels = {t.key: t.label for t in data.topics(ws, pb)}
    for r in ranked:
        if r["topic"] and r["topic"] not in recent:
            c = by_topic.setdefault(r["topic"], {"topic": r["topic"], "label": r["topic_label"], "queries": [],
                                                 "score": 0.0, "asked": 0, "page": r["page"]})
            c["queries"].append(r)
            c["score"] += r["score"]
    for g in analysis.gaps(ws, pb, ledger, as_of):
        if g["topic"] not in recent:
            c = by_topic.setdefault(g["topic"], {"topic": g["topic"], "label": labels[g["topic"]], "queries": [],
                                                 "score": 0.0, "asked": 0, "page": None})
            c["asked"] = g["asked"]
            c["score"] += 3 * math.log10(g["asked"] + 1)  # weighed like a high-intent query in reach
    return sorted(by_topic.values(), key=lambda c: (-c["score"], c["topic"]))


def _question(c: dict) -> str:
    """The searcher's own question if they typed one; otherwise a plain one about the topic."""
    for r in c["queries"]:
        q = r["query"].strip()
        if q.split()[0].lower() in QUESTION_WORDS:
            return q[0].upper() + q[1:].rstrip("?") + "?"
    return f"What should I know about {c['label'].lower()}?"


def _their_words(ws: Workspace, ledger: Ledger, topic: data.Topic, as_of: datetime) -> list[str]:
    out = []
    for s in reversed(ledger.signals(as_of)):
        if s["text"] and s["kind"] in analysis.BUYER_WORDS and topic.asked_in(s["text"]) and s["at"] >= as_of - timedelta(days=analysis.GAP_DAYS):
            words = re.sub(r"\s+", " ", scrub(s["text"])).strip()
            words = f"{words[:160]}{'…' if len(words) > 160 else ''}"
            if words not in out:
                out.append(words)
        if len(out) == 3:
            break
    return out


def make_draft(ws: Workspace, ledger: Ledger, c: dict, as_of: datetime) -> dict:
    pb = data.load_playbook(ws)
    today = as_of.date()
    facts = [f for f in load_facts(ws).values() if c["topic"] in f.topics and f.problem(today) is None]
    topic = next(t for t in data.topics(ws, pb) if t.key == c["topic"])
    draft_id = f"S-{as_of:%Y%m%d}-{data.slug(c['topic'])}"
    page = c["page"]
    meta = {"id": draft_id, "status": "draft", "agent": AGENT, "topic": c["topic"], "page": page or "new",
            "queries": [q["query"] for q in c["queries"][:5]], "created": iso(as_of),
            "facts": sorted(f.key for f in facts), "published": []}
    where = (f"improve `{page}` ({pb['pages'][page].get('label', page)})" if page
             else "a new FAQ entry or page; no page in `[search.pages]` covers this yet")
    L = [f"## Search draft: {c['label']}", "", f"- **Where:** {where}"]
    if c["queries"]:
        L.append("- **What people search** (latest snapshot):")
        L += [f"  - \"{q['query']}\": {q['impressions']} impressions, {q['clicks']} clicks, position {q['position']}"
              for q in c["queries"][:5]]
    if c["asked"]:
        L.append(f"- **Buyers asked about it** {c['asked']} time(s) in the last {analysis.GAP_DAYS} days. "
                 "In their words (for language only; don't quote anyone):")
        L += [f"  - {w}" for w in _their_words(ws, ledger, topic, as_of)]
    L.append("- **Facts you may use:** " + (", ".join(f"`{f.key}`" for f in facts) if facts else
                                             "none tagged with this topic yet; add one or write the answer by hand"))
    L += ["", "## FAQ", "", f"### {_question(c)}", ""]
    if facts:
        segs = {s: ws.segment_label(s) for f in facts for s in f.segments}
        for f in facts:
            prefix = f"For {', '.join(segs[s] for s in f.segments)}: " if f.segments else ""
            L.append(prefix + f.text)
    else:
        L.append(f"{{answer needed: {c['label'].lower()}}}")
    L += ["", "_Add one sentence of the business's own point of view if it has one. Write for the reader, not "
              "the search engine: say the query once, plainly._", "",
          "## Checks", "", f"_Run `mefw search approve {draft_id}` once it reads right._", ""]
    path = ws.path(f"{DRAFTS}/{draft_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, "\n".join(L)))
    return meta


def faq_text(body: str) -> str:
    section = body.split("## FAQ", 1)[-1].split("\n## Checks", 1)[0]
    return "\n".join(ln for ln in section.strip().splitlines() if not ln.startswith("_")).strip()


def check(ws: Workspace, text: str, queries: list[str], today, quote_permission: bool) -> list[Issue]:
    pb = data.load_playbook(ws)
    issues = [i for i in check_text(ws, text, load_facts(ws), None, today, pb["must_include"]) if i.blocking]
    limit = int(pb["max_query_repeats"])
    for q in queries:
        n = len(re.findall(rf"\b{re.escape(q)}\b", text, re.I))
        if len(q.split()) >= 2 and n > limit:
            issues.append(Issue("stuffing", f"\"{q}\" appears {n} times (limit {limit}); write for the reader"))
    if GATING.search(text):
        issues.append(Issue("reviews", "asks only happy customers for reviews (review gating); ask everyone or no one"))
    if not quote_permission:
        for q in QUOTE.findall(text):
            issues.append(Issue("testimonial", f"quotes someone (\"{q[:40]}...\"). Only publish a review or "
                                               "customer's words with their permission; then approve with "
                                               "--quote-permission"))
    return issues


def approve(ws: Workspace, draft_id: str, by: str, at: datetime, quote_permission: bool = False) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] not in ("draft", "approved"):
        raise ValueError(f"{draft_id} is {meta['status']}")
    text = faq_text(body)
    issues = check(ws, text, meta.get("queries", []), at.date(), quote_permission)
    if issues:
        raise ValueError("Can't approve; the draft fails checks:\n" +
                         "\n".join(f"  - {i.check}: {i.message}" for i in issues))
    meta.update(status="approved", approved_by=by, approved_at=iso(at), quote_permission=quote_permission)
    body = body.split("\n## Checks", 1)[0] + (
        "\n## Checks\n\n- ✅ facts, claims, banned language, sensitive data, required text, keyword stuffing, "
        f"review gating{', quotes (permission confirmed)' if quote_permission else ', no quotations'}\n"
        f"- Approved by {by} on {at.date().isoformat()}. Put it on the site yourself, then "
        f"`mefw search published {meta['id']} --url <link>`.\n")
    path.write_text(dump(meta, body))
    return meta


def published(ws: Workspace, draft_id: str, url: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, draft_id)
    if meta["status"] not in ("approved", "published"):
        raise ValueError(f"{draft_id} is {meta['status']}; approve it before publishing")
    meta["published"] = [*meta.get("published", []), {"url": url, "at": iso(at), "by": by}]
    meta["status"] = "published"
    path.write_text(dump(meta, body))
    return meta
