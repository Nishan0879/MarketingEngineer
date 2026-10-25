# Agent: growth-cockpit

## Job
Write the weekly memo the operator steers by: the north star, wins, losses, what changed, the next tests, agent errors, and the decisions only the operator can make.

## Engine
core

## Autonomy level
0 — starting level

## Trigger / schedule
Weekly, after the week's imports, `mefw truth` and `mefw experiment measure`. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due.

## Inputs
- The lead/outcome ledger
- Customer truth (computed fresh from imported signal)
- Experiment briefs
- The activity log and kill switch state
- `[north_star]` in `profile/mefw.toml`

## Filters
- Wins, losses and agent errors outside the ISO week

## Steps
1. Count the north star for this week, last week, and the last four weeks against the four before.
2. List deals won and lost this week, and leads that went cold this week for reasons on our side.
3. Compare each segment's funnel over the last four complete weeks with the four before.
4. Pull the customer truth headline, rising themes and mentions of alternatives.
5. List proposed and running experiments, plus the top fixable leak per segment as a test idea.
6. List agent failures, refusals and escalations from the activity log.
7. List the operator's decisions: approvals, starts, verdicts, new insight records, paused agents, missing outcomes.

## Output
- **Format:** Markdown memo using the Section 15 template
- **Destination:** `cockpit/YYYY-Www.md` (a rerun the same week gets a suffix; memos are never overwritten)
- **What good looks like:** every number has its sample size or lead references; every decision says what to run
- **What bad looks like:** activity counts as wins; trends from a handful of leads stated as fact

## Approval
None to write the memo. The decisions in it are the operator's.

## Escalate to a human when
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Operator decisions made per week from the memo.

## Quality checks
Receipts, Right buyer, Pipeline (Section 12.2).

## Write-back
The memo; one activity log entry per run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 5). Reads only.

## Change log
- {today}: created at Level 0
