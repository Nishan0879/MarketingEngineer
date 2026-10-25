"""Funnel metrics over a set of leads (Section 14.2), shared by experiments and the cockpit.

A rate only counts leads old enough to have reached the stage it measures: a lead
that inquired yesterday hasn't had time to book a tour, so counting it would make
any recent change look like a drop. Every metric comes back with its sample size.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from .ledger import LeadState

# name: (label, direction that counts as better, maturity in days or "cycle")
METRICS = {
    "inquiry_to_meeting": ("Inquiry → meeting rate", "increase", 14),
    "meeting_to_commit": ("Meeting → commitment rate", "increase", "cycle"),
    "inquiry_to_commit": ("Inquiry → commitment rate", "increase", "cycle"),
    "first_response_minutes": ("Median minutes to first response", "decrease", 1),
    "responded_within_1h": ("Share answered within 1 hour", "increase", 1),
}


@dataclass
class Value:
    value: float | None
    n: int  # leads the value is computed from

    def fmt(self, metric: str) -> str:
        if self.value is None:
            return "n/a"
        if metric == "first_response_minutes":
            m = self.value
            return f"{m:.0f} min" if m < 60 else (f"{m / 60:.1f} h" if m < 1440 else f"{m / 1440:.1f} d")
        return f"{self.value:.0%}"


def maturity_days(metric: str, cycle_days: int) -> int:
    m = METRICS[metric][2]
    return cycle_days if m == "cycle" else m


def compute(metric: str, leads: list[LeadState], as_of: datetime, cycle_days: int) -> Value:
    """The metric over leads old enough to be judged on it as of `as_of`."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric {metric!r}; choose from {', '.join(METRICS)}")
    cutoff = as_of - timedelta(days=maturity_days(metric, cycle_days))
    mature = [s for s in leads if s.inquired_at <= cutoff]
    if metric == "inquiry_to_meeting":
        return _ratio(sum(1 for s in mature if s.reached("meet")), len(mature))
    if metric == "inquiry_to_commit":
        return _ratio(sum(1 for s in mature if s.outcome == "won"), len(mature))
    if metric == "meeting_to_commit":
        met = [s for s in mature if s.reached("meet")]
        return _ratio(sum(1 for s in met if s.outcome == "won"), len(met))
    responded = [(s.first_response_at - s.inquired_at).total_seconds() / 60
                 for s in mature if s.first_response_at]
    if metric == "first_response_minutes":
        return Value(statistics.median(responded) if responded else None, len(responded))
    return _ratio(sum(1 for m in responded if m <= 60), len(mature))


def _ratio(num: int, den: int) -> Value:
    return Value(num / den if den else None, den)


def relative_change(metric: str, test: Value, base: Value) -> float | None:
    """Change from base to test, signed so that positive always means better."""
    if test.value is None or base.value is None or base.value == 0:
        return None
    change = (test.value - base.value) / base.value
    return change if METRICS[metric][1] == "increase" else -change


def in_window(leads: list[LeadState], start: datetime, end: datetime) -> list[LeadState]:
    return [s for s in leads if start <= s.inquired_at < end]
