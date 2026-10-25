"""Cold-inquiry audit: where do inquiries go cold, and which of those were ours to lose?

A Level 0 (observe) job for the conversion engine (Section 9.3). It reads the
ledger, never contacts anyone, and writes a report with receipts: every finding
lists the CRM references of the leads behind it, and every comparison carries
its sample size and a confidence label (Section 13.2). When the numbers are too
small it says "not enough evidence" instead of forcing a conclusion.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ...core.ledger import Ledger, LeadState, iso
from ...core.workspace import Workspace

DEFAULTS = {
    "lookback_days": 180,
    "cold_after_days": 14,
    "slow_response_hours": 24,
    "min_followups": 3,
    "min_group_size": 10,
    "response_buckets_minutes": [5, 60, 1440],
    "max_candidates": 25,
}

# Why a lead went cold, in priority order. The first four were ours to fix.
LEAKS = {
    "never_responded": "Never got a response from us",
    "ball_in_our_court": "Prospect wrote last and we never answered",
    "slow_first_response": "First response came too late",
    "few_followups": "We stopped following up too early",
    "stalled_after_meeting": "Met, then stalled before commitment",
    "went_quiet": "Followed up properly; prospect went quiet",
}
FIXABLE = ("never_responded", "ball_in_our_court", "slow_first_response", "few_followups")

NEXT_TESTS = {
    "never_responded": "Guarantee a first response for every inquiry: route new inquiries to an instant, approved-facts reply (conversion agent at Level 1 drafts, human sends) and measure inquiry → meeting rate against the baseline above.",
    "ball_in_our_court": "Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents.",
    "slow_first_response": "Cut speed to first response for one channel (start with the slowest) and compare its inquiry → meeting rate with the baseline period.",
    "few_followups": "Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked.",
    "stalled_after_meeting": "Ask the client for the top reasons meetings don't convert, then test one post-meeting follow-up that answers the most common objection with approved facts.",
    "went_quiet": "Leads that went quiet despite follow-up are the evidence base for objections: pull their notes into the customer truth file before changing messaging.",
}


@dataclass
class Settings:
    lookback_days: int
    cold_after_days: int
    slow_response_hours: float
    min_followups: int
    min_group_size: int
    response_buckets_minutes: list[int]
    max_candidates: int

    @classmethod
    def from_config(cls, conversion_cfg: dict) -> "Settings":
        merged = {**DEFAULTS, **conversion_cfg.get("cold_audit", {})}
        return cls(**{k: merged[k] for k in DEFAULTS})


def classify(s: LeadState, cfg: Settings) -> str:
    if s.first_response_at is None:
        return "never_responded"
    if s.last_in and (s.last_out is None or s.last_in > s.last_out):
        return "ball_in_our_court"
    if (s.first_response_at - s.inquired_at) > timedelta(hours=cfg.slow_response_hours):
        return "slow_first_response"
    if s.touches_out < cfg.min_followups:
        return "few_followups"
    if s.reached("meet"):
        return "stalled_after_meeting"
    return "went_quiet"


def response_bucket(s: LeadState, edges: list[int]) -> str:
    if s.first_response_at is None:
        return "no response"
    minutes = (s.first_response_at - s.inquired_at).total_seconds() / 60
    labels = _bucket_labels(edges)
    for edge, label in zip(edges, labels):
        if minutes <= edge:
            return label
    return labels[-1]


def _fmt_minutes(m: int) -> str:
    if m < 60:
        return f"{m}m"
    if m < 1440:
        return f"{m // 60}h"
    return f"{m // 1440}d"


def _bucket_labels(edges: list[int]) -> list[str]:
    labels, lo = [], None
    for e in edges:
        labels.append(f"≤ {_fmt_minutes(e)}" if lo is None else f"{_fmt_minutes(lo)}–{_fmt_minutes(e)}")
        lo = e
    labels.append(f"> {_fmt_minutes(edges[-1])}")
    return labels


def confidence(sizes: list[int], min_size: int) -> tuple[str, str]:
    """Directional confidence for a comparison between groups (Section 13.2).

    Groups under min_size are left out of the comparison; at least two must remain.
    """
    usable = [n for n in sizes if n >= min_size]
    if len(usable) < 2:
        return "not enough evidence", f"fewer than two groups have {min_size}+ leads"
    smallest = min(usable)
    left_out = len(sizes) - len(usable)
    note = f"; {left_out} group(s) under {min_size} leads left out" if left_out else ""
    if smallest < 3 * min_size:
        return "low", f"smallest compared group has {smallest} leads; observational, not a controlled test{note}"
    return "medium", f"every compared group has at least {smallest} leads; observational, so confounders may apply{note}"


def _rate(num: int, den: int) -> str:
    return f"{num / den:.0%}" if den else "n/a"


def run_audit(ws: Workspace, ledger: Ledger, as_of: datetime) -> dict:
    cfg = Settings.from_config(ws.config.conversion)
    all_states = ledger.states(as_of)
    start = as_of - timedelta(days=cfg.lookback_days)
    pop = [s for s in all_states if s.inquired_at >= start]
    judged_cut = as_of - timedelta(days=cfg.cold_after_days)
    judged = [s for s in pop if s.inquired_at <= judged_cut]  # old enough to have gone cold

    data = {
        "client": ws.client_id,
        "as_of": iso(as_of),
        "settings": asdict(cfg),
        "population": len(pop),
        "judged": len(judged),
        "gaps": [],
    }
    if not pop:
        data["headline"] = "Not enough evidence: no inquiries in the lookback window."
        return data

    # Baseline funnel
    funnel = {st: sum(1 for s in pop if s.reached(st)) for st in ("inquire", "qualify", "meet", "commit")}
    won = [s for s in pop if s.outcome == "won"]
    lost = [s for s in pop if s.outcome == "lost"]
    speeds = [(s.first_response_at - s.inquired_at).total_seconds() / 60 for s in pop if s.first_response_at]
    data["funnel"] = {
        "counts": funnel, "won": len(won), "lost": len(lost),
        "open": len(pop) - len(won) - len(lost),
        "median_first_response_minutes": round(statistics.median(speeds)) if speeds else None,
        "never_responded": sum(1 for s in pop if s.first_response_at is None),
    }

    # Outcomes through Commit (Section 7)
    due = [s for s in pop if s.inquired_at <= as_of - timedelta(days=ws.config.cycle_days)]
    with_outcome = [s for s in due if s.outcome]
    coverage = len(with_outcome) / len(due) if due else None
    data["outcome_coverage"] = {"due": len(due), "with_outcome": len(with_outcome), "rate": coverage}
    if coverage is not None and coverage < 0.8:
        data["gaps"].append(
            f"Only {coverage:.0%} of leads older than the {ws.config.cycle_days}-day cycle have a won/lost "
            "outcome. Open leads may really be lost; ask the client to close them out with reasons."
        )
    if not any(s.touches_out for s in pop):
        data["gaps"].append("No outbound touches in the data, so response speed and follow-up can't be judged.")
    if not any(s.last_in for s in pop):
        data["gaps"].append("No inbound replies in the data, so 'waiting on us' leads can't be detected.")

    # Cold leads
    cold = [
        s for s in judged
        if s.outcome is None and not s.reached("commit")
        and s.last_activity <= judged_cut
    ]
    by_leak: dict[str, list[LeadState]] = defaultdict(list)
    for s in cold:
        by_leak[classify(s, cfg)].append(s)
    for v in by_leak.values():
        v.sort(key=lambda s: s.last_activity, reverse=True)
    fixable = [s for k in FIXABLE for s in by_leak.get(k, [])]
    data["cold"] = {
        "count": len(cold),
        "rate": len(cold) / len(judged) if judged else None,
        "by_leak": {k: [s.ref for s in by_leak.get(k, [])] for k in LEAKS},
        "by_stage": dict(Counter(s.furthest_stage for s in cold)),
        "fixable": len(fixable),
        "value_at_risk": sum(s.value or 0 for s in fixable) or None,
    }

    # Speed to first response vs. outcomes, among judged leads
    labels = ["no response", *_bucket_labels(cfg.response_buckets_minutes)]
    groups = defaultdict(list)
    for s in judged:
        groups[response_bucket(s, cfg.response_buckets_minutes)].append(s)
    rows = []
    for label in labels:
        g = groups.get(label, [])
        if g:
            rows.append({"bucket": label, "n": len(g),
                         "meet": sum(1 for s in g if s.reached("meet")),
                         "won": sum(1 for s in g if s.outcome == "won")})
    conf, why = confidence([r["n"] for r in rows], cfg.min_group_size)
    data["speed_vs_outcome"] = {"rows": rows, "confidence": conf, "why": why}

    # By channel
    chans = defaultdict(list)
    for s in judged:
        chans[s.channel or "unknown"].append(s)
    data["by_channel"] = [
        {"channel": c, "n": len(g),
         "meet": sum(1 for s in g if s.reached("meet")),
         "won": sum(1 for s in g if s.outcome == "won"),
         "cold": sum(1 for s in g if s in cold)}
        for c, g in sorted(chans.items(), key=lambda kv: -len(kv[1]))
    ]

    # Lost reasons
    reasons = defaultdict(list)
    for s in lost:
        reasons[(s.lost_reason or "not recorded").strip().lower()].append(s.ref)
    data["lost_reasons"] = sorted(([r, refs] for r, refs in reasons.items()), key=lambda x: -len(x[1]))

    # Re-engagement candidates: ours to fix, highest value then most recent
    cands = sorted(fixable, key=lambda s: (-(s.value or 0), -s.last_activity.timestamp()))
    data["candidates"] = [
        {"ref": s.ref, "reason": classify(s, cfg), "stage": s.furthest_stage,
         "channel": s.channel, "value": s.value, "last_activity": iso(s.last_activity),
         "days_quiet": (as_of - s.last_activity).days}
        for s in cands[: cfg.max_candidates]
    ]

    # Headline: the biggest fixable leak
    top = max(FIXABLE, key=lambda k: len(by_leak.get(k, [])))
    if by_leak.get(top) and len(cold) >= cfg.min_group_size:
        n = len(by_leak[top])
        data["headline"] = (
            f"{len(cold)} of {len(judged)} inquiries ({_rate(len(cold), len(judged))}) went cold, "
            f"{len(fixable)} of them for reasons on our side. "
            f"The biggest fixable leak: {LEAKS[top].lower()} ({n} leads)."
        )
        data["headline_refs"] = [s.ref for s in by_leak[top]]
        data["top_leak"] = top
    else:
        data["headline"] = (
            f"Not enough evidence for a headline: {len(cold)} cold leads "
            f"(minimum {cfg.min_group_size} to call a pattern)."
        )
    return data


def render_markdown(data: dict, source_note: str) -> str:
    L: list[str] = []
    w = L.append
    w(f"# Cold-inquiry audit — {data['client']} — as of {data['as_of'][:10]}")
    w("")
    w("_Conversion engine · agent `cold-inquiry-auditor` · Level 0 (observe). Nothing was sent to anyone._")
    w("")
    w(f"**Source:** {source_note}. Lead references are IDs in the client's lead-tracking tool; "
      "look them up there for names and details.")
    w("")
    w("## Headline")
    w("")
    w(data["headline"])
    if data.get("headline_refs"):
        w("")
        w(f"Receipts: {_refs_from(data['headline_refs'])}")
    w("")
    if "funnel" not in data:
        return "\n".join(L) + "\n"

    s = data["settings"]
    w("## Baseline")
    w("")
    f = data["funnel"]
    c = f["counts"]
    w(f"Inquiries in the last {s['lookback_days']} days: **{data['population']}** "
      f"({data['judged']} are older than {s['cold_after_days']} days and can be judged).")
    w("")
    w("| Stage | Leads | From inquiry |")
    w("|---|---|---|")
    for st in ("inquire", "qualify", "meet", "commit"):
        w(f"| {st.title()} | {c[st]} | {_rate(c[st], c['inquire'])} |")
    w("")
    med = f["median_first_response_minutes"]
    w(f"- Won: {f['won']} · Lost: {f['lost']} · Open: {f['open']}")
    w(f"- Median speed to first response: {_human_minutes(med) if med is not None else 'n/a'}")
    w(f"- Never responded to: {f['never_responded']}")
    oc = data["outcome_coverage"]
    if oc["rate"] is not None:
        w(f"- Outcome reported for {oc['with_outcome']} of {oc['due']} leads past the sales cycle ({oc['rate']:.0%})")
    w("")

    cold = data["cold"]
    w("## Where inquiries went cold")
    w("")
    w(f"A lead counts as cold when it is open, short of commitment, and nothing has happened for "
      f"{s['cold_after_days']}+ days. **{cold['count']}** leads are cold "
      f"({_rate(cold['count'], data['judged'])} of judged inquiries); "
      f"**{cold['fixable']}** of them went cold for reasons on our side.")
    if cold["value_at_risk"]:
        L[-1] += f" Recorded value of those {cold['fixable']} leads: **{cold['value_at_risk']:,.0f}**."
    w("")
    w("| Why it went cold | Leads | Ours to fix | Receipts |")
    w("|---|---|---|---|")
    for k, label in LEAKS.items():
        refs = cold["by_leak"][k]
        if refs:
            w(f"| {label} | {len(refs)} | {'yes' if k in FIXABLE else 'no'} | {_refs_from(refs)} |")
    w("")
    if cold["by_stage"]:
        w("Furthest stage reached by cold leads: " +
          ", ".join(f"{k} {v}" for k, v in sorted(cold["by_stage"].items(), key=lambda kv: -kv[1])) + ".")
        w("")

    sv = data["speed_vs_outcome"]
    w("## Speed to first response vs. outcome")
    w("")
    w("| First response | Leads | Reached meeting | Won |")
    w("|---|---|---|---|")
    for r in sv["rows"]:
        small = " (too few to compare)" if r["n"] < s["min_group_size"] else ""
        w(f"| {r['bucket']}{small} | {r['n']} | {r['meet']} ({_rate(r['meet'], r['n'])}) | {r['won']} ({_rate(r['won'], r['n'])}) |")
    w("")
    w(f"**Confidence: {sv['confidence']}** — {sv['why']}. Faster replies may also go to warmer leads, "
      "so treat a gap here as a reason to test, not as proof.")
    w("")

    if data["by_channel"]:
        w("## By channel")
        w("")
        w("| Channel | Leads | Reached meeting | Won | Went cold |")
        w("|---|---|---|---|---|")
        for r in data["by_channel"]:
            w(f"| {r['channel']} | {r['n']} | {_rate(r['meet'], r['n'])} | {_rate(r['won'], r['n'])} | {_rate(r['cold'], r['n'])} |")
        w("")

    if data["lost_reasons"]:
        w("## Lost reasons")
        w("")
        w("| Reason | Leads | Receipts |")
        w("|---|---|---|")
        for reason, refs in data["lost_reasons"]:
            w(f"| {reason} | {len(refs)} | {_refs_from(refs)} |")
        w("")

    if data["candidates"]:
        w("## Leads worth a second look")
        w("")
        w("Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; "
          "no message has been drafted or sent.")
        w("")
        w("| Lead | Why | Stage | Channel | Value | Quiet for |")
        w("|---|---|---|---|---|---|")
        for cnd in data["candidates"]:
            val = f"{cnd['value']:,.0f}" if cnd["value"] else ""
            w(f"| `{cnd['ref']}` | {LEAKS[cnd['reason']]} | {cnd['stage']} | {cnd['channel'] or ''} | {val} | {cnd['days_quiet']} days |")
        w("")

    w("## Proposed next tests")
    w("")
    w("Hypotheses for the operator to decide on. None is approved or running.")
    w("")
    # Leaks on our side first, biggest first; then the rest.
    ranked = sorted(LEAKS, key=lambda k: (k not in FIXABLE, -len(cold["by_leak"][k])))
    shown = 0
    for k in ranked:
        if cold["by_leak"][k] and shown < 3:
            shown += 1
            w(f"{shown}. **{LEAKS[k]}** ({len(cold['by_leak'][k])} leads). {NEXT_TESTS[k]}")
    if not shown:
        w("None: no cold leads in this window.")
    w("")

    w("## Data gaps")
    w("")
    if data["gaps"]:
        for g in data["gaps"]:
            w(f"- {g}")
    else:
        w("- None found.")
    w("")
    w("## Settings")
    w("")
    w(", ".join(f"`{k}` = {v}" for k, v in s.items()))
    w("")
    return "\n".join(L)


def _refs_from(refs: list[str], limit: int = 8) -> str:
    out = ", ".join(f"`{r}`" for r in refs[:limit])
    return out + (f" and {len(refs) - limit} more" if len(refs) > limit else "")


def _human_minutes(m: float) -> str:
    if m < 60:
        return f"{m:.0f} minutes"
    if m < 1440:
        return f"{m / 60:.1f} hours"
    return f"{m / 1440:.1f} days"


def write_outputs(ws: Workspace, data: dict, source_note: str) -> dict:
    out_dir = ws.path("engines/conversion/audits")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{data['as_of'][:10]}-cold-inquiry-audit"
    md = out_dir / f"{stem}.md"
    js = out_dir / f"{stem}.json"
    md.write_text(render_markdown(data, source_note))
    js.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return {"report": str(md.relative_to(ws.root)), "data": str(js.relative_to(ws.root))}
