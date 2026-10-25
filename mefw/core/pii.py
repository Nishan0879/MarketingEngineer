"""Keep sensitive personal data out of the workspace (Section 8.1).

The ledger stores the CRM's reference for a lead, never who the lead is. Free
text that does come in (lost reasons, notes) is scrubbed of contact details and
card-like numbers before it is stored.
"""

from __future__ import annotations

import re

from .errors import SensitiveData

# Column names that must never be mapped into the ledger.
BLOCKED_FIELDS = re.compile(
    r"(e-?mail|phone|mobile|^name$|first.?name|last.?name|full.?name|address|ssn|"
    r"social.?security|passport|licen[cs]e.?(no|number)|dob|birth|card|iban|account.?(no|number)|"
    r"routing|credit)",
    re.I,
)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
LONG_NUMBER = re.compile(r"\b\d{9,19}\b")


def assert_field_allowed(field: str) -> None:
    if BLOCKED_FIELDS.search(field):
        raise SensitiveData(
            f"Field '{field}' looks like personal data. Keep it in the CRM and map only the lead's reference ID."
        )


def scrub(text: str | None) -> str | None:
    if text is None:
        return None
    text = EMAIL.sub("[email removed]", text)
    text = LONG_NUMBER.sub("[number removed]", text)
    text = PHONE.sub("[phone removed]", text)
    return text.strip()
