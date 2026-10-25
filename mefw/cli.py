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
from .core import cockpit, customer_truth, experiments, truth_report
from .core.control import Control
from .core.errors import GuardrailError
from .core.ledger import Ledger, parse_ts
from .core.runner import Runner
from .core.workspace import Workspace
from .engines.conversion import cold_audit

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
        print(f"  {a.name}: engine={a.engine} level={a.level} cap={a.max_actions_per_day}/day {spec} {state}")
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

    sp = with_client(sub.add_parser("status", help="kill switch, agents, ledger and log health"))
    sp.set_defaults(fn=cmd_status)

    sp = with_client(sub.add_parser("log", help="verify or render the activity log"))
    sp.add_argument("action", choices=["verify", "render"])
    sp.set_defaults(fn=cmd_log)

    args = p.parse_args(argv)
    return args.fn(args)
