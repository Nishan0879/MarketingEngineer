"""Customer truth (Section 8.2): what buyers are saying, what changed, and what
separates the ones who committed from the ones who didn't.

Signal comes from the ledger: imported notes, messages and reviews, plus lost
reasons from recorded outcomes. Each piece is tagged with themes; v0.1 tags by
keyword from the client's theme list in profile/mefw.toml. Anything with a
`tags(text) -> list[str]` method can replace the keyword tagger later (for
example a model-based one), without changing the analysis.

Every finding carries counts and source references. Small numbers are reported
as "not enough evidence", and nothing here is promoted past `observed`: the
operator decides what becomes `tested` (Section 8.1).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .evidence import confidence
from .ledger import Ledger, iso
from .workspace import Workspace

DEFAULTS = {
    "period_days": 30,
    "baseline_periods": 3,
    "min_mentions": 3,
    "rising_factor": 1.5,
    "min_group_size": 5,
    "quote_max_chars": 160,
}

# Signal kinds that describe why someone didn't move forward.
OBJECTION_KINDS = {"lost_note", "lost_reason"}


class Tagger(Protocol):
    def tags(self, text: str) -> list[str]: ...


@dataclass
class Theme:
    name: str
    label: str
    keywords: list[str]
    pattern: re.Pattern = field(repr=False, default=None)

    def __post_init__(self):
        alts = "|".join(re.escape(k.strip()) for k in self.keywords if k.strip())
        self.pattern = re.compile(rf"(?<!\w)(?:{alts})", re.I) if alts else re.compile(r"(?!x)x")


class KeywordTagger:
    def __init__(self, themes: dict[str, Theme]):
        self.themes = themes

    def tags(self, text: str) -> list[str]:
        return [name for name, t in self.themes.items() if t.pattern.search(text)]


@dataclass
class Settings:
    period_days: int
    baseline_periods: int
    min_mentions: int
    rising_factor: float
    min_group_size: int
    quote_max_chars: int

    @classmethod
    def from_config(cls, cfg: dict) -> "Settings":
        merged = {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}
        return cls(**merged)


def load_themes(cfg: dict) -> dict[str, Theme]:
    themes = {}
    for name, t in cfg.get("themes", {}).items():
        themes[name] = Theme(name, t.get("label", name.replace("_", " ").capitalize()), list(t.get("keywords", [])))
    return themes


def quote(text: str, theme: Theme, max_chars: int) -> str:
    """The sentence where the theme is mentioned, trimmed to a short exact quote."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    hit = next((s for s in sentences if theme.pattern.search(s)), text)
    hit = hit.strip()
    if len(hit) <= max_chars:
        return hit
    m = theme.pattern.search(hit)
    start = max(0, min(m.start() - max_chars // 3, len(hit) - max_chars)) if m else 0
    out = hit[start:start + max_chars].strip()
    return ("…" if start > 0 else "") + out + ("…" if start + max_chars < len(hit) else "")


def run_truth(ws: Workspace, ledger: Ledger, as_of: datetime, tagger: Tagger | None = None) -> dict:
    cfg = Settings.from_config(ws.config.customer_truth)
    themes = load_themes(ws.config.customer_truth)
    tagger = tagger or KeywordTagger(themes)
    signals = ledger.signals(as_of)
    for s in signals:
        s["tags"] = tagger.tags(s["text"])
        s["segment_name"] = ws.segment_for(s["segment"])
    outcomes = {st.lead_id: st.outcome for st in ledger.states(as_of)}

    by_segment = defaultdict(list)
    for s in signals:
        by_segment[s["segment_name"]].append(s)
    names = ws.segment_names() + [n for n in by_segment if n not in ws.segment_names()]
    segments = {}
    for name in names:
        seg = analyze(by_segment.get(name, []), themes, outcomes, cfg, as_of)
        seg["label"] = ws.segment_label(name)
        segments[name] = seg

    data = {"client": ws.client_id, "as_of": iso(as_of), "settings": asdict(cfg),
            "themes": {n: t.label for n, t in themes.items()}, "segments": segments,
            "signals": len(signals)}
    data["open_questions"] = [
        f"No {kind.replace('_', ' ')}s in the data. Where do they live?"
        for kind in ("tour_note", "lost_note", "review") if not any(s["kind"] == kind for s in signals)
    ]
    with_headline = [n for n, d in segments.items() if d.get("headline_refs")]
    if not themes:
        data["headline"] = "No themes configured yet: add [customer_truth.themes] to profile/mefw.toml."
    elif not with_headline:
        data["headline"] = "Not enough evidence for a headline this period."
    else:
        best = max(with_headline, key=lambda n: segments[n]["headline_score"])
        prefix = "" if len(segments) == 1 else f"{segments[best]['label']}: "
        data["headline"] = prefix + segments[best]["headline"]
        data["headline_refs"] = segments[best]["headline_refs"]
    return data


def analyze(signals: list[dict], themes: dict[str, Theme], outcomes: dict, cfg: Settings,
            as_of: datetime) -> dict:
    period = timedelta(days=cfg.period_days)
    cur_start = as_of - period
    base_start = cur_start - cfg.baseline_periods * period
    current = [s for s in signals if s["at"] > cur_start]
    baseline = [s for s in signals if base_start < s["at"] <= cur_start]
    window = current + baseline

    data = {"current_signals": len(current), "baseline_signals": len(baseline),
            "by_kind": _count(s["kind"] for s in current)}

    # Rising and falling themes, current period against the baseline average
    trends = []
    for name, theme in themes.items():
        cur = [s for s in current if name in s["tags"]]
        base_n = sum(1 for s in baseline if name in s["tags"])
        base_avg = base_n / cfg.baseline_periods
        cur.sort(key=lambda s: s["at"], reverse=True)
        if len(cur) >= cfg.min_mentions and (base_avg == 0 or len(cur) >= cfg.rising_factor * base_avg):
            direction = "new" if base_avg == 0 else "rising"
        elif base_avg >= cfg.min_mentions and len(cur) <= base_avg / cfg.rising_factor:
            direction = "falling"
        else:
            direction = "steady"
        trends.append({
            "theme": name, "label": theme.label, "current": len(cur), "baseline_avg": round(base_avg, 1),
            "direction": direction, "refs": [s["ref"] for s in cur],
            "quotes": _distinct_quotes(cur, theme, cfg.quote_max_chars, 3),
        })
    trends.sort(key=lambda t: (-t["current"], t["theme"]))
    data["trends"] = trends

    # Objections: why people didn't move forward, over the whole window
    objections = []
    obj_signals = [s for s in window if s["kind"] in OBJECTION_KINDS]
    for name, theme in themes.items():
        hits = sorted((s for s in obj_signals if name in s["tags"]), key=lambda s: s["at"], reverse=True)
        if hits:
            objections.append({
                "theme": name, "label": theme.label, "count": len(hits), "refs": [s["ref"] for s in hits],
                "quote": {"text": quote(hits[0]["text"], theme, cfg.quote_max_chars), "ref": hits[0]["ref"]},
            })
    objections.sort(key=lambda o: -o["count"])
    data["objections"] = objections
    data["objection_signals"] = len(obj_signals)

    # Won vs. lost: which themes show up in the conversations of each group
    lead_tags: dict[str, set] = defaultdict(set)
    for s in signals:  # all history, so early conversations count for later outcomes
        if s["lead_id"] and s["kind"] not in OBJECTION_KINDS:
            lead_tags[s["lead_id"]].update(s["tags"])
    won = [l for l in lead_tags if outcomes.get(l) == "won"]
    lost = [l for l in lead_tags if outcomes.get(l) == "lost"]
    conf, why = confidence([len(won), len(lost)], cfg.min_group_size)
    rows = []
    for name, theme in themes.items():
        w = [l for l in won if name in lead_tags[l]]
        lo = [l for l in lost if name in lead_tags[l]]
        if len(w) + len(lo) >= cfg.min_mentions:
            rows.append({"theme": name, "label": theme.label, "won": len(w), "lost": len(lo),
                         "won_share": len(w) / len(won) if won else None,
                         "lost_share": len(lo) / len(lost) if lost else None})
    rows.sort(key=lambda r: -abs((r["won_share"] or 0) - (r["lost_share"] or 0)))
    data["won_vs_lost"] = {"won_leads": len(won), "lost_leads": len(lost), "rows": rows,
                           "confidence": conf, "why": why}

    # Open questions
    questions = []
    untagged = [s for s in current if not s["tags"]]
    if current and len(untagged) / len(current) > 0.3:
        questions.append({
            "text": f"{len(untagged)} of {len(current)} signals this period match no theme. "
                    "Read a few and add themes or keywords.",
            "refs": [s["ref"] for s in untagged[:8]],
        })
    if conf == "not enough evidence" and (won or lost):
        questions.append({"text": f"Won vs. lost comparison is too small ({len(won)} won, {len(lost)} lost "
                                  "with linked conversations). Link notes to lead IDs.", "refs": []})
    data["open_questions"] = questions

    # Headline: the biggest rise this period; failing that, the top objection
    moving = [t for t in trends if t["direction"] in ("new", "rising")]
    if moving:
        top = max(moving, key=lambda t: t["current"] - t["baseline_avg"])
        data["headline"] = (
            f"{top['label']} came up {top['current']} times in the last {cfg.period_days} days "
            f"(about {top['baseline_avg']:g} per period before)."
        )
        data["headline_refs"] = top["refs"]
        data["headline_score"] = top["current"] - top["baseline_avg"]
        data["headline_theme"] = top["theme"]
    elif objections and objections[0]["count"] >= cfg.min_mentions:
        top = objections[0]
        data["headline"] = (f"No theme is rising. The most common objection is {top['label'].lower()} "
                            f"({top['count']} lost deals or notes).")
        data["headline_refs"] = top["refs"]
        data["headline_score"] = 0
        data["headline_theme"] = top["theme"]
    else:
        data["headline"] = "Not enough evidence for a headline this period."
    return data


def _distinct_quotes(signals: list[dict], theme: Theme, max_chars: int, n: int) -> list[dict]:
    """Up to n quotes with different wording, most recent first."""
    out, seen = [], set()
    for s in signals:
        text = quote(s["text"], theme, max_chars)
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append({"text": text, "ref": s["ref"], "kind": s["kind"]})
        if len(out) == n:
            break
    return out


def _count(items) -> dict:
    out: dict = defaultdict(int)
    for i in items:
        out[i] += 1
    return dict(out)
