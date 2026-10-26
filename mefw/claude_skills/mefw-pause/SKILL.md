---
name: mefw-pause
description: Pause or resume a MarketingEngineer client, one engine or one agent (the kill switch). Use when the operator says stop, pause, hold, or something is going wrong, and to resume afterwards.
---

# Pause or resume

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Pause

1. Work out the scope from what the operator said: the whole client, one engine (`--engine conversion`, `content`, `search`, `outbound`, `creative`) or one agent (`--agent first-response-drafter`). If they said "stop" or something is going wrong and the scope is unclear, pause the whole client first and ask after. Stopping is always safe.
2. Run `pause --reason "<their words>"` with the scope.
3. Run `status` and confirm what's paused now.

A paused agent's work is refused and logged, not queued. Drafts already written stay where they are.

## Resume

1. Run `status` and show what's paused and why.
2. Ask whether the cause is fixed. Resume only what the operator names: `resume` with the same scope.
3. Run `status` again to confirm.

If `status` says the activity log is broken, everything stays stopped whatever the pause state. Tell the operator and don't try to repair the log.
