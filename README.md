# MarketingEngineerFW

A reusable system for running marketing for lead-based businesses with AI agents, overseen by one operator. The operating manual is [MarketingEngineerFW.md](MarketingEngineerFW.md); this repository is the code that enforces it.

**Built so far (v0.3):** the core guardrails, a lead/outcome ledger, segments with their own funnels, customer truth, experiment briefs with locked decision rules, the weekly growth cockpit, CSV adapters for any lead-tracking tool and for notes/messages/reviews, and the conversion engine's first job, a cold-inquiry audit. Client-agnostic: a new client is a new workspace plus a config file.

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
python -m mefw experiment new --client ../client-demo --name "Reply within an hour" --segment members \
    --metric inquiry_to_meeting --hypothesis "If ..., then ..., because ..." --at 2026-08-20T09:00
python -m mefw experiment approve --client ../client-demo EXP-demo-001 --at 2026-08-21T09:00
python -m mefw experiment start --client ../client-demo EXP-demo-001 --at 2026-08-22T09:00
python -m mefw experiment measure --client ../client-demo --at 2026-10-25T12:00
python -m mefw cockpit --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw status --client ../client-demo
```

What comes out: [a cold-inquiry audit](examples/sample-audit.md), [the customer truth file](examples/sample-customer-truth.md), [an insight record](examples/sample-insight-record.md), [an experiment brief](examples/sample-experiment-brief.md) and [a weekly cockpit memo](examples/sample-cockpit.md).

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

## Experiments

`mefw experiment new` writes a brief in `experiments/active/` following the Section 13.1 template, with its settings in TOML front matter: segment, optional channels, one metric, the comparison (`before_after` against the same segment before the start, or `holdout` against other channels over the same dates), the minimum window and volume, and the keep/kill bars.

The Section 13.2 rules are enforced:

- **Criteria are locked at approval.** `approve` stores a hash of the decision rule and logs it. If the rule changes later, measurement says so and suggests no verdict.
- **Only mature leads count.** A rate only includes leads old enough to have reached the stage it measures, so recent leads don't look like a drop.
- **No verdict before the window.** Until the minimum days and leads are met, the suggestion is `inconclusive`.
- **The operator decides.** `measure` (agent `experiment-tracker`, Level 0) suggests keep, iterate or kill and appends a line to the brief. `close` records the operator's verdict, moves the brief to `experiments/completed/`, and adds the lesson to `experiments/lessons.md`.

Metrics: `inquiry_to_meeting`, `meeting_to_commit`, `inquiry_to_commit`, `first_response_minutes`, `responded_within_1h`.

## Growth cockpit

`mefw cockpit` (agent `growth-cockpit`, Level 0) writes `cockpit/YYYY-Www.md` using the Section 15 template:

- **North star:** from `[north_star]`, for this week, last week, and the four-week trend.
- **Wins and losses:** deals won and lost with reasons, leads that went cold this week for reasons on our side, experiments heading for keep or kill, and big funnel moves.
- **What changed:** the customer truth headline and rising themes, mentions of alternatives, and each segment's funnel over the last four complete weeks against the four before.
- **Recommended next tests:** proposed briefs, plus the top fixable leak per segment.
- **Agent errors:** failures, refusals and escalations from the activity log.
- **Decisions needed:** approvals, starts, verdicts, new insight records, paused agents and missing outcomes.

Memos are never overwritten. A rerun in the same week gets a suffix.

## Commands

| Command | Does |
|---|---|
| `init DIR --client-id ID` | Create a client workspace from the template |
| `import-csv FILE [--activities FILE]` | Import a lead export; re-importing the same file adds nothing |
| `import-signals FILE [--kind K]` | Import notes, messages or reviews; contact details are scrubbed |
| `truth [--as-of]` | Update customer truth and insight records (Level 0) |
| `experiment new \| list \| approve \| start \| stop \| measure \| close` | Run experiments; approve, start, stop and close are operator actions |
| `cockpit [--as-of]` | Write this week's growth cockpit memo (Level 0) |
| `outcome REF won\|lost\|reopened [--reason] [--at]` | Record an outcome by hand |
| `audit-cold [--as-of]` | Run the cold-inquiry audit (Level 0, contacts nobody) |
| `pause` / `resume [--engine E \| --agent A]` | Kill switch |
| `status` | Pause state, agents, ledger and log health |
| `log verify \| render` | Check the hash chain, or write `logs/agent-activity.md` |

All take `--client DIR` (or `$MEFW_CLIENT`).

## Layout

```
mefw/core/          runner, kill switch, activity log, ledger, PII guard, workspace,
                    evidence rules, metrics, customer truth, experiments, cockpit
mefw/adapters/      lead-source interface, lead CSV adapter, signals CSV adapter
mefw/engines/conversion/cold_audit.py
mefw/templates/client/   what `init` copies into a new client workspace
templates/          the spec's templates (agent spec, experiment brief, ...)
examples/           sample data generator, coworking profile, sample outputs
tests/              python -m unittest discover -s tests
```

## Adding a lead-tracking tool

Write a class with a `name` and a `records()` method that yields `LeadRecord`s (`mefw/adapters/base.py`), then pass it to `import_records`. The core doesn't change.
