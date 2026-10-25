# Agent: customer-truth-analyst

## Job
Keep `what-the-market-is-telling-us.md` current: what buyers are saying more or less often, what stops them, and what differs between those who committed and those who didn't, with a source for every point.

## Engine
core

## Autonomy level
0 — starting level

## Trigger / schedule
Weekly, after new notes, messages and reviews are imported; daily for high-volume clients. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due.

## Inputs
- Signals in the ledger: call and tour notes, inquiry messages, lost-deal notes, reviews, tickets (imported through an adapter)
- Lost reasons from recorded outcomes
- Themes and thresholds in `profile/mefw.toml` under `[customer_truth]`
- `rules/corrections.md`

## Filters
- Signals outside the current period and baseline window, except for won vs. lost, which uses all history
- Themes with fewer than `min_mentions` mentions are not called rising or turned into insight records

## Steps
1. Tag each signal with the client's themes.
2. Compare this period's mentions per theme with the baseline average, per segment.
3. Group objections from lost reasons and lost-deal notes.
4. Compare themes among leads that committed vs. leads that were lost, with a confidence label.
5. List open questions: untagged signal, missing sources, comparisons too small to read.
6. Write the running file, a dated copy, and insight records for themes with enough evidence.

## Output
- **Format:** Markdown file + JSON copy; insight records using the Section 8.6 template
- **Destination:** `customer-truth/what-the-market-is-telling-us.md`, `customer-truth/updates/`, `customer-truth/insights/`
- **What good looks like:** "5 tour notes this month mentioned parking, up from about 1 a month; 4 of the 6 lost office deals did too [refs]"
- **What bad looks like:** "Customers want a better experience"; any quote without a source; any statement from fewer mentions than the minimum

## Approval
None to update memory. New insight records start as `observed`; only the operator changes status to `tested` or `retired`.

## Escalate to a human when
- Over 30% of this period's signal matches no theme (the theme list needs work)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Insights the operator keeps and turns into experiments.

## Quality checks
Receipts, Customer words, Right buyer (Section 12.2).

## Write-back
The files above; one activity log entry per run. Existing insight records are never rewritten; new evidence is appended to their evidence log.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 5). Reads only; contacts nobody.

## Change log
- {today}: created at Level 0
