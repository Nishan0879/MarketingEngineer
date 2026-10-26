---
name: mefw-run
description: Run the MarketingEngineer jobs that are due now (imports, audits, drafts, cockpit, reports) and summarize what changed. Use when the operator says run it, catch up, or there's no cron on this machine.
---

# Run what's due

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Steps

1. Run `schedule` and tell the operator in one line which jobs are due.
2. Run `run-due`. It runs each due job once, in a fixed order, under the same guardrails as a hand run (kill switch, levels, daily caps, dedupe). A paused agent shows as `blocked`; that's expected, not an error.
3. Summarize what changed, one line each: leads imported, new drafts waiting, reports or memos written (with their paths), anything that failed or was blocked and why.
4. If drafts are waiting, offer `/mefw-review`. If a job failed twice, it's left for the operator: show the error and ask before trying anything else.

To run one job by hand instead (the operator names it), use its own command, for example `drafts make`, `audit-cold`, `truth`, `cockpit` or `search analyze`.

Don't change `[schedule]` in `profile/mefw.toml` unless the operator asks.
