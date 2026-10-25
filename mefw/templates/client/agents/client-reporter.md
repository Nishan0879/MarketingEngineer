# Agent: client-reporter

## Job
Draft the monthly report the client reads: results, how inquiries were handled, what customers are telling us, what we tested, follow-up, and what's next. It's separate from the internal cockpit.

## Engine
core

## Autonomy level
0 — observe (drafts a report; the operator approves before the client sees it)

## Trigger / schedule
Monthly, on the first working day, for the month just ended; or on demand with `mefw report make --month YYYY-MM`. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due.

## Inputs
- The lead/outcome ledger
- Insight records in `customer-truth/insights/` with Status `confirmed` or `acted on`
- Experiment briefs (closed this month, running, approved)
- Sent drafts in `engines/conversion/drafts/`

## Filters
- Only confirmed insights; drafts are listed for the operator, not the client
- No lead IDs, source references, agent names, agent errors or internal decisions

## Steps
1. Count the north star for the month and the month before.
2. For each segment: inquiries, typical time to first reply, share answered within an hour, share that went on to a meeting. Each rate shows its sample size; small samples are marked.
3. Add confirmed insights in plain words, with the customer's own words where recorded.
4. Add experiments closed this month (decision, outcome, lesson, confidence) and the ones running.
5. Add follow-up sent this month and how many quiet leads came back.
6. Add what's next, and what would help from the client (for example, leads with no won/lost result).
7. Write `reports/YYYY-MM-client-report.md` as a draft, with notes for the operator in the front matter.

## Output
- **Format:** Markdown with front matter; an HTML copy on approval
- **Destination:** `reports/YYYY-MM-client-report.md` and `.html`
- **What good looks like:** one page, plain words, every number from the data with its sample size, honest about small samples
- **What bad looks like:** vanity numbers, unconfirmed claims, internal jargon, lead-level detail

## Approval
Every report. The operator edits it, then `mefw report approve`. Approval refuses a report with placeholders, draft wording, source references, agent names or anything that looks like contact details, and writes the HTML copy. An approved report is never overwritten.

## Escalate to a human when
- Outcome data is too thin to report results honestly (shown under "What would help from you")
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
The client reads it and acts on the asks; operator edit time goes down month to month.

## Quality checks
Receipts, Customer words, Right buyer, Approval. Section 12.2.

## Write-back
The draft report; one activity log entry per run and per approval.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 5).

## Change log
- {today}: created at Level 0
