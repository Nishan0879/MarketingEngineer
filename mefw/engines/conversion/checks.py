"""Checks every outgoing draft must pass before a human can release it (Sections 11.4 and 12.2).

These are the checks code can do. Voice, customer words and right-buyer are
still the operator's call at approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ...core.facts import Fact
from ...core.workspace import Workspace

# Things that read as a claim: money, percentages, numbers, promises.
CLAIM = re.compile(
    r"[$€£]\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?%|\b\d[\d,.]*\b|\b(?:guarantee[ds]?|free|discount|cheapest|best)\b",
    re.I,
)
# Asking for any of these is forbidden at every level (Section 11.4, rule 4).
SENSITIVE_ASK = re.compile(
    r"social security|\bssn\b|bank account|routing number|card number|credit (?:score|check|card)|"
    r"passport|driver'?s licen[cs]e|date of birth",
    re.I,
)
# Inbound words that mean a human should handle the lead (Section 11.5).
ESCALATE = re.compile(
    r"\b(?:lawyer|attorney|legal action|sue|lawsuit|complain(?:t|ed|ing)?|refund|furious|angry|"
    r"unacceptable|scam|harass\w*|stop contacting|unsubscribe)\b",
    re.I,
)
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


@dataclass
class Issue:
    check: str
    message: str
    blocking: bool = True


def banned_phrases(ws: Workspace) -> list[str]:
    """First column of the table in rules/banned-language.md."""
    path = ws.path("rules/banned-language.md")
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 1 and line.strip().startswith("|") and cells[0] and cells[0] != "Phrase" \
                and not set(cells[0]) <= set("-: "):
            out.append(cells[0])
    return out


def render(template: str, facts: dict[str, Fact], segment: str, today: date) -> tuple[str, list[str], list[Issue]]:
    """Fill {fact:key} placeholders. Any other placeholder is an error."""
    used, issues = [], []

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if not name.startswith("fact:"):
            issues.append(Issue("template", f"unknown placeholder {{{name}}}; only {{fact:key}} is allowed"))
            return m.group(0)
        key = name[5:]
        fact = facts.get(key)
        if fact is None:
            issues.append(Issue("facts", f"fact '{key}' is not in approved facts"))
            return m.group(0)
        problem = fact.problem(today, segment)
        if problem:
            issues.append(Issue("facts", problem))
        used.append(key)
        return fact.text

    return PLACEHOLDER.sub(sub, template), used, issues


def check_text(ws: Workspace, text: str, facts: dict[str, Fact], segment: str, today: date,
               must_include: list[str]) -> list[Issue]:
    issues = []
    leftover = PLACEHOLDER.findall(text)
    if leftover:
        issues.append(Issue("template", f"unfilled placeholder(s): {', '.join(leftover)}"))

    # A fact that is expired, unapproved or for another segment can't be used, even pasted in by hand.
    for f in facts.values():
        problem = f.problem(today, segment)
        if problem and f.text.strip() and f.text in text:
            issues.append(Issue("facts", problem))

    # Receipts: any claim must come from an approved fact usable for this segment.
    stripped = text
    for f in sorted(facts.values(), key=lambda f: -len(f.text)):
        if f.problem(today, segment) is None and f.text:
            stripped = stripped.replace(f.text, " ")
    claims = sorted({m.group(0).strip() for m in CLAIM.finditer(stripped)})
    if claims:
        issues.append(Issue("receipts", "claims not covered by an approved fact: " + ", ".join(claims)))

    for phrase in banned_phrases(ws):
        if phrase.lower() in text.lower():
            issues.append(Issue("voice", f"banned phrase: \"{phrase}\" (rules/banned-language.md)"))
    if SENSITIVE_ASK.search(text):
        issues.append(Issue("compliance", "mentions sensitive personal data; agents may never ask for it"))
    for required in must_include:
        if required.lower() not in text.lower():
            issues.append(Issue("compliance", f"missing required text: \"{required}\""))
    return issues
