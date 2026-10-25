# Agent: re-engagement-drafter

## Job
Draft a short, honest follow-up for each lead that went cold because of us, so a human can send it and win back pipeline we already paid for.

## Engine
conversion

## Autonomy level
1 — starting level (drafts only; a human approves and sends)

## Trigger / schedule
Weekly after the cold-inquiry audit, or on demand with `mefw drafts make`. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due.

## Inputs
- The lead/outcome ledger, and signals linked to each lead
- `engines/conversion/playbook.toml` (the operator's templates, one per reason a lead went cold)
- `profile/approved-facts.toml`
- `rules/banned-language.md`, `rules/corrections.md`

## Filters
- Only leads the cold audit marks as ours to fix: never answered, waiting on us, slow first reply, too few follow-ups
- Skip leads that opted out, committed, or were lost (promotional follow-up stops; Section 9.3)
- Skip leads whose messages mention a complaint, legal issue, refund or a request to stop; route them to a human (Section 11.5)
- Skip leads that already have a pending or approved draft

## Steps
1. List eligible leads, highest value first.
2. Fill the playbook template for the lead's reason and segment with approved facts.
3. Check the draft: facts approved and in date for the segment, no claim outside approved facts, no banned language, no request for sensitive data, required text present.
4. Write the draft to `engines/conversion/drafts/` as `pending`, with the reasons and checks shown.

## Output
- **Format:** Markdown draft with front matter
- **Destination:** `engines/conversion/drafts/D-YYYYMMDD-<lead>.md`
- **What good looks like:** short, owns the miss, offers one useful next step, every claim from an approved fact
- **What bad looks like:** fake urgency, invented availability or prices, pretending to remember the conversation

## Approval
Every draft. The operator edits the file if needed and approves, or rejects with a reason. Approval reruns the checks on the edited text. Nothing is sent by the system.

## Escalate to a human when
- A lead's messages mention a complaint, legal issue, refund, or a request to stop
- A template uses a fact that is missing, unapproved or expired
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Cold leads that reply or book a meeting after a sent draft.

## Quality checks
Receipts, Compliance, Approval (checked in code); Voice, Customer words, Right buyer (operator at approval). Section 12.2.

## Write-back
Drafts; rejections go to `rules/corrections.md`; `mefw drafts sent` records an outbound touch on the lead; one activity log entry per draft.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 25); `--max` per run (default 10); one draft per lead per cold spell.

## Promotion
Level 2 (sending on its own) needs, by the Section 11.2 default, 20 approvals in a row without edits over at least 2 weeks, a written playbook of exactly what it may send, and operator sign-off in this change log. `mefw drafts record` shows progress.

## Change log
- {today}: created at Level 1
