# MarketingEngineerFW

A reusable system for running marketing for lead-based businesses with AI agents, overseen by one operator. The operating manual is [MarketingEngineerFW.md](MarketingEngineerFW.md); this repository is the code that enforces it.

**Built so far (v0.7):** the core guardrails, a lead/outcome ledger with opt-outs, approved facts, segments with their own funnels, customer truth, experiment briefs with locked decision rules, the weekly growth cockpit, two conversion drafting agents held for approval (first replies to new inquiries and re-engagement of cold leads), CSV adapters for any lead-tracking tool and for notes/messages/reviews, the conversion engine's first job, a cold-inquiry audit, a scheduler that runs it all on its own, and a monthly report for the client. Client-agnostic: a new client is a new workspace plus a config file.

## Quick start

Python 3.11+, no dependencies.

```bash
python examples/make_sample.py examples                 # fictional coworking + office-leasing data
python -m mefw init ../client-demo --client-id demo      # new client workspace (Section 17.2 layout)
sed 's/{client_id}/demo/' examples/coworking/mefw.toml > ../client-demo/profile/mefw.toml   # example profile
cp examples/coworking/approved-facts.toml ../client-demo/profile/
cp examples/coworking/playbook.toml ../client-demo/engines/conversion/
python -m mefw import-csv --client ../client-demo examples/sample_leads.csv --activities examples/sample_activities.csv
python -m mefw import-signals --client ../client-demo examples/sample_signals.csv
python -m mefw audit-cold --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw truth --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw experiment new --client ../client-demo --name "Reply within an hour" --segment members \
    --metric inquiry_to_meeting --hypothesis "If ..., then ..., because ..." --at 2026-08-20T09:00
python -m mefw experiment approve --client ../client-demo EXP-demo-001 --at 2026-08-21T09:00
python -m mefw experiment start --client ../client-demo EXP-demo-001 --at 2026-08-22T09:00
python -m mefw experiment measure --client ../client-demo --at 2026-10-25T12:00
python -m mefw drafts make --client ../client-demo --at 2026-10-25T12:00
python -m mefw cockpit --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw status --client ../client-demo
```

What comes out: [a cold-inquiry audit](examples/sample-audit.md), [the customer truth file](examples/sample-customer-truth.md), [an insight record](examples/sample-insight-record.md), [an experiment brief](examples/sample-experiment-brief.md), [a monthly client report](examples/sample-client-report.md), [a first-response draft](examples/sample-first-response.md), [a re-engagement draft](examples/sample-draft.md) and [a weekly cockpit memo](examples/sample-cockpit.md).

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

## Drafts (conversion engine, Level 1)

`mefw drafts make` runs two drafting agents. Use `--agent` to run one.

- **`first-response-drafter`** writes the first reply to each open inquiry nobody has answered yet, longest waiting first. It finds which questions the lead asked (topics with keywords in `[first_response.topics]` of the playbook) and answers them only with approved facts tagged with that topic (`topics = ["price"]` on a fact). A question with no usable fact is never guessed: the draft gets an `{answer needed: Price}` line that blocks approval until you write the answer. Once a lead passes the cold line it's the next agent's job.
- **`re-engagement-drafter`** writes a message for each lead the cold audit marks as ours to fix: never answered, waiting on us, slow first reply, or too few follow-ups. Each one fills the operator's template for that reason and segment.

Templates live in `engines/conversion/playbook.toml`, and **approved facts only** come from `profile/approved-facts.toml` (each with who approved it, when, an optional expiry, segments and topics). A lead has at most one draft in flight across both agents.

Before a draft reaches the operator it is checked:

- Every fact is approved, in date and allowed for the segment.
- Every claim (a price, a number, "free", "guaranteed", "best") comes from one of those facts.
- No banned language (`rules/banned-language.md`).
- No request for sensitive data.
- The required opt-out text is present.

