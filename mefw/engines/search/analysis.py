"""The weekly search visibility report (Section 9.5): opportunities, gaps, listings, AI assistants, results.

A Level 0 job: it reads and reports. The workflow in the spec is search data →
opportunities → check what exists → rank → draft → approve → publish → track.
This module does the reading, ranking and tracking; pages.py does the drafts.

Each query from the latest snapshot is ranked on four things:

- **buyer intent:** words that mean someone is ready to act ("near me",
  "price", "tour"), from `[search.intent]`
- **relevance:** whether it's about a topic buyers ask about (the
  first-response topics plus `[search.topics]`)
- **ranking distance:** positions 4 to 20 are the ones a better page can move;
  the top 3 have little left to gain and past 50 is a long way off
- **volume:** impressions, on a log scale so one big query doesn't drown the rest

Brand queries are reported apart. Then it checks what already exists: a page
in `[search.pages]` that covers the topic gets an "improve" action, and a topic
with no page gets a "new" one. Topics buyers raise in their own messages that
no page covers are listed too, because those are the questions to answer
before anyone searches for them (Section 9.5, "be the cited source").
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

from ...core.facts import load_facts
from ...core.ledger import Ledger
from ...core.workspace import Workspace
from . import data

AGENT = "search-analyst"
DISTANCE = ((3, 0.3), (10, 1.0), (20, 0.8), (50, 0.4))
TOP = 15
GAP_DAYS = 90
BUYER_WORDS = ("inquiry_message", "call_note", "tour_note", "review", "ticket", "survey", "social")  # not loss reasons


def _distance(position: float) -> float:
    return next((w for limit, w in DISTANCE if position <= limit), 0.1)


def _intent(pb: dict, query: str) -> tuple[int, str]:
    terms = pb.get("intent", {})
    for level, weight in (("high", 3), ("medium", 2)):
        if any(re.search(rf"\b{re.escape(t)}\b", query, re.I) for t in terms.get(level, [])):
            return weight, level
    return 1, "low"


def opportunities(ws: Workspace, pb: dict, snap: dict) -> tuple[list[dict], list[dict]]:
    """Ranked non-brand queries, and the brand ones."""
    all_topics = data.topics(ws, pb)
    ranked, brand = [], []
    for q in snap["queries"]:
        if data.is_brand(pb, q["query"]):
            brand.append(q)
            continue
        if q["impressions"] < int(pb["min_impressions"]):
            continue
        weight, intent = _intent(pb, q["query"])
        topic = data.topic_for(q["query"], all_topics)
        score = weight * (1.0 if topic else 0.5) * _distance(q["position"]) * math.log10(q["impressions"] + 1)
        pages = data.pages_for(pb, topic.key) if topic else []
        if not topic:
            action = "Decide whether it's a fit; no buyer topic matches it"
        elif pages:
            action = f"Improve {pages[0][0]} ({pages[0][1]}): answer it plainly on the page"
        else:
            action = f"New FAQ entry or page about {topic.label.lower()}"
        ranked.append({**q, "intent": intent, "topic": topic.key if topic else None,
                       "topic_label": topic.label if topic else None, "page": pages[0][0] if pages else None,
                       "score": round(score, 1), "action": action})
    ranked.sort(key=lambda r: (-r["score"], r["query"]))
    return ranked, sorted(brand, key=lambda q: -q["impressions"])


def gaps(ws: Workspace, pb: dict, ledger: Ledger, as_of: datetime) -> list[dict]:
    """Topics buyers raised in their own words in the last 90 days that no page covers."""
    all_topics = data.topics(ws, pb)
    counts: dict[str, int] = {}
    for s in ledger.signals(as_of):
        if s["at"] < as_of - timedelta(days=GAP_DAYS) or not s["text"] or s["kind"] not in BUYER_WORDS:
            continue
        for t in all_topics:
            if t.asked_in(s["text"]):
                counts[t.key] = counts.get(t.key, 0) + 1
    labels = {t.key: t.label for t in all_topics}
    return sorted(({"topic": k, "label": labels[k], "asked": n} for k, n in counts.items()
                   if not data.pages_for(pb, k)), key=lambda g: (-g["asked"], g["topic"]))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().rstrip(".")


def listings(ws: Workspace, pb: dict, today: date) -> list[dict]:
    """Each listing's problems: not checked lately, or saying something approved facts don't."""
    facts = load_facts(ws)
    out = []
    for name, lst in pb.get("listings", {}).items():
        problems = []
        checked = lst.get("checked_on")
        if not checked:
            problems.append("never checked; set checked_on once you've looked at it")
        elif (today - date.fromisoformat(str(checked))).days > int(pb["listing_check_days"]):
            problems.append(f"last checked {checked}; check it again")
        for field, f in lst.get("fields", {}).items():
            fact = facts.get(f.get("fact", ""))
            if fact is None:
                problems.append(f"{field}: names fact '{f.get('fact')}', which isn't in approved facts")
                continue
            problem = fact.problem(today)
            if problem:
                problems.append(f"{field}: {problem}, but the listing still shows it")
            elif _norm(f.get("says", "")) != _norm(fact.text):
                problems.append(f"{field}: says something other than approved fact `{fact.key}`; "
                                f"update it to \"{fact.text}\"")
        out.append({"listing": name, "label": lst.get("label", name), "checked_on": str(checked or ""),
                    "problems": problems})
    return out


def ai_summary(ws: Workspace, pb: dict, as_of: datetime) -> dict:
    latest: dict[tuple[str, str], dict] = {}
    for e in data.ai_checks(ws):
        k = (e["assistant"], e["prompt"])
        if k not in latest or e["at"] >= latest[k]["at"]:
            latest[k] = e
    rows = {}
    for (assistant, _), e in sorted(latest.items()):
        r = rows.setdefault(assistant, {"assistant": assistant, "checked": 0, "mentioned": 0, "cited": 0})
        r["checked"] += 1
        r["mentioned"] += bool(e["mentioned"])
        r["cited"] += bool(e["cited"])
    return {"rows": list(rows.values()), "due": data.ai_due(ws, pb, as_of),
            "prompts": pb.get("ai", {}).get("prompts", {})}


def results(ws: Workspace, pb: dict, ledger: Ledger, as_of: datetime, snaps: list[dict]) -> dict:
    """Search clicks over the last snapshots, and inquiries from search channels in the last 28 days."""
    trend = []
    for s in snaps[-4:]:
        nb = [q for q in s["queries"] if not data.is_brand(pb, q["query"])]
        trend.append({"period_end": s["period_end"], "days": s["days"],
                      "clicks": sum(q["clicks"] for q in nb), "impressions": sum(q["impressions"] for q in nb),
                      "brand_clicks": sum(q["clicks"] for q in s["queries"]) - sum(q["clicks"] for q in nb)})
    channels = {c.lower() for c in pb["search_channels"]}
    states = [s for s in ledger.states(as_of) if s.inquired_at and (s.channel or "").lower() in channels]

    def window(end: datetime) -> dict:
        group = [s for s in states if end - timedelta(days=28) < s.inquired_at <= end]
        met = sum(1 for s in group if s.reached("meet"))
        return {"inquiries": len(group), "meetings": met, "rate": met / len(group) if group else None}
    return {"trend": trend, "channels": sorted(pb["search_channels"]),
            "now": window(as_of), "before": window(as_of - timedelta(days=28))}


def published_movement(ws: Workspace, snaps: list[dict]) -> list[dict]:
    """For each published draft, where its queries ranked before it went live and in the latest snapshot."""
    from . import pages
    out = []
    for _, meta, _ in pages.all_drafts(ws):
        if meta["status"] != "published" or not snaps:
            continue
        went_live = meta["published"][0]["at"][:10]
        before = [s for s in snaps if s["period_end"] <= went_live]
        if not before:
            continue
        pos = lambda s, q: next((r["position"] for r in s["queries"] if r["query"] == q), None)  # noqa: E731
        for q in meta.get("queries", []):
            out.append({"id": meta["id"], "query": q, "before": pos(before[-1], q), "now": pos(snaps[-1], q),
                        "latest": snaps[-1]["period_end"]})
    return out


def analyze(ws: Workspace, ledger: Ledger, as_of: datetime) -> dict:
    pb = data.load_playbook(ws)
    snaps = data.snapshots(ws, as_of.date())
    ranked, brand = opportunities(ws, pb, snaps[-1]) if snaps else ([], [])
    return {
        "as_of": as_of.date().isoformat(), "snapshot": snaps[-1]["period_end"] if snaps else None,
        "opportunities": ranked, "brand": brand, "gaps": gaps(ws, pb, ledger, as_of),
        "listings": listings(ws, pb, as_of.date()), "ai": ai_summary(ws, pb, as_of),
        "results": results(ws, pb, ledger, as_of, snaps), "movement": published_movement(ws, snaps),
    }


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def render(d: dict) -> str:
    L = [f"# Search visibility, {d['as_of']}", ""]
    if not d["snapshot"]:
        L += ["No search data yet. Export the Queries table from Search Console for the last 28 days and run "
              "`mefw search import <file> --period-end <date>`.", ""]
    else:
        L += [f"From the search data for the {d['results']['trend'][-1]['days']} days to {d['snapshot']}.", ""]
    L += ["## Opportunities", ""]
    if d["opportunities"]:
        L += ["Ranked by buyer intent × relevance × ranking distance × volume. Brand searches are left out.", "",
              "| Query | Impressions | Clicks | Position | Intent | Topic | Score | Next step |",
              "|---|---|---|---|---|---|---|---|"]
        for r in d["opportunities"][:TOP]:
            L.append(f"| {r['query']} | {r['impressions']} | {r['clicks']} | {r['position']} | {r['intent']} | "
                     f"{r['topic_label'] or '–'} | {r['score']} | {r['action']} |")
        if len(d["opportunities"]) > TOP:
            L.append(f"\n_{len(d['opportunities']) - TOP} more below the cut._")
    else:
        L.append("None yet.")
    if d["brand"]:
        b = d["brand"]
        L += ["", f"Brand searches: {sum(q['clicks'] for q in b)} clicks from {sum(q['impressions'] for q in b)} "
                  f"impressions over {len(b)} {'query' if len(b) == 1 else 'queries'}."]
    L += ["", "## Questions buyers ask that no page answers", ""]
    if d["gaps"]:
        L += [f"- **{g['label']}:** came up {g['asked']} time(s) in the last {GAP_DAYS} days" for g in d["gaps"]]
    else:
        L.append("None. Every topic buyers raised has a page in `[search.pages]`.")
    L += ["", "## Listings", ""]
    if not d["listings"]:
        L.append("No listings recorded in `[search.listings]`.")
    for lst in d["listings"]:
        if lst["problems"]:
            L.append(f"- **{lst['label']}:** " + "; ".join(lst["problems"]))
        else:
            L.append(f"- **{lst['label']}:** matches approved facts (checked {lst['checked_on']})")
    ai = d["ai"]
    L += ["", "## AI assistants", ""]
    if ai["rows"]:
        L += ["| Assistant | Prompts checked | Mentioned us | Cited our site |", "|---|---|---|---|"]
        L += [f"| {r['assistant']} | {r['checked']} | {r['mentioned']} | {r['cited']} |" for r in ai["rows"]]
    else:
        L.append("No checks recorded yet.")
    if ai["due"]:
        L += ["", f"Due this month ({len(ai['due'])}): ask each assistant the prompt, then record it with "
                  "`mefw search ai-record --assistant <name> --prompt <key> --mentioned yes|no [--cited <url>]`."]
        for key, text in ai["prompts"].items():
            who = [a for a, p in ai["due"] if p == key]
            if who:
                L.append(f"- `{key}` \"{text}\": {', '.join(who)}")
    r = d["results"]
    L += ["", "## Results", ""]
    if r["trend"]:
        L += ["| Period ending | Clicks (not brand) | Impressions (not brand) | Brand clicks |", "|---|---|---|---|"]
        L += [f"| {t['period_end']} | {t['clicks']} | {t['impressions']} | {t['brand_clicks']} |" for t in r["trend"]]
        L.append("")
    if r["channels"]:
        n, b = r["now"], r["before"]
        L.append(f"Inquiries from search ({', '.join(r['channels'])}), last 28 days: {n['inquiries']} "
                 f"({n['meetings']} to a meeting, {_pct(n['rate'])}); the 28 days before: {b['inquiries']} "
                 f"({b['meetings']}, {_pct(b['rate'])}). Small numbers are a direction, not proof.")
    else:
        L.append("Set `search_channels` in the playbook to the lead tool's channel values for search, so inquiries "
                 "from search can be counted.")
    if d["movement"]:
        L += ["", "| Published draft | Query | Position before | Position now |", "|---|---|---|---|"]
        L += [f"| {m['id']} | {m['query']} | {m['before'] or '–'} | {m['now'] or '–'} |" for m in d["movement"]]
    return "\n".join(L) + "\n"


def write(ws: Workspace, d: dict) -> str:
    rel = f"engines/search/reports/{d['as_of']}.md"
    path = ws.path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(d))
    return rel
