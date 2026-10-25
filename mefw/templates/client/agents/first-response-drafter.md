# Agent: first-response-drafter

## Job
Draft the first reply to every new inquiry nobody has answered yet, answering the lead's questions from approved facts only, so a human can send a correct reply fast.

## Engine
conversion

## Autonomy level
1 — starting level (drafts only; a human approves and sends)

## Trigger / schedule
Several times a day, or on demand with `mefw drafts make`. Speed to first response is what this agent exists to improve, so run it often.

## Inputs
- The lead/outcome ledger, and the messages (signals) linked to each lead
- `engines/conversion/playbook.toml`: the `[first_response]` template and its `topics`
- `profile/approved-facts.toml`, using each fact's `topics` to know which questions it answers
- `rules/banned-language.md`, `rules/corrections.md`

## Filters
- Only open leads with no reply from us, that haven't booked a meeting and haven't gone cold (past the cold line they belong to `re-engagement-drafter`)
- Skip leads that opted out
- Skip leads whose messages mention a complaint, legal issue, refund or a request to stop; route them to a human (Section 11.5)
- Skip leads that already have a pending or approved draft from any agent

## Steps
1. List eligible leads, longest waiting first.
2. Find which playbook topics the lead asked about in their messages.
3. Fill the `[first_response]` template for the lead's segment. `{answers}` becomes the approved facts tagged with those topics.
4. For a topic with no usable fact (missing, unapproved, expired or for another segment), add an `{answer needed: <topic>}` line instead of guessing. It blocks approval until the operator writes the answer.
5. Check the draft: facts approved and in date for the segment, no claim outside approved facts, no banned language, no request for sensitive data, required text present.
6. Write the draft to `engines/conversion/drafts/` as `pending`, with the topics asked, the lead's message and the checks shown.

## Output
- **Format:** Markdown draft with front matter
- **Destination:** `engines/conversion/drafts/F-YYYYMMDD-<lead>.md`
- **What good looks like:** answers what they asked in plain words, one clear next step (usually booking the visit), every claim from an approved fact
- **What bad looks like:** a guessed price or availability, generic filler that ignores the question, pressure

## Approval
Every draft. The operator fills any `{answer needed: ...}` lines, edits if needed and approves, or rejects with a reason. Approval reruns the checks on the edited text. Nothing is sent by the system.

## Escalate to a human when
- A lead asks something no approved fact answers (shown in the draft as `answer needed`)
- A lead's messages mention a complaint, legal issue, refund, or a request to stop
- A template uses a fact that is missing, unapproved or expired
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Speed to first response, and inquiry → meeting rate (Section 9.3).

## Quality checks
Receipts, Compliance, Approval (checked in code); Voice, Customer words, Right buyer (operator at approval). Section 12.2.

## Write-back
Drafts; rejections go to `rules/corrections.md`; `mefw drafts sent` records the first outbound touch on the lead; one activity log entry per draft.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 50); `--max` per run (default 10); one first response per lead.

## Promotion
Section 9.3 allows Level 2 for first responses using approved facts once accuracy is proven. By the Section 11.2 default that is 20 approvals in a row without edits over at least 2 weeks, a written playbook of exactly what it may send, and operator sign-off in this change log. Drafts with an `answer needed` line can never be sent unattended. `mefw drafts record` shows progress.

## Change log
- {today}: created at Level 1
