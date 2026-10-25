"""Search visibility inputs (Section 9.5): the playbook, search performance snapshots and AI assistant checks.

Search performance comes from a Search Console export (or any tool with the
same columns): one row per query, with clicks, impressions, click rate and
average position. Each import is kept as a snapshot for the period it covers,
and a snapshot is never overwritten. Queries are scrubbed of contact details
before they're stored.

Nothing here calls a search engine or an AI assistant. The operator runs the
monthly assistant checks by hand and records what came back with
`mefw search ai-record`; the records are append-only.
"""

from __future__ import annotations

import csv
import json
import re
import tomllib
from datetime import date, datetime
from pathlib import Path

from ...core.ledger import iso, parse_ts
from ...core.pii import scrub
from ...core.workspace import Workspace
from ..conversion import first_response, queue

PLAYBOOK = "engines/search/playbook.toml"
SNAPSHOTS = "engines/search/snapshots"
AI_LOG = "engines/search/ai-checks.jsonl"
DEFAULTS = {"brand_terms": [], "min_impressions": 10, "must_include": [], "max_query_repeats": 2,
            "refresh_days": 90, "listing_check_days": 90, "ai_check_days": 30, "search_channels": []}


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Set up pages, intent terms and listings first.")
    pb = tomllib.loads(path.read_text()).get("search", {})
    return {**DEFAULTS, **pb}


Topic = first_response.Topic  # a subject buyers ask about, with the words that give it away


def topics(ws: Workspace, pb: dict) -> list[Topic]:
    """The first-response topics, plus any the search playbook adds."""
    out: dict[str, Topic] = {}
    try:
        for t in first_response.topics(queue.load_playbook(ws)):
            out[t.key] = Topic(t.key, t.label, t.keywords)
    except FileNotFoundError:
        pass
    for k, v in pb.get("topics", {}).items():
        out[k] = Topic(k, v.get("label", k), list(v.get("keywords", [])))
    return list(out.values())


def topic_for(text: str, all_topics: list[Topic]) -> Topic | None:
    return next((t for t in all_topics if t.asked_in(text)), None)


def pages_for(pb: dict, topic: str) -> list[tuple[str, str]]:
    """Existing pages that cover a topic, as (path, label)."""
    return [(p, v.get("label", p)) for p, v in pb.get("pages", {}).items() if topic in v.get("topics", [])]


def is_brand(pb: dict, query: str) -> bool:
    return any(b.lower() in query.lower() for b in pb["brand_terms"] if b)


def _num(raw: str | None) -> float:
    raw = (raw or "").strip().rstrip("%").replace(",", "")
    return float(raw) if raw else 0.0


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty")
        key = reader.fieldnames[0]  # "Top queries", "Query", "Top pages" or "Page"
        need = {"Clicks", "Impressions", "Position"}
        if not need <= set(reader.fieldnames):
            raise ValueError(f"{path} needs the columns {', '.join(sorted(need))} (a Search Console export)")
        out = []
        for r in reader:
            if not (r.get(key) or "").strip():
                continue
            impressions = _num(r["Impressions"])
            clicks = _num(r["Clicks"])
            out.append({"key": r[key].strip(), "clicks": int(clicks), "impressions": int(impressions),
                        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
                        "position": round(_num(r["Position"]), 1)})
        return out


def import_snapshot(ws: Workspace, queries_csv: Path, period_end: date, days: int = 28,
                    pages_csv: Path | None = None, at: datetime | None = None) -> dict:
    queries = [{**r, "query": scrub(r.pop("key")).lower()} for r in _rows(queries_csv)]
    pages = [{**r, "page": r.pop("key")} for r in _rows(pages_csv)] if pages_csv else []
    snap = {"period_end": period_end.isoformat(), "days": days, "imported_at": iso(at or datetime.now()),
            "queries": queries, "pages": pages}
    path = ws.path(f"{SNAPSHOTS}/{period_end.isoformat()}.json")
    if path.exists():
        old = json.loads(path.read_text())
        if old["queries"] == queries and old["pages"] == pages:
            return {**old, "unchanged": True}
        raise ValueError(f"There's already a snapshot for the period ending {period_end}; snapshots are never "
                         "overwritten. Export the next period instead.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=1) + "\n")
    return snap


def snapshots(ws: Workspace, as_of: date | None = None) -> list[dict]:
    d = ws.path(SNAPSHOTS)
    out = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []
    return [s for s in out if as_of is None or date.fromisoformat(s["period_end"]) <= as_of]


def ai_checks(ws: Workspace) -> list[dict]:
    path = ws.path(AI_LOG)
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def record_ai_check(ws: Workspace, assistant: str, prompt: str, mentioned: bool, cited: str | None,
                    by: str, at: datetime, note: str = "") -> dict:
    pb = load_playbook(ws)
    ai = pb.get("ai", {})
    prompts = ai.get("prompts", {})
    if prompt not in prompts:
        raise ValueError(f"No prompt '{prompt}' under [search.ai.prompts]; known: {', '.join(prompts) or 'none'}")
    known = {a.lower(): a for a in ai.get("assistants", [])}
    if known and assistant.lower() not in known:
        raise ValueError(f"Assistant '{assistant}' isn't in [search.ai] assistants: {', '.join(known.values())}")
    assistant = known.get(assistant.lower(), assistant)
    entry = {"at": iso(at), "assistant": assistant, "prompt": prompt, "mentioned": mentioned,
             "cited": cited or None, "by": by, "note": scrub(note) or ""}
    path = ws.path(AI_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def ai_due(ws: Workspace, pb: dict, as_of: datetime) -> list[tuple[str, str]]:
    """(assistant, prompt) pairs not checked in the last ai_check_days."""
    ai = pb.get("ai", {})
    last: dict[tuple[str, str], datetime] = {}
    for e in ai_checks(ws):
        k = (e["assistant"].lower(), e["prompt"])
        last[k] = max(last.get(k, parse_ts(e["at"])), parse_ts(e["at"]))
    due = []
    for a in ai.get("assistants", []):
        for p in ai.get("prompts", {}):
            seen = last.get((a.lower(), p))
            if seen is None or (as_of - seen).days >= int(pb["ai_check_days"]):
                due.append((a, p))
    return due


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
