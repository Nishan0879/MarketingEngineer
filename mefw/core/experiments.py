"""Experiments (Section 13): briefs, a locked decision rule, measurement, verdicts.

A brief is a Markdown file in experiments/active/ (moved to experiments/completed/
when closed). Its settings sit in TOML front matter between `+++` lines; the body
follows the Section 13.1 template.

The rules from Section 13.2 are enforced, not just written down:
- The decision criteria are fixed when the operator approves the brief. Their hash
  is stored and logged; if they change afterwards, measurement says so and won't
  suggest a verdict.
- Every result has a comparison: the same segment before the start (before_after),
  or leads outside the test channels over the same dates (holdout).
- Nothing is called until the minimum window and volume are met.
- Only the operator sets the verdict. The agent suggests one.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from . import metrics
from .evidence import confidence
from .ledger import LeadState, Ledger, iso, parse_ts
from .workspace import ALL, Workspace

STATUSES = ("proposed", "approved", "running", "completed", "stopped")
TRANSITIONS = {
    "approve": ("proposed", "approved"),
    "start": ("approved", "running"),
    "stop": ("running", "stopped"),
}
VERDICTS = ("keep", "iterate", "kill", "inconclusive")
CRITERIA = ("segment", "channels", "metric", "comparison", "baseline_days",
            "min_window_days", "min_leads", "keep_if", "kill_if")
DEFAULTS = {"comparison": "before_after", "baseline_days": 60, "min_window_days": 14,
            "min_leads": 20, "keep_if": 0.15, "kill_if": 0.0}


# Files

def _dump_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_dump_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # JSON string escapes are valid TOML basic strings


def dump(meta: dict, body: str) -> str:
    lines = ["+++"] + [f"{k} = {_dump_value(v)}" for k, v in meta.items() if v is not None] + ["+++", ""]
    return "\n".join(lines) + body.lstrip("\n")


def load(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n", text, re.S)
    if not m:
        raise ValueError(f"{path.name} has no +++ front matter")
    return tomllib.loads(m.group(1)), text[m.end():]


def all_briefs(ws: Workspace) -> list[tuple[Path, dict, str]]:
    out = []
    for sub in ("active", "completed"):
        d = ws.path(f"experiments/{sub}")
        if d.exists():
            for p in sorted(d.glob("EXP-*.md")):
                meta, body = load(p)
                out.append((p, meta, body))
    return out


def find(ws: Workspace, exp_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in all_briefs(ws):
        if meta["id"].lower() == exp_id.lower():
            return p, meta, body
    raise KeyError(f"No experiment {exp_id}")


def criteria_hash(meta: dict) -> str:
    crit = {k: meta.get(k) for k in CRITERIA}
    return hashlib.sha256(json.dumps(crit, sort_keys=True).encode()).hexdigest()[:16]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


# Lifecycle

def new(ws: Workspace, ledger: Ledger, name: str, metric: str, hypothesis: str, as_of: datetime,
        segment: str | None = None, channels: list[str] | None = None, engine: str = "conversion",
        customer: str = "", evidence: str = "", offer: str = "", assets: str = "",
        owner: str = "operator", **criteria) -> Path:
    if metric not in metrics.METRICS:
        raise ValueError(f"Unknown metric {metric!r}; choose from {', '.join(metrics.METRICS)}")
    segment = segment or (ALL if not ws.config.segments else None)
    if segment not in ws.segment_names():
        raise ValueError(f"Segment must be one of: {', '.join(ws.segment_names())}")
    crit = {**DEFAULTS, **{k: v for k, v in criteria.items() if v is not None}}
    if crit["comparison"] not in ("before_after", "holdout"):
        raise ValueError("comparison must be before_after or holdout")
    if crit["comparison"] == "holdout" and not channels:
        raise ValueError("A holdout comparison needs --channels for the test group")
    if crit["kill_if"] >= crit["keep_if"]:
        raise ValueError("kill_if must be below keep_if")

    n = 1 + max((int(m["id"].rsplit("-", 1)[1]) for _, m, _ in all_briefs(ws)), default=0)
    exp_id = f"EXP-{ws.client_id}-{n:03d}"
    leads = _segment_leads(ws, ledger, segment, as_of)
    base = metrics.compute(metric, metrics.in_window(leads, as_of - timedelta(days=crit["baseline_days"]), as_of),
                           as_of, ws.cycle_days(segment))
    meta = {
        "id": exp_id, "name": name, "status": "proposed", "owner": owner, "engine": engine,
        "segment": segment, "channels": channels or [], "metric": metric,
        **crit, "created": iso(as_of),
        "baseline_at_proposal": round(base.value, 4) if base.value is not None else None,
        "baseline_n_at_proposal": base.n,
    }
    label, better, _ = metrics.METRICS[metric]
    group = (f"{ws.segment_label(segment)} leads" +
             (f" from {', '.join(channels)}" if channels else ""))
    compare = (f"the same leads in the {crit['baseline_days']} days before the start"
               if crit["comparison"] == "before_after"
               else f"{ws.segment_label(segment)} leads from other channels over the same dates")
    body = f"""# Experiment: {name}
