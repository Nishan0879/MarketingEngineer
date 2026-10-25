"""Onboarding a client's lead export (Section 8.1, Section 17.2).

A preset (`presets/*.toml`) describes one common lead tool's export: the header
names each lead field usually goes by, the tool's default stage names and its
won/lost values. Exports differ by account, version and plan, so a preset is a
list of likely names, never a fixed layout: `check` resolves it against the
real file's header and reports what matched, what's missing, which columns look
like personal data (left out, never imported), and which stage values the
funnel can't place yet. `apply` writes the result into the client's
profile/mefw.toml, keeping a copy of the old one, and proves the new mapping
reads the file before it keeps it.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import tomllib
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..core.ledger import parse_ts
from ..core.pii import BLOCKED_FIELDS
from ..core.workspace import FUNNEL, Workspace, load_config
from .csv_source import LEAD_FIELDS, CsvSource

PRESETS = Path(__file__).parent / "presets"
REQUIRED = ("ref", "inquired_at")
DATE_FIELDS = ("inquired_at", "first_response_at", "last_outbound_at", "last_inbound_at", "outcome_at")
PROFILE = "profile/mefw.toml"


def norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def list_presets() -> dict[str, dict]:
    return {p.stem: tomllib.loads(p.read_text()) for p in sorted(PRESETS.glob("*.toml"))}


def load_preset(name: str) -> dict:
    presets = list_presets()
    if name not in presets:
        raise KeyError(f"No preset '{name}'. Choose one of: {', '.join(presets)}")
    return presets[name]


def resolve(preset: dict, headers: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """The file's column for each lead field and each stage date, taking each field's first alias present.

    Matching ignores case, spaces and punctuation. A column that looks like personal data is never mapped.
    """
    by_norm = {}
    for h in headers:
        by_norm.setdefault(norm(h), h)

    def first(aliases: list[str]) -> str | None:
        for alias in aliases:
            h = by_norm.get(norm(alias))
            if h and not BLOCKED_FIELDS.search(h):
                return h
        return None

    columns = {f: h for f in LEAD_FIELDS if (h := first(preset.get("columns", {}).get(f, [])))}
    dates = {stage: h for stage, aliases in preset.get("stage_dates", {}).items() if (h := first(aliases))}
    return columns, dates


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _stage_lookup(preset: dict, ws: Workspace | None) -> dict[str, str]:
    out = {n.strip().lower(): stage for stage, names in preset.get("stages", {}).items() for n in names}
    if ws is not None:
        out.update(ws.config.stage_map)
        for seg in ws.config.segments.values():
            out.update(seg.stage_map)
    return out


def _bad_date(raw: str) -> bool:
    try:
        parse_ts(raw)
        return False
    except ValueError:
        return True


def check(path: Path, preset: str | None = None, ws: Workspace | None = None) -> dict:
    """What a preset makes of this export. With no preset, the one that matches the most fields is used."""
    headers, rows = _read(path)
    presets = list_presets()
    scores = {}
    for name, p in presets.items():
        cols, _ = resolve(p, headers)
        scores[name] = 10 * sum(f in cols for f in REQUIRED) + len(cols)
    name = preset or max(scores, key=lambda n: scores[n])
    p = load_preset(name)
    columns, stage_dates = resolve(p, headers)
    rep = {"file": Path(path).name, "rows": len(rows), "preset": name, "label": p["preset"]["label"],
           "export": p["preset"].get("export", ""), "scores": scores, "columns": columns,
           "stage_dates": stage_dates,
           "missing_required": [f for f in REQUIRED if f not in columns],
           "missing": [f for f in LEAD_FIELDS if f not in columns and f not in REQUIRED],
           "personal": [h for h in headers if BLOCKED_FIELDS.search(h)],
           "unused": [h for h in headers if h not in columns.values() and h not in stage_dates.values()
                      and not BLOCKED_FIELDS.search(h)]}

    def values(field: str) -> Counter:
        col = columns.get(field)
        return Counter((r.get(col) or "").strip() for r in rows if col and (r.get(col) or "").strip())

    lookup = _stage_lookup(p, ws)
    won = {v.lower() for v in p.get("outcome_values", {}).get("won", [])}
    lost = {v.lower() for v in p.get("outcome_values", {}).get("lost", [])}
    # A lost value in the stage column is an outcome, not a funnel stage; it needs no place.
    rep["stages"] = {v: (lookup.get(v.lower()) or (v.lower() if v.lower() in FUNNEL else None)
                         or ("lost" if v.lower() in lost else None), n)
                     for v, n in values("stage").most_common()}
    rep["unmapped_stages"] = [v for v, (stage, _) in rep["stages"].items() if stage is None]
    rep["outcomes"] = {v: ("won" if v.lower() in won else "lost" if v.lower() in lost else "open", n)
                       for v, n in values("outcome").most_common()}
    bad = {}
    for field in DATE_FIELDS:
        col = columns.get(field)
        if not col:
            continue
        examples = [r[col].strip() for r in rows if (r.get(col) or "").strip() and _bad_date(r[col])]
        if examples:
            bad[field] = {"count": len(examples), "examples": examples[:3]}
    rep["bad_dates"] = bad
    refs = [(r.get(columns["ref"]) or "").strip() for r in rows] if "ref" in columns else []
    rep["blank_refs"] = sum(1 for x in refs if not x)
    rep["duplicate_refs"] = sum(n - 1 for x, n in Counter(x for x in refs if x).items() if n > 1)
    rep["ready"] = not rep["missing_required"] and not bad
    return rep


def render(rep: dict) -> str:
    L = [f"{rep['file']}: {rep['rows']} rows, read with the {rep['preset']} preset ({rep['label']})."]
    others = sorted((s, n) for n, s in rep["scores"].items() if n != rep["preset"] and s)
    if others and max(others)[0] >= rep["scores"][rep["preset"]]:
        L.append(f"  Also close: {', '.join(n for s, n in reversed(others) if s >= rep['scores'][rep['preset']])}.")
    L.append("")
    L.append("Columns that will be read:")
    L += [f"  {f:<18} <- {h}" for f, h in rep["columns"].items()]
    L += [f"  {'date ' + s:<18} <- {h}" for s, h in rep["stage_dates"].items()]
    if rep["missing_required"]:
        L.append(f"Missing and required: {', '.join(rep['missing_required'])}. Add the column to the export, or "
                 "map it by hand in [adapters.csv.columns].")
    if rep["missing"]:
        L.append(f"Not in this export (optional): {', '.join(rep['missing'])}")
    if rep["personal"]:
        L.append(f"Left out as personal data, never imported: {', '.join(rep['personal'])}. Better still, leave "
                 "these columns out of the export.")
    if rep["unused"]:
        L.append(f"Not used: {', '.join(rep['unused'])}")
    if rep["stages"]:
        L += ["", "Stage values:"]
        L += [f"  {v} ({n}) -> " + ("an outcome (lost), not a stage" if stage == "lost" else stage or "NOT MAPPED")
              for v, (stage, n) in rep["stages"].items()]
    if rep["unmapped_stages"]:
        L.append(f"Place the unmapped ones with --stage \"NAME=STAGE\" on apply (stages: {', '.join(FUNNEL)}), "
                 "or leave them out if they're not part of the funnel.")
    if rep["outcomes"]:
        L += ["", "Outcome values:"]
        L += [f"  {v} ({n}) -> {o}" for v, (o, n) in rep["outcomes"].items()]
    for field, b in rep["bad_dates"].items():
        L.append(f"Unreadable dates in {rep['columns'][field]}: {b['count']} (e.g. {', '.join(b['examples'])}). "
                 "Export dates as YYYY-MM-DD or YYYY-MM-DD HH:MM.")
    if rep["blank_refs"]:
        L.append(f"Rows with no ID: {rep['blank_refs']} (skipped on import).")
    if rep["duplicate_refs"]:
        L.append(f"Repeated IDs: {rep['duplicate_refs']}. Each lead should be one row; repeats update the same lead.")
    L += ["", "Ready to apply." if rep["ready"] else "Not ready: fix the items above first."]
    return "\n".join(L)


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _replace_table(text: str, header: str, body: list[str]) -> str:
    """Replace a TOML table's lines (up to the comments that lead into the next table), or append it."""
    lines = text.splitlines()
    block = [f"[{header}]", *body]
    try:
        start = lines.index(f"[{header}]")
    except ValueError:
        return text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return "\n".join(lines[:start] + block + lines[end:]) + "\n"


