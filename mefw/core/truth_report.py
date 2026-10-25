"""Writes customer truth to memory (Sections 8.2 and 8.6).

- customer-truth/what-the-market-is-telling-us.md: the running view, replaced each run
- customer-truth/updates/YYYY-MM-DD.md (+ .json): a dated copy, so history is kept
- customer-truth/insights/<theme>--<segment>.md: one insight record per theme and
  segment. Created once, never rewritten: later runs only append dated evidence,
  because the operator curates these files.
"""

from __future__ import annotations

import json
from pathlib import Path

from .evidence import rate, refs_md
from .workspace import Workspace

ARROWS = {"new": "new", "rising": "rising", "falling": "falling", "steady": "steady"}


def render(data: dict, source_note: str) -> str:
    L: list[str] = []
    w = L.append
    w(f"# What the market is telling us — {data['client']}")
    w("")
    w(f"_Updated {data['as_of'][:10]} by `customer-truth-analyst` (Level 0). "
      f"Generated from {source_note}; edit the insight records, not this file._")
    w("")
    w("## This period's headline")
    w("")
    w(data["headline"])
    if data.get("headline_refs"):
        w("")
        w(f"Receipts: {refs_md(data['headline_refs'])}")
    w("")
    for q in data.get("open_questions", []):
        w(f"- {q}")
    if data.get("open_questions"):
        w("")
    segs = data["segments"]
    single = len(segs) == 1
    for seg in segs.values():
        h = "##" if single else "###"
        if not single:
            w(f"## {seg['label']}")
            w("")
            w(seg["headline"])
            w("")
        _segment(L, seg, data["settings"], h)
    return "\n".join(L) + "\n"


def _segment(L: list[str], d: dict, s: dict, h: str) -> None:
    w = L.append
    period = s["period_days"]
    kinds = ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in sorted(d["by_kind"].items())) or "none"
    w(f"Signals in the last {period} days: **{d['current_signals']}** ({kinds}). "
      f"Baseline: {d['baseline_signals']} over the {s['baseline_periods']} periods before.")
    w("")

    w(f"{h} Rising pains and language")
    w("")
    moving = [t for t in d["trends"] if t["direction"] in ("new", "rising", "falling")]
    if not moving:
        w(f"Nothing rose or fell clearly (a theme needs {s['min_mentions']}+ mentions this period).")
    for t in moving:
        w(f"- **{t['label']}** — {ARROWS[t['direction']]}: {t['current']} this period vs. "
          f"~{t['baseline_avg']:g} per period before." + (f" {refs_md(t['refs'], 5)}" if t["refs"] else ""))
        for q in t["quotes"]:
            w(f"  - \"{q['text']}\" ({q['kind'].replace('_', ' ')}, `{q['ref']}`)")
    w("")
    steady = [t for t in d["trends"] if t["direction"] == "steady" and t["current"]]
    if steady:
        w("Steady: " + ", ".join(f"{t['label'].lower()} {t['current']}" for t in steady) + ".")
        w("")

    w(f"{h} Objections")
    w("")
    if not d["objections"]:
        w("No lost reasons or lost-deal notes matched a theme in this window.")
    for o in d["objections"][:6]:
        w(f"- **{o['label']}**: {o['count']} — \"{o['quote']['text']}\" (`{o['quote']['ref']}`). "
          f"{refs_md(o['refs'], 5)}")
    w("")

    wl = d["won_vs_lost"]
    w(f"{h} What converted vs. what didn't")
    w("")
    w(f"Themes in conversations with leads that later committed ({wl['won_leads']}) vs. those that were lost "
      f"({wl['lost_leads']}).")
    w("")
    if wl["rows"]:
        w("| Theme | Won leads mentioning | Lost leads mentioning |")
        w("|---|---|---|")
        for r in wl["rows"]:
            w(f"| {r['label']} | {r['won']} ({rate(r['won'], wl['won_leads'])}) | "
              f"{r['lost']} ({rate(r['lost'], wl['lost_leads'])}) |")
        w("")
    w(f"**Confidence: {wl['confidence']}** — {wl['why']}. A theme showing up more among won leads is a "
      "lead for a test, not proof that it causes commitment.")
    w("")

    w(f"{h} Open questions")
    w("")
    if not d["open_questions"]:
        w("- None this period.")
    for q in d["open_questions"]:
        w(f"- {q['text']}" + (f" {refs_md(q['refs'], 5)}" if q["refs"] else ""))
    w("")


INSIGHT_TEMPLATE = """## Insight: {label} ({segment_label})
- **Status:** {status}
- **Segment:** {segment_label}
- **Date observed:** {date}
- **Statement:** {statement}
- **Customer language:** "{quote}" ({quote_ref})
- **Evidence:** {evidence}
- **Confidence:** {confidence}
- **Related experiments:**
- **Retired reason (if retired):**

_Drafted by `customer-truth-analyst`. The operator owns this record: edit the statement, status and confidence freely; the agent only appends below._

## Evidence log
"""


def write_insights(ws: Workspace, data: dict) -> list[str]:
    """Create insight records for themes with enough evidence; append evidence to existing ones."""
    out_dir = ws.path("customer-truth/insights")
    out_dir.mkdir(parents=True, exist_ok=True)
    min_mentions = data["settings"]["min_mentions"]
    date = data["as_of"][:10]
    touched = []
    for seg_name, seg in data["segments"].items():
        candidates = {}
        for t in seg["trends"]:
            if t["direction"] in ("new", "rising") and t["current"] >= min_mentions:
                candidates[t["theme"]] = (t["label"], t["refs"], t["quotes"][0] if t["quotes"] else None,
                                          f"{t['label']} came up {t['current']} times in {data['settings']['period_days']} days "
                                          f"(~{t['baseline_avg']:g} per period before).")
        for o in seg["objections"]:
            if o["count"] >= min_mentions and o["theme"] not in candidates:
                candidates[o["theme"]] = (o["label"], o["refs"], o["quote"],
                                          f"{o['label']} was given as a reason for not moving forward {o['count']} times.")
        for theme, (label, refs, q, statement) in candidates.items():
            path = out_dir / f"{theme}--{seg_name}.md"
            line = f"- {date}: {statement} {refs_md(refs, 10)}\n"
            if path.exists():
                text = path.read_text()
                if f"- {date}:" not in text:  # one entry per day; never rewrite what's there
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(line)
                    touched.append(str(path.relative_to(ws.root)))
                continue
            n = len(refs)
            path.write_text(INSIGHT_TEMPLATE.format(
                label=label, segment_label=seg["label"], status="observed", date=date,
                statement=f"{statement} Draft wording; operator to confirm.",
                quote=q["text"] if q else "", quote_ref=f"`{q['ref']}`" if q else "",
                evidence=f"{n} signals: {refs_md(refs, 10)}",
                confidence="medium" if n >= 3 * min_mentions else "low",
            ) + line)
            touched.append(str(path.relative_to(ws.root)))
    return touched


def write_outputs(ws: Workspace, data: dict, source_note: str) -> dict:
    md = render(data, source_note)
    main = ws.path("customer-truth/what-the-market-is-telling-us.md")
    main.write_text(md)
    upd = ws.path("customer-truth/updates")
    upd.mkdir(parents=True, exist_ok=True)
    stem = data["as_of"][:10]
    (upd / f"{stem}.md").write_text(md)
    (upd / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n")
    insights = write_insights(ws, data)
    return {"report": str(main.relative_to(ws.root)), "snapshot": f"customer-truth/updates/{stem}.md",
            "insights": insights}
