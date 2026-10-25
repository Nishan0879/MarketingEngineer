"""Errors raised by the core when a guardrail blocks an action."""


class GuardrailError(Exception):
    """Base class: an action was refused by a guardrail. Always logged."""


class Paused(GuardrailError):
    """The client, engine or agent is paused by the kill switch."""


class NoSpec(GuardrailError):
    """The agent has no job spec. Agents without a spec do not run (Section 10)."""


class LevelTooLow(GuardrailError):
    """The action needs a higher autonomy level than the agent holds (Section 11.1)."""


class RateLimited(GuardrailError):
    """The agent hit its per-day action cap (Section 11.6)."""


class DuplicateAction(GuardrailError):
    """The action already ran, or an earlier attempt is in an unknown state (Section 11.6)."""


class LogTampered(GuardrailError):
    """The activity log's hash chain does not verify (Section 11.4, rule 8)."""


class OutsideWorkspace(GuardrailError):
    """A path or record points outside this client's workspace (Section 11.4, rule 9)."""


class SensitiveData(GuardrailError):
    """Input contained sensitive personal data that must stay in the CRM (Section 8.1)."""
