# Agent: outbound-drafter

## Job
Find companies with a real reason to need the client now, score them on fit, reason and timing, and draft a message tied to that reason for a human to send.

## Engine
outbound

## Autonomy level
1 — starting level (scores and drafts; a human picks the person, sends and records what came back)

## Trigger / schedule
Weekly, after fresh triggers are imported. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due. On demand with `mefw outbound drafts`.

## Inputs
- Trigger events in `engines/outbound/triggers.jsonl` (company data only), imported with `mefw outbound import`
- `engines/outbound/playbook.toml` (ICP, trigger types and weights, templates, limits, required text)
- `engines/outbound/suppressed.jsonl` (opted out, customers, companies the client asked to leave alone)
- `profile/approved-facts.toml`, `rules/banned-language.md`

## Filters
- Watch → Enrich → Score → Send → Learn (Section 9.2)
- Drop companies outside the ICP, with no trigger in `fresh_days`, scoring under `min_score`, suppressed, or contacted within `recontact_days`
- One draft in flight per company

## Steps
1. Score each company: ICP fit × trigger weight × how recent the trigger is.
2. For the best ones, fill the trigger type's template with the company, the trigger detail and approved facts.
3. Check the draft and write `engines/outbound/drafts/O-YYYYMMDD-<company>.md`.
4. Write `engines/outbound/reports/YYYY-MM-DD.md`: who's worth contacting, who was left out and why, and what came back by trigger type and score band.

## Output
- **Format:** Markdown draft with front matter; Markdown report
- **Destination:** `engines/outbound/drafts/`, `engines/outbound/reports/`
- **What good looks like:** short, about the trigger, one approved fact that helps, an easy way out
- **What bad looks like:** fake personalization, flattery, claims that aren't approved facts, volume for its own sake

## Approval
`mefw outbound approve <id>` blocks a message that doesn't mention the trigger, stock flattery, unapproved claims, banned language, sensitive-data requests and missing required text. A human sends it from their own tool, within `daily_send_limit`, and runs `mefw outbound sent`. Level 2 sending only after a strong track record and with limits (Section 9.2).

## Escalate to a human when
- A reply is anything but a clear yes or no (the operator records the outcome)
- Someone opts out: `mefw outbound outcome <id> opted_out` suppresses the company and withdraws its open drafts at once
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Qualified reply rate and meetings booked. Not messages sent (Section 9.2).

## Quality checks
Receipts, Compliance, Right buyer, Approval. Section 12.2.

## Write-back
Drafts, the report, one activity log entry per draft and per run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 15); `--max` per run (default 5); `daily_send_limit` for sends.

## Change log
- {today}: created at Level 1
