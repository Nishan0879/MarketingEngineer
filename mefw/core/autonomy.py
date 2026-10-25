"""Promotion, demotion and the error budget (Sections 11.2 and 11.3).

An agent's level in profile/mefw.toml is where it starts, and it can start at
Level 0 or 1 only. Every change after that goes through `mefw promote` or
`mefw demote` and is kept in control/autonomy.json. That file is what the
runner reads. Each change is also written to the activity log and to the
agent's change log, which is the operator's sign-off (Section 11.2). Raising
the number in mefw.toml by hand gives no more than Level 1.

Promotion is one level at a time, and only once the default threshold is met:

- 0 → 1: at least 14 days of successful runs and no failures in the last 14
  days. The operator's sign-off covers "accurate and sourced".
- 1 → 2: the agent's draft track record meets the bar (20 unedited approvals
  in a row over 2+ weeks), and a written playbook exists in the workspace.
- 2 → 3: 30+ days at Level 2 with no serious error, a budget cap, and a
  reference to the client's approval to spend.

Demotion by one level happens after any serious error the operator records
(a false claim sent, a message to an opted-out contact, a duplicate send, a
budget overrun, an accuracy complaint). An agent at Level 2 or above also
drops back to Level 1 when its correction rate over its last 20 decided
drafts goes above `max_correction_rate` in its config (the error budget).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .activity_log import ActivityLog
from .ledger import iso, parse_ts
from .workspace import Workspace

PATH = "control/autonomy.json"
MAX_STARTING_LEVEL = 1
SERIOUS_ERRORS = {
    "false_claim": "a false claim was published or sent",
    "opted_out_contact": "someone who opted out was contacted",
    "duplicate_send": "the same message went out twice",
    "budget_overrun": "spend went over the cap",
    "accuracy_complaint": "a customer or the client complained about accuracy",
}
ERROR_BUDGET_WINDOW = 20


def _load(ws: Workspace) -> dict | None:
    path = ws.path(PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        return None  # unreadable: fail closed


def _save(ws: Workspace, data: dict) -> None:
    path = ws.path(PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def level(ws: Workspace, agent: str) -> int:
    """The level the runner enforces."""
    cfg = ws.config.agents.get(agent)
    if cfg is None:
        return 0
    data = _load(ws)
    if data is None:
        return 0
    if agent in data:
        return int(data[agent]["level"])
    return min(cfg.level, MAX_STARTING_LEVEL)


def record(ws: Workspace, agent: str) -> dict | None:
    data = _load(ws) or {}
    return data.get(agent)


def _change(ws: Workspace, agent: str, new: int, kind: str, by: str, reason: str, at: datetime,
            extra: dict | None = None) -> dict:
    old = level(ws, agent)
    data = _load(ws)
    if data is None:
        raise ValueError(f"{PATH} is unreadable; fix it by hand before changing levels")
    entry = {"level": new, "since": iso(at), "by": by, "reason": reason, "change": kind, **(extra or {})}
    data[agent] = entry
    _save(ws, data)
    ActivityLog(ws.log_path, ws.client_id).append(
        by, kind, "ok", {"agent": agent, "from": old, "to": new, **(extra or {})}, {"reason": reason})
    spec = ws.path(ws.config.agents[agent].spec)
    if spec.exists():
        line = f"- {at.date().isoformat()}: {kind}d from Level {old} to Level {new} by {by}: {reason}"
        if extra:
            line += " (" + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in extra.items()) + ")"
        text = spec.read_text()
        spec.write_text(text.rstrip("\n") + "\n" + line + "\n")
    return {"agent": agent, "from": old, **entry}


def _runs(ws: Workspace, agent: str) -> list[dict]:
    log = ActivityLog(ws.log_path, ws.client_id)
    return [e for e in log.entries() if e["agent"] == agent] if log.path.exists() else []


def serious_errors(ws: Workspace, agent: str, since: datetime | None = None) -> list[dict]:
    log = ActivityLog(ws.log_path, ws.client_id)
    out = [e for e in log.entries() if e["action"] == "serious_error" and e["inputs"].get("agent") == agent]
    return [e for e in out if since is None or parse_ts(e["inputs"]["at"]) >= since]


def promotion_check(ws: Workspace, agent: str, at: datetime, playbook: str | None = None,
                    budget_cap: float | None = None, client_approval: str | None = None) -> list[str]:
    """Why this agent can't go up a level yet; an empty list means it can."""
    from ..engines.conversion import queue  # drafting agents keep their track record in the queue
    if agent not in ws.config.agents:
        return [f"No agent '{agent}' in profile/mefw.toml"]
    now = level(ws, agent)
    if now >= 3:
        return ["Already at Level 3, the top of the ladder"]
    missing = []
    if now == 0:
        ok = [parse_ts(e["ts"]) for e in _runs(ws, agent) if e["result"] == "ok"]
        if len(ok) < 2 or at - min(ok) < timedelta(days=14):
            missing.append("needs successful runs across at least 14 days")
        if any(e["result"] == "failed" and parse_ts(e["ts"]) >= at - timedelta(days=14) for e in _runs(ws, agent)):
            missing.append("failed in the last 14 days")
    elif now == 1:
        rec = queue.track_record(ws, agent)
        if not queue.existing_drafts(ws, agent):
            missing.append("writes no drafts; Level 2 is only defined for drafting agents")
        elif not rec["decided"]:
            missing.append("has no approved or rejected drafts yet")
        elif not rec["meets_threshold"]:
            missing.append(f"needs {queue.PROMOTION_STREAK} unedited approvals in a row over "
                           f"{queue.PROMOTION_DAYS}+ days (now {rec['streak']} over {rec['streak_days']} days)")
        if not playbook:
            missing.append("needs --playbook: the written playbook of exactly what it may do at Level 2")
        elif not ws.path(playbook).exists():
            missing.append(f"playbook {playbook} doesn't exist")
    else:
        since = parse_ts(record(ws, agent)["since"])
        if at - since < timedelta(days=30):
            missing.append(f"needs 30 days at Level 2 (has {(at - since).days})")
        if serious_errors(ws, agent, since):
            missing.append("had a serious error at Level 2")
        if not budget_cap or budget_cap <= 0:
            missing.append("needs --budget-cap")
        if not (client_approval or "").strip():
            missing.append("needs --client-approval: where the client approved the spend")
    return missing