def apply(ws: Workspace, path: Path, preset: str, extra_stages: dict[str, str] | None = None,
          at: datetime | None = None) -> dict:
    """Write the preset's mapping for this export into profile/mefw.toml. The old profile is kept alongside."""
    rep = check(path, preset, ws)
    if not rep["ready"]:
        raise ValueError("This export can't be imported yet:\n" + render(rep))
    p = load_preset(preset)
    extra = {}
    for name, stage in (extra_stages or {}).items():
        if stage not in FUNNEL:
            raise ValueError(f"'{stage}' isn't a funnel stage; use one of {', '.join(FUNNEL)}")
        extra[name] = stage
    profile = ws.path(PROFILE)
    old = profile.read_text()
    raw = tomllib.loads(old)
    # Stage names: keep the operator's, add the preset's and --stage ones that aren't placed yet.
    stages = {k: list(v) if isinstance(v, list) else [v] for k, v in raw.get("funnel", {}).get("stages", {}).items()}
    placed = {n.strip().lower() for names in stages.values() for n in names}
    added = []
    for stage, names in [*p.get("stages", {}).items(), *((s, [n]) for n, s in extra.items())]:
        for n in names:
            if n.strip().lower() not in placed:
                stages.setdefault(stage, []).append(n)
                placed.add(n.strip().lower())
                added.append(f"{n} -> {stage}")
    text = _replace_table(old, "funnel.stages",
                          [f"{s:<7} = [{', '.join(_q(n) for n in stages[s])}]" for s in FUNNEL if stages.get(s)])
    text = _replace_table(text, "adapters.csv.columns", [f"{f:<17} = {_q(h)}" for f, h in rep["columns"].items()])
    text = _replace_table(text, "adapters.csv.stage_dates", [f"{_q(s)} = {_q(h)}" for s, h in rep["stage_dates"].items()])
    ov = p.get("outcome_values", {})
    text = _replace_table(text, "adapters.csv.outcome_values",
                          [f"{k:<4} = [{', '.join(_q(v) for v in ov.get(k, []))}]" for k in ("won", "lost")])
    if "[adapters.csv]" not in text.splitlines():
        text = text.replace("[adapters.csv.columns]", '[adapters.csv]\nsource = "crm"\n\n[adapters.csv.columns]', 1)
    backup = profile.with_name(f"mefw.toml.{(at or datetime.now()):%Y%m%dT%H%M%S}.bak")
    shutil.copyfile(profile, backup)
    profile.write_text(text)
    try:
        cfg = load_config(profile)
        n = sum(1 for _ in CsvSource(path, cfg.csv).records())
    except Exception:
        shutil.copyfile(backup, profile)
        raise
    return {**rep, "backup": str(backup.relative_to(ws.root)), "stages_added": added, "readable_rows": n}
