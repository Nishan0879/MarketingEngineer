# Agent: cold-inquiry-auditor

## Job
Find where this client's inquiries go cold, separate the leaks that were ours to fix from the ones that weren't, and back every finding with lead references.

## Engine
conversion

## Autonomy level
0 — starting level

## Trigger / schedule
On demand during onboarding week 1 (audit), then weekly before the cockpit memo.

## Inputs
- The lead/outcome ledger (`data/ledger.db`), filled from the client's lead-tracking tool through an adapter
- `profile/mefw.toml` for funnel stage mapping, cycle length and audit thresholds
- `rules/corrections.md`

## Filters
- Leads outside the lookback window
- Leads younger than `cold_after_days` (too early to call cold)
- Leads with a won or lost outcome (not cold, they're decided)

## Steps
1. Build each lead's state as of the audit date from ledger events.
2. Compute the baseline funnel, speed to first response and outcome coverage.
3. Mark leads that are open, short of commitment, and quiet for `cold_after_days`.
4. Give each cold lead one reason, in order: never responded, waiting on us, slow first response, too few follow-ups, stalled after meeting, went quiet.
5. Compare speed to first response with meeting and win rates, with sample sizes and a confidence label.
6. Group lost reasons and break results down by channel.
7. List the fixable cold leads worth a human's second look.
8. Propose up to three next tests as hypotheses.

## Output
- **Format:** Markdown report plus a JSON copy of the numbers
- **Destination:** `engines/conversion/audits/YYYY-MM-DD-cold-inquiry-audit.{md,json}`
- **What good looks like:** one clear headline with receipts; every number traceable to lead references; "not enough evidence" where groups are small
- **What bad looks like:** conclusions from a handful of leads; claims of cause from correlation; personal data in the report

## Approval
None to produce the report. The operator decides whether any proposed test runs.

## Escalate to a human when
- The ledger has no outbound touches or no outcomes (the audit can't judge the leak)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Fixable cold leads per month, trending down once the top leak is addressed.

## Quality checks
Receipts, Right buyer, Pipeline (Section 12.2).

## Write-back
Report and JSON under `engines/conversion/audits/`; one activity log entry per run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 5). No outbound contact at Level 0.

## Change log
- {today}: created at Level 0