def promote(ws: Workspace, agent: str, by: str, reason: str, at: datetime, playbook: str | None = None,
            budget_cap: float | None = None, client_approval: str | None = None) -> dict:
    if not reason.strip():
        raise ValueError("A promotion needs a reason; it goes in the agent's change log")
    missing = promotion_check(ws, agent, at, playbook, budget_cap, client_approval)
    if missing:
        raise ValueError(f"Can't promote {agent} yet: " + "; ".join(missing))
    extra = {k: v for k, v in (("playbook", playbook), ("budget_cap", budget_cap),
                               ("client_approval", client_approval)) if v}
    return _change(ws, agent, level(ws, agent) + 1, "promote", by, reason.strip(), at, extra)


def report_serious_error(ws: Workspace, agent: str, kind: str, note: str, by: str, at: datetime) -> dict:
    """Record a serious error (Section 11.3) and demote the agent by one level."""
    if kind not in SERIOUS_ERRORS:
        raise ValueError(f"Kind must be one of: {', '.join(SERIOUS_ERRORS)}")
    if agent not in ws.config.agents:
        raise ValueError(f"No agent '{agent}' in profile/mefw.toml")
    ActivityLog(ws.log_path, ws.client_id).append(
        by, "serious_error", "escalated", {"agent": agent, "kind": kind, "at": iso(at)},
        {"reason": f"{SERIOUS_ERRORS[kind]}: {note}".rstrip(": ")})
    now = level(ws, agent)
    if now == 0:
        return {"agent": agent, "from": 0, "level": 0, "reason": "already at Level 0"}
    return _change(ws, agent, now - 1, "demote", by, f"serious error, {SERIOUS_ERRORS[kind]}"
                   + (f" ({note})" if note else ""), at)


def demote(ws: Workspace, agent: str, by: str, reason: str, at: datetime) -> dict:
    """The operator steps an agent down a level without a serious error."""
    if agent not in ws.config.agents:
        raise ValueError(f"No agent '{agent}' in profile/mefw.toml")
    if not reason.strip():
        raise ValueError("A demotion needs a reason; it goes in the agent's change log")
    now = level(ws, agent)
    if now == 0:
        raise ValueError(f"{agent} is already at Level 0")
    return _change(ws, agent, now - 1, "demote", by, reason.strip(), at)


def correction_rate(ws: Workspace, agent: str) -> tuple[float | None, int]:
    """Share of the agent's last 20 decided drafts that were edited or rejected."""
    from ..engines.conversion import queue
    decided = []
    for _, meta, _ in queue.existing_drafts(ws, agent):
        if meta["status"] in ("approved", "sent"):
            decided.append((meta["approved_at"], bool(meta.get("edited"))))
        elif meta["status"] == "rejected":
            decided.append((meta["rejected_at"], True))
    last = [c for _, c in sorted(decided)][-ERROR_BUDGET_WINDOW:]
    return (sum(last) / len(last) if last else None), len(last)


def enforce_error_budget(ws: Workspace, at: datetime) -> list[dict]:
    """Drop agents at Level 2+ back to Level 1 when their correction rate is over budget."""
    out = []
    for name, cfg in ws.config.agents.items():
        if level(ws, name) < 2:
            continue
        rate, n = correction_rate(ws, name)
        if rate is not None and n >= 5 and rate > cfg.max_correction_rate:
            out.append(_change(ws, name, 1, "demote", "error-budget",
                               f"correction rate {rate:.0%} over the last {n} drafts is above the "
                               f"{cfg.max_correction_rate:.0%} budget; back to Level 1 until reviewed", at))
    return out