Leads are skipped, not drafted, when they opted out (from the export's do-not-contact column or `mefw opt-out`), already committed or were lost, or wrote something a human should handle, such as a complaint, a legal threat or a refund request.

Nothing is sent by the system:

- `approve` reruns the checks on the text as edited and records whether it was edited.
- `reject --reason` adds a row to `rules/corrections.md`.
- `export` writes a CSV for the client's own sending tool.
- `sent` records the outbound touch on the lead, so later audits and experiments see it.

`mefw drafts record` tracks the Section 11.2 bar for Level 2 for each agent: 20 approvals in a row without edits over at least 2 weeks. The cockpit flags it when it's met, and lists first responses still waiting with how long the oldest lead has waited. Promotion still needs your sign-off.

## Running on a schedule

Each job's schedule lives in the `[schedule]` table of `profile/mefw.toml`, in the client's timezone: `"every 2h"`, `"every 30m"`, `"hourly"`, `"daily 07:00"`, `"weekly mon 07:00"` or `"monthly 1 08:00"`. Leave a job out to run it only by hand.

`mefw run-due` runs every job whose latest slot hasn't run yet:
- **Order.** Jobs run in a fixed order: import, customer truth, cold audit, first responses, re-engagement, experiments, cockpit, client report. Imports land before the agents that read them.
- **Same guardrails.** Each job is the same command you'd run by hand, so the kill switch, levels, caps and dedupe all still apply. A paused agent shows as `blocked`.
- **Missed slots.** These aren't replayed; only the latest slot runs.
- **Failures.** A failed slot is retried once on the next call, then left for you. Every attempt is in the activity log as a `scheduler` entry.
- **Overlap.** A lock stops two runs from overlapping.
- **Imports.** The import job reads the exports listed in `[schedule.inbox]`, `inbox/leads.csv` by default, and skips them if they haven't changed. `inbox/` is gitignored.
- **Status.** `mefw schedule` shows each job's last and next run. The weekly cockpit flags any job that has fallen two runs behind.

Call it every 15 minutes from whatever runs scheduled tasks on the operator's machine or server:

```
# cron (Linux/macOS): crontab -e
*/15 * * * * cd /path/to/MarketingEngineer && python -m mefw run-due --client /path/to/client-acme >> /path/to/client-acme/logs/run-due.txt 2>&1
```

```
# systemd timer: mefw-acme.service runs the same command; mefw-acme.timer has
[Timer]
OnCalendar=*:0/15
Persistent=true
```

On Windows, the scheduler needs `fcntl`, like the rest of the core, so run it under WSL with the cron line above. Exports stay on the machine that runs it. Nothing is sent from here, so an unattended run can only import, analyze and draft.

## Monthly client report

`mefw report make` (agent `client-reporter`, Level 0) drafts the report the client reads, for the last complete month by default (`--month 2026-10` for another). It's separate from the cockpit and has no agent errors, lead IDs or internal decisions.

What it covers:
- **Results:** the north star against last month.
- **How inquiries were handled:** for each segment, time to first reply, share answered within an hour and share that went on to a meeting. Each rate shows its sample size, and small samples are marked.
- **What customers are telling us:** only insight records you've set to `confirmed` or `acted on`, with the customer's own words.
- **What we tested:** experiments closed that month and the ones still running.
- **Follow-up:** messages sent, and quiet leads that came back.
- **What's next,** and **what would help from the client**, such as leads with no won/lost result.

The draft goes to `reports/YYYY-MM-client-report.md`. Its front matter lists anything left out for you to decide on. Edit it, then run `mefw report approve`. Approval refuses a report that still contains placeholders, draft wording, source references, agent names or contact details. It writes `reports/YYYY-MM-client-report.html`, a clean page you can send or print to PDF. An approved report is never overwritten.

Schedule it with `client-reporter = "monthly 1 08:00"`.

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
| `drafts make \| list \| approve \| reject \| sent \| export \| record` | First-response and re-engagement drafts; everything but `make` is the operator's |
| `opt-out REF [--undo]` | Record that a lead asked not to be contacted |
| `outcome REF won\|lost\|reopened [--reason] [--at]` | Record an outcome by hand |
| `audit-cold [--as-of]` | Run the cold-inquiry audit (Level 0, contacts nobody) |
| `pause` / `resume [--engine E \| --agent A]` | Kill switch |
| `report make \| approve` | Draft the monthly client report; approve it to get the shareable HTML |
| `run-due` | Run every scheduled job that's due (call it from cron) |
| `schedule` | Each scheduled job's last and next run |
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
