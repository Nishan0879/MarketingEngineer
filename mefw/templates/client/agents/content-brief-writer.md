# Agent: content-brief-writer

## Job
Turn a confirmed customer insight into a content brief: what customers keep saying, the facts we may claim, angles to try and a place to write for each channel, so one insight becomes several assets people respond to.

## Engine
content

## Autonomy level
1 — starting level (writes briefs; a human writes the assets, approves and publishes)

## Trigger / schedule
Weekly, after customer truth updates. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due. On demand with `mefw content briefs`.

## Inputs
- Insight records in `customer-truth/insights/` with Status `confirmed` or `acted on`
- `profile/approved-facts.toml` (only facts usable for the insight's segment)
- `engines/content/playbook.toml` (channels, guidance, angles, required text)
- `rules/banned-language.md`, `rules/corrections.md`

## Filters
- Only confirmed insights with at least `min_evidence` signals behind them ("only after the insight has shown it resonates")
- At most one brief per insight every `refresh_days`

## Steps
1. List confirmed insights with enough evidence and no recent brief.
2. Write `engines/content/briefs/C-YYYYMMDD-<insight>.md`. The brief holds the insight, the audience, customers' words (for language only), the facts that may be claimed, angles, one section per channel, and a tracking tag.
3. Refresh `engines/content/results.md`: inquiries carrying each published brief's tag, and how far they got.

## Output
- **Format:** Markdown brief with front matter
- **Destination:** `engines/content/briefs/`
- **What good looks like:** specific to one segment and one problem, in customers' words, every claim from an approved fact
- **What bad looks like:** generic thought leadership, invented stories, results or testimonials

## Approval
`mefw content approve <id>` checks every written asset: claims only from approved facts usable for the segment, no banned language, no request for sensitive data, required text present, and no quotation of a person unless the operator confirms permission (`--quote-permission`). A human publishes and records it with `mefw content published`.

## Escalate to a human when
- An insight has no approved facts for its segment (the brief says so)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Qualified inquiries attributed to content: inquiries carrying a brief's tag that go on to a meeting (Section 9.1).

## Quality checks
Receipts, Compliance, Customer words, Right buyer, Approval. Section 12.2.

## Write-back
Briefs, `engines/content/results.md`, one activity log entry per brief.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 10); `--max` per run (default 3).

## Change log
- {today}: created at Level 1
