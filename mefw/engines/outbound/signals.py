"""Outbound signal engine, watch and score (Section 9.2).

Watch: trigger events about companies (hiring, a move, an expansion, funding,
a lease ending, a public post about a relevant pain) come in as a CSV from
whatever the operator uses to find them: a job board export, a news alert, a
list the client keeps. Every row is about a company, never a person. Columns
that look like personal data are refused, and free text is scrubbed of contact
details. Events are kept append-only in `engines/outbound/triggers.jsonl`.

Score: ICP fit × reason × right now. Fit comes from `[outbound.icp]` (company
size, location, industry). A company that clearly falls outside it is dropped.
The reason is the best trigger's weight from `[outbound.events.<type>]`.
"Right now" fades from 1 to 0 over `fresh_days`. Companies that are suppressed
(opted out, existing customers, asked by the client to leave alone) or already
contacted within `recontact_days` are left out, with the reason recorded.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from ...core.ledger import iso, parse_ts
from ...core.pii import assert_field_allowed, scrub
from ...core.workspace import Workspace

PLAYBOOK = "engines/outbound/playbook.toml"
TRIGGERS = "engines/outbound/triggers.jsonl"
SUPPRESSED = "engines/outbound/suppressed.jsonl"
DEFAULTS = {"fresh_days": 45, "recontact_days": 90, "min_score": 4.0, "daily_send_limit": 20, "must_include": []}
COLUMNS = {"account": "Company", "event": "Event", "at": "Date", "source": "Source", "detail": "Detail",
           "employees": "Employees", "location": "Location", "industry": "Industry", "account_ref": "Account ID"}
MAX_WEIGHT = 3


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Set up the ICP, trigger types and templates first.")
    pb = {**DEFAULTS, **tomllib.loads(path.read_text()).get("outbound", {})}
    if not pb.get("events"):
        raise ValueError(f"{PLAYBOOK} has no [outbound.events.<type>] sections")
    return pb


def account_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def _append(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def triggers(ws: Workspace) -> list[dict]:
    return _read_jsonl(ws.path(TRIGGERS))


def import_triggers(ws: Workspace, path: Path, at: datetime) -> dict:
    """Read a trigger CSV. Returns counts; rows already imported are skipped."""
    pb = load_playbook(ws)
    cols = {**COLUMNS, **pb.get("columns", {})}
    known = {t["id"] for t in triggers(ws)}
    new, skipped, unknown = [], 0, {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for col in reader.fieldnames or []:
            assert_field_allowed(col)  # company data only; people stay in the client's own tools
        missing = [cols[k] for k in ("account", "event", "at") if cols[k] not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing column(s): {', '.join(missing)}")
        for row in reader:
            get = lambda k: (row.get(cols[k]) or "").strip()  # noqa: E731
            name, event = get("account"), get("event").lower().replace(" ", "_")
            if not name or not event:
                skipped += 1
                continue
            if event not in pb["events"]:
                unknown[event] = unknown.get(event, 0) + 1
                continue
            try:
                when = parse_ts(get("at"))
            except ValueError:
                when = None
            if when is None:
                skipped += 1
                continue
            detail = scrub(get("detail")) or ""
            tid = hashlib.sha256(f"{account_key(name)}|{event}|{when.date()}|{detail}".encode()).hexdigest()[:12]
            if tid in known:
                skipped += 1
                continue
            known.add(tid)
            emp = get("employees")
            new.append({"id": tid, "account": name, "account_key": account_key(name), "event": event,
                        "at": iso(when), "source": get("source"), "detail": detail,
                        "employees": int(float(emp)) if emp else None, "location": get("location"),
                        "industry": get("industry"), "account_ref": get("account_ref"), "imported_at": iso(at)})
    _append(ws.path(TRIGGERS), new)
    return {"new": len(new), "skipped": skipped, "unknown_events": unknown}


def suppressed(ws: Workspace) -> dict[str, dict]:
    """Accounts never to contact, by account key. The latest entry wins, so an entry can be lifted."""
    out = {}
    for e in _read_jsonl(ws.path(SUPPRESSED)):
        if e.get("lifted"):
            out.pop(e["account_key"], None)
        else:
            out[e["account_key"]] = e
    return out


def suppress(ws: Workspace, account: str, reason: str, by: str, at: datetime, lift: bool = False) -> dict:
    if not reason.strip():
        raise ValueError("Say why (opted out, customer, client asked), so the next person knows")
    entry = {"account": account, "account_key": account_key(account), "reason": scrub(reason), "by": by,
             "at": iso(at), "lifted": lift}
    _append(ws.path(SUPPRESSED), [entry])
    return entry


def fit(pb: dict, t: dict) -> tuple[float, list[str]]:
    """ICP fit from 0 to 1, and why. 0 means the company clearly falls outside the ICP."""
    icp = pb.get("icp", {})
    parts, why = [], []
    lo, hi = (list(icp.get("employees") or []) + [None, None])[:2]
    if lo is not None or hi is not None:
        if t["employees"] is None:
            parts.append(0.5)
            why.append("size unknown")
        elif (lo is not None and t["employees"] < lo) or (hi is not None and t["employees"] > hi):
            return 0.0, [f"{t['employees']} people is outside {lo}–{hi}"]
        else:
            parts.append(1.0)
            why.append(f"{t['employees']} people")
    for field, label in (("locations", "location"), ("industries", "industry")):
        wanted = [w.lower() for w in icp.get(field, [])]
        if not wanted:
            continue
        have = (t.get(label) or "").lower()
        if not have:
            parts.append(0.5)
            why.append(f"{label} unknown")
        elif any(w in have for w in wanted):
            parts.append(1.0)
            why.append(t[label])
        else:
            return 0.0, [f"{label} {t[label]} isn't in the ICP"]
    return (sum(parts) / len(parts) if parts else 1.0), why


def score(ws: Workspace, as_of: datetime, contacted: dict[str, datetime] | None = None) -> tuple[list[dict], dict]:
    """Accounts worth contacting now, best first; and how many were dropped for each reason."""
    pb = load_playbook(ws)
    sup = suppressed(ws)
    contacted = contacted or {}
    fresh = int(pb["fresh_days"])
    by_account: dict[str, list[dict]] = {}
    for t in triggers(ws):
        if parse_ts(t["at"]) <= as_of:
            by_account.setdefault(t["account_key"], []).append(t)
    out, dropped = [], {}

    def drop(why: str) -> None:
        dropped[why] = dropped.get(why, 0) + 1

    for key, ts in by_account.items():
        if key in sup:
            drop("suppressed")
            continue
        last = contacted.get(key)
        if last and as_of - last < timedelta(days=int(pb["recontact_days"])):
            drop("contacted recently")
            continue
        live = [t for t in ts if (as_of - parse_ts(t["at"])).days < fresh]
        if not live:
            drop("no recent trigger")
            continue
        latest = max(ts, key=lambda t: t["at"])
        f, why = fit(pb, latest)
        if f == 0:
            drop("poor fit")
            continue

        def strength(t: dict) -> float:
            weight = float(pb["events"][t["event"]].get("weight", 1))
            return weight / MAX_WEIGHT * (1 - (as_of - parse_ts(t["at"])).days / fresh)
        best = max(live, key=strength)
        reason = float(pb["events"][best["event"]].get("weight", 1)) / MAX_WEIGHT
        now = 1 - (as_of - parse_ts(best["at"])).days / fresh
        s = round(10 * f * reason * now, 1)
        if s < float(pb["min_score"]):
            drop("score below min_score")
            continue
        out.append({"account": latest["account"], "account_key": key, "account_ref": latest.get("account_ref", ""),
                    "score": s, "fit": round(f, 2), "reason": round(reason, 2), "now": round(now, 2),
                    "fit_why": why, "trigger": best, "triggers": sorted(live, key=lambda t: t["at"], reverse=True)})
    out.sort(key=lambda a: (-a["score"], a["account_key"]))
    return out, dropped
