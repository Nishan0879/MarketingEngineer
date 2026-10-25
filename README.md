# MarketingEngineerFW

A reusable system for running marketing for lead-based businesses with AI agents, overseen by one operator. The operating manual is [MarketingEngineerFW.md](MarketingEngineerFW.md); this repository is the code that enforces it.

**Built so far (v0.1):** the core guardrails, a lead/outcome ledger, a CSV adapter for any lead-tracking tool, and the conversion engine's first job, a cold-inquiry audit. Client-agnostic: a new client is a new workspace plus a config file.

## Quick start

Python 3.11+, no dependencies.

```bash
python examples/make_sample.py examples                # fictional coworking leads
python -m mefw init ../client-demo --client-id demo     # new client workspace (Section 17.2 layout)
python -m mefw import-csv --client ../client-demo examples/sample_leads.csv --activities examples/sample_activities.csv
python -m mefw audit-cold --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw status --client ../client-demo
```

The audit lands in `client-demo/engines/conversion/audits/`. See [examples/sample-audit.md](examples/sample-audit.md) for what it looks like.

For a real client, edit `profile/mefw.toml` in their workspace: map their stage names onto the funnel, and their export's column names onto the CSV fields.

## What the core enforces in code

Every agent action goes through `mefw/core/runner.py`. In order:

| Check | Spec | What happens |
|---|---|---|
| Activity log verifies | 11.4 rule 8 | Hash-chained JSONL; any edit or deletion stops all agents |
| Kill switch | 11.3 | Client, engine or agent paused in `control/pause.json` → refused. A corrupt file counts as paused |
| Job spec exists | 10 | No spec file → the agent doesn't run |
| Autonomy level | 11.1 | `observe` 0, `draft` 1, `act` 2, `spend` 3 |
| Daily cap | 11.6 | `max_actions_per_day` per agent |
| Dedupe | 11.6 | Each action has a key. Done → skipped. A failed or unfinished `act`/`spend` is never retried automatically; the agent is paused and the operator decides |
| Repeated errors | 11.5 | `max_consecutive_errors` failures in a row pause the agent and log an escalation |

Every outcome, including refusals, is written to `logs/agent-activity.jsonl`.

The ledger (`data/ledger.db`, SQLite) stores lead history as events that database triggers stop anyone from editing or deleting. It keeps the lead's ID from the client's tool, never names or contact details: the importer refuses columns that look like personal data and scrubs emails and phone numbers from free text. Outcomes through Commit (won, lost with a reason, reopened) are events too.

## Commands

| Command | Does |
|---|---|
| `init DIR --client-id ID` | Create a client workspace from the template |
| `import-csv FILE [--activities FILE]` | Import a lead export; re-importing the same file adds nothing |
| `outcome REF won\|lost\|reopened [--reason] [--at]` | Record an outcome by hand |
| `audit-cold [--as-of]` | Run the cold-inquiry audit (Level 0, contacts nobody) |
| `pause` / `resume [--engine E \| --agent A]` | Kill switch |
| `status` | Pause state, agents, ledger and log health |
| `log verify \| render` | Check the hash chain, or write `logs/agent-activity.md` |

All take `--client DIR` (or `$MEFW_CLIENT`).

## Layout

```
mefw/core/          runner, kill switch, activity log, ledger, PII guard, workspace
mefw/adapters/      lead-source interface + CSV adapter
mefw/engines/conversion/cold_audit.py
mefw/templates/client/   what `init` copies into a new client workspace
templates/          the spec's templates (agent spec, experiment brief, ...)
examples/           sample data generator and sample report
tests/              python -m unittest discover -s tests
```

## Adding a lead-tracking tool

Write a class with a `name` and a `records()` method that yields `LeadRecord`s (`mefw/adapters/base.py`), then pass it to `import_records`. The core doesn't change.
