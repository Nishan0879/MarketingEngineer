"""The one gate every agent action goes through.

Agents never act directly. They hand the runner a function to call, and the
runner enforces, in code and in this order:

1. The activity log verifies (nobody rewrote history).
2. The kill switch: client, engine and agent are all active (Section 11.3).
3. The agent has a job spec on disk (Section 10).
4. The agent's autonomy level covers this type of action (Section 11.1). The level
   comes from autonomy.py: promotions and demotions, not just the profile.
5. The agent is under its per-day cap (Section 11.6).
6. Dedupe: this action key has not already run (Section 11.6).
7. The kill switch again, right before acting.

Every outcome is logged, including refusals. Repeated failures pause the agent
and log an escalation (Section 11.5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import autonomy
from .activity_log import ActivityLog
from .control import Control
from .errors import DuplicateAction, GuardrailError, LevelTooLow, LogTampered, NoSpec, RateLimited
from .ledger import Ledger
from .workspace import Workspace

# Minimum autonomy level per action type (Section 11.1).
ACTION_LEVELS = {
    "observe": 0,   # read, analyze, report
    "draft": 1,     # create something a human releases
    "act": 2,       # execute a pre-approved pattern (send, publish)
    "spend": 3,     # commit money within caps
}
# Action types with no outside effect can be retried after a failure.
RETRYABLE = {"observe", "draft"}
MAX_RETRIES = 3


@dataclass
class RunResult:
    status: str  # ok | duplicate
    key: str
    output: Any


class Runner:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.log = ActivityLog(ws.log_path, ws.client_id)
        self.control = Control(ws.control_path)
        self.ledger = Ledger(ws.db_path, ws.client_id)

    def close(self) -> None:
        self.ledger.close()

    def run(
        self,
        agent: str,
        action: str,
        action_type: str,
        key: str,
        fn: Callable[[], dict],
        inputs: dict | None = None,
    ) -> RunResult:
        """Run fn() as one agent action. fn returns a dict; its 'summary' is logged."""
        inputs = dict(inputs or {}, key=key, action_type=action_type)
        cfg = self.ws.config.agents.get(agent)
        engine = cfg.engine if cfg else "unknown"
        try:
            self.log.verify()
            self.control.check(engine, agent)
            if cfg is None or not self.ws.path(cfg.spec).exists():
                raise NoSpec(f"Agent '{agent}' has no job spec; agents without a spec do not run.")
            if action_type not in ACTION_LEVELS:
                raise GuardrailError(f"Unknown action type '{action_type}'")
            current = autonomy.level(self.ws, agent)
            if current < ACTION_LEVELS[action_type]:
                raise LevelTooLow(
                    f"'{action_type}' needs Level {ACTION_LEVELS[action_type]}; "
                    f"'{agent}' is Level {current}."
                )
            if self._actions_today(agent) >= cfg.max_actions_per_day:
                raise RateLimited(f"'{agent}' reached its cap of {cfg.max_actions_per_day} actions today.")
            claimed_key, earlier = self._claim(agent, action, action_type, key)
            if earlier is not None:
                self.log.append(agent, action, "skipped_duplicate", inputs,
                                {"reason": f"{key} already ran", "earlier": earlier})
                return RunResult("duplicate", key, earlier)
            self.control.check(engine, agent)
        except GuardrailError as e:
            if isinstance(e, LogTampered):
                raise
            self.log.append(agent, action, "blocked", inputs,
                            {"reason": str(e), "guardrail": type(e).__name__})
            if isinstance(e, DuplicateAction):
                self._escalate(agent, f"Unsafe retry refused: {e}")
            raise

        inputs["key"] = claimed_key
        try:
            output = fn() or {}
        except Exception as e:
            self.ledger.finish_action(claimed_key, "failed", {"error": repr(e)})
            self.log.append(agent, action, "failed", inputs, {"reason": repr(e)})
            if self._consecutive_failures(agent) >= cfg.max_consecutive_errors:
                self._escalate(agent, f"{cfg.max_consecutive_errors} failures in a row; last: {e!r}")
            raise
        self.ledger.finish_action(claimed_key, "done", _jsonable(output))
        self.log.append(agent, action, "ok", inputs, _jsonable(output))
        return RunResult("ok", claimed_key, output)

    # Internals

    def _claim(self, agent: str, action: str, action_type: str, key: str):
        """Claim the key. Returns (claimed_key, None), or (key, earlier_result) if it already ran."""
        candidate = key
        for attempt in range(1, MAX_RETRIES + 2):
            existing = self.ledger.claim_action(candidate, agent, action)
            if existing is None:
                return candidate, None
            status, result = existing
            if status == "done":
                return candidate, json.loads(result or "{}")
            if action_type not in RETRYABLE:
                raise DuplicateAction(
                    f"{candidate} was already attempted (status '{status}'). It may have reached "
                    "the outside world, so it will not be retried automatically."
                )
            candidate = f"{key}#retry{attempt}"
        raise DuplicateAction(f"{key} failed {MAX_RETRIES + 1} times; retry limit reached.")

    def _actions_today(self, agent: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(
            1 for e in self.log.entries()
            if e["agent"] == agent and e["ts"].startswith(today) and e["result"] in ("ok", "failed")
        )

    def _consecutive_failures(self, agent: str) -> int:
        n = 0
        for e in reversed(self.log.entries()):
            if e["agent"] != agent or e["result"] not in ("ok", "failed"):
                continue
            if e["result"] == "ok":
                break
            n += 1
        return n

    def _escalate(self, agent: str, reason: str) -> None:
        self.control.pause("agent", agent, reason, by="runner")
        self.log.append(agent, "escalate", "escalated", {}, {"reason": f"Agent paused: {reason}"})


def _jsonable(obj: Any) -> dict:
    return json.loads(json.dumps(obj, default=str))