- **ID:** {exp_id}
- **Status:** proposed
- **Owner:** {owner}
- **Engine:** {engine}

## Customer
{customer or ws.segment_label(segment)}

## Evidence
{evidence or "_Link the insight records, audit findings and receipts that support this._"}

## Hypothesis
{hypothesis}

## Offer
{offer or "_The useful next step offered to the prospect._"}

## Assets and channel
{assets or "_What will be created, and where it appears._"}

## Measurement
- **Primary metric:** {label} ({better} is better), for {group}
- **Baseline:** {compare}. At proposal: {base.fmt(metric)} over {base.n} leads.
- **Minimum observation window:** {crit['min_window_days']} days and {crit['min_leads']} leads in the test group
- **What would make us keep / iterate / kill:** keep if the metric improves by {crit['keep_if']:.0%} or more; kill if the change is {crit['kill_if']:.0%} or worse; iterate in between. Fixed when approved.

## Priority score
Customer fit (_/5) + Evidence strength (_/5) + Business impact (_/5) − Effort (_/5) = _

## Result
- **Outcome:**
- **Verdict:**
- **Confidence:**
- **Lesson:**
- **Next test:**

## Measurements log
"""
    path = ws.path(f"experiments/active/{exp_id}-{_slug(name)}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, body))
    return path


def transition(ws: Workspace, exp_id: str, action: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, exp_id)
    frm, to = TRANSITIONS[action]
    if meta["status"] != frm:
        raise ValueError(f"{meta['id']} is {meta['status']}; '{action}' needs it to be {frm}")
    meta["status"] = to
    meta[f"{to}_at"] = iso(at)
    meta[f"{to}_by"] = by
    if action == "approve":
        meta["criteria_hash"] = criteria_hash(meta)
    if action == "stop":
        meta["ended_at"] = iso(at)
    body = re.sub(r"^- \*\*Status:\*\* .*$", f"- **Status:** {to}", body, count=1, flags=re.M)
    path.write_text(dump(meta, body))
    return meta


def close(ws: Workspace, exp_id: str, verdict: str, lesson: str, confidence_label: str, outcome: str,
          by: str, at: datetime, next_test: str = "") -> Path:
    """The operator's verdict (Section 13.1 Result). Moves the brief to completed/ and records the lesson."""
    if verdict not in VERDICTS:
        raise ValueError(f"Verdict must be one of {VERDICTS}")
    if confidence_label not in ("low", "medium", "high"):
        raise ValueError("Confidence must be low, medium or high")
    if not lesson.strip():
        raise ValueError("A lesson is required: one sentence, written to memory")
    path, meta, body = find(ws, exp_id)
    if meta["status"] not in ("running", "stopped"):
        raise ValueError(f"{meta['id']} is {meta['status']}; only a running or stopped experiment can be closed")
    meta.setdefault("ended_at", iso(at))
    meta.update(status="completed", completed_at=iso(at), completed_by=by,
                verdict=verdict, confidence=confidence_label)
    body = re.sub(r"^- \*\*Status:\*\* .*$", "- **Status:** completed", body, count=1, flags=re.M)
    for field, value in (("Outcome", outcome), ("Verdict", verdict), ("Confidence", confidence_label),
                         ("Lesson", lesson), ("Next test", next_test)):
        body = re.sub(rf"^- \*\*{field}:\*\*.*$", f"- **{field}:** {value}".rstrip(), body, count=1, flags=re.M)
    dest = ws.path(f"experiments/completed/{path.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dump(meta, body))
    path.unlink()
    lessons = ws.path("experiments/lessons.md")
    if not lessons.exists():
        lessons.write_text("# Lessons\n\nOne line per closed experiment. A lesson applies to the segment it was "
                           "tested on until repeated (Section 13.2).\n\n")
    with open(lessons, "a", encoding="utf-8") as f:
        f.write(f"- {at.date().isoformat()} · {meta['id']} · {ws.segment_label(meta['segment'])} · "
                f"{verdict} ({confidence_label}): {lesson.strip()}\n")
    return dest


# Measurement

def _segment_leads(ws: Workspace, ledger: Ledger, segment: str, as_of: datetime) -> list[LeadState]:
    return [s for s in ledger.states(as_of) if ws.segment_for(s.segment) == segment]


def measure(ws: Workspace, ledger: Ledger, meta: dict, as_of: datetime) -> dict:
    metric, segment = meta["metric"], meta["segment"]
    cycle = ws.cycle_days(segment)
    leads = _segment_leads(ws, ledger, segment, as_of)
    channels = set(meta.get("channels") or [])
    in_test = (lambda s: s.channel in channels) if channels else (lambda s: True)

    result = {"id": meta["id"], "as_of": iso(as_of), "metric": metric, "status": meta["status"]}
    if meta["status"] not in ("running", "stopped", "completed"):
        result["note"] = f"Not started (status {meta['status']})."
        return result
    start = parse_ts(meta["running_at"])
    end = parse_ts(meta["ended_at"]) if meta.get("ended_at") else as_of
    if meta["comparison"] == "before_after":
        test_leads = [s for s in metrics.in_window(leads, start, end) if in_test(s)]
        base_leads = [s for s in metrics.in_window(leads, start - timedelta(days=meta["baseline_days"]), start)
                      if in_test(s)]
    else:
        window = metrics.in_window(leads, start, end)
        test_leads = [s for s in window if in_test(s)]
        base_leads = [s for s in window if not in_test(s)]
    test = metrics.compute(metric, test_leads, as_of, cycle)
    base = metrics.compute(metric, base_leads, as_of, cycle)
    change = metrics.relative_change(metric, test, base)
    days = (min(end, as_of) - start).days
    conf, why = confidence([test.n, base.n], max(5, meta["min_leads"] // 2))

    result.update({
        "test": {"value": test.value, "n": test.n, "shown": test.fmt(metric)},
        "baseline": {"value": base.value, "n": base.n, "shown": base.fmt(metric)},
        "change": change, "days": days, "confidence": conf, "why": why,
        "maturity_days": metrics.maturity_days(metric, cycle),
    })
    problems = []
    if meta.get("criteria_hash") != criteria_hash(meta):
        problems.append("the decision criteria changed after approval")
    if days < meta["min_window_days"]:
        problems.append(f"{days} of {meta['min_window_days']} days observed")
    if test.n < meta["min_leads"]:
        problems.append(f"{test.n} of {meta['min_leads']} leads in the test group are old enough to count")
    if change is None:
        problems.append("no comparable baseline value")
    if problems:
        result["suggested"] = "inconclusive"
        result["reason"] = "; ".join(problems)
    elif change >= meta["keep_if"]:
        result["suggested"], result["reason"] = "keep", f"{change:+.0%} meets the keep bar ({meta['keep_if']:+.0%})"
    elif change <= meta["kill_if"]:
        result["suggested"], result["reason"] = "kill", f"{change:+.0%} is at or below the kill bar ({meta['kill_if']:.0%})"
    else:
        result["suggested"], result["reason"] = "iterate", f"{change:+.0%} is between the kill and keep bars"
    result["ready"] = not problems
    return result


def log_measurement(ws: Workspace, exp_id: str, result: dict) -> None:
    """Append one line to the brief's measurements log. Earlier lines are never changed."""
    path, meta, body = find(ws, exp_id)
    if "test" not in result:
        return
    line = (f"- {result['as_of'][:10]}: test {result['test']['shown']} (n={result['test']['n']}) vs. "
            f"baseline {result['baseline']['shown']} (n={result['baseline']['n']})"
            + (f", {result['change']:+.0%}" if result["change"] is not None else "")
            + f"; day {result['days']}; suggested **{result['suggested']}** — {result['reason']}; "
            f"confidence {result['confidence']}\n")
    if line.split(":")[0] in body:  # one entry per day
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
