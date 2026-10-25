"""System quality metrics per agent (Section 14.3).

Marketing results show whether the work is effective. These show whether the
agents save the operator time and stay accurate:

- approval rate without substantive edits
- operator correction time (draft written → approved or rejected)
- unsupported claims caught before the operator saw them
- escalations to a human
- failed, duplicate and late actions

They come from the activity log and the draft queue. The same numbers feed
promotion (Section 11.2) and the error budget (Section 11.3) in autonomy.py.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from . import autonomy
from .activity_log import ActivityLog
from .control import Control
from .ledger import parse_ts
from .workspace import Workspace

LATE_AFTER = timedelta(hours=1)


def _in(ts: str, start: datetime, end: datetime) -> bool:
    return start <= parse_ts(ts) <= end


def scorecard(ws: Workspace, as_of: datetime, days: int = 28) -> list[dict]:
    from ..engines.conversion import queue
    start = as_of - timedelta(days=days)
    log = ActivityLog(ws.log_path, ws.client_id)
    entries = log.entries() if log.path.exists() else []
    paused = Control(ws.control_path).load()["agents"]
    rows = []
    for name, cfg in ws.config.agents.items():
        mine = [e for e in entries if e["agent"] == name and _in(e["ts"], start, as_of)]
        count = lambda result: sum(1 for e in mine if e["result"] == result)  # noqa: E731
        late = [e for e in entries if e["agent"] == "scheduler" and e["inputs"].get("job") == name
                and _in(e["inputs"]["slot"], start, as_of)
                and parse_ts(e["ts"]) - parse_ts(e["inputs"]["slot"]) > LATE_AFTER]
        row = {
            "agent": name, "level": autonomy.level(ws, name), "paused": name in paused,
            "runs": count("ok"), "failed": count("failed"), "blocked": count("blocked"),
            "duplicates": count("skipped_duplicate"), "late": len(late),
            "escalations": count("escalated") + sum(1 for e in mine if e["action"] == "skip_lead"
                                                    and str(e["output"].get("reason", "")).startswith("needs a human")),
            "serious_errors": len([e for e in autonomy.serious_errors(ws, name) if _in(e["inputs"]["at"], start, as_of)]),
        }
        drafts = queue.existing_drafts(ws, name)
        if drafts:
            decided, minutes, caught = [], [], 0
            for _, meta, _ in drafts:
                done_at = meta.get("approved_at") or meta.get("rejected_at")
                if done_at and _in(done_at, start, as_of):
                    decided.append(meta["status"] in ("approved", "sent") and not meta.get("edited"))
                    minutes.append((parse_ts(done_at) - parse_ts(meta["created"])).total_seconds() / 60)
                if _in(meta["created"], start, as_of) and any(
                        i.startswith(("receipts:", "facts:")) for i in meta.get("blocking_issues", [])):
                    caught += 1
            rate, n = autonomy.correction_rate(ws, name)
            row.update({
                "decided": len(decided),
                "unedited_rate": sum(decided) / len(decided) if decided else None,
                "correction_minutes": statistics.median(minutes) if minutes else None,
                "claims_caught": caught,
                "correction_rate": rate, "correction_n": n, "budget": cfg.max_correction_rate,
                "over_budget": rate is not None and n >= 5 and rate > cfg.max_correction_rate,
            })
        rows.append(row)
    return rows


def _minutes(m: float | None) -> str:
    if m is None:
        return "–"
    return f"{m:.0f} min" if m < 60 else (f"{m / 60:.1f} h" if m < 1440 else f"{m / 1440:.1f} d")


def render(rows: list[dict], days: int) -> str:
    L = [f"Agent quality, last {days} days (Section 14.3)", "",
         "| Agent | Level | Runs | Failed | Blocked | Duplicates | Late | Escalated | Serious errors |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['agent']}{' (paused)' if r['paused'] else ''} | {r['level']} | {r['runs']} | {r['failed']} | "
                 f"{r['blocked']} | {r['duplicates']} | {r['late']} | {r['escalations']} | {r['serious_errors']} |")
    drafters = [r for r in rows if "decided" in r]
    if drafters:
        L += ["", "| Drafting agent | Decided | Approved without edits | Typical correction time | "
                  "Unsupported claims caught | Corrections, last 20 (budget) |", "|---|---|---|---|---|---|"]
        for r in drafters:
            un = f"{r['unedited_rate']:.0%}" if r["unedited_rate"] is not None else "–"
            cr = (f"{r['correction_rate']:.0%} of {r['correction_n']}" if r["correction_rate"] is not None else "–")
            L.append(f"| {r['agent']} | {r['decided']} | {un} | {_minutes(r['correction_minutes'])} | "
                     f"{r['claims_caught']} | {cr} ({r['budget']:.0%}){' **over**' if r['over_budget'] else ''} |")
    return "\n".join(L) + "\n"
