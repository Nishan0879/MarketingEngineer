# Agent: experiment-tracker

## Job
Measure each running experiment against its comparison group and the decision rule fixed at approval, and suggest a verdict only once the minimum window and volume are met.

## Engine
core

## Autonomy level
0 — starting level

## Trigger / schedule
Weekly before the cockpit memo, or on demand with `mefw experiment measure`.

## Inputs
- Experiment briefs in `experiments/active/` (front matter holds the metric, comparison and decision criteria)
- The lead/outcome ledger

## Filters
- Leads outside the experiment's segment and channels
- Leads too recent to have reached the stage the metric measures

## Steps
1. Check the decision criteria still match the hash stored at approval.
2. Build the test group and the comparison group (before/after or holdout).
3. Compute the metric for both, with sample sizes.
4. Suggest keep, iterate, kill, or inconclusive, with the reason.
5. Append one line to the brief's measurements log.

## Output
- **Format:** one dated line per measurement
- **Destination:** the brief's `## Measurements log`
- **What good looks like:** "test 48% (n=31) vs. baseline 36% (n=40), +33%; day 21; suggested keep"
- **What bad looks like:** a verdict before the window is met; a verdict after the criteria changed

## Approval
None to measure. Only the operator sets the verdict (`mefw experiment close`).

## Escalate to a human when
- The criteria changed after approval
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Experiments closed with a verdict the operator agrees with.

## Quality checks
Receipts, Pipeline (Section 12.2).

## Write-back
Measurements log line per brief per day; one activity log entry per run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 20). Reads only.

## Change log
- {today}: created at Level 0
