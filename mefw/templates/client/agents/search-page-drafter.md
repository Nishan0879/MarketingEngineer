# Agent: search-page-drafter

## Job
Draft the FAQ entries and page changes that answer what buyers search for and ask, from approved facts only, so the business is easy to find and easy to cite.

## Engine
search

## Autonomy level
1 — starting level (drafts; a human approves and publishes)

## Trigger / schedule
Weekly, after the search-analyst. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due. On demand with `mefw search drafts`.

## Inputs
- The latest search snapshot and the ranking from the search-analyst
- Buyer questions in the ledger's signals (last 90 days)
- `engines/search/playbook.toml` (topics, pages, required text, limits)
- `profile/approved-facts.toml` (facts tagged with the topic)
- `rules/banned-language.md`, `rules/corrections.md`

## Filters
- Only topics buyers ask about (first-response topics plus `[search.topics]`)
- At most one draft per topic every `refresh_days`

## Steps
1. Group the ranked queries and unanswered buyer questions by topic, best first.
2. Write `engines/search/drafts/S-YYYYMMDD-<topic>.md`: where it goes (the page to improve, or new), the queries, buyers' words for language, and an FAQ entry answered only from approved facts tagged with the topic.
3. A topic with no usable fact gets `{answer needed: <topic>}`, which blocks approval.

## Output
- **Format:** Markdown draft with front matter
- **Destination:** `engines/search/drafts/`
- **What good looks like:** the question as buyers ask it, a plain answer from approved facts, the business's own view
- **What bad looks like:** keyword stuffing, pages built only for search engines, invented reviews

## Approval
`mefw search approve <id>` checks the FAQ: claims only from approved facts, no banned language, no request for sensitive data, required text present, no search phrase repeated past `max_query_repeats`, no review gating, and no quotation of a person unless the operator confirms permission (`--quote-permission`). A human puts it on the site and records it with `mefw search published`.

## Escalate to a human when
- No approved fact answers the topic (the draft says so and can't be approved)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Inquiries from search, and the drafted queries moving up after publishing (Section 9.5).

## Quality checks
Receipts, Compliance, Customer words, Right buyer, Approval. Section 12.2.

## Write-back
Drafts, one activity log entry per draft.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 10); `--max` per run (default 3).

## Change log
- {today}: created at Level 1
