# Agent: creative-tester

## Job
Find the angles and hooks that bring qualified inquiries and meetings at the lowest cost, by planning tests of several variants of an insight that has already shown it resonates, and reading the results.

## Engine
creative

## Autonomy level
1 — starting level (plans tests and reads results; a human writes, approves, sets budgets and runs the ads)

## Trigger / schedule
Weekly. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due. On demand with `mefw creative plan`.

## Inputs
- Insight records in `customer-truth/insights/` with Status `confirmed` or `acted on` and enough evidence (`[content] min_evidence`)
- `profile/approved-facts.toml` (approved offers and claims for the segment)
- `engines/creative/playbook.toml` (angles, channel, budget cap and plan, stop rules, required text)
- `engines/creative/winners.md` (past creative results for the same audience)
- Ad platform exports imported with `mefw creative results-import`, and the lead ledger's campaign field
- `rules/banned-language.md`

## Filters
- One test per insight at a time, and at most one every `refresh_days`
- A plan's total budget must fit under `max_test_budget`

## Steps
1. Write `engines/creative/plans/T-YYYYMMDD-<insight>.md`: hypothesis, audience, customers' words, facts that may be claimed, past winners, the budget plan, stop rules, and one section per variant with its angle and tag.
2. For running tests, match the latest ad export and the tagged inquiries to each variant, and write `engines/creative/results.md` with cost per qualified inquiry, meeting and commitment, and a suggested call.

## Output
- **Format:** Markdown plan with front matter; Markdown results
- **Destination:** `engines/creative/plans/`, `engines/creative/results.md`
- **What good looks like:** distinct angles from real customer language, every claim an approved fact, a clear call on cost per meeting
- **What bad looks like:** variants that differ only in wording, decisions on click rate, invented results or misleading visuals

## Approval
`mefw creative approve <id>` checks every written variant: claims only from approved facts, no banned language, no request for sensitive data, required text present, no misleading imagery or urgency, no invented results, no quotation without permission (`--quote-permission`), at least two variants, and the planned budget under the cap. The operator builds the ads, sets the budgets in the ad tool, runs `mefw creative start`, and closes the test with `mefw creative close`. Budget changes only at Level 3, within caps (Section 9.4).

## Escalate to a human when
- Spend goes over the approved budget (the results say pause it)
- A variant has spent enough with no qualified inquiry (the results say stop it)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Cost per qualified inquiry, cost per meeting and cost per commitment (Section 9.4).

## Quality checks
Receipts, Compliance, Evidence, Customer words, Approval. Section 12.2.

## Write-back
Plans, `engines/creative/results.md`, `engines/creative/winners.md` (on close), one activity log entry per plan and per results run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 10); `--max` per run (default 2).

## Change log
- {today}: created at Level 1
