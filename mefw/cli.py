"""Command line for the operator: `python -m mefw <command> --client <dir>`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

from . import skills
from .adapters import onboarding
from .adapters.base import import_records
from .adapters.csv_source import CsvSource
from .adapters.signals_csv import import_signals
from .core.activity_log import ActivityLog
from .core import autonomy, client_report, cockpit, quality, customer_truth, experiments, scheduler, truth_report
from .core.control import Control
from .core.errors import GuardrailError
from .core.ledger import Ledger, iso, parse_ts
from .core.runner import Runner
from .core.workspace import Workspace
from .engines.content import briefs as content
from .engines.creative import plans as creative, results as creative_results
from .engines.outbound import drafts as outbound, signals as outbound_signals
from .engines.search import analysis as search_analysis, data as search_data, pages as search_pages
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
    skills.install(dest / ".claude" / "skills")
    print(f"Created client workspace for '{args.client_id}' at {dest}")
    print("Next: edit profile/mefw.toml (stage names, CSV columns), then `mefw import-csv`.")
    print("Open Claude Code in it and type /mefw-today to see what needs you.")
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


def cmd_onboard(args) -> int:
    if args.action == "presets":
        for name, p in onboarding.list_presets().items():
            print(f"{name:<12} {p['preset']['label']}\n             Export: {p['preset']['export']}")
        return 0
    if args.action == "check":
        ws = _ws(args) if (args.client or os.environ.get("MEFW_CLIENT")) else None
        rep = onboarding.check(Path(args.file), args.preset, ws)
        print(onboarding.render(rep))
        if not args.preset:
            print(f"\nNext: mefw onboard apply {args.file} --preset {rep['preset']} --client DIR")
        return 0 if rep["ready"] else 1
    ws = _ws(args)
    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    extra = {}
    for s in args.stage or []:
        name, _, stage = s.rpartition("=")
        if not name:
            raise ValueError(f"--stage takes NAME=STAGE, not {s!r}")
        extra[name.strip()] = stage.strip().lower()
    at = datetime.now(timezone.utc)
    rep = onboarding.apply(ws, Path(args.file), args.preset, extra, at)
    log.append(OPERATOR, "onboard", "ok", {"file": rep["file"], "preset": args.preset},
               {"summary": f"Mapped {len(rep['columns'])} columns from the {args.preset} preset",
                "columns": rep["columns"], "stages_added": rep["stages_added"], "backup": rep["backup"]})
    print(f"Updated profile/mefw.toml for {rep['file']} ({rep['label']}); the old one is {rep['backup']}.")
    print(f"Mapped {len(rep['columns'])} columns; {rep['readable_rows']} of {rep['rows']} rows read cleanly.")
    if rep["stages_added"]:
        print("Stage names added: " + ", ".join(rep["stages_added"]))
    left = [v for v in rep["unmapped_stages"] if v not in extra]
    if left:
        print("Still not placed in the funnel: " + ", ".join(left))
    print(f"Next: mefw import-csv {args.file} --client {args.client or ws.root}")
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


def cmd_content(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)

    if args.action == "briefs":
        runner = Runner(ws)
        made, refused = [], None
        try:
            cands, passed = content.candidates(ws, at, runner.ledger)
            for c in cands[: args.max]:
                try:
                    res = runner.run(content.AGENT, "content_brief", "draft", f"brief:{c['insight']}:{at.date()}",
                                     lambda c=c: _brief_job(ws, c, at), {"insight": c["insight"]})
                except GuardrailError as e:
                    refused = str(e)
                    break
                if res.status == "ok":
                    made.append(res.output["id"])
            rows = content.results(ws, runner.ledger, at)
        finally:
            runner.close()
        ws.path(content.RESULTS).parent.mkdir(parents=True, exist_ok=True)
        ws.path(content.RESULTS).write_text(content.render_results(rows, at))
        print(f"Wrote {len(made)} content brief(s)" + (": " + ", ".join(made) if made else "."))
        if passed:
            print("Not enough evidence yet for: " + ", ".join(passed))
        if not cands and not passed:
            print("No confirmed insights without a recent brief. Confirm an insight record to brief it.")
        print(f"Results so far: {ws.root / content.RESULTS}")
        if refused:
            print(f"Stopped: {refused}", file=sys.stderr)
            return 2
        return 0

    if args.action == "list":
        for _, meta, _ in content.all_briefs(ws):
            pubs = ", ".join(p["channel"] for p in meta.get("published", []))
            print(f"{meta['id']}  {meta['status']:<9} tag={meta['tag']}" + (f"  published: {pubs}" if pubs else ""))
        return 0

    if args.action == "results":
        ledger = Ledger(ws.db_path, ws.client_id)
        try:
            print(content.render_results(content.results(ws, ledger, at), at))
        finally:
            ledger.close()
        return 0

    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    if args.action == "approve":
        meta = content.approve(ws, args.id, args.by, at, args.quote_permission)
        log.append(args.by, "content_approve", "ok", {"id": meta["id"], "assets": meta["approved_assets"]},
                   {"summary": f"Approved {meta['id']}: {', '.join(meta['approved_assets'])}"})
        print(f"Approved {', '.join(meta['approved_assets'])} in {meta['id']}. Publish them, then "
              f"`mefw content published {meta['id']} --channel <name> --url <link>`.")
    else:
        meta = content.published(ws, args.id, args.channel, args.url, args.by, at)
        log.append(args.by, "content_published", "ok", {"id": meta["id"], "channel": args.channel, "url": args.url},
                   {"summary": f"{meta['id']} published on {args.channel}"})
        print(f"Recorded {args.channel} for {meta['id']}. Inquiries tagged {meta['tag']} will count toward it.")
    return 0


def cmd_search(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)

    if args.action == "import":
        snap = search_data.import_snapshot(ws, Path(args.queries), date.fromisoformat(args.period_end), args.days,
                                           Path(args.pages) if args.pages else None, at)
        if snap.get("unchanged"):
            print(f"Already imported the period ending {args.period_end}; nothing new.")
            return 0
        ActivityLog(ws.log_path, ws.client_id).append(
            OPERATOR, "search_import", "ok", {"period_end": args.period_end, "days": args.days},
            {"summary": f"{len(snap['queries'])} queries, {len(snap['pages'])} pages"})
        print(f"Imported {len(snap['queries'])} queries and {len(snap['pages'])} pages for the {args.days} days "
              f"to {args.period_end}.")
        return 0

    if args.action == "analyze":
        runner = Runner(ws)
        try:
            snaps = search_data.snapshots(ws, at.date())
            key = f"search-analyze:{at.date()}:{snaps[-1]['period_end'] if snaps else 'none'}"

            def job() -> dict:
                d = search_analysis.analyze(ws, runner.ledger, at)
                rel = search_analysis.write(ws, d)
                return {"summary": f"{len(d['opportunities'])} opportunities, {len(d['gaps'])} unanswered topics, "
                                   f"{sum(bool(x['problems']) for x in d['listings'])} listing(s) to fix",
                        "report": rel}
            res = runner.run(search_analysis.AGENT, "search_report", "observe", key, job, {"at": iso(at)})
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

    if args.action == "drafts":
        runner = Runner(ws)
        made, refused = [], None
        try:
            for c in search_pages.candidates(ws, runner.ledger, at)[: args.max]:
                try:
                    res = runner.run(search_pages.AGENT, "search_draft", "draft", f"search:{c['topic']}:{at.date()}",
                                     lambda c=c: _search_job(ws, runner.ledger, c, at), {"topic": c["topic"]})
                except GuardrailError as e:
                    refused = str(e)
                    break
                if res.status == "ok":
                    made.append(res.output["id"])
        finally:
            runner.close()
        print(f"Wrote {len(made)} search draft(s)" + (": " + ", ".join(made) if made else "."))
        if refused:
            print(f"Stopped: {refused}", file=sys.stderr)
            return 2
        return 0

    if args.action == "list":
        for _, meta, _ in search_pages.all_drafts(ws):
            urls = ", ".join(p["url"] for p in meta.get("published", []))
            print(f"{meta['id']}  {meta['status']:<9} page={meta['page']}" + (f"  live: {urls}" if urls else ""))
        return 0

    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    if args.action == "ai-record":
        e = search_data.record_ai_check(ws, args.assistant, args.prompt, args.mentioned == "yes", args.cited,
                                        args.by, at, args.note or "")
        log.append(args.by, "search_ai_check", "ok", {"assistant": e["assistant"], "prompt": e["prompt"]},
                   {"mentioned": e["mentioned"], "cited": e["cited"]})
        print(f"Recorded {e['assistant']} on {e['prompt']}: " + ("mentioned" if e["mentioned"] else "not mentioned")
              + (f", cited {e['cited']}" if e["cited"] else "") + ".")
    elif args.action == "approve":
        meta = search_pages.approve(ws, args.id, args.by, at, args.quote_permission)
        log.append(args.by, "search_approve", "ok", {"id": meta["id"]}, {"summary": f"Approved {meta['id']}"})
        print(f"Approved {meta['id']}. Put it on the site, then `mefw search published {meta['id']} --url <link>`.")
    else:
        meta = search_pages.published(ws, args.id, args.url, args.by, at)
        log.append(args.by, "search_published", "ok", {"id": meta["id"], "url": args.url},
                   {"summary": f"{meta['id']} live at {args.url}"})
        print(f"Recorded {meta['id']} at {args.url}. The weekly report will track its queries.")
    return 0


def cmd_outbound(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)
    log = ActivityLog(ws.log_path, ws.client_id)

    if args.action == "import":
        rep = outbound_signals.import_triggers(ws, Path(args.file), at)
        log.append(OPERATOR, "outbound_import", "ok", {"file": Path(args.file).name}, rep)
        print(f"Imported {rep['new']} new trigger(s); skipped {rep['skipped']} already seen or incomplete.")
        if rep["unknown_events"]:
            print("Not in [outbound.events], so left out: " +
                  ", ".join(f"{k} ({v})" for k, v in rep["unknown_events"].items()))
        return 0

    if args.action == "drafts":
        runner = Runner(ws)
        made, notes, refused = [], [], None
        try:
            ranked, _ = outbound.candidates(ws, at)
            for a in ranked[: args.max]:
                try:
                    res = runner.run(outbound.AGENT, "outbound_draft", "draft",
                                     f"outbound:{a['account_key']}:{a['trigger']['id']}",
                                     lambda a=a: _outbound_job(ws, a, at), {"account": a["account_key"]})
                except GuardrailError as e:
                    refused = str(e)
                    break
                if res.status == "ok" and res.output.get("id"):
                    made.append(res.output["id"])
                elif res.output.get("skipped"):
                    notes.append(res.output["skipped"])
            if refused is None:
                key = f"outbound-report:{at.date()}:{len(outbound_signals.triggers(ws))}:{len(made)}"
                res = runner.run(outbound.AGENT, "outbound_report", "observe", key,
                                 lambda: _outbound_report(ws, at), {"at": iso(at)})
        finally:
            runner.close()
        print(f"Wrote {len(made)} outbound draft(s)" + (": " + ", ".join(made) if made else "."))
        for n in dict.fromkeys(notes):
            print(f"  note: {n}")
        if refused:
            print(f"Stopped: {refused}", file=sys.stderr)
            return 2
        if res.output.get("report"):
            print(f"Report: {ws.root / res.output['report']}")
        return 0

    if args.action == "list":
        for _, m, _ in outbound.all_drafts(ws):
            got = ", ".join(o["outcome"] for o in m.get("outcomes", []))
            print(f"{m['id']}  {m['status']:<9} score={m['score']} {m['event']}" + (f"  back: {got}" if got else ""))
        return 0

    log.verify()
    if args.action == "approve":
        meta = outbound.approve(ws, args.id, args.by, at)
        msg = f"Approved {meta['id']}" + (" (edited)" if meta["edited"] else "")
        print(f"{msg}. Pick the person in your own tool, send it, then `mefw outbound sent {meta['id']}`.")
    elif args.action == "reject":
        meta = outbound.reject(ws, args.id, args.reason, args.by, at)
        msg = f"Rejected {meta['id']}: {meta['reason']}"
        print(msg + ".")
    elif args.action == "sent":
        meta = outbound.mark_sent(ws, args.id, args.by, at)
        msg = f"Sent {meta['id']}"
        print(f"{msg}. Record what comes back with `mefw outbound outcome {meta['id']} <outcome>`.")
    elif args.action == "outcome":
        meta = outbound.record_outcome(ws, args.id, args.outcome, args.by, at)
        msg = f"{meta['id']}: {args.outcome}"
        print(msg + (f". {meta['account']} is suppressed; nobody will draft to them again." if
                     args.outcome == "opted_out" else "."))
    else:
        withdrawn = outbound.stop(ws, args.company, args.reason, args.by, at)
        msg = f"Suppressed {args.company}: {args.reason}"
        print(msg + (f". Withdrew {', '.join(withdrawn)}." if withdrawn else "."))
    log.append(args.by, f"outbound_{args.action}", "ok", {"id": getattr(args, "id", None) or args.company},
               {"summary": msg})
    return 0


def cmd_creative(args) -> int:
    ws = _ws(args)
    at = parse_ts(args.at) if getattr(args, "at", None) else datetime.now(timezone.utc)

    if args.action == "plan":
        runner = Runner(ws)
        made, refused = [], None
        try:
            cands, passed = creative.candidates(ws, at, runner.ledger)
            for c in cands[: args.max]:
                try:
                    res = runner.run(creative.AGENT, "creative_plan", "draft", f"creative:{c['insight']}:{at.date()}",
                                     lambda c=c: _creative_job(ws, c, at), {"insight": c["insight"]})
                except GuardrailError as e:
                    refused = str(e)
                    break
                if res.status == "ok":
                    made.append(res.output["id"])
            if refused is None:
                key = f"creative-results:{at.isoformat()}"
                res = runner.run(creative.AGENT, "creative_results", "observe", key,
                                 lambda: _creative_results_job(ws, runner.ledger, at), {"at": iso(at)})
        finally:
            runner.close()
        print(f"Wrote {len(made)} creative test plan(s)" + (": " + ", ".join(made) if made else "."))
        if passed:
            print("Not enough evidence yet for: " + ", ".join(passed))
        if refused:
            print(f"Stopped: {refused}", file=sys.stderr)
            return 2
        if res.output.get("report"):
            print(f"Results: {ws.root / res.output['report']}")
        return 0

    if args.action == "list":
        for _, m, _ in creative.all_plans(ws):
            keys = m.get("live_variants") or [v["key"] for v in m["variants"]]
            extra = f"  winner={m['winner']}" if m.get("winner") else ""
            print(f"{m['id']}  {m['status']:<9} variants={','.join(keys)}{extra}")
        return 0

    if args.action == "results":
        ledger = Ledger(ws.db_path, ws.client_id)
        try:
            _, measured = creative_results.write_report(ws, ledger, at)
            print(creative_results.render(ws, measured, at))
        finally:
            ledger.close()
        return 0

    log = ActivityLog(ws.log_path, ws.client_id)
    log.verify()
    if args.action == "approve":
        meta = creative.approve(ws, args.id, args.by, at, args.quote_permission)
        msg = f"Approved {meta['id']}: variants {', '.join(k.upper() for k in meta['live_variants'])}"
        print(f"{msg}. Build the ads with each variant's tag, set the budgets yourself, then "
              f"`mefw creative start {meta['id']}`.")
    elif args.action == "start":
        meta = creative.start(ws, args.id, args.by, at)
        msg = f"Started {meta['id']}"
        print(f"{msg}. Import the ad platform's numbers with `mefw creative results-import {meta['id']} <file>`.")
    elif args.action == "results-import":
        snap = creative_results.import_results(ws, args.id, Path(args.file), at)
        spend = sum(v["spend"] for v in snap["variants"].values())
        msg = f"Imported results for {args.id}: {spend:g} spent"
        print(msg + (f"; {snap['unmatched_rows']} row(s) matched no variant tag" if snap["unmatched_rows"] else "")
              + ".")
    else:
        ledger = Ledger(ws.db_path, ws.client_id)
        try:
            meta = creative_results.close(ws, ledger, args.id, args.winner, args.lesson, args.by, at)
        finally:
            ledger.close()
        msg = f"Closed {meta['id']}: winner {meta['winner']}"
        print(msg + (f". Added to {creative.WINNERS}." if meta["winner"] != "none" else "."))
    log.append(args.by, f"creative_{args.action.replace('-', '_')}", "ok", {"id": args.id}, {"summary": msg})
    return 0


def _creative_job(ws: Workspace, c: dict, at: datetime) -> dict:
    meta = creative.make_plan(ws, c, at)
    return {"summary": f"Creative test plan {meta['id']} for {c['insight']}", "id": meta["id"]}


def _creative_results_job(ws: Workspace, ledger: Ledger, at: datetime) -> dict:
    rel, measured = creative_results.write_report(ws, ledger, at)
    return {"summary": f"{len(measured)} running test(s) measured", "report": rel}


def _outbound_job(ws: Workspace, a: dict, at: datetime) -> dict:
    meta = outbound.make_draft(ws, a, at)
    if "skipped" in meta:
        return {"summary": meta["skipped"], "skipped": meta["skipped"]}
    blocked = f"; {len(meta['blocking_issues'])} blocking issue(s)" if meta["blocking_issues"] else ""
    return {"summary": f"Outbound draft {meta['id']} ({meta['event']}, score {meta['score']}){blocked}",
            "id": meta["id"]}


def _outbound_report(ws: Workspace, at: datetime) -> dict:
    rel, info = outbound.write_report(ws, at)
    return {"summary": f"{info['ranked']} companies worth contacting", "report": rel}


def _search_job(ws: Workspace, ledger: Ledger, c: dict, at: datetime) -> dict:
    meta = search_pages.make_draft(ws, ledger, c, at)
    return {"summary": f"Search draft {meta['id']} for {c['topic']}", "id": meta["id"]}


def _brief_job(ws: Workspace, c: dict, at: datetime) -> dict:
    meta = content.make_brief(ws, c, at)
    return {"summary": f"Brief {meta['id']} for {c['insight']}", "id": meta["id"]}


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


def cmd_today(args) -> int:
    """What needs the operator right now. No agent runs and nothing goes in the activity log."""
    ws = _ws(args)
    at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    ctl = Control(ws.control_path).load()
    try:
        log_ok, log_state = True, f"OK ({ActivityLog(ws.log_path, ws.client_id).verify()} entries)"
    except GuardrailError as e:
        log_ok, log_state = False, f"BROKEN: {e}. Every agent is stopped until it's fixed."
    ledger = Ledger(ws.db_path, ws.client_id)
    try:
        data = cockpit.build(ws, ledger, at)
        counts = ledger.counts()
    finally:
        ledger.close()
    paused = ([f"whole client ({ctl['client'].get('reason')})"] if ctl.get("client") else []) + \
        [f"{name} ({flag.get('reason')})" for name, flag in {**ctl["engines"], **ctl["agents"]}.items()]
    try:
        local = at.astimezone(ZoneInfo(ws.config.timezone))
    except (KeyError, ValueError):
        local = at
    out = {"client": ws.client_id, "name": ws.config.client_name, "at": iso(at),
           "local_time": local.strftime("%a %d %b %Y %H:%M ") + str(local.tzinfo),
           "activity_log_ok": log_ok, "activity_log": log_state, "paused": paused,
           "leads": counts["leads"], "north_star": data["north_star"], "decisions": data["decisions"]}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    ns = data["north_star"]
    print(f"{ws.config.client_name or ws.client_id} ({ws.client_id}), {out['local_time']}")
    print(f"Activity log: {log_state}")
    print(f"Paused: {', '.join(paused) if paused else 'nothing'}")
    print(f"{ns['label']}: {ns['this_week']:g} this week, {ns['last_week']:g} last week. "
          f"{counts['leads']} leads in the ledger.")
    print()
    if not data["decisions"]:
        print("Nothing needs you right now.")
        return 0
    print(f"What needs you ({len(data['decisions'])}):")
    for i, d in enumerate(data["decisions"], 1):
        print(f"{i}. {d}")
    return 0


def cmd_skills(args) -> int:
    if args.action == "list":
        for name, text in skills.shipped().items():
            print(f"/{name}  {skills.description(text)}")
        return 0
    if args.user:
        dest = Path.home() / ".claude" / "skills"
    else:
        dest = _ws(args).root / ".claude" / "skills"
    for name, state in skills.install(dest):
        print(f"{state:9}  /{name}")
    print(f"Installed in {dest}. Start a new Claude Code session there to use them.")
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

    sp = sub.add_parser("onboard", help="map a client's lead export with a preset for their lead tool")
    osub = sp.add_subparsers(dest="action", required=True)
    osub.add_parser("presets", help="the lead tools with a preset, and how to export from each")
    c = with_client(osub.add_parser("check", help="what a preset makes of an export (picks one if not given)"))
    c.add_argument("file")
    c.add_argument("--preset")
    c = with_client(osub.add_parser("apply", help="write the mapping into profile/mefw.toml (keeps a backup)"))
    c.add_argument("file")
    c.add_argument("--preset", required=True)
    c.add_argument("--stage", action="append", help="place a stage value in the funnel: \"Tour Done=meet\"")
    sp.set_defaults(fn=cmd_onboard)

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

    sp = sub.add_parser("content", help="content engine: briefs from confirmed insights, approval, publishing, results")
    csub = sp.add_subparsers(dest="action", required=True)
    c = with_client(csub.add_parser("briefs", help="write briefs for confirmed insights (Level 1)"))
    c.add_argument("--max", type=int, default=3)
    c.add_argument("--at")
    with_client(csub.add_parser("list", help="briefs and what's been published"))
    c = with_client(csub.add_parser("approve", help="check the written assets and approve them"))
    c.add_argument("id")
    c.add_argument("--quote-permission", action="store_true",
                   help="you have permission from anyone quoted in the assets")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(csub.add_parser("published", help="record that an approved asset went live"))
    c.add_argument("id")
    c.add_argument("--channel", required=True)
    c.add_argument("--url", required=True)
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(csub.add_parser("results", help="inquiries traced to each brief's tag"))
    c.add_argument("--at")
    sp.set_defaults(fn=cmd_content)

    sp = sub.add_parser("search", help="search visibility: import search data, report, drafts, AI assistant checks")
    ssub = sp.add_subparsers(dest="action", required=True)
    c = with_client(ssub.add_parser("import", help="import a Search Console queries export"))
    c.add_argument("queries")
    c.add_argument("--pages", help="the matching pages export (optional)")
    c.add_argument("--period-end", required=True, help="last day the export covers (YYYY-MM-DD)")
    c.add_argument("--days", type=int, default=28)
    c.add_argument("--at")
    c = with_client(ssub.add_parser("analyze", help="weekly search report (Level 0)"))
    c.add_argument("--at")
    c = with_client(ssub.add_parser("drafts", help="draft FAQ and page changes (Level 1)"))
    c.add_argument("--max", type=int, default=3)
    c.add_argument("--at")
    with_client(ssub.add_parser("list", help="search drafts and where they went live"))
    c = with_client(ssub.add_parser("approve", help="check a draft and approve it"))
    c.add_argument("id")
    c.add_argument("--quote-permission", action="store_true",
                   help="you have permission from anyone quoted in the draft")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(ssub.add_parser("published", help="record that an approved draft went live"))
    c.add_argument("id")
    c.add_argument("--url", required=True)
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(ssub.add_parser("ai-record", help="record what an AI assistant said for one prompt"))
    c.add_argument("--assistant", required=True)
    c.add_argument("--prompt", required=True, help="the prompt's key under [search.ai.prompts]")
    c.add_argument("--mentioned", required=True, choices=["yes", "no"])
    c.add_argument("--cited", help="the URL it cited, if any of ours")
    c.add_argument("--note")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("creative", help="creative testing: plans from confirmed insights, checks, results by cost")
    rsub = sp.add_subparsers(dest="action", required=True)
    c = with_client(rsub.add_parser("plan", help="plan tests and measure running ones (Level 1)"))
    c.add_argument("--max", type=int, default=2)
    c.add_argument("--at")
    with_client(rsub.add_parser("list", help="creative tests and their state"))
    c = with_client(rsub.add_parser("results", help="cost per qualified inquiry, meeting and commitment"))
    c.add_argument("--at")
    c = with_client(rsub.add_parser("approve", help="check the written variants and the budget plan"))
    c.add_argument("id")
    c.add_argument("--quote-permission", action="store_true",
                   help="you have permission from anyone quoted in the ads")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(rsub.add_parser("start", help="record that the ads are live"))
    c.add_argument("id")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(rsub.add_parser("results-import", help="import the ad platform's export (totals to date)"))
    c.add_argument("id")
    c.add_argument("file")
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(rsub.add_parser("close", help="make the call and record the lesson"))
    c.add_argument("id")
    c.add_argument("--winner", required=True, help="the variant letter, or none")
    c.add_argument("--lesson", required=True)
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    sp.set_defaults(fn=cmd_creative)

    sp = sub.add_parser("outbound", help="outbound signals: import triggers, score, draft, send by hand, learn")
    osub = sp.add_subparsers(dest="action", required=True)
    c = with_client(osub.add_parser("import", help="import a CSV of company trigger events"))
    c.add_argument("file")
    c.add_argument("--at")
    c = with_client(osub.add_parser("drafts", help="score companies, draft messages, write the report (Level 1)"))
    c.add_argument("--max", type=int, default=5)
    c.add_argument("--at")
    with_client(osub.add_parser("list", help="outbound drafts and what came back"))
    for name, help_ in (("approve", "check a draft and approve it"), ("sent", "record that you sent it")):
        c = with_client(osub.add_parser(name, help=help_))
        c.add_argument("id")
        c.add_argument("--by", default=OPERATOR)
        c.add_argument("--at")
    c = with_client(osub.add_parser("reject", help="reject a draft, with the reason"))
    c.add_argument("id")
    c.add_argument("--reason", required=True)
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(osub.add_parser("outcome", help="record what came back"))
    c.add_argument("id")
    c.add_argument("outcome", choices=list(outbound.OUTCOMES))
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    c = with_client(osub.add_parser("suppress", help="never contact this company (opted out, customer, client asked)"))
    c.add_argument("company")
    c.add_argument("--reason", required=True)
    c.add_argument("--by", default=OPERATOR)
    c.add_argument("--at")
    sp.set_defaults(fn=cmd_outbound)

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

    sp = with_client(sub.add_parser("today", help="what needs you right now (reads only)"))
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--at", help="pretend it is this time (for testing)")
    sp.set_defaults(fn=cmd_today)

    sp = sub.add_parser("skills", help="Claude Code slash commands for the operator (/mefw-today and others)")
    ksub = sp.add_subparsers(dest="action", required=True)
    ksub.add_parser("list", help="the skills that ship with mefw")
    k = with_client(ksub.add_parser("install", help="install or update them in the client workspace"))
    k.add_argument("--user", action="store_true", help="install in ~/.claude/skills instead, for every folder")
    sp.set_defaults(fn=cmd_skills)

    sp = with_client(sub.add_parser("log", help="verify or render the activity log"))
    sp.add_argument("action", choices=["verify", "render"])
    sp.set_defaults(fn=cmd_log)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"Error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1
