"""Scheduled runs (Section 19, "Scheduled workflows"; Section 22, where agents run day to day).

Each client's profile/mefw.toml has a [schedule] table: one line per job, in
the client's timezone.

    [schedule]
    import                 = "every 2h"
    first-response-drafter = "every 2h"
    growth-cockpit         = "weekly mon 07:00"

`mefw run-due` is meant to be called often (every 15 minutes by cron, Task
Scheduler or any runner). It works out each job's latest scheduled slot and
runs the jobs whose slot hasn't run yet, in a fixed order, so imports land
before the agents that read them and the cockpit comes last. Missed slots
aren't replayed; only the latest one runs. Every job goes through the same
commands, and so the same runner guardrails, as running it by hand. Each
attempt is logged as a `scheduler` entry; a failed slot is retried once on the
next call, then left for the operator.

The import job reads the client's exports from the paths in [schedule.inbox]
and skips them when they haven't changed since the last import.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import re
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .activity_log import ActivityLog
from .ledger import iso, parse_ts
from .workspace import Workspace

AGENT = "scheduler"
ACTION = "scheduled_run"
# The order jobs run in when several are due at once.
ORDER = ["import", "customer-truth-analyst", "cold-inquiry-auditor", "first-response-drafter",
         "re-engagement-drafter", "experiment-tracker", "growth-cockpit", "client-reporter"]
MAX_ATTEMPTS = 2  # per slot: the first try and one retry
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LOCK = "control/scheduler.lock"


@dataclass
class Schedule:
    text: str
    kind: str          # every | daily | weekly | monthly
    minutes: int = 0   # every: interval
    at: time | None = None
    weekday: int = 0
    day: int = 1       # monthly: day of the month

    @classmethod
    def parse(cls, text: str) -> "Schedule":
        t = text.strip().lower()
        if t == "hourly":
            return cls(text, "every", minutes=60)
        m = re.fullmatch(r"every (\d+)\s*(m|min|minutes?|h|hours?)", t)
        if m:
            n = int(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
            if not 5 <= n <= 24 * 60:
                raise ValueError(f"'{text}': an interval must be between 5 minutes and 24 hours")
            return cls(text, "every", minutes=n)
        m = re.fullmatch(r"daily (\d{1,2}):(\d{2})", t)
        if m:
            return cls(text, "daily", at=time(int(m.group(1)), int(m.group(2))))
        m = re.fullmatch(r"weekly (mon|tue|wed|thu|fri|sat|sun)\w* (\d{1,2}):(\d{2})", t)
        if m:
            return cls(text, "weekly", at=time(int(m.group(2)), int(m.group(3))), weekday=DAYS.index(m.group(1)))
        m = re.fullmatch(r"monthly (\d{1,2}) (\d{1,2}):(\d{2})", t)
        if m:
            if not 1 <= int(m.group(1)) <= 28:
                raise ValueError(f"'{text}': use a day from 1 to 28 so every month has it")
            return cls(text, "monthly", at=time(int(m.group(2)), int(m.group(3))), day=int(m.group(1)))
        raise ValueError(f"Can't read schedule '{text}'. Use \"every 2h\", \"every 30m\", \"hourly\", "
                         "\"daily 07:00\", \"weekly mon 07:00\" or \"monthly 1 08:00\".")

    @property
    def period(self) -> timedelta:
        return {"every": timedelta(minutes=self.minutes), "daily": timedelta(days=1),
                "weekly": timedelta(days=7), "monthly": timedelta(days=31)}[self.kind]

    def latest_slot(self, now: datetime, tz) -> datetime:
        """The most recent scheduled time at or before now, in UTC. Wall-clock times follow the client's timezone."""
        local = now.astimezone(tz)
        midnight = datetime.combine(local.date(), time(0), tz)
        if self.kind == "monthly":
            slot = datetime.combine(local.date().replace(day=self.day), self.at)
            if slot > local.replace(tzinfo=None):
                slot = _add_months(slot, -1)
            return slot.replace(tzinfo=tz).astimezone(timezone.utc)
        if self.kind == "every":
            elapsed = int((local.replace(tzinfo=None) - midnight.replace(tzinfo=None)).total_seconds() // 60)
            slot = midnight.replace(tzinfo=None) + timedelta(minutes=elapsed - elapsed % self.minutes)
        else:
            slot = datetime.combine(local.date(), self.at)
            if self.kind == "weekly":
                slot -= timedelta(days=(local.weekday() - self.weekday) % 7)
            if slot > local.replace(tzinfo=None):
                slot -= self.period
        return slot.replace(tzinfo=tz).astimezone(timezone.utc)

    def next_slot(self, now: datetime, tz) -> datetime:
        if self.kind == "monthly":
            local = _add_months(self.latest_slot(now, tz).astimezone(tz).replace(tzinfo=None), 1)
            return local.replace(tzinfo=tz).astimezone(timezone.utc)
        local = self.latest_slot(now, tz).astimezone(tz).replace(tzinfo=None) + self.period
        if self.kind == "every" and local.date() != self.latest_slot(now, tz).astimezone(tz).date():
            local = datetime.combine(local.date(), time(0))  # intervals restart at local midnight
        return local.replace(tzinfo=tz).astimezone(timezone.utc)


def _add_months(dt: datetime, n: int) -> datetime:
    y, m = divmod(dt.month - 1 + n, 12)
    return dt.replace(year=dt.year + y, month=m + 1)  # day is 1-28, so it exists in every month


def client_tz(ws: Workspace):
    try:
        return ZoneInfo(ws.config.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def schedules(ws: Workspace) -> dict[str, Schedule]:
    raw = {k: v for k, v in ws.config.schedule.items() if isinstance(v, str)}
    unknown = sorted(set(raw) - set(ORDER))
    if unknown:
        raise ValueError(f"Unknown job(s) in [schedule]: {', '.join(unknown)}. Known jobs: {', '.join(ORDER)}")
    for name in raw:
        if name != "import" and name not in ws.config.agents:
            raise ValueError(f"[schedule] has '{name}', but there is no [agents.{name}] in profile/mefw.toml")
    return {name: Schedule.parse(raw[name]) for name in ORDER if name in raw}


def history(ws: Workspace) -> list[dict]:
    log = ActivityLog(ws.log_path, ws.client_id)
    if not log.path.exists():
        return []
    return [e for e in log.entries() if e["agent"] == AGENT and e["action"] == ACTION]


def attempts(hist: list[dict], job: str, slot: str) -> list[dict]:
    return [e for e in hist if e["inputs"].get("job") == job and e["inputs"].get("slot") == slot]


def due(ws: Workspace, now: datetime) -> list[tuple[str, Schedule, datetime, int]]:
    """Jobs whose latest slot hasn't run yet (or failed once): (job, schedule, slot, attempt number)."""
    tz, hist, out = client_tz(ws), history(ws), []
    for job, sched in schedules(ws).items():
        slot = sched.latest_slot(now, tz)
        tries = attempts(hist, job, iso(slot))
        if any(e["result"] in ("ok", "skipped") for e in tries) or len(tries) >= MAX_ATTEMPTS:
            continue
        out.append((job, sched, slot, len(tries) + 1))
    return out


def _fingerprint(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _last_import_fingerprint(hist: list[dict]) -> str | None:
    done = [e for e in hist if e["inputs"].get("job") == "import" and e["result"] == "ok"]
    return done[-1]["output"].get("fingerprint") if done else None


def _call(argv: list[str]) -> tuple[int, str]:
    from .. import cli  # the scheduler drives the same commands an operator runs
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        try:
            code = cli.main(argv)
        except Exception as e:  # a crash in one job must not stop the others
            print(f"Error: {type(e).__name__}: {e}")
            code = 1
    return code, out.getvalue()


def command_for(ws: Workspace, job: str, now: datetime) -> list[list[str]]:
    c, at = ["--client", str(ws.root)], now.isoformat()
    return {
        "customer-truth-analyst": [["truth", *c, "--as-of", at]],
        "cold-inquiry-auditor": [["audit-cold", *c, "--as-of", at]],
        "first-response-drafter": [["drafts", "make", *c, "--agent", job, "--at", at]],
        "re-engagement-drafter": [["drafts", "make", *c, "--agent", job, "--at", at]],
        "experiment-tracker": [["experiment", "measure", *c, "--at", at]],
        "growth-cockpit": [["cockpit", *c, "--as-of", at]],
        "client-reporter": [["report", "make", *c, "--as-of", at]],
    }[job]


def run_import(ws: Workspace, hist: list[dict]) -> tuple[str, dict]:
    inbox = ws.config.schedule.get("inbox", {})
    if not inbox.get("leads"):
        return "skipped", {"summary": "no [schedule.inbox] leads path set"}
    leads = ws.path(inbox["leads"])
    if not leads.exists():
        return "skipped", {"summary": f"no export at {inbox['leads']}"}
    activities = ws.path(inbox["activities"]) if inbox.get("activities") else None
    signals = ws.path(inbox["signals"]) if inbox.get("signals") else None
    files = [p for p in (leads, activities, signals) if p and p.exists()]
    fp = _fingerprint(files)
    if fp == _last_import_fingerprint(hist):
        return "skipped", {"summary": "exports unchanged since the last import", "fingerprint": fp}
    c = ["--client", str(ws.root)]
    argv = ["import-csv", *c, str(leads)] + (["--activities", str(activities)] if activities in files else [])
    code, out = _call(argv)
    if code == 0 and signals in files:
        code, more = _call(["import-signals", *c, str(signals)])
        out += more
    return ("ok" if code == 0 else "failed"), {"summary": _tail(out), "fingerprint": fp, "exit": code}


NOISE = ("Review them in", "Insight:", "  warning:", "  ...and")


def _tail(out: str, lines: int = 6) -> str:
    kept = [ln for ln in out.strip().splitlines() if ln.strip() and not ln.startswith(NOISE)]
    return "\n".join(kept[-lines:])


def run_due(ws: Workspace, now: datetime) -> list[dict]:
    """Run every due job once. Returns what happened to each, in order."""
    lock_path = ws.path(LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return [{"job": "*", "result": "skipped", "summary": "another scheduled run is still going"}]
        log = ActivityLog(ws.log_path, ws.client_id)
        results = []
        for job, sched, slot, attempt in due(ws, now):
            if job == "import":
                result, output = run_import(ws, history(ws))
            else:
                code = 0
                out = ""
                for argv in command_for(ws, job, now):
                    code, more = _call(argv)
                    out += more
                    if code:
                        break
                # Exit 2 means a guardrail refused the job (paused, level, cap): blocked, not broken.
                result = {0: "ok", 2: "blocked"}.get(code, "failed")
                output = {"summary": _tail(out), "exit": code}
            if result in ("failed", "blocked"):
                output["reason"] = output["summary"].splitlines()[-1] if output["summary"] else "no output"
                if attempt >= MAX_ATTEMPTS:
                    output["reason"] += " (gave up on this slot; check it by hand)"
            log.append(AGENT, ACTION, result, {"job": job, "slot": iso(slot), "attempt": attempt}, output)
            results.append({"job": job, "slot": iso(slot), "attempt": attempt, "result": result, **output})
        return results


def overview(ws: Workspace, now: datetime) -> list[dict]:
    """Each scheduled job's last run, next slot, and whether it has fallen behind."""
    tz, hist, out = client_tz(ws), history(ws), []
    # A job is only "behind" once the scheduler is in use: measured from its last good run, or the first run.
    started = min((parse_ts(e["inputs"]["slot"]) for e in hist), default=None)
    for job, sched in schedules(ws).items():
        runs = [e for e in hist if e["inputs"].get("job") == job]
        good = [e for e in runs if e["result"] in ("ok", "skipped")]
        last_good = max((parse_ts(e["inputs"]["slot"]) for e in good), default=None)
        out.append({
            "job": job, "schedule": sched.text,
            "last_run": runs[-1]["inputs"]["slot"] if runs else None,
            "last_result": runs[-1]["result"] if runs else None,
            "last_ok": iso(last_good) if last_good else None,
            "next": iso(sched.next_slot(now, tz)),
            "behind": started is not None and now - (last_good or started) > 2 * sched.period + timedelta(hours=1),
        })
    return out
