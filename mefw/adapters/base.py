"""Lead-source adapters.

Each client tracks leads in its own tool (a CRM, a spreadsheet, an inbox). An
adapter turns that tool's data into LeadRecords; `import_records` turns
LeadRecords into ledger events. Adding a new tool means writing one adapter,
not changing the core (Section 5, onboarding test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol

from ..core.ledger import Ledger
from ..core.workspace import Workspace


@dataclass
class LeadRecord:
    ref: str                                   # the lead's ID in the client's tool; never a name or email
    inquired_at: datetime
    channel: str | None = None
    segment: str | None = None
    value: float | None = None
    touches: list[tuple[datetime, str]] = field(default_factory=list)  # (when, "in" | "out")
    touches_out_reported: int | None = None    # the tool's own follow-up count, if it has one
    stage_dates: dict[str, datetime] = field(default_factory=dict)     # client stage name -> date reached
    current_stage: str | None = None           # client stage name
    outcome: str | None = None                 # won | lost | None
    outcome_at: datetime | None = None
    lost_reason: str | None = None
    opted_out: bool = False                    # the tool says this person asked not to be contacted
    campaign: str | None = None                # campaign or UTM tag, for content attribution


class LeadSource(Protocol):
    name: str

    def records(self) -> Iterable[LeadRecord]: ...


@dataclass
class ImportReport:
    leads: int = 0
    new_events: int = 0
    unknown_stages: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = f"Imported {self.leads} leads, {self.new_events} new events."
        if self.unknown_stages:
            s += " Unmapped stages: " + ", ".join(f"{k} ({v})" for k, v in self.unknown_stages.items()) + "."
        return s


def import_records(ws: Workspace, ledger: Ledger, source: LeadSource) -> ImportReport:
    rep = ImportReport()
    for r in source.records():
        rep.leads += 1
        lead_id = ledger.upsert_lead(source.name, r.ref, r.channel, r.segment, r.value, r.touches_out_reported,
                                     r.campaign)
        add = lambda *a, **k: ledger.add_event(lead_id, *a, source=source.name, **k)  # noqa: E731
        rep.new_events += add("inquired", r.inquired_at)
        for at, direction in r.touches:
            rep.new_events += add("touch_in" if direction == "in" else "touch_out", at)

        for client_stage, at in r.stage_dates.items():
            canonical = ws.canonical_stage(client_stage, r.segment)
            if canonical is None:
                rep.unknown_stages[client_stage] = rep.unknown_stages.get(client_stage, 0) + 1
                continue
            rep.new_events += add("stage", at, stage=canonical)

        if r.current_stage:
            canonical = ws.canonical_stage(r.current_stage, r.segment)
            if canonical is None:
                rep.unknown_stages[r.current_stage] = rep.unknown_stages.get(r.current_stage, 0) + 1
            elif canonical not in {ws.canonical_stage(s, r.segment) for s in r.stage_dates}:
                # No date for the current stage: use the latest activity we know of, and say so.
                known = [r.inquired_at, *(t for t, _ in r.touches), *r.stage_dates.values()]
                rep.new_events += add("stage", max(known), stage=canonical,
                                      detail="date not exported; taken from latest activity")

        if r.opted_out:
            # The export rarely says when; use the latest activity so the opt-out is never missed.
            known = [r.inquired_at, *(t for t, _ in r.touches), *r.stage_dates.values()]
            if r.outcome_at:
                known.append(r.outcome_at)
            rep.new_events += add("consent", max(known), value="opted_out",
                                  detail="from lead export; date not exported")

        if r.outcome in ("won", "lost"):
            at = r.outcome_at or max([r.inquired_at, *(t for t, _ in r.touches)])
            reason = r.lost_reason if r.outcome == "lost" else None
            if r.outcome == "lost" and not reason:
                reason = "not recorded"
                rep.warnings.append(f"{r.ref}: lost without a reason")
            rep.new_events += add("outcome", at, value=r.outcome, detail=reason)
    return rep
