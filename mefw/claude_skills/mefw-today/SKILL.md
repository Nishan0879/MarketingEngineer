---
name: mefw-today
description: Show what needs the operator today for a MarketingEngineer client: drafts to review, leads waiting on a reply, tests to call, paused agents. Use when the operator asks what to do, what's waiting, or for a morning check.
---

# What needs you today

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Steps

1. Run `mefw today`. It only reads; it runs no agent.
2. If the activity log is BROKEN, say that first and stop: every agent is stopped until the operator finds out who changed `logs/agent-activity.jsonl`. Don't try to repair it.
3. Give the operator a short list, most urgent first:
   - leads waiting on a first reply, with how long the oldest has waited
   - drafts to review or send, by engine
   - anything paused, and why
   - tests or experiments waiting on a call
   - everything else in one line each
   Keep each item to one sentence in plain words. Leave out the CLI commands unless the operator asks.
4. End with the one thing you'd do first, and offer the slash command that does it: `/mefw-review` for drafts, `/mefw-lead` to log new leads or outcomes, `/mefw-run` to run what's due, `/mefw-report` for the weekly memo or monthly report.

If `mefw today` says nothing needs them, say so in one line and suggest logging today's leads with `/mefw-lead`.
