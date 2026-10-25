"""CSV adapter for customer signal: call and tour notes, inquiry messages,
lost-deal notes, reviews, tickets (Section 8.2).

Columns are mapped in profile/mefw.toml under [adapters.signals_csv]. Text is
scrubbed of contact details on the way in. Keep raw transcripts in the client's
own systems; import notes and messages, and point `ref` at where the original lives.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..core.ledger import SIGNAL_KINDS, Ledger, parse_ts
from ..core.pii import assert_field_allowed

FIELDS = ("kind", "ref", "at", "text", "lead_ref", "segment")


@dataclass
class SignalImportReport:
    rows: int = 0
    new: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = f"Read {self.rows} signal rows, stored {self.new} new."
        if self.skipped:
            s += f" Skipped {len(self.skipped)}."
        return s


def import_signals(ledger: Ledger, path: Path, cfg: dict, default_kind: str | None = None) -> SignalImportReport:
    source = cfg.get("source", "signals")
    cols = cfg.get("columns", {})
    unknown = set(cols) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown fields in [adapters.signals_csv.columns]: {', '.join(sorted(unknown))}")
    for f in ("ref", "at", "text"):
        if f not in cols:
            raise ValueError(f"[adapters.signals_csv.columns] must map '{f}'")
    if "kind" not in cols and not default_kind:
        raise ValueError("Map a 'kind' column, or pass --kind for a file of one kind")
    for field_name, col in cols.items():
        if field_name != "text":  # free text is scrubbed instead
            assert_field_allowed(col)
    kind_values = {
        k: {v.strip().lower() for v in vals} for k, vals in cfg.get("kind_values", {}).items()
    }

    def kind_of(raw: str | None) -> str | None:
        if not raw:
            return default_kind
        key = raw.strip().lower()
        for kind, values in kind_values.items():
            if key in values:
                return kind
        return key if key in SIGNAL_KINDS else None

    rep = SignalImportReport()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        absent = [c for c in cols.values() if c not in (reader.fieldnames or [])]
        if absent:
            raise ValueError(f"{Path(path).name} is missing mapped columns: {', '.join(absent)}")
        for row in reader:
            rep.rows += 1
            get = lambda f: (row.get(cols[f]) or "").strip() if f in cols else ""  # noqa: E731
            kind = kind_of(get("kind"))
            ref, at, text = get("ref"), get("at"), get("text")
            if not (kind and ref and at and text):
                rep.skipped.append(ref or f"row {rep.rows}")
                continue
            rep.new += ledger.add_signal(source, kind, ref, parse_ts(at), text,
                                         segment=get("segment") or None, lead_ref=get("lead_ref") or None)
    return rep
