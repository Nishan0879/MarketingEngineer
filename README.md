# MarketingEngineerFW

A reusable system for running marketing for lead-based businesses with AI agents, overseen by one operator. The operating manual is [MarketingEngineerFW.md](MarketingEngineerFW.md); this repository is the code that enforces it.

**Built so far (v0.2):** the core guardrails, a lead/outcome ledger, segments with their own funnels, customer truth, CSV adapters for any lead-tracking tool and for notes/messages/reviews, and the conversion engine's first job, a cold-inquiry audit. Client-agnostic: a new client is a new workspace plus a config file.

## Quick start

Python 3.11+, no dependencies.

```bash
python examples/make_sample.py examples                 # fictional coworking + office-leasing data
python -m mefw init ../client-demo --client-id demo      # new client workspace (Section 17.2 layout)
sed 's/{client_id}/demo/' examples/coworking/mefw.toml > ../client-demo/profile/mefw.toml   # example profile
python -m mefw import-csv --client ../client-demo examples/sample_leads.csv --activities examples/sample_activities.csv
python -m mefw import-signals --client ../client-demo examples/sample_signals.csv
python -m mefw audit-cold --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw truth --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw status --client ../client-demo
```

What comes out: [a cold-inquiry audit](examples/sample-audit.md), [the customer truth file](examples/sample-customer-truth.md) and [an insight record](examples/sample-insight-record.md).

For a real client, edit `profile/mefw.toml` in their workspace: segments, stage names, themes in their customers' words, and the column names of their exports. [examples/coworking/mefw.toml](examples/coworking/mefw.toml) is a filled-in example for a coworking space that also leases offices.

## Segments

A business can sell to groups that buy very differently, like coworking members (decide in days) and companies leasing offices (decide in months, with more stages). Each segment in `[segments.*]` has its own cycle length, its own extra stage names (for example `Proposal Sent` counts as a meeting for offices) and its own audit thresholds. The audit and customer truth report each segment separately, because a learning applies to the segment it came from (Section 8.1).

## Customer truth

`mefw truth` reads imported notes, messages and reviews plus the lost reasons from recorded outcomes, tags them with the client's themes, and writes:

- `customer-truth/what-the-market-is-telling-us.md`: the headline, rising and falling themes with short quotes, objections, what won leads talked about compared with lost ones, and open questions
- `customer-truth/updates/YYYY-MM-DD.md`: a dated copy
- `customer-truth/insights/<theme>--<segment>.md`: an insight record (Section 8.6) for each theme with enough evidence. Created once as `observed`; later runs only append dated evidence, so the operator's edits are never overwritten

Themes are matched by keyword for now. The tagger is one small interface (`tags(text) -> list[str]`), so a model-based tagger can replace it later without touching the analysis.

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
| `import-signals FILE [--kind K]` | Import notes, messages or reviews; contact details are scrubbed |
| `truth [--as-of]` | Update customer truth and insight records (Level 0) |
| `outcome REF won\|lost\|reopened [--reason] [--at]` | Record an outcome by hand |
| `audit-cold [--as-of]` | Run the cold-inquiry audit (Level 0, contacts nobody) |
| `pause` / `resume [--engine E \| --agent A]` | Kill switch |
| `status` | Pause state, agents, ledger and log health |
| `log verify \| render` | Check the hash chain, or write `logs/agent-activity.md` |

All take `--client DIR` (or `$MEFW_CLIENT`).

## Layout

```
mefw/core/          runner, kill switch, activity log, ledger, PII guard, workspace,
                    evidence rules, customer truth
mefw/adapters/      lead-source interface, lead CSV adapter, signals CSV adapter
mefw/engines/conversion/cold_audit.py
mefw/templates/client/   what `init` copies into a new client workspace
templates/          the spec's templates (agent spec, experiment brief, ...)
examples/           sample data generator, coworking profile, sample outputs
tests/              python -m unittest discover -s tests
```

## Adding a lead-tracking tool

Write a class with a `name` and a `records()` method that yields `LeadRecord`s (`mefw/adapters/base.py`), then pass it to `import_records`. The core doesn't change.
