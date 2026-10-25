"""CSV adapter: the fallback for any tool that can export a spreadsheet.

Column names are mapped in the client's profile/mefw.toml under [adapters.csv],
so a new export format is a config change, not a code change. Columns that look
like personal data are refused (see core/pii.py).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from ..core.ledger import parse_ts
from ..core.pii import assert_field_allowed
from .base import LeadRecord

LEAD_FIELDS = (
    "ref", "inquired_at", "channel", "segment", "value", "first_response_at",
    "last_outbound_at", "last_inbound_at", "outbound_count", "stage",
    "outcome", "outcome_at", "lost_reason", "opted_out", "campaign",
)
TRUTHY = {"1", "true", "yes", "y", "x", "opted out", "unsubscribed", "do not contact", "dnc"}


class CsvSource:
    def __init__(self, leads_csv: Path, cfg: dict, activities_csv: Path | None = None):
        self.name = cfg.get("source", "csv")
        self.leads_csv = Path(leads_csv)
        self.activities_csv = Path(activities_csv) if activities_csv else None
        self.columns = cfg.get("columns", {})
        self.stage_dates = cfg.get("stage_dates", {})
        self.outcome_values = {
            k: {v.strip().lower() for v in vals}
            for k, vals in cfg.get("outcome_values", {"won": ["won"], "lost": ["lost"]}).items()
        }
        self.activity_cfg = cfg.get("activities", {})
        unknown = set(self.columns) - set(LEAD_FIELDS)
        if unknown:
            raise ValueError(f"Unknown fields in [adapters.csv.columns]: {', '.join(sorted(unknown))}")
        # Only mapped columns are ever read, so mapping a personal-data column is the one way in.
        for col in self.columns.values():
            assert_field_allowed(col)
        missing = [f for f in ("ref", "inquired_at") if f not in self.columns]
        if missing:
            raise ValueError(f"[adapters.csv.columns] must map: {', '.join(missing)}")

    def _get(self, row: dict, field: str) -> str | None:
        col = self.columns.get(field)
        if not col:
            return None
        v = row.get(col)
        return v.strip() if v and v.strip() else None

    def _outcome(self, raw: str | None) -> str | None:
        if not raw:
            return None
        key = raw.strip().lower()
        for outcome, values in self.outcome_values.items():
            if key in values:
                return outcome
        return None

    def _stage(self, raw: str | None) -> str | None:
        # Tools like HubSpot keep "Closed Lost" in the stage column. It's an outcome, not a funnel stage.
        return None if raw and raw.strip().lower() in self.outcome_values.get("lost", set()) else raw

    def _activities(self) -> dict[str, list]:
        out = defaultdict(list)
        if not self.activities_csv:
            return out
        c = self.activity_cfg
        out_values = {v.lower() for v in c.get("out_values", ["out", "outbound", "sent"])}
        with open(self.activities_csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ref = row[c.get("ref", "ref")].strip()
                at = parse_ts(row[c.get("at", "at")])
                direction = "out" if row[c.get("direction", "direction")].strip().lower() in out_values else "in"
                out[ref].append((at, direction))
        return out

    def records(self) -> Iterable[LeadRecord]:
        activities = self._activities()
        with open(self.leads_csv, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            mapped = set(self.columns.values()) | set(self.stage_dates.values())
            absent = [c for c in mapped if c not in (reader.fieldnames or [])]
            if absent:
                raise ValueError(f"{self.leads_csv.name} is missing mapped columns: {', '.join(absent)}")
            for row in reader:
                ref = self._get(row, "ref")
                inquired = parse_ts(self._get(row, "inquired_at"))
                if not ref or not inquired:
                    continue
                touches = list(activities.get(ref, []))
                for field, direction in (("first_response_at", "out"), ("last_outbound_at", "out"),
                                         ("last_inbound_at", "in")):
                    t = parse_ts(self._get(row, field))
                    if t and (t, direction) not in touches:
                        touches.append((t, direction))
                count = self._get(row, "outbound_count")
                value = self._get(row, "value")
                yield LeadRecord(
                    ref=ref,
                    inquired_at=inquired,
                    channel=self._get(row, "channel"),
                    segment=self._get(row, "segment"),
                    value=float(value.replace(",", "").replace("$", "")) if value else None,
                    touches=sorted(touches),
                    touches_out_reported=int(float(count)) if count else None,
                    stage_dates={
                        stage: parse_ts(row[col]) for stage, col in self.stage_dates.items()
                        if row.get(col) and row[col].strip()
                    },
                    current_stage=self._stage(self._get(row, "stage")),
                    outcome=self._outcome(self._get(row, "outcome")),
                    outcome_at=parse_ts(self._get(row, "outcome_at")),
                    lost_reason=self._get(row, "lost_reason"),
                    campaign=self._get(row, "campaign"),
                    opted_out=(self._get(row, "opted_out") or "").lower() in TRUTHY,
                )
