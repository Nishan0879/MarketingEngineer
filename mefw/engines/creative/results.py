"""Creative testing engine, results and learning (Section 9.4).

The operator exports the ad platform's numbers to date (one row per ad, with
the variant's tag in the ad name) and imports them with `mefw creative
results-import`. Each export is kept as it came; the latest one is the
running total. Inquiries come from the lead ledger: leads whose campaign field
carries the variant's tag, that came in after the test started.

Each variant is judged on cost per qualified inquiry, cost per meeting and
cost per commitment. Click rate is shown as an early hint and never decides.
The verdict is a suggestion that follows the directional learning rules
(Section 13.2): too early until every live variant has `min_qualified`
qualified inquiries; stop a variant early once it has spent enough with
nothing to show; flag any spend over the approved budget. The operator closes
the test with `mefw creative close`, and the winner goes in
`engines/creative/winners.md`, which the next plan for that audience shows.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from ...core.ledger import Ledger, iso, parse_ts
from ...core.workspace import Workspace
from . import plans

RESULTS = "engines/creative/results"
COLUMNS = {"ad": "Ad name", "spend": "Amount spent", "impressions": "Impressions", "clicks": "Link clicks"}


def _num(raw: str | None) -> float:
    raw = (raw or "").strip().replace(",", "").lstrip("$€£")
    return float(raw) if raw else 0.0


def import_results(ws: Workspace, plan_id: str, path: Path, at: datetime) -> dict:
    """Totals to date per variant from an ad platform export. Rows that match no variant tag are counted."""
    _, meta, _ = plans.find(ws, plan_id)
    if meta["status"] not in ("running", "closed"):
        raise ValueError(f"{plan_id} is {meta['status']}; start it before importing results")
    cols = {**COLUMNS, **plans.load_playbook(ws).get("columns", {})}
    totals = {v["key"]: {"spend": 0.0, "impressions": 0, "clicks": 0} for v in meta["variants"]}
    unmatched = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in cols.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing column(s): {', '.join(missing)}. Map them under [creative.columns].")
        for row in reader:
            name = (row[cols["ad"]] or "").lower()
            v = next((v for v in sorted(meta["variants"], key=lambda v: -len(v["tag"])) if v["tag"].lower() in name),
                     None)
            if v is None:
                unmatched += 1
                continue
            t = totals[v["key"]]
            t["spend"] += _num(row[cols["spend"]])
            t["impressions"] += int(_num(row[cols["impressions"]]))
            t["clicks"] += int(_num(row[cols["clicks"]]))
    snap = {"plan": meta["id"], "imported_at": iso(at), "variants": totals, "unmatched_rows": unmatched}
    out = ws.path(f"{RESULTS}/{meta['id']}/{at:%Y-%m-%dT%H%M}.json")
    if out.exists():
        raise ValueError(f"Results for {meta['id']} were already imported at {at:%Y-%m-%d %H:%M}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1) + "\n")
    return snap


def latest(ws: Workspace, plan_id: str, as_of: datetime) -> dict | None:
    d = ws.path(f"{RESULTS}/{plan_id}")
    snaps = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []
    snaps = [s for s in snaps if parse_ts(s["imported_at"]) <= as_of]
    return snaps[-1] if snaps else None


def measure(ws: Workspace, ledger: Ledger, meta: dict, as_of: datetime) -> dict:
    pb = plans.load_playbook(ws)
    snap = latest(ws, meta["id"], as_of)
    started = parse_ts(meta["started_at"])
    states = [s for s in ledger.states(as_of) if s.inquired_at and s.inquired_at >= started]
    stage = pb["qualified_stage"]
    rows = []
    for v in meta["variants"]:
        if v["key"] not in meta.get("live_variants", []):
            continue
        ads = (snap or {}).get("variants", {}).get(v["key"], {"spend": 0.0, "impressions": 0, "clicks": 0})
        leads = [s for s in states if (s.campaign or "").lower() == v["tag"].lower()]
        r = {"key": v["key"], "angle": v["angle"], "tag": v["tag"], **ads,
             "ctr": ads["clicks"] / ads["impressions"] if ads["impressions"] else None,
             "inquiries": len(leads), "qualified": sum(1 for s in leads if s.reached(stage)),
             "meetings": sum(1 for s in leads if s.reached("meet")),
             "commits": sum(1 for s in leads if s.reached("commit"))}
        for k in ("qualified", "meetings", "commits"):
            r[f"cost_per_{k}"] = ads["spend"] / r[k] if r[k] else None
        rows.append(r)
    return {"id": meta["id"], "rows": rows, "imported_at": (snap or {}).get("imported_at"),
            "spend": sum(r["spend"] for r in rows), "budget": float(meta.get("planned_budget", 0)),
            "cap": float(meta.get("budget_cap", 0)), **verdict(pb, rows, float(meta.get("planned_budget", 0)))}


def verdict(pb: dict, rows: list[dict], budget: float) -> dict:
    """A suggested call, following the directional learning rules. The operator makes the real one."""
    notes, stop = [], []
    spend = sum(r["spend"] for r in rows)
    if budget and spend > budget:
        notes.append(f"Spend {pb['currency']}{spend:g} is over the approved {pb['currency']}{budget:g}. Pause it in "
                     "the ad tool; budget changes are yours, not the agent's.")
    with_q = [r for r in rows if r["cost_per_qualified"] is not None]
    best_cpq = min((r["cost_per_qualified"] for r in with_q), default=None)
    kill = float(pb["kill_spend"]) or (3 * best_cpq if best_cpq else 0)
    for r in rows:
        if kill and not r["qualified"] and r["spend"] >= kill:
            stop.append(r["key"])
    live = [r for r in rows if r["key"] not in stop]
    if not rows or not any(r["spend"] for r in rows):
        return {"suggested": "waiting", "reason": "no results imported yet", "stop": stop, "notes": notes}
    if len(live) < 2:
        leader = live[0]["key"].upper() if live else None
        return {"suggested": f"keep {leader}" if leader else "kill",
                "reason": "only one variant is still worth running" if leader else "no variant brought a "
                          "qualified inquiry", "stop": stop, "notes": notes}
    need = int(pb["min_qualified"])
    short = [r["key"].upper() for r in live if r["qualified"] < need]
    by = "cost_per_meetings" if all(r["meetings"] for r in live) else "cost_per_qualified"
    ranked = sorted(live, key=lambda r: (r[by] is None, r[by] or 0))
    leader = ranked[0]
    label = "cost per meeting" if by == "cost_per_meetings" else "cost per qualified inquiry"
    if short:
        return {"suggested": "too early", "stop": stop, "notes": notes,
                "reason": f"variant(s) {', '.join(short)} have fewer than {need} qualified inquiries; "
                          f"{leader['key'].upper()} leads on {label} so far"}
    return {"suggested": f"keep {leader['key'].upper()}", "stop": stop, "notes": notes,
            "reason": f"lowest {label} with at least {need} qualified inquiries per variant"}


def close(ws: Workspace, ledger: Ledger, plan_id: str, winner: str, lesson: str, by: str, at: datetime) -> dict:
    path, meta, body = plans.find(ws, plan_id)
    if meta["status"] != "running":
        raise ValueError(f"{plan_id} is {meta['status']}; only a running test can be closed")
    if not lesson.strip():
        raise ValueError("Write the lesson; it's what the next test learns from")
    winner = winner.lower()
    if winner != "none" and winner not in meta.get("live_variants", []):
        raise ValueError(f"Winner must be one of {', '.join(meta['live_variants'])} or none")
    m = measure(ws, ledger, meta, at)
    meta.update(status="closed", closed_by=by, closed_at=iso(at), winner=winner, lesson=lesson.strip(),
                final={r["key"]: {k: r[k] for k in ("spend", "qualified", "meetings", "commits")} for r in m["rows"]})
    plans.save(path, meta, body)
    if winner != "none":
        fields = plans.written(meta, body).get(winner, {})
        row = next(r for r in m["rows"] if r["key"] == winner)
        cur = plans.load_playbook(ws)["currency"]
        cpm = f"{cur}{row['cost_per_meetings']:.0f} per meeting" if row["cost_per_meetings"] else "no meetings yet"
        line = (f"- {at.date().isoformat()} [{meta['segment']}] {meta['id']} variant {winner.upper()} "
                f"({row['angle']}): "
                f"\"{fields.get('Headline', '–')}\"; {row['qualified']} qualified, {cpm}. {lesson.strip()}")
        wp = ws.path(plans.WINNERS)
        wp.parent.mkdir(parents=True, exist_ok=True)
        head = "" if wp.exists() else "# Creative winners\n\nWhat won, for whom, at what cost. Plans for the same " \
                                      "audience show the latest three.\n\n"
        with wp.open("a") as f:
            f.write(head + line + "\n")
    return meta


def _money(cur: str, x: float | None) -> str:
    return "–" if x is None else f"{cur}{x:,.0f}"


def render(ws: Workspace, measured: list[dict], as_of: datetime) -> str:
    cur = plans.load_playbook(ws)["currency"] if ws.path(plans.PLAYBOOK).exists() else "$"
    L = [f"# Creative tests, {as_of.date().isoformat()}", "",
         "Judged on cost per qualified inquiry, meeting and commitment. Click rate is only an early hint. A result "
         "from a handful of inquiries is a direction, not proof (Section 13.2).", ""]
    if not measured:
        L.append("No tests running.")
    for m in measured:
        L += [f"## {m['id']}", "",
              f"Spent {_money(cur, m['spend'])} of {_money(cur, m['budget'])} planned (cap {_money(cur, m['cap'])}); "
              f"results imported {m['imported_at'] or 'never'}.", "",
              "| Variant | Spend | Click rate | Inquiries | Qualified | Meetings | Commits | Per qualified | "
              "Per meeting | Per commit |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in m["rows"]:
            ctr = f"{r['ctr']:.1%}" if r["ctr"] is not None else "–"
            L.append(f"| {r['key'].upper()} ({r['angle']}) | {_money(cur, r['spend'])} | {ctr} | {r['inquiries']} | "
                     f"{r['qualified']} | {r['meetings']} | {r['commits']} | {_money(cur, r['cost_per_qualified'])} | "
                     f"{_money(cur, r['cost_per_meetings'])} | {_money(cur, r['cost_per_commits'])} |")
        L += ["", f"**Suggested:** {m['suggested']} ({m['reason']})."]
        if m["stop"]:
            L.append(f"**Stop early:** variant(s) {', '.join(k.upper() for k in m['stop'])}: spent enough with no "
                     "qualified inquiry. Pause them in the ad tool.")
        L += [f"**Note:** {n}" for n in m["notes"]] + [""]
    return "\n".join(L).rstrip() + "\n"


def write_report(ws: Workspace, ledger: Ledger, as_of: datetime) -> tuple[str, list[dict]]:
    measured = [measure(ws, ledger, m, as_of) for _, m, _ in plans.all_plans(ws) if m["status"] == "running"]
    rel = "engines/creative/results.md"
    ws.path(rel).parent.mkdir(parents=True, exist_ok=True)
    ws.path(rel).write_text(render(ws, measured, as_of))
    return rel, measured


def stale_imports(ws: Workspace, as_of: datetime, days: int = 7) -> list[str]:
    out = []
    for _, m, _ in plans.all_plans(ws):
        if m["status"] == "running":
            snap = latest(ws, m["id"], as_of)
            last = parse_ts(snap["imported_at"]) if snap else parse_ts(m["started_at"])
            if (as_of - last).days >= days:
                out.append(m["id"])
    return out
