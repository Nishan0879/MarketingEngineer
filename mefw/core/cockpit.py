"""Weekly growth cockpit memo (Sections 8.3 and 15).

One memo per client per week, built from what's already in memory: the ledger,
customer truth, experiment briefs and the activity log. It's how the operator
steers, so it ends with the decisions only the operator can make.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from . import customer_truth, experiments, metrics, quality, scheduler
from .activity_log import ActivityLog
from .control import Control
from .evidence import refs_md
from .ledger import Ledger, LeadState, iso
from .workspace import Workspace
from ..engines.content import briefs as content
from ..engines.search import analysis as search_analysis, data as search_data, pages as search_pages
from ..engines.conversion import cold_audit, first_response, queue, reengage

NORTH_STAR_METRICS = ("commits", "commit_value")


def week_bounds(as_of: datetime) -> tuple[datetime, datetime, str]:
    """Monday 00:00 UTC of the ISO week containing as_of, the following Monday, and its label."""
    start = (as_of - timedelta(days=as_of.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    y, w, _ = as_of.isocalendar()
    return start, start + timedelta(days=7), f"{y}-W{w:02d}"


def _won_in(states: list[LeadState], start: datetime, end: datetime) -> list[LeadState]:
    return [s for s in states if s.outcome == "won" and s.outcome_at and start <= s.outcome_at < end]


def _north_star_value(won: list[LeadState], metric: str) -> float:
    return sum(s.value or 0 for s in won) if metric == "commit_value" else len(won)


def build(ws: Workspace, ledger: Ledger, as_of: datetime) -> dict:
    start, end, label = week_bounds(as_of)
    end = min(end, as_of)
    states = ledger.states(as_of)
    seg_of = {s.lead_id: ws.segment_for(s.segment) for s in states}
    ns_cfg = ws.config.north_star
    ns_metric = ns_cfg.get("metric", "commits")
    if ns_metric not in NORTH_STAR_METRICS:
        raise ValueError(f"[north_star] metric must be one of {NORTH_STAR_METRICS}")
    data = {"client": ws.client_id, "week": label, "start": iso(start), "as_of": iso(as_of)}

    # North star: this week, last week, and the last four weeks against the four before
    weeks = [_north_star_value(_won_in(states, start - timedelta(days=7 * i), start - timedelta(days=7 * (i - 1))
                                       if i else end), ns_metric) for i in range(0, 8)]
    recent, prior = sum(weeks[0:4]), sum(weeks[4:8])
    trend = "flat" if recent == prior else ("up" if recent > prior else "down")
    by_seg = defaultdict(int)
    for s in _won_in(states, start, end):
        by_seg[seg_of[s.lead_id]] += 1
    data["north_star"] = {
        "label": ns_cfg.get("label", "Commitments"), "metric": ns_metric,
        "this_week": weeks[0], "last_week": weeks[1], "four_weeks": recent, "prior_four_weeks": prior,
        "trend": trend, "by_segment": {ws.segment_label(k): v for k, v in by_seg.items()},
    }

    # Wins and losses this week
    won = _won_in(states, start, end)
    lost = [s for s in states if s.outcome == "lost" and s.outcome_at and start <= s.outcome_at < end]
    data["won"] = [{"ref": s.ref, "segment": ws.segment_label(seg_of[s.lead_id]), "value": s.value} for s in won]
    data["lost"] = [{"ref": s.ref, "segment": ws.segment_label(seg_of[s.lead_id]), "reason": s.lost_reason}
                    for s in lost]

    # Leads that went cold this week for reasons on our side
    newly_cold = []
    for s in states:
        seg = ws.config.segments.get(seg_of[s.lead_id])
        cfg = cold_audit.Settings.from_config(ws.config.conversion, seg.cold_audit if seg else None)
        cold_at = s.last_activity + timedelta(days=cfg.cold_after_days) if s.last_activity else None
        if (s.outcome is None and not s.reached("commit") and cold_at and start <= cold_at < end):
            reason = cold_audit.classify(s, cfg)
            if reason in cold_audit.FIXABLE:
                newly_cold.append({"ref": s.ref, "segment": ws.segment_label(seg_of[s.lead_id]),
                                   "reason": cold_audit.LEAKS[reason]})
    data["newly_cold"] = newly_cold

    # Funnel: last 28 days against the 28 before, per segment
    funnel = []
    for seg in ws.segment_names():
        leads = [s for s in states if seg_of[s.lead_id] == seg]
        cycle = ws.cycle_days(seg)
        row = {"segment": ws.segment_label(seg)}
        for m in ("inquiry_to_meeting", "first_response_minutes"):
            # Each window is judged as of its own end plus the metric's maturity, so both are complete.
            mat = timedelta(days=metrics.maturity_days(m, cycle))
            cur_end = as_of - mat
            cur = metrics.compute(m, metrics.in_window(leads, cur_end - timedelta(days=28), cur_end), as_of, cycle)
            prev = metrics.compute(m, metrics.in_window(leads, cur_end - timedelta(days=56),
                                                        cur_end - timedelta(days=28)), as_of, cycle)
            row[m] = {"now": cur.fmt(m), "n": cur.n, "before": prev.fmt(m), "n_before": prev.n,
                      "change": metrics.relative_change(m, cur, prev)}
        funnel.append(row)
    data["funnel"] = funnel

    # Market, from customer truth
    truth = customer_truth.run_truth(ws, ledger, as_of)
    data["market"] = {
        "headline": truth["headline"],
        "rising": [{"segment": d["label"], "label": t["label"], "current": t["current"],
                    "baseline_avg": t["baseline_avg"], "refs": t["refs"]}
                   for d in truth["segments"].values() for t in d["trends"] if t["direction"] in ("new", "rising")],
        "competitor": [{"segment": d["label"], "count": t["current"], "refs": t["refs"]}
                       for d in truth["segments"].values() for t in d["trends"]
                       if t["theme"] == "competitor" and t["current"]],
    }

    # Experiments
    exps = []
    for path, meta, body in experiments.all_briefs(ws):
        if meta["status"] == "completed":
            continue
        entry = {"id": meta["id"], "name": meta["name"], "status": meta["status"],
                 "segment": ws.segment_label(meta["segment"]),
                 "priority": _priority(body), "path": str(path.relative_to(ws.root))}
        if meta["status"] in ("running", "stopped"):
            entry["measure"] = experiments.measure(ws, ledger, meta, as_of)
        exps.append(entry)
    data["experiments"] = exps

    # Suggested tests from the cold audit, for leaks no brief covers yet
    audit = cold_audit.run_audit(ws, ledger, as_of)
    data["suggested_tests"] = [
        {"segment": d["label"], "leak": cold_audit.LEAKS[d["top_leak"]],
         "count": len(d["cold"]["by_leak"][d["top_leak"]]), "test": cold_audit.NEXT_TESTS[d["top_leak"]]}
        for d in audit["segments"].values() if d.get("top_leak")
    ]

    # Agent errors this week, from the activity log
    log = ActivityLog(ws.log_path, ws.client_id)
    data["agent_errors"] = [
        {"ts": e["ts"], "agent": e["agent"], "action": e["action"], "result": e["result"],
         "reason": e["output"].get("reason", "")}
        for e in log.entries()
        if e["result"] in ("failed", "blocked", "escalated") and iso(start) <= e["ts"] < iso(end + timedelta(seconds=1))
    ]

    data["quality"] = [r for r in quality.scorecard(ws, as_of) if "decided" in r]
    changes = [e for e in log.entries() if e["action"] in ("promote", "demote")
               and iso(start) <= e["ts"] < iso(end + timedelta(seconds=1))]

    # Decisions only the operator can make
    decisions = []
    for e in changes:
        if e["action"] == "demote":
            decisions.append(f"`{e['inputs']['agent']}` was demoted to Level {e['inputs']['to']} "
                             f"({e['output']['reason']}). Review what happened before promoting it again.")
    for r in data["quality"]:
        if r["over_budget"]:
            decisions.append(f"`{r['agent']}`: {r['correction_rate']:.0%} of its last {r['correction_n']} drafts were "
                             f"edited or rejected, over its {r['budget']:.0%} budget. Look for the pattern in "
                             "rules/corrections.md and fix the playbook or rules.")
    for e in exps:
        if e["status"] == "proposed":
            decisions.append(f"Approve or drop {e['id']} ({e['name']}): `mefw experiment approve {e['id']}`")
        elif e["status"] == "approved":
            decisions.append(f"Start {e['id']} ({e['name']}) once its assets are live: `mefw experiment start {e['id']}`")
        elif e.get("measure", {}).get("ready"):
            m = e["measure"]
            decisions.append(f"Verdict for {e['id']}: suggested **{m['suggested']}** ({m['reason']}). "
                             f"`mefw experiment close {e['id']} --verdict ...`")
    insight_dir = ws.path("customer-truth/insights")
    new_insights = []
    for path in sorted(insight_dir.glob("*.md")) if insight_dir.exists() else []:
        text = path.read_text()
        m = re.search(r"\*\*Date observed:\*\* (\S+)", text)
        if m and iso(start)[:10] <= m.group(1) <= iso(end)[:10] and "Draft wording" in text:
            new_insights.append(path.stem)
    if new_insights:
        decisions.append(f"Review {len(new_insights)} new insight record(s) in `customer-truth/insights/` "
                         f"(keep, reword or retire): {', '.join(new_insights)}")
    waiting = first_response.waiting(ws, end)
    if waiting:
        hours = waiting["oldest_hours"]
        age = f"{hours:.0f} hours" if hours < 48 else f"{hours / 24:.0f} days"
        decisions.append(f"Release {waiting['count']} first response(s) waiting in the queue; the oldest lead has "
                         f"waited {age}. Speed to first response is the conversion engine's first metric: "
                         "`mefw drafts list`")
    drafts = queue.summary_counts(ws, reengage.AGENT)
    if drafts["pending"]:
        decisions.append(f"Review {drafts['pending']} pending re-engagement draft(s): `mefw drafts list`")
    if drafts["approved"]:
        decisions.append(f"Send {drafts['approved']} approved re-engagement draft(s) from your own tool, then mark "
                         "them `mefw drafts sent`")
    unwritten = [m["id"] for _, m, _ in content.all_briefs(ws) if m["status"] == "brief"]
    if unwritten:
        decisions.append(f"Write or drop {len(unwritten)} content brief(s) ({', '.join(unwritten)}), then "
                         "`mefw content approve <id>`")
    unpublished = [m["id"] for _, m, _ in content.all_briefs(ws) if m["status"] == "approved"]
    if unpublished:
        decisions.append(f"Publish {len(unpublished)} approved content brief(s) ({', '.join(unpublished)}), then "
                         "record each with `mefw content published`")
    search_waiting = [m["id"] for _, m, _ in search_pages.all_drafts(ws) if m["status"] == "draft"]
    if search_waiting:
        decisions.append(f"Review {len(search_waiting)} search draft(s) ({', '.join(search_waiting)}), then "
                         "`mefw search approve <id>`")
    search_approved = [m["id"] for _, m, _ in search_pages.all_drafts(ws) if m["status"] == "approved"]
    if search_approved:
        decisions.append(f"Put {len(search_approved)} approved search draft(s) on the site "
                         f"({', '.join(search_approved)}), then record each with `mefw search published`")
    try:
        pb = search_data.load_playbook(ws)
    except FileNotFoundError:
        pb = None
    if pb:
        for lst in search_analysis.listings(ws, pb, end.date()):
            if lst["problems"]:
                decisions.append(f"Fix the {lst['label']} listing: " + "; ".join(lst["problems"]))
        due = search_data.ai_due(ws, pb, end)
        if due:
            decisions.append(f"Run {len(due)} AI assistant check(s) and record them with `mefw search ai-record` "
                             "(the list is in the latest search report)")
    for agent in (first_response.AGENT, reengage.AGENT):
        record = queue.track_record(ws, agent)
        if record["meets_threshold"]:
            decisions.append(f"`{agent}` has {record['streak']} unedited approvals in a row over "
                             f"{record['streak_days']} days, the Section 11.2 bar for Level 2. Promote only with a "
                             "written playbook of what it may send, and note it in the agent's change log.")
    try:
        jobs = scheduler.overview(ws, end)
    except ValueError as e:
        jobs = []
        decisions.append(f"Fix the [schedule] table in profile/mefw.toml: {e}")
    for job in jobs:
        if job["behind"]:
            since = f"since {job['last_ok'][:16].replace('T', ' ')} UTC" if job["last_ok"] else "at all"
            decisions.append(f"Scheduled job `{job['job']}` ({job['schedule']}) hasn't run {since}. Check that "
                             "`mefw run-due` is still being called, then `mefw schedule`.")
    ctl = Control(ws.control_path).load()
    if ctl.get("client"):
        decisions.append(f"The whole client is paused ({ctl['client'].get('reason')}). Resume when ready.")
    for name, flag in {**ctl.get("engines", {}), **ctl.get("agents", {})}.items():
        decisions.append(f"`{name}` is paused ({flag.get('reason')}). Fix the cause, then resume it.")
    for d in audit["segments"].values():
        oc = d.get("outcome_coverage") or {}
        if oc.get("rate") is not None and oc["rate"] < 0.8:
            decisions.append(f"{d['label']}: only {oc['rate']:.0%} of leads past the sales cycle have an outcome. "
                             "Ask the client to close them out with reasons.")
    data["decisions"] = decisions
    return data


def _priority(body: str) -> str:
    m = re.search(r"## Priority score\n(.+)", body)
    return m.group(1).strip() if m else ""


def render(data: dict) -> str:
    L: list[str] = []
    w = L.append
    ns = data["north_star"]
    w(f"# Growth Cockpit — {data['client']} — Week {data['week']}")
    w("")
    w(f"_Built {data['as_of'][:10]} by `growth-cockpit` (Level 0) from the ledger, customer truth, "
      "experiment briefs and the activity log._")
    w("")
    w("## North star")
    w("")
    fmt = (lambda v: f"{v:,.0f}") if ns["metric"] == "commit_value" else (lambda v: f"{v:g}")
    w(f"{ns['label']}: **{fmt(ns['this_week'])}** this week (last week: {fmt(ns['last_week'])}, "
      f"4-week trend: {ns['trend']}, {fmt(ns['four_weeks'])} vs. {fmt(ns['prior_four_weeks'])} the 4 weeks before)")
    if len(ns["by_segment"]) > 0 and ns["metric"] == "commits":
        w("")
        w("This week by segment: " + ", ".join(f"{k} {v}" for k, v in ns["by_segment"].items()) + ".")
    w("")

    w("## Wins")
    w("")
    wins = []
    if data["won"]:
        by = defaultdict(list)
        for x in data["won"]:
            by[x["segment"]].append(x["ref"])
        for seg, refs in by.items():
            wins.append(f"{len(refs)} committed ({seg}): {refs_md(refs)}")
    for e in data["experiments"]:
        m = e.get("measure", {})
        if m.get("suggested") == "keep":
            wins.append(f"{e['id']} {e['name']}: {m['test']['shown']} vs. {m['baseline']['shown']} ({m['reason']})")
    for f in data["funnel"]:
        c = f["inquiry_to_meeting"]["change"]
        if c is not None and c >= 0.15:
            wins.append(f"{f['segment']}: inquiry → meeting {f['inquiry_to_meeting']['now']} "
                        f"(n={f['inquiry_to_meeting']['n']}) vs. {f['inquiry_to_meeting']['before']} the 4 weeks before")
    w("\n".join(f"- {x}" for x in wins) if wins else "- None this week.")
    w("")

    w("## Losses")
    w("")
    losses = []
    if data["lost"]:
        by = defaultdict(list)
        for x in data["lost"]:
            by[(x["segment"], (x["reason"] or "no reason").lower())].append(x["ref"])
        for (seg, reason), refs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            losses.append(f"{len(refs)} lost ({seg}) — {reason}: {refs_md(refs)}")
    if data["newly_cold"]:
        by = defaultdict(list)
        for x in data["newly_cold"]:
            by[(x["segment"], x["reason"])].append(x["ref"])
        for (seg, reason), refs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            losses.append(f"{len(refs)} went cold ({seg}) — {reason.lower()}: {refs_md(refs)}")
    for e in data["experiments"]:
        m = e.get("measure", {})
        if m.get("suggested") == "kill":
            losses.append(f"{e['id']} {e['name']}: {m['test']['shown']} vs. {m['baseline']['shown']} ({m['reason']})")
    for f in data["funnel"]:
        c = f["inquiry_to_meeting"]["change"]
        if c is not None and c <= -0.15:
            losses.append(f"{f['segment']}: inquiry → meeting {f['inquiry_to_meeting']['now']} "
                          f"(n={f['inquiry_to_meeting']['n']}) vs. {f['inquiry_to_meeting']['before']} the 4 weeks before")
    w("\n".join(f"- {x}" for x in losses) if losses else "- None this week.")
    w("")

    w("## What changed")
    w("")
    mk = data["market"]
    rising = "; ".join(f"{r['label'].lower()} ({r['segment']}, {r['current']} vs. ~{r['baseline_avg']:g})"
                       for r in mk["rising"][:4])
    w(f"- **Market / customers:** {mk['headline']}" + (f" Rising: {rising}." if rising else ""))
    comp = "; ".join(f"{c['count']} mention{'s' if c['count'] != 1 else ''} ({c['segment']}) {refs_md(c['refs'], 4)}"
                     for c in mk["competitor"])
    w(f"- **Competitors:** {comp or 'No mentions of alternatives this period in imported signal.'}")
    parts = []
    for f in data["funnel"]:
        im, fr = f["inquiry_to_meeting"], f["first_response_minutes"]
        parts.append(f"{f['segment']}: inquiry → meeting {im['now']} (n={im['n']}) vs. {im['before']} "
                     f"(n={im['n_before']}); first response {fr['now']} vs. {fr['before']}")
    w("- **Funnel** (last 4 complete weeks vs. the 4 before): " + "; ".join(parts) + ".")
    w("")

    w("## Recommended next tests")
    w("")
    n = 0
    for e in data["experiments"]:
        if e["status"] == "proposed":
            n += 1
            w(f"{n}. **{e['id']} {e['name']}** ({e['segment']}), brief at `{e['path']}`. {e['priority']}")
    for s in data["suggested_tests"]:
        n += 1
        w(f"{n}. **{s['leak']}** ({s['segment']}, {s['count']} leads). {s['test']} "
          "Priority score: Customer fit _/5 + Evidence strength _/5 + Business impact _/5 − Effort _/5.")
    if not n:
        w("None proposed.")
    w("")
    running = [e for e in data["experiments"] if e["status"] in ("running", "stopped", "approved")]
    if running:
        w("Running or approved:")
        w("")
        for e in running:
            m = e.get("measure")
            detail = (f"{m['test']['shown']} vs. {m['baseline']['shown']}, day {m['days']}, "
                      f"suggested {m['suggested']} ({m['reason']})") if m and "test" in m else e["status"]
            w(f"- {e['id']} {e['name']}: {detail}")
        w("")

    w("## Agent errors")
    w("")
    if data["agent_errors"]:
        for x in data["agent_errors"]:
            w(f"- {x['ts'][:16]} `{x['agent']}` {x['action']}: {x['result']} — {x['reason']}")
    else:
        w("- None this week.")
    for r in data.get("quality", []):
        un = f"{r['unedited_rate']:.0%}" if r["unedited_rate"] is not None else "n/a"
        w(f"- `{r['agent']}` (Level {r['level']}), last 28 days: {r['decided']} drafts decided, {un} approved "
          f"without edits, {r['claims_caught']} unsupported claims caught before review.")
    w("")

    w("## Decisions needed from the operator")
    w("")
    w("\n".join(f"- [ ] {d}" for d in data["decisions"]) if data["decisions"] else "- [ ] None this week.")
    w("")
    return "\n".join(L)


def write(ws: Workspace, data: dict) -> str:
    """Write cockpit/YYYY-Www.md. A memo is never overwritten; a rerun the same week gets a suffix."""
    out = ws.path("cockpit")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{data['week']}.md"
    n = 2
    while path.exists():
        path = out / f"{data['week']}-{n}.md"
        n += 1
    path.write_text(render(data))
    return str(path.relative_to(ws.root))
