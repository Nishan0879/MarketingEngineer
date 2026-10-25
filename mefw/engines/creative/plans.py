"""Creative testing engine, plans and approval (Section 9.4).

A Level 1 job. Only insights that have shown they resonate (confirmed, with
enough evidence, the same bar as the content engine) get a test plan. A plan
holds the hypothesis, the audience, what customers said in their words, the
facts that may be claimed, what won before for this segment, and one section
per variant: an angle, a place for the headline, the main text, the visual and
the landing page, and its own tracking tag. It also holds a budget plan: each
variant's daily budget times the days, which must fit under the playbook's
`max_test_budget`. The agent never sets or changes a budget. The operator does
that in the ad tool (Section 9.4: budget changes only at Level 3, within caps).

`mefw creative approve` checks every written variant. Claims must come from
approved facts for the segment, and banned language, sensitive-data requests
and missing required text are blocked. So are misleading visuals or urgency
(before-and-after shots, actors posing as customers, fake countdowns or
scarcity), invented results, and quotations that look like testimonials unless
the operator confirms permission. At least two variants must be written, or
there's nothing to compare.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from ...core.facts import load_facts
from ...core.frontmatter import dump, load
from ...core.ledger import Ledger, iso, parse_ts
from ...core.workspace import Workspace
from ..content import briefs as content
from ..conversion.checks import Issue, check_text

AGENT = "creative-tester"
PLAYBOOK = "engines/creative/playbook.toml"
PLANS = "engines/creative/plans"
WINNERS = "engines/creative/winners.md"
WRITE_HERE = "_Write here._"
FIELDS = ("Headline", "Main text", "Visual", "Landing page")
DEFAULTS = {"max_test_budget": 0, "daily_per_variant": 10, "days": 14, "currency": "$", "variants": 3,
            "min_qualified": 5, "kill_spend": 0, "qualified_stage": "qualify", "refresh_days": 60,
            "channel": "your ad platform", "must_include": [], "tag_prefix": "mefw-cr"}
MISLEADING = re.compile(
    r"\b(?:before[- ]and[- ]after|actors? (?:as|playing|posing as) (?:a )?(?:customers?|members?|clients?)|"
    r"stock (?:photo|image|footage|video)s? of (?:a |our )?(?:customers?|members?|clients?|team)|"
    r"fake (?:review|countdown|scarcity|urgency)|countdown timer|only \w+ (?:spots?|desks?|offices?|places?) left|"
    r"limited time only|results guaranteed|real results)\b",
    re.I,
)


def load_playbook(ws: Workspace) -> dict:
    path = ws.path(PLAYBOOK)
    if not path.exists():
        raise FileNotFoundError(f"No {PLAYBOOK}. Set the budget cap, angles and channel first.")
    pb = {**DEFAULTS, **tomllib.loads(path.read_text()).get("creative", {})}
    if not pb.get("angles"):
        raise ValueError(f"{PLAYBOOK} has no [creative.angles]")
    return pb


def all_plans(ws: Workspace) -> list[tuple[Path, dict, str]]:
    d = ws.path(PLANS)
    return [(p, *load(p)) for p in sorted(d.glob("T-*.md"))] if d.exists() else []


def find(ws: Workspace, plan_id: str) -> tuple[Path, dict, str]:
    for p, meta, body in all_plans(ws):
        if meta["id"].lower() == plan_id.lower():
            return p, meta, body
    raise KeyError(f"No creative test {plan_id}")


def save(path: Path, meta: dict, body: str) -> None:
    path.write_text(dump(meta, body))


def candidates(ws: Workspace, as_of: datetime, ledger: Ledger | None = None) -> tuple[list[dict], list[str]]:
    """Insights that have shown they resonate and have no recent test."""
    pb = load_playbook(ws)
    recent = {m["insight"] for _, m, _ in all_plans(ws)
              if m["status"] != "closed" or parse_ts(m["created"]) > as_of - timedelta(days=int(pb["refresh_days"]))}
    return content.candidates(ws, as_of, ledger, recent=recent)


def past_winners(ws: Workspace, segment: str) -> list[str]:
    path = ws.path(WINNERS)
    if not path.exists():
        return []
    return [ln[2:] for ln in path.read_text().splitlines() if ln.startswith("- ") and f"[{segment}]" in ln][-3:]


def make_plan(ws: Workspace, c: dict, as_of: datetime) -> dict:
    pb = load_playbook(ws)
    today = as_of.date()
    facts = {k: f for k, f in load_facts(ws).items() if f.problem(today, c["segment"]) is None}
    plan_id = f"T-{as_of:%Y%m%d}-{c['insight']}"
    base = f"{pb['tag_prefix']}-{re.sub(r'[^a-z0-9]+', '-', c['insight'].lower()).strip('-')}-{as_of:%m%d}"
    angles = list(pb["angles"].items())[: max(2, min(5, int(pb["variants"])))]
    variants = [{"key": chr(97 + i), "angle": name, "tag": f"{base}-{chr(97 + i)}"} for i, (name, _) in
                enumerate(angles)]
    daily, days = float(pb["daily_per_variant"]), int(pb["days"])
    meta = {"id": plan_id, "status": "plan", "agent": AGENT, "insight": c["insight"], "segment": c["segment"],
            "created": iso(as_of), "channel": pb["channel"], "variants": variants, "daily_per_variant": daily,
            "days": days, "facts": sorted(facts)}
    cur = pb["currency"]
    L = [f"## Creative test: {c['title']}", "",
         f"- **Hypothesis:** if the ads lead with what this audience keeps telling us ({c['statement'].rstrip('.')}), "
         "more of the people who click will become qualified inquiries and meetings, at a lower cost per meeting.",
         f"- **Insight:** `customer-truth/insights/{c['insight']}.md` (confidence {c['confidence']}, "
         f"{c['evidence']} signals)",
         f"- **Audience:** {c['segment_label']}, on {pb['channel']}",
         "- **Their words** (for language; don't quote anyone in an ad without their permission):"]
    L += [f"  - {q}" for q in c["quotes"]] or ["  - none recorded"]
    L.append("- **Facts you may claim** (nothing else: no prices, numbers, results or promises that aren't here):")
    L += [f"  - `{k}`: {f.text}" for k, f in sorted(facts.items())] or ["  - none approved for this segment yet"]
    won = past_winners(ws, c["segment"])
    if won:
        L.append("- **What won before for this audience:**")
        L += [f"  - {w}" for w in won]
    L += ["- **Judged on:** cost per qualified inquiry, cost per meeting and cost per commitment. Click rate is "
          "only an early hint.",
          f"- **Budget plan:** {cur}{daily:g} a day per variant for {days} days, {cur}{daily * days:g} per variant. "
          f"The total must stay under the cap of {cur}{float(pb['max_test_budget']):g}. You set budgets in the ad "
          "tool yourself; nothing here spends money.",
          f"- **Stop rules:** call a winner once every variant has {pb['min_qualified']} qualified inquiries. Stop a "
          "variant early when it has spent "
          + (f"{cur}{float(pb['kill_spend']):g}" if float(pb["kill_spend"]) else "three times the leader's cost per "
             "qualified inquiry") + " with none.",
          "", "## Variants", "",
          "Write the variants you want to run (two at least). Put each variant's tag in its ad name and its "
          "`utm_campaign`, so results and inquiries can be matched to it. Leave a variant as it is to skip it.", ""]
    for v, (name, guidance) in zip(variants, angles):
        L += [f"### Variant {v['key'].upper()}: {name}", "", f"_Angle: {guidance}_", f"_Tag: `{v['tag']}`_", ""]
        L += [f"{field}: {WRITE_HERE}" for field in FIELDS] + [""]
    L += ["## Checks", "", f"_Run `mefw creative approve {plan_id}` once the variants are written._", ""]
    path = ws.path(f"{PLANS}/{plan_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, meta, "\n".join(L))
    return meta


def written(meta: dict, body: str) -> dict[str, dict[str, str]]:
    """The written variants, keyed by variant letter, each a dict of its filled-in fields."""
    section = body.split("## Variants", 1)[-1].split("\n## Checks", 1)[0]
    out = {}
    for m in re.finditer(r"^### Variant ([A-Z]):[^\n]*\n(.*?)(?=^### |\Z)", section, re.S | re.M):
        fields, current = {}, None
        for ln in m.group(2).splitlines():
            head = re.match(rf"^({'|'.join(FIELDS)}):\s*(.*)$", ln)
            if head:
                current = head.group(1)
                fields[current] = head.group(2)
            elif current and not ln.startswith("_"):
                fields[current] += "\n" + ln
        fields = {k: v.strip() for k, v in fields.items() if v.strip() and v.strip() != WRITE_HERE}
        if fields:
            out[m.group(1).lower()] = fields
    return out


def check_variant(ws: Workspace, pb: dict, fields: dict[str, str], segment: str, today,
                  quote_permission: bool) -> list[Issue]:
    words = "\n".join(v for k, v in fields.items() if k != "Visual")
    issues = [i for i in check_text(ws, words, load_facts(ws), segment, today, pb["must_include"]) if i.blocking]
    for text in fields.values():
        for m in MISLEADING.finditer(text):
            issues.append(Issue("misleading", f"\"{m.group(0)}\": no misleading imagery, urgency or invented results"))
    if not quote_permission:
        for q in content.QUOTE.findall(words):
            issues.append(Issue("testimonial", f"quotes someone (\"{q[:40]}...\"). Only use a customer's words "
                                               "with their permission; then approve with --quote-permission"))
    return issues


def approve(ws: Workspace, plan_id: str, by: str, at: datetime, quote_permission: bool = False) -> dict:
    path, meta, body = find(ws, plan_id)
    if meta["status"] not in ("plan", "approved"):
        raise ValueError(f"{plan_id} is {meta['status']}")
    pb = load_playbook(ws)
    done = written(meta, body)
    if len(done) < 2:
        raise ValueError(f"Write at least two variants in {plan_id}; a test needs something to compare.")
    lines = [f"  - variant {k.upper()}: {i.check}: {i.message}" for k, f in done.items()
             for i in check_variant(ws, pb, f, meta["segment"], at.date(), quote_permission)]
    total = float(meta["daily_per_variant"]) * int(meta["days"]) * len(done)
    cap = float(pb["max_test_budget"])
    if cap <= 0:
        lines.append("  - budget: set max_test_budget in the playbook (the client's cap for one test)")
    elif total > cap:
        lines.append(f"  - budget: {pb['currency']}{total:g} planned is over the {pb['currency']}{cap:g} cap; "
                     "run fewer variants, fewer days or less a day")
    if lines:
        raise ValueError("Can't approve; fix these first:\n" + "\n".join(lines))
    meta.update(status="approved", approved_by=by, approved_at=iso(at), live_variants=sorted(done),
                planned_budget=total, budget_cap=cap, quote_permission=quote_permission)
    body = body.split("\n## Checks", 1)[0] + (
        f"\n## Checks\n\n- ✅ variants {', '.join(k.upper() for k in sorted(done))}: facts, claims, banned "
        "language, sensitive data, required text, misleading imagery or urgency, "
        f"{'quotes (permission confirmed)' if quote_permission else 'no quotations'}\n"
        f"- ✅ budget: {pb['currency']}{total:g} planned, cap {pb['currency']}{cap:g}\n"
        f"- Approved by {by} on {at.date().isoformat()}. Build the ads with each variant's tag, set the budgets "
        f"yourself, then `mefw creative start {meta['id']}`.\n")
    save(path, meta, body)
    return meta


def start(ws: Workspace, plan_id: str, by: str, at: datetime) -> dict:
    path, meta, body = find(ws, plan_id)
    if meta["status"] != "approved":
        raise ValueError(f"{plan_id} is {meta['status']}; approve it before it starts")
    meta.update(status="running", started_by=by, started_at=iso(at))
    save(path, meta, body)
    return meta
