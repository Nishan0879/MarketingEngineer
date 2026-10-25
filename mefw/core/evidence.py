"""Shared rules for how strongly the evidence supports a comparison (Section 13.2)."""

from __future__ import annotations


def confidence(sizes: list[int], min_size: int) -> tuple[str, str]:
    """Directional confidence for a comparison between groups.

    Groups under min_size are left out of the comparison; at least two must remain.
    Never returns "high": these are observational comparisons, not controlled tests.
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


def rate(num: int, den: int) -> str:
    return f"{num / den:.0%}" if den else "n/a"


def refs_md(refs: list[str], limit: int = 8) -> str:
    out = ", ".join(f"`{r}`" for r in refs[:limit])
    return out + (f" and {len(refs) - limit} more" if len(refs) > limit else "")
