"""Command line for the operator: `python -m mefw <command> --client <dir>`."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path

from .adapters.base import import_records
from .adapters.csv_source import CsvSource
from .adapters.signals_csv import import_signals
from .core.activity_log import ActivityLog
from .core import autonomy, client_report, cockpit, quality, customer_truth, experiments, scheduler, truth_report
from .core.control import Control
from .core.errors import GuardrailError
from .core.ledger import Ledger, parse_ts
from .core.runner import Runner
from .core.workspace import Workspace
from .engines.conversion import cold_audit, first_response, queue, reengage

OPERATOR = "operator"


def _ws(args) -> Workspace:
    return Workspace(args.client or os.environ.get("MEFW_CLIENT") or ".")


def cmd_init(args) -> int:
    dest = Path(args.dir)
    if dest.exists() and any(dest.iterdir()):
        print(f"{dest} is not empty; refusing to overwrite.", file=sys.stderr)
        return 1
    src = resources.files("mefw") / "templates" / "client"
    with resources.as_file(src) as src_path:
        shutil.copytree(src_path, dest, dirs_exist_ok=True)
    (dest / "gitignore").rename(dest / ".gitignore")
    for p in dest.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".toml"):
            p.write_text(p.read_text().replace("{client_id}", args.client_id)
                         .replace("{today}", date.today().isoformat()))
    ws = Workspace(dest)
    ActivityLog(ws.log_path, ws.client_id).append(
        OPERATOR, "init", "ok", {"client_id": args.client_id}, {"summary": "Workspace created"})
    print(f"Created client workspace for '{args.client_id}' at {dest}")
    print("Next: edit profile/mefw.toml (stage names, CSV columns), then `mefw import-csv`.")
    return 0


def cmd_import_csv(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    ledger = Ledger(ws.db_path, ws.client_id)
    try:
        src = CsvSource(Path(args.leads), ws.config.csv, Path(args.activities) if args.activities else None)
        rep = import_records(ws, ledger, src)
    except Exception as e:
        log.append(OPERATOR, "import", "failed", {"file": Path(args.leads).name}, {"reason": str(e)})
        raise
    finally:
        ledger.close()
    log.append(OPERATOR, "import", "ok",
               {"file": Path(args.leads).name, "activities": Path(args.activities).name if args.activities else None},
               {"summary": rep.summary(), "warnings": rep.warnings[:20]})
    print(rep.summary())
    for w in rep.warnings[:10]:
        print(f"  warning: {w}")
    if len(rep.warnings) > 10:
        print(f"  ...and {len(rep.warnings) - 10} more warnings")
    return 0


def cmd_import_signals(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    ledger = Ledger(ws.db_path, ws.client_id)
    cfg = ws.config.signals_csv
    try:
        rep = import_signals(ledger, Path(args.file), cfg, default_kind=args.kind)
    except Exception as e:
        log.append(OPERATOR, "import_signals", "failed", {"file": Path(args.file).name}, {"reason": str(e)})
        raise
    finally:
        ledger.close()
    log.append(OPERATOR, "import_signals", "ok", {"file": Path(args.file).name, "kind": args.kind},
               {"summary": rep.summary(), "skipped": rep.skipped[:20]})
    print(rep.summary())
    return 0


def cmd_truth(args) -> int:
    ws = _ws(args)
    as_of = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    runner = Runner(ws)
    try:
        db = runner.ledger.db
        n_signals = db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        last = db.execute("SELECT MAX(recorded_at) FROM signals").fetchone()[0]
        n_events = db.execute("SELECT COUNT(*) FROM lead_events").fetchone()[0]
        key = f"customer-truth:{as_of.isoformat()}:{n_signals}:{n_events}:{last}"
        note = f"{n_signals} imported signals plus recorded lost reasons (last import {last or 'never'})"

        def job() -> dict:
            data = customer_truth.run_truth(ws, runner.ledger, as_of)
            return {"summary": data["headline"], **truth_report.write_outputs(ws, data, note)}

        res = runner.run("customer-truth-analyst", "customer_truth_update", "observe", key, job,
                         {"as_of": as_of.isoformat()})
    except GuardrailError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    finally:
        runner.close()
    if res.status == "duplicate":
        print("Already ran for this data and date; nothing new to do.")
    print(res.output.get("summary", ""))
    if res.output.get("report"):
        print(f"Report: {ws.root / res.output['report']}")
    for p in res.output.get("insights", []):
        print(f"Insight: {p}")
    return 0


def _run_agent(ws: Workspace, agent: str, action: str, key: str, job, inputs: dict):
    """Run one Level 0 job through the runner; returns the RunResult, or None if a guardrail refused it."""
    runner = Runner(ws)
    try:
        return runner.run(agent, action, "observe", key, lambda: job(runner), inputs)
    except GuardrailError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return None
    finally:
        runner.close()


def cmd_experiment(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)

    if args.action == "new":
        ledger = Ledger(ws.db_path, ws.client_id)
        try:
            path = experiments.new(
                ws, ledger, args.name, args.metric, args.hypothesis, at, segment=args.segment,
                channels=args.channels, comparison=args.comparison, baseline_days=args.baseline_days,
                min_window_days=args.min_window_days, min_leads=args.min_leads,
                keep_if=args.keep_if, kill_if=args.kill_if, evidence=args.evidence or "")
        finally:
            ledger.close()
        meta, _ = experiments.load(path)
        log.append(OPERATOR, "experiment_new", "ok", {"id": meta["id"]},
                   {"summary": f"Proposed {meta['id']}: {meta['name']}"})
        print(f"Proposed {meta['id']}: {path.relative_to(ws.root)}")
        print("Fill in Customer, Evidence, Offer, Assets and Priority score, then `mefw experiment approve`.")
        return 0

    if args.action == "list":
        for path, meta, _ in experiments.all_briefs(ws):
            print(f"{meta['id']}  {meta['status']:<10} {ws.segment_label(meta['segment'])}: {meta['name']}")
        return 0

    if args.action in ("approve", "start", "stop"):
        meta = experiments.transition(ws, args.id, args.action, args.by, at)
        log.append(args.by, f"experiment_{args.action}", "ok",
                   {"id": meta["id"], "criteria_hash": meta.get("criteria_hash")},
                   {"summary": f"{meta['id']} is now {meta['status']}"})
        print(f"{meta['id']} is now {meta['status']}.")
        return 0

    if args.action == "close":
        dest = experiments.close(ws, args.id, args.verdict, args.lesson, args.confidence, args.outcome or "",
                                 args.by, at, next_test=args.next_test or "")
        log.append(args.by, "experiment_close", "ok", {"id": args.id, "verdict": args.verdict},
                   {"summary": f"{args.id} closed: {args.verdict} ({args.confidence}). {args.lesson}"})
        print(f"Closed {args.id} as {args.verdict}; brief moved to {dest.relative_to(ws.root)}, lesson recorded.")
        return 0

    # measure: one or all running experiments
    briefs = [experiments.find(ws, args.id)] if args.id else [
        b for b in experiments.all_briefs(ws) if b[1]["status"] in ("running", "stopped")]
    if not briefs:
        print("No running experiments.")
        return 0
    status = 0
    for path, meta, _ in briefs:
        def job(runner, meta=meta):
            res = experiments.measure(ws, runner.ledger, meta, at)
            experiments.log_measurement(ws, meta["id"], res)
            return {"summary": f"{meta['id']}: suggested {res.get('suggested', 'n/a')} — {res.get('reason', res.get('note', ''))}",
                    "suggested": res.get("suggested")}
        key = f"measure:{meta['id']}:{at.date().isoformat()}"
        res = _run_agent(ws, "experiment-tracker", "experiment_measure", key, job, {"id": meta["id"]})
        if res is None:
            status = 2
            continue
        print(res.output.get("summary", ""))
    return status


def cmd_cockpit(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)

    def job(runner):
        data = cockpit.build(ws, runner.ledger, at)
        path = cockpit.write(ws, data)
        ns = data["north_star"]
        return {"summary": f"Week {data['week']}: {ns['label']} {ns['this_week']:g} (last week {ns['last_week']:g}); "
                           f"{len(data['decisions'])} decisions needed", "memo": path}

    res = _run_agent(ws, "growth-cockpit", "cockpit_memo", f"cockpit:{at.isoformat()}", job,
                        {"as_of": at.isoformat()})
    if res is None:
        return 2
    if res.status == "duplicate":
        print("Already built for this time; nothing new to do.")
    print(res.output.get("summary", ""))
    if res.output.get("memo"):
        print(f"Memo: {ws.root / res.output['memo']}")
    return 0


def cmd_report(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.as_of) if getattr(args, "as_of", None) else datetime.now(timezone.utc)
    month = args.month or client_report.default_month(at)

    if args.action == "approve":
        log = ActivityLog(ws.log_path, ws.client_id)
        log.verify()
        meta, out = client_report.approve(ws, month, args.by, at)
        log.append(args.by, "report_approve", "ok", {"month": month}, {"summary": f"Approved the {month} report"})
        print(f"Approved. Share this with the client (open it in a browser and print to PDF if needed): {out}")
        return 0

    existing = client_report.path_for(ws, month)
    if existing.exists() and client_report.load(existing)[0].get("status") == "approved":
        print(f"The {month} report is already approved; leaving it as it is.")
        return 0

    def job(runner):
        data = client_report.build(ws, runner.ledger, month, at)
        path = client_report.write(ws, data, at)
        return {"summary": f"Drafted the {data['label']} client report", "report": str(path.relative_to(ws.root)),
                "notes": client_report.load(path)[0]["operator_notes"]}

    res = _run_agent(ws, client_report.AGENT, "client_report", f"report:{month}:{at.isoformat()}", job,
                     {"month": month})
    if res is None:
        return 2
    print(res.output.get("summary", ""))
    for note in res.output.get("notes", []):
        print(f"  note: {note}")
    if res.output.get("report"):
        print(f"Read and edit {ws.root / res.output['report']}, then `mefw report approve --month {month}`.")
    return 0


def cmd_drafts(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)

    if args.action == "make":
        status = 0
        for agent in DRAFTERS if args.agent == "all" else [args.agent]:
            if agent not in ws.config.agents:
                print(f"{agent}: not set up in profile/mefw.toml; skipped.")
                continue
            status = max(status, _make_drafts(ws, agent, at, args.max))
        print(f"Review them in {ws.root / queue.DRAFTS}/")
        return status
    if args.action == "list":
        for _, meta, _ in queue.existing_drafts(ws):
            if args.all or meta["status"] in ("pending", "approved"):
                flag = " (needs fixes)" if meta.get("blocking_issues") else ""
                print(f"{meta['id']}  {meta['status']:<9} {meta['lead']:<10} {queue.situation(meta)}{flag}")
        return 0

    if args.action == "record":
        for agent in DRAFTERS:
            r = queue.track_record(ws, agent)
            print(f"{agent}: decided {r['decided']} (approved unedited {r['approved_unedited']}, "
                  f"edited {r['edited']}, rejected {r['rejected']}); current streak of unedited approvals "
                  f"{r['streak']} over {r['streak_days']} days")
        print(f"Level 2 needs {queue.PROMOTION_STREAK} in a row over {queue.PROMOTION_DAYS}+ days, a written "
              "playbook of what it may send, and your sign-off.")
        return 0

    if args.action == "export":
        path = queue.export_approved(ws, at)
        print(f"Wrote {path}" if path else "No approved drafts waiting to be sent.")
        return 0

    log.verify()
    if args.action == "approve":
        meta = queue.approve(ws, args.id, args.by, at)
        log.append(args.by, "draft_approve", "ok", {"id": meta["id"], "edited": meta["edited"]},
                   {"summary": f"Approved {meta['id']}" + (" after edits" if meta["edited"] else " as drafted")})
        print(f"Approved {meta['id']}" + (" (edited)" if meta["edited"] else "") + ". Send it from your own tool, "
              f"then `mefw drafts sent {meta['id']}`.")
    elif args.action == "reject":
        meta = queue.reject(ws, args.id, args.reason, args.by, at)
        log.append(args.by, "draft_reject", "ok", {"id": meta["id"]}, {"reason": args.reason})
        print(f"Rejected {meta['id']}; reason added to rules/corrections.md.")
    elif args.action == "sent":
        ledger = Ledger(ws.db_path, ws.client_id)
        try:
            meta = queue.mark_sent(ws, ledger, args.id, args.by, at)
        finally:
            ledger.close()
        log.append(args.by, "draft_sent", "ok", {"id": meta["id"], "lead": meta["lead"]},
                   {"summary": f"{meta['id']} sent to {meta['lead']} by a human"})
        print(f"Recorded {meta['id']} as sent.")
    return 0


# Drafting agents: module, logged action name, and what the operator calls the leads it drafts for.
DRAFTERS = {
    first_response.AGENT: (first_response, "draft_first_response", "new inquiries waiting on a first reply"),
    reengage.AGENT: (reengage, "draft_reengagement", "leads that went cold on our side"),
}


def _make_drafts(ws: Workspace, agent: str, at: datetime, limit: int) -> int:
    """Run one drafting agent through the runner, one gated action per lead."""
    mod, action, label = DRAFTERS[agent]
    runner = Runner(ws)
    made, blocked, refused, no_template = 0, 0, None, set()
    try:
        playbook = queue.load_playbook(ws)
        cands, skipped = mod.candidates(ws, runner.ledger, at)
        for c in cands:
            if made >= limit:
                break
            if queue.open_draft_for(ws, c.state.lead_id):
                continue
            if not mod.has_template(playbook, c):
                no_template.add(mod.template_label(c))
                continue
            try:
                res = runner.run(agent, action, "draft", mod.key(c), lambda c=c: _draft_job(ws, mod, c, at),
                                 {"lead": c.state.ref, "segment": c.segment})
            except GuardrailError as e:
                refused = str(e)
                break
            if res.status == "ok" and "id" in res.output:
                made += 1
                blocked += bool(res.output.get("blocking_issues"))
        for sk in skipped:
            runner.log.append(agent, "skip_lead", "skipped", {"lead": sk["ref"]},
                              {"reason": sk["why"], "receipt": sk.get("receipt")})
    finally:
        runner.close()
    print(f"{agent} ({label}): drafted {made} ({blocked} need fixes before they can be approved). "
          f"Skipped {len(skipped)}: " + (", ".join(f"{s['ref']} ({s['why']})" for s in skipped[:10]) or "none"))
    if no_template:
        print("  No playbook template for: " + ", ".join(sorted(no_template)))
    if refused:
        print(f"  Stopped: {refused}", file=sys.stderr)
        return 2
    return 0


def _draft_job(ws: Workspace, mod, c, at: datetime) -> dict:
    meta = mod.make_draft(ws, c, at)
    if "skipped" in meta:
        return {"summary": meta["skipped"], "skipped": meta["skipped"]}
    return {"summary": f"Drafted {meta['id']} for {meta['lead']} ({queue.situation(meta)})", "id": meta["id"],
            "blocking_issues": meta["blocking_issues"]}


def cmd_opt_out(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    ledger = Ledger(ws.db_path, ws.client_id)
    try:
        lead_id = ledger.find_lead(args.ref)
        if not lead_id:
            print(f"No lead with reference {args.ref}", file=sys.stderr)
            return 1
        at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
        value = "opted_in" if args.undo else "opted_out"
        ledger.add_event(lead_id, "consent", at, source=OPERATOR, value=value)
    finally:
        ledger.close()
    log.append(OPERATOR, "consent", "ok", {"lead": lead_id, "value": value}, {"summary": f"{lead_id} {value}"})
    print(f"{lead_id}: {value.replace('_', ' ')}")
    return 0


def cmd_outcome(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    ledger = Ledger(ws.db_path, ws.client_id)
    try:
        lead_id = ledger.find_lead(args.ref)
        if not lead_id:
            print(f"No lead with reference {args.ref}", file=sys.stderr)
            return 1
        at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
        added = ledger.record_outcome(lead_id, args.outcome, at, source=OPERATOR, reason=args.reason)
    finally:
        ledger.close()
    log.append(OPERATOR, "record_outcome", "ok" if added else "skipped_duplicate",
               {"lead": lead_id, "outcome": args.outcome, "at": at.isoformat()},
               {"summary": f"{lead_id} → {args.outcome}" + (f" ({args.reason})" if args.reason else "")})
    print(f"{lead_id}: {args.outcome}" + ("" if added else " (already recorded)"))
    return 0


def cmd_audit_cold(args) -> int:
    ws = _ws(args)
    as_of = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    runner = Runner(ws)
    try:
        counts = runner.ledger.counts()
        last = runner.ledger.db.execute("SELECT MAX(recorded_at) FROM lead_events").fetchone()[0]
        key = f"cold-audit:{as_of.isoformat()}:{counts['events']}:{last}"
        sources = [r[0] for r in runner.ledger.db.execute("SELECT DISTINCT source FROM leads")]
        note = f"lead ledger ({counts['leads']} leads, {counts['events']} events from {', '.join(sources) or 'no source'}; last import {last or 'never'})"

        def job() -> dict:
            data = cold_audit.run_audit(ws, runner.ledger, as_of)
            paths = cold_audit.write_outputs(ws, data, note)
            return {"summary": data["headline"], **paths}

        res = runner.run("cold-inquiry-auditor", "cold_inquiry_audit", "observe", key, job,
                         {"as_of": as_of.isoformat()})
    except GuardrailError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    finally:
        runner.close()
    if res.status == "duplicate":
        print("Already ran for this data and date; nothing new to do.")
    print(res.output.get("summary", ""))
    if res.output.get("report"):
        print(f"Report: {ws.root / res.output['report']}")
    return 0


def _scope(args) -> tuple[str, str | None]:
    if args.agent:
        return "agent", args.agent
    if args.engine:
        return "engine", args.engine
    return "client", None


def cmd_pause(args) -> int:
    ws = _ws(args)
    scope, name = _scope(args)
    Control(ws.control_path).pause(scope, name, args.reason, by=args.by)
    ActivityLog(ws.log_path, ws.client_id).append(
        args.by, "pause", "ok", {"scope": scope, "name": name}, {"reason": args.reason})
    print(f"Paused {scope}{' ' + name if name else ''}.")
    return 0


def cmd_resume(args) -> int:
    ws = _ws(args)
    scope, name = _scope(args)
    Control(ws.control_path).resume(scope, name)
    ActivityLog(ws.log_path, ws.client_id).append(
        args.by, "resume", "ok", {"scope": scope, "name": name}, {"summary": f"Resumed {scope} {name or ''}".strip()})
    print(f"Resumed {scope}{' ' + name if name else ''}.")
    return 0


def cmd_quality(args) -> int:
    ws = _ws(args)
    ActivityLog(ws.log_path, ws.client_id).verify()
    at = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    for d in autonomy.enforce_error_budget(ws, at):
        print(f"Demoted {d['agent']} from Level {d['from']} to Level {d['level']}: {d['reason']}")
    print(quality.render(quality.scorecard(ws, at, args.days), args.days))
    return 0


def cmd_promote(args) -> int:
    ws = _ws(args)
    ActivityLog(ws.log_path, ws.client_id).verify()
    at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    if args.check:
        missing = autonomy.promotion_check(ws, args.agent, at, args.playbook, args.budget_cap, args.client_approval)
        print(f"{args.agent} is at Level {autonomy.level(ws, args.agent)}. "
              + ("Ready to promote with your sign-off." if not missing else "Not yet: " + "; ".join(missing)))
        return 0
    r = autonomy.promote(ws, args.agent, args.by, args.reason or "", at, args.playbook, args.budget_cap,
                         args.client_approval)
    print(f"Promoted {r['agent']} from Level {r['from']} to Level {r['level']}; noted in its change log.")
    return 0


def cmd_demote(args) -> int:
    ws = _ws(args)
    ActivityLog(ws.log_path, ws.client_id).verify()
    at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    if args.kind == "operator":
        r = autonomy.demote(ws, args.agent, args.by, args.note or "", at)
    else:
        r = autonomy.report_serious_error(ws, args.agent, args.kind, args.note or "", args.by, at)
    print(f"{r['agent']}: Level {r['from']} → Level {r['level']}. {r['reason']}")
    return 0


def cmd_run_due(args) -> int:
    ws = _ws(args)
    ActivityLog(ws.log_path, ws.client_id).verify()
    now = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    results = scheduler.run_due(ws, now)
    if not results:
        print("Nothing due.")
    for r in results:
        print(f"{r['job']}: {r['result']}" + (f" — {r['summary'].splitlines()[-1]}" if r.get("summary") else ""))
    return 1 if any(r["result"] == "failed" for r in results) else 0


def cmd_schedule(args) -> int:
    ws = _ws(args)
    now = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    rows = scheduler.overview(ws, now)
    if not rows:
        print("No [schedule] in profile/mefw.toml; jobs only run when you run them.")
        return 0
    tz = scheduler.client_tz(ws)

    def local(ts):
        return parse_ts(ts).astimezone(tz).strftime("%a %Y-%m-%d %H:%M") if ts else "never"

    print(f"Times in {getattr(tz, 'key', 'UTC')}.")
    for r in rows:
        flag = "  BEHIND" if r["behind"] else ""
        last = f"{local(r['last_run'])} ({r['last_result']})" if r["last_run"] else "never"
        print(f"{r['job']:<24} {r['schedule']:<18} last: {last:<32} next: {local(r['next'])}{flag}")
    return 0


def cmd_status(args) -> int:
    ws = _ws(args)
    ctl = Control(ws.control_path).load()
    log = ActivityLog(ws.log_path, ws.client_id)
    try:
        n = log.verify()
        log_state = f"OK ({n} entries)"
    except GuardrailError as e:
        log_state = f"BROKEN: {e}"
    ledger = Ledger(ws.db_path, ws.client_id)
    counts = ledger.counts()
    ledger.close()
    print(f"Client: {ws.client_id}  ({ws.root})")
    print(f"Client paused: {'yes — ' + ctl['client']['reason'] if ctl.get('client') else 'no'}")
    for e, f in ctl["engines"].items():
        print(f"Engine paused: {e} — {f['reason']}")
    print("Agents:")
    for a in ws.config.agents.values():
        flag = ctl["agents"].get(a.name)
        spec = "spec ok" if ws.path(a.spec).exists() else "NO SPEC"
        state = f"PAUSED ({flag['reason']})" if flag else "active"
        lvl = autonomy.level(ws, a.name)
        note = f" (profile says {a.level}; above 1 needs `mefw promote`)" if a.level > lvl and not autonomy.record(ws, a.name) else ""
        print(f"  {a.name}: engine={a.engine} level={lvl}{note} cap={a.max_actions_per_day}/day {spec} {state}")
    print(f"Ledger: {counts['leads']} leads, {counts['events']} events")
    print(f"Activity log: {log_state}")
    return 0


def cmd_log(args) -> int:
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    if args.action == "verify":
        try:
            print(f"Activity log OK: {log.verify()} entries, chain intact.")
            return 0
        except GuardrailError as e:
            print(f"Activity log BROKEN: {e}", file=sys.stderr)
            return 3
    out = ws.path("logs/agent-activity.md")
    log.render_markdown(out)
    print(f"Wrote {out}")
    return 0


def metrics_names():
    from .core.metrics import METRICS
    return METRICS


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mefw", description="MarketingEngineerFW operator commands")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_client(sp):
        sp.add_argument("--client", help="client workspace dir (default: $MEFW_CLIENT or .)")
        return sp

    sp = sub.add_parser("init", help="create a client workspace")
    sp.add_argument("dir")
    sp.add_argument("--client-id", required=True)
    sp.set_defaults(fn=cmd_init)

    sp = with_client(sub.add_parser("import-csv", help="import leads from a CSV export"))
    sp.add_argument("leads")
    sp.add_argument("--activities", help="optional CSV with one row per message or call")
    sp.set_defaults(fn=cmd_import_csv)

    sp = with_client(sub.add_parser("import-signals", help="import notes, messages or reviews from a CSV"))
    sp.add_argument("file")
    sp.add_argument("--kind", help="signal kind for every row, if the file has no kind column")
    sp.set_defaults(fn=cmd_import_signals)

    sp = with_client(sub.add_parser("truth", help="update the customer truth file"))
    sp.add_argument("--as-of")
    sp.set_defaults(fn=cmd_truth)

    sp = sub.add_parser("experiment", help="propose, approve, start, measure and close experiments")
    esub = sp.add_subparsers(dest="action", required=True)
    e = with_client(esub.add_parser("new", help="propose an experiment brief"))
    e.add_argument("--name", required=True)
    e.add_argument("--metric", required=True, choices=list(metrics_names()))
    e.add_argument("--hypothesis", required=True, help="If we <change>, then <segment> will <behavior>, because <evidence>.")
    e.add_argument("--segment")
    e.add_argument("--channels", nargs="*", help="limit the test group to these channels")
    e.add_argument("--comparison", choices=["before_after", "holdout"])
    e.add_argument("--baseline-days", type=int)
    e.add_argument("--min-window-days", type=int)
    e.add_argument("--min-leads", type=int)
    e.add_argument("--keep-if", type=float, help="relative improvement to keep, e.g. 0.15")
    e.add_argument("--kill-if", type=float, help="relative change at or below which to kill, e.g. 0")
    e.add_argument("--evidence", help="links to the insight records or audit findings behind this")
    e.add_argument("--at")
    with_client(esub.add_parser("list", help="list experiments"))
    for name in ("approve", "start", "stop"):
        e = with_client(esub.add_parser(name, help=f"{name} an experiment (operator)"))
        e.add_argument("id")
        e.add_argument("--by", default=OPERATOR)
        e.add_argument("--at")
    e = with_client(esub.add_parser("measure", help="measure running experiments (Level 0 agent)"))
    e.add_argument("id", nargs="?")
    e.add_argument("--at")
    e = with_client(esub.add_parser("close", help="record the operator's verdict"))
    e.add_argument("id")
    e.add_argument("--verdict", required=True, choices=["keep", "iterate", "kill", "inconclusive"])
    e.add_argument("--confidence", required=True, choices=["low", "medium", "high"])
    e.add_argument("--lesson", required=True)
    e.add_argument("--outcome", help="the numbers, in one line")
    e.add_argument("--next-test")
    e.add_argument("--by", default=OPERATOR)
    e.add_argument("--at")
    sp.set_defaults(fn=cmd_experiment)

    sp = with_client(sub.add_parser("cockpit", help="build this week's growth cockpit memo"))
    sp.add_argument("--as-of")
    sp.set_defaults(fn=cmd_cockpit)

    sp = sub.add_parser("report", help="the monthly client report: make a draft, approve it to share")
    rsub = sp.add_subparsers(dest="action", required=True)
    r = with_client(rsub.add_parser("make", help="draft the client report (Level 0)"))
    r.add_argument("--month", help="YYYY-MM (default: the last complete month)")
    r.add_argument("--as-of")
    r = with_client(rsub.add_parser("approve", help="approve the report and write the HTML copy to share"))
    r.add_argument("--month", help="YYYY-MM (default: the last complete month)")
    r.add_argument("--by", default=OPERATOR)
    r.add_argument("--as-of")
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser("drafts", help="first-response and re-engagement drafts: make, review, approve, reject, "
                                       "mark sent")
    dsub = sp.add_subparsers(dest="action", required=True)
    d = with_client(dsub.add_parser("make", help="draft first replies to new inquiries and follow-ups for leads "
                                                 "that went cold on our side (Level 1)"))
    d.add_argument("--agent", choices=["all", *DRAFTERS], default="all")
    d.add_argument("--max", type=int, default=10, help="most drafts per agent this run")
    d.add_argument("--at")
    d = with_client(dsub.add_parser("list", help="pending and approved drafts"))
    d.add_argument("--all", action="store_true", help="include rejected and sent")
    for name in ("approve", "sent"):
        d = with_client(dsub.add_parser(name, help=f"{name} a draft (operator)"))
        d.add_argument("id")
        d.add_argument("--by", default=OPERATOR)
        d.add_argument("--at")
    d = with_client(dsub.add_parser("reject", help="reject a draft; the reason becomes a correction"))
    d.add_argument("id")
    d.add_argument("--reason", required=True)
    d.add_argument("--by", default=OPERATOR)
    d.add_argument("--at")
    d = with_client(dsub.add_parser("export", help="CSV of approved drafts for your sending tool"))
    d.add_argument("--at")
    with_client(dsub.add_parser("record", help="track record toward Level 2"))
    sp.set_defaults(fn=cmd_drafts)

    sp = with_client(sub.add_parser("opt-out", help="record that a lead asked not to be contacted"))
    sp.add_argument("ref")
    sp.add_argument("--undo", action="store_true", help="record that they opted back in")
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_opt_out)

    sp = with_client(sub.add_parser("outcome", help="record a won/lost outcome for a lead"))
    sp.add_argument("ref")
    sp.add_argument("outcome", choices=["won", "lost", "reopened"])
    sp.add_argument("--reason")
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_outcome)

    sp = with_client(sub.add_parser("audit-cold", help="run the cold-inquiry audit"))
    sp.add_argument("--as-of")
    sp.set_defaults(fn=cmd_audit_cold)

    for name, fn in (("pause", cmd_pause), ("resume", cmd_resume)):
        sp = with_client(sub.add_parser(name, help=f"{name} the client, an engine or an agent"))
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--engine")
        g.add_argument("--agent")
        sp.add_argument("--reason", default="operator request", required=(name == "pause"))
        sp.add_argument("--by", default=OPERATOR)
        sp.set_defaults(fn=fn)

    sp = with_client(sub.add_parser("quality", help="per-agent quality numbers; enforces the error budget"))
    sp.add_argument("--days", type=int, default=28)
    sp.add_argument("--as-of")
    sp.set_defaults(fn=cmd_quality)

    sp = with_client(sub.add_parser("promote", help="raise an agent one level, with your sign-off (Section 11.2)"))
    sp.add_argument("agent")
    sp.add_argument("--check", action="store_true", help="only say whether it meets the bar")
    sp.add_argument("--reason", help="why; goes in the agent's change log")
    sp.add_argument("--playbook", help="Level 2: the written playbook, a path in the workspace")
    sp.add_argument("--budget-cap", type=float, help="Level 3: the spending cap")
    sp.add_argument("--client-approval", help="Level 3: where the client approved the spend")
    sp.add_argument("--by", default=OPERATOR)
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_promote)

    sp = with_client(sub.add_parser("demote", help="record a serious error and drop the agent a level (Section 11.3)"))
    sp.add_argument("agent")
    sp.add_argument("--kind", required=True, choices=[*autonomy.SERIOUS_ERRORS, "operator"],
                    help="the serious error, or 'operator' to step it down for another reason")
    sp.add_argument("--note", help="what happened")
    sp.add_argument("--by", default=OPERATOR)
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_demote)

    sp = with_client(sub.add_parser("run-due", help="run every scheduled job that is due (call from cron)"))
    sp.add_argument("--at", help="pretend it is this time (for testing)")
    sp.set_defaults(fn=cmd_run_due)

    sp = with_client(sub.add_parser("schedule", help="each scheduled job's last and next run"))
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_schedule)

    sp = with_client(sub.add_parser("status", help="kill switch, agents, ledger and log health"))
    sp.set_defaults(fn=cmd_status)

    sp = with_client(sub.add_parser("log", help="verify or render the activity log"))
    sp.add_argument("action", choices=["verify", "render"])
    sp.set_defaults(fn=cmd_log)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"Error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1
