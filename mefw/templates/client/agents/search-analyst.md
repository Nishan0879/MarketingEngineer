# Agent: search-analyst

## Job
Show where search can bring more qualified inquiries: rank search opportunities, list the questions buyers ask that no page answers, check listings against approved facts, track AI assistant mentions, and report search results.

## Engine
search

## Autonomy level
0 — starting level (reads and reports; changes nothing)

## Trigger / schedule
Weekly, after a fresh Search Console export. Set in `[schedule]` of `profile/mefw.toml`; `mefw run-due` runs it when due. On demand with `mefw search analyze`.

## Inputs
- Search snapshots imported with `mefw search import` (`engines/search/snapshots/`)
- `engines/search/playbook.toml` (intent terms, topics, pages, listings, AI prompts, search channels)
- Topics from `[first_response.topics]` in `engines/conversion/playbook.toml`
- Signals in the ledger (what buyers asked, last 90 days), and inquiries by channel
- `profile/approved-facts.toml`, AI checks in `engines/search/ai-checks.jsonl`

## Filters
- Brand searches are reported apart, never as opportunities
- Queries under `min_impressions` are left out

## Steps
1. Rank non-brand queries by buyer intent × relevance × ranking distance × volume.
2. For each, check whether a page in `[search.pages]` already covers its topic: improve it, or say a new one is needed.
3. List topics buyers raised that no page answers.
4. Check each listing: when it was last checked, and whether each field matches its approved fact.
5. Summarize AI assistant checks and list the ones due.
6. Report clicks over recent snapshots, inquiries from search channels, and how published drafts' queries moved.

## Output
- **Format:** Markdown report
- **Destination:** `engines/search/reports/YYYY-MM-DD.md`
- **What good looks like:** a short, ranked list a person can act on this week, tied to what buyers ask
- **What bad looks like:** keyword lists with no buyer behind them, vanity traffic

## Approval
None needed; it changes nothing. Its findings feed the search-page-drafter and the cockpit.

## Escalate to a human when
- A listing says something approved facts don't (the cockpit asks the operator to fix it)
- The run fails twice in a row (the runner pauses the agent automatically)

## Success metric
Inquiries from search that go on to a meeting (Section 9.5).

## Quality checks
Receipts, Evidence, Right buyer. Section 12.2.

## Write-back
The report, one activity log entry per run.

## Limits
`max_actions_per_day` in `profile/mefw.toml` (default 5).

## Change log
- {today}: created at Level 0
