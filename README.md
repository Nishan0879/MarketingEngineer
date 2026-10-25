# MarketingEngineerFW

A reusable system for running marketing for lead-based businesses with AI agents, overseen by one operator. The operating manual is [MarketingEngineerFW.md](MarketingEngineerFW.md); this repository is the code that enforces it.

**Built so far (v0.8):** the core guardrails, a lead/outcome ledger with opt-outs, approved facts, segments with their own funnels, customer truth, experiment briefs with locked decision rules, the weekly growth cockpit, two conversion drafting agents held for approval (first replies to new inquiries and re-engagement of cold leads), CSV adapters for any lead-tracking tool and for notes/messages/reviews, the conversion engine's first job, a cold-inquiry audit, a scheduler that runs it all on its own, a monthly report for the client, and per-agent quality numbers with promotion and demotion checked in code. Client-agnostic: a new client is a new workspace plus a config file.

## Quick start

Python 3.11+, no dependencies.

```bash
python examples/make_sample.py examples                 # fictional coworking + office-leasing data
python -m mefw init ../client-demo --client-id demo      # new client workspace (Section 17.2 layout)
sed 's/{client_id}/demo/' examples/coworking/mefw.toml > ../client-demo/profile/mefw.toml   # example profile
cp examples/coworking/approved-facts.toml ../client-demo/profile/
cp examples/coworking/playbook.toml ../client-demo/engines/conversion/
cp examples/coworking/search-playbook.toml ../client-demo/engines/search/playbook.toml
cp examples/coworking/outbound-playbook.toml ../client-demo/engines/outbound/playbook.toml
cp examples/coworking/creative-playbook.toml ../client-demo/engines/creative/playbook.toml
python -m mefw import-csv --client ../client-demo examples/sample_leads.csv --activities examples/sample_activities.csv
python -m mefw import-signals --client ../client-demo examples/sample_signals.csv
python -m mefw audit-cold --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw truth --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw experiment new --client ../client-demo --name "Reply within an hour" --segment members \
    --metric inquiry_to_meeting --hypothesis "If ..., then ..., because ..." --at 2026-08-20T09:00
python -m mefw experiment approve --client ../client-demo EXP-demo-001 --at 2026-08-21T09:00
python -m mefw experiment start --client ../client-demo EXP-demo-001 --at 2026-08-22T09:00
python -m mefw experiment measure --client ../client-demo --at 2026-10-25T12:00
python -m mefw drafts make --client ../client-demo --at 2026-10-25T12:00
python -m mefw search import --client ../client-demo examples/sample_search_queries.csv --period-end 2026-10-24
python -m mefw search analyze --client ../client-demo --at 2026-10-25T12:00
python -m mefw search drafts --client ../client-demo --at 2026-10-25T12:00
python -m mefw outbound import --client ../client-demo examples/sample_outbound_triggers.csv
python -m mefw outbound drafts --client ../client-demo --at 2026-10-25T12:00
python -m mefw creative plan --client ../client-demo --at 2026-10-25T12:00   # plans once you confirm an insight
python -m mefw cockpit --client ../client-demo --as-of 2026-10-25T12:00
python -m mefw status --client ../client-demo
```

What comes out: [a cold-inquiry audit](examples/sample-audit.md), [the customer truth file](examples/sample-customer-truth.md), [an insight record](examples/sample-insight-record.md), [an experiment brief](examples/sample-experiment-brief.md), [a monthly client report](examples/sample-client-report.md), [a first-response draft](examples/sample-first-response.md), [a re-engagement draft](examples/sample-draft.md), [a content brief](examples/sample-content-brief.md), [a search report](examples/sample-search-report.md), [a search draft](examples/sample-search-draft.md), [an outbound report](examples/sample-outbound-report.md), [an outbound draft](examples/sample-outbound-draft.md), [a creative test plan](examples/sample-creative-plan.md), [creative test results](examples/sample-creative-results.md) and [a weekly cockpit memo](examples/sample-cockpit.md).

For a real client, edit `profile/mefw.toml` in their workspace: segments, stage names, themes in their customers' words, and the column names of their exports. [examples/coworking/mefw.toml](examples/coworking/mefw.toml) is a filled-in example for a coworking space that also leases offices.

## Segments

A business can sell to groups that buy very differently, like coworking members (decide in days) and companies leasing offices (decide in months, with more stages). Each segment in `[segments.*]` has its own cycle length, its own extra stage names (for example `Proposal Sent` counts as a meeting for offices) and its own audit thresholds. The audit and customer truth report each segment separately, because a learning applies to the segment it came from (Section 8.1).

## Customer truth

`mefw truth` reads imported notes, messages and reviews plus the lost reasons from recorded outcomes, tags them with the client's themes, and writes:

- `customer-truth/what-the-market-is-telling-us.md`: the headline, rising and falling themes with short quotes, objections, what won leads talked about compared with lost ones, and open questions
- `customer-truth/updates/YYYY-MM-DD.md`: a dated copy
- `customer-truth/insights/<theme>--<segment>.md`: an insight record (Section 8.6) for each theme with enough evidence. Created once as `observed`; later runs only append dated evidence, so the operator's edits are never overwritten

Themes are matched by keyword for now. The tagger is one small interface (`tags(text) -> list[str]`), so a model-based tagger can replace it later without touching the analysis.

## What the core enforces in code

Every agent action goes through `mefw/core/runner.py`. In order:

| Check | Spec | What happens |
|---|---|---|
| Activity log verifies | 11.4 rule 8 | Hash-chained JSONL; any edit or deletion stops all agents |
| Kill switch | 11.3 | Client, engine or agent paused in `control/pause.json` → refused. A corrupt file counts as paused |
| Job spec exists | 10 | No spec file → the agent doesn't run |
| Autonomy level | 11.1 | `observe` 0, `draft` 1, `act` 2, `spend` 3 |
| Daily cap | 11.6 | `max_actions_per_day` per agent |
| Dedupe | 11.6 | Each action has a key. Done → skipped. A failed or unfinished `act`/`spend` is never retried automatically; the agent is paused and the operator decides |
| Repeated errors | 11.5 | `max_consecutive_errors` failures in a row pause the agent and log an escalation |

Every outcome, including refusals, is written to `logs/agent-activity.jsonl`.

The ledger (`data/ledger.db`, SQLite) stores lead history as events that database triggers stop anyone from editing or deleting. It keeps the lead's ID from the client's tool, never names or contact details: the importer refuses columns that look like personal data and scrubs emails and phone numbers from free text. Outcomes through Commit (won, lost with a reason, reopened) are events too.

## Experiments

`mefw experiment new` writes a brief in `experiments/active/` following the Section 13.1 template, with its settings in TOML front matter: segment, optional channels, one metric, the comparison (`before_after` against the same segment before the start, or `holdout` against other channels over the same dates), the minimum window and volume, and the keep/kill bars.

The Section 13.2 rules are enforced:

- **Criteria are locked at approval.** `approve` stores a hash of the decision rule and logs it. If the rule changes later, measurement says so and suggests no verdict.
- **Only mature leads count.** A rate only includes leads old enough to have reached the stage it measures, so recent leads don't look like a drop.
- **No verdict before the window.** Until the minimum days and leads are met, the suggestion is `inconclusive`.
- **The operator decides.** `measure` (agent `experiment-tracker`, Level 0) suggests keep, iterate or kill and appends a line to the brief. `close` records the operator's verdict, moves the brief to `experiments/completed/`, and adds the lesson to `experiments/lessons.md`.

Metrics: `inquiry_to_meeting`, `meeting_to_commit`, `inquiry_to_commit`, `first_response_minutes`, `responded_within_1h`.

## Drafts (conversion engine, Level 1)

`mefw drafts make` runs two drafting agents. Use `--agent` to run one.

- **`first-response-drafter`** writes the first reply to each open inquiry nobody has answered yet, longest waiting first. It finds which questions the lead asked (topics with keywords in `[first_response.topics]` of the playbook) and answers them only with approved facts tagged with that topic (`topics = ["price"]` on a fact). A question with no usable fact is never guessed: the draft gets an `{answer needed: Price}` line that blocks approval until you write the answer. Once a lead passes the cold line it's the next agent's job.
- **`re-engagement-drafter`** writes a message for each lead the cold audit marks as ours to fix: never answered, waiting on us, slow first reply, or too few follow-ups. Each one fills the operator's template for that reason and segment.

Templates live in `engines/conversion/playbook.toml`, and **approved facts only** come from `profile/approved-facts.toml` (each with who approved it, when, an optional expiry, segments and topics). A lead has at most one draft in flight across both agents.

Before a draft reaches the operator it is checked:

- Every fact is approved, in date and allowed for the segment.
- Every claim (a price, a number, "free", "guaranteed", "best") comes from one of those facts.
- No banned language (`rules/banned-language.md`).
- No request for sensitive data.
- The required opt-out text is present.

Leads are skipped, not drafted, when they opted out (from the export's do-not-contact column or `mefw opt-out`), already committed or were lost, or wrote something a human should handle, such as a complaint, a legal threat or a refund request.

Nothing is sent by the system:

- `approve` reruns the checks on the text as edited and records whether it was edited.
- `reject --reason` adds a row to `rules/corrections.md`.
- `export` writes a CSV for the client's own sending tool.
- `sent` records the outbound touch on the lead, so later audits and experiments see it.

`mefw drafts record` tracks the Section 11.2 bar for Level 2 for each agent: 20 approvals in a row without edits over at least 2 weeks. The cockpit flags it when it's met, and lists first responses still waiting with how long the oldest lead has waited. Promotion still needs your sign-off.

## Content briefs (content engine, Level 1)

The content engine (Section 9.1) turns one customer insight into posts for several channels, and only once the insight has shown it resonates. `mefw content briefs` (agent `content-brief-writer`) writes a brief for each insight record you've set to `confirmed` or `acted on` that has at least `min_evidence` signals (default 5) and no brief in the last `refresh_days` (default 60). It doesn't write the posts. It gives whoever does (you, the founder or a writing model) what they need:

- the insight, and what customers said, in their words, with contact details scrubbed
- the approved facts usable for that segment, and nothing else to claim
- the angles and per-channel guidance from `engines/content/playbook.toml`, with an empty section per channel
- a tracking tag (`mefw-<insight>`) to put in every link as `utm_campaign`

Briefs go to `engines/content/briefs/C-YYYYMMDD-<insight>.md`. Write in the channel sections you want to publish, then run `mefw content approve <id>`. Every written section goes through the same checks as drafts: claims must come from approved facts for the segment, and banned phrases, requests for sensitive data and missing required text are blocked. A quotation that looks like a customer's words is also blocked unless you pass `--quote-permission`, because the engine never invents or borrows testimonials.

You publish it yourself, then record it with `mefw content published <id> --channel linkedin --url <link>`. Map your lead tool's campaign or UTM column (`campaign = "UTM Campaign"` under `[adapters.csv.columns]`). `mefw content results` then counts the inquiries that came in with each brief's tag since it was published, and how many reached a meeting or were won, against the rest of the segment. The cockpit asks you to write briefs that are waiting and to publish approved ones.

Schedule it with `content-brief-writer = "weekly mon 06:40"`. Settings live under `[content]` in the profile.

## Search visibility (search engine, Levels 0 and 1)

The search visibility engine (Section 9.5) makes the business easy to find and easy to cite in search, local search and AI assistants. It works from `engines/search/playbook.toml`, which lists the buyer-intent words, the pages that exist and the topics each covers, the listings, and the questions to put to AI assistants ([example](examples/coworking/search-playbook.toml)). Topics are the first-response topics plus any the playbook adds.

1. **Import search data.** Export the Queries table from Search Console for the last 28 days, then run `mefw search import queries.csv --period-end 2026-10-24` (add `--pages pages.csv` for the Pages table). Each period becomes a snapshot that's never overwritten. Queries are scrubbed of contact details.
2. **Weekly report.** `mefw search analyze` (agent `search-analyst`, Level 0) writes `engines/search/reports/YYYY-MM-DD.md` ([sample](examples/sample-search-report.md)) with:
   - **Opportunities:** non-brand queries ranked by buyer intent × relevance × ranking distance × volume. Each gets a next step: improve the page that covers its topic, or write a new one.
   - **Questions buyers ask that no page answers:** topics from inquiries, call and tour notes, reviews and other signals in the buyer's own words, over the last 90 days.
   - **Listings:** each listing's fields against the approved fact they should match, and listings not checked for `listing_check_days`.
   - **AI assistants:** how often each assistant mentioned or cited the business, and the checks due this month.
   - **Results:** clicks over recent snapshots, inquiries from `search_channels` and how many reached a meeting, and how published drafts' queries moved.
3. **Drafts.** `mefw search drafts` (agent `search-page-drafter`, Level 1) writes `engines/search/drafts/S-YYYYMMDD-<topic>.md` ([sample](examples/sample-search-draft.md)), one per topic, at most every `refresh_days`. Each draft says where the change goes and lists the queries and the buyers' words. It has an FAQ entry answered only from approved facts tagged with the topic. A topic with no such fact gets `{answer needed: <topic>}`, which blocks approval until you write it.
4. **Approve and publish.** `mefw search approve <id>` runs the draft checks (claims, banned language, sensitive data, required text). It also blocks keyword stuffing (a search phrase used more than `max_query_repeats` times), review gating (asking only happy customers for reviews) and quotations that look like reviews, unless you pass `--quote-permission`. You put it on the site, then run `mefw search published <id> --url <link>`.
5. **AI assistant checks.** Ask each assistant the prompts in `[search.ai.prompts]` by hand once a month. Record each answer with `mefw search ai-record --assistant ChatGPT --prompt best_coworking --mentioned yes --cited <url>`. Nothing here calls a search engine or an assistant.

The cockpit asks you to review search drafts, publish approved ones, fix listings that disagree with approved facts, and run the AI checks that are due.

## Outbound signals (outbound engine, Level 1)

The outbound signal engine (Section 9.2) reaches companies with a real reason to care now. Its flow is Watch → Enrich → Score → Send → Learn. Everything client-specific is in `engines/outbound/playbook.toml`: the ICP, the trigger types and their weights, the message templates, the limits and the text the channel and region require ([example](examples/coworking/outbound-playbook.toml)).

1. **Watch.** Collect trigger events from wherever the client finds them, such as job boards, local news, a broker or the client's own list. Then run `mefw outbound import triggers.csv`. Each row is a company with an event type, a date, a few words of detail ("is hiring four designers") and a source link. The import keeps company data only: columns that look like personal data are refused, and text is scrubbed of contact details.
2. **Score.** Each company is scored on ICP fit × trigger weight × how recent the trigger is, from 0 to 10. Some companies are left out, with the reason counted in the report:
   - outside the ICP
   - no trigger in `fresh_days`
   - scoring under `min_score`
   - suppressed (opted out, an existing customer, or the client asked)
   - contacted in the last `recontact_days`
3. **Draft.** `mefw outbound drafts` (agent `outbound-drafter`) drafts a message for the best companies. It also writes `engines/outbound/reports/YYYY-MM-DD.md` ([sample report](examples/sample-outbound-report.md), [sample draft](examples/sample-outbound-draft.md)). A template may use `{company}`, `{detail}` and `{fact:key}` only, so the only personal touch is the real reason to get in touch.
4. **Approve.** `mefw outbound approve <id>` blocks:
   - a message that no longer mentions the trigger
   - stock flattery ("big fan of your work")
   - unapproved claims and banned language
   - requests for sensitive data
   - missing required text
5. **Send.** You pick the person in your own tool, send it, and run `mefw outbound sent <id>`. No more than `daily_send_limit` can be marked sent per day.
6. **Learn.** `mefw outbound outcome <id> replied|qualified|meeting|not_interested|opted_out|bounced|no_reply` records what came back. The report counts qualified replies and meetings by trigger type and by score band, never messages sent.

`opted_out`, or `mefw outbound suppress "Company" --reason "..."`, stops all contact at once. Open drafts are withdrawn, and marking anything else sent to that company is refused. The cockpit asks you to review drafts, send approved ones and record what came back.

## Creative testing (creative engine, Level 1)

The creative testing engine (Section 9.4) finds the angles and hooks that bring qualified inquiries and meetings at the lowest cost. It's set up in `engines/creative/playbook.toml`: the channel, the angles, the client's budget cap per test, the planned daily budget and length, and the stop rules ([example](examples/coworking/creative-playbook.toml)).

1. **Plan.** `mefw creative plan` (agent `creative-tester`) writes a test plan for each insight that has shown it resonates. That's the same bar as the content engine: confirmed or acted on, with at least `[content] min_evidence` signals. Each insight gets one test at a time. The plan ([sample](examples/sample-creative-plan.md)) has:
   - the hypothesis
   - the audience
   - customers' words
   - the facts that may be claimed
   - what won before for that audience
   - the budget plan and the stop rules
   - one section per variant, each with an angle and its own tag
2. **Approve.** Write at least two variants (headline, main text, visual, landing page), then run `mefw creative approve <id>`. It blocks:
   - claims that aren't approved facts
   - banned language and sensitive-data requests
   - missing required text
   - misleading imagery or urgency: before-and-after shots, actors posing as customers, fake countdowns or scarcity
   - invented results
   - quotations, unless you pass `--quote-permission`
   - a budget plan over `max_test_budget`
3. **Run.** You build the ads, put each variant's tag in the ad name and in `utm_campaign`, and set the budgets in the ad tool yourself. Nothing here spends or moves money; budget changes are Level 3 only, within caps. Then run `mefw creative start <id>`.
4. **Measure.** Import the ad platform's export to date with `mefw creative results-import <id> ads.csv`. The weekly run writes `engines/creative/results.md` ([sample](examples/sample-creative-results.md)). It combines spend with the tagged inquiries in the ledger to show cost per qualified inquiry, meeting and commitment for each variant. Click rate is only an early hint. It suggests:
   - **too early**, until every variant has `min_qualified` qualified inquiries
   - **keep** the variant with the lowest cost per meeting
   - **stop** a variant that has spent enough with no qualified inquiry
   - **pause** if spend goes over the approved budget
5. **Learn.** `mefw creative close <id> --winner a --lesson "..."` records the call. The winner goes into `engines/creative/winners.md`, and the next plan for that audience shows it.

The cockpit asks you to write plans, start approved tests, import results weekly, pause variants and close tests that have a winner.

## Running on a schedule

Each job's schedule lives in the `[schedule]` table of `profile/mefw.toml`, in the client's timezone: `"every 2h"`, `"every 30m"`, `"hourly"`, `"daily 07:00"`, `"weekly mon 07:00"` or `"monthly 1 08:00"`. Leave a job out to run it only by hand.

`mefw run-due` runs every job whose latest slot hasn't run yet:
- **Order.** Jobs run in a fixed order: import, customer truth, cold audit, first responses, re-engagement, experiments, quality check, cockpit, client report. Imports land before the agents that read them.
- **Same guardrails.** Each job is the same command you'd run by hand, so the kill switch, levels, caps and dedupe all still apply. A paused agent shows as `blocked`.
- **Missed slots.** These aren't replayed; only the latest slot runs.
- **Failures.** A failed slot is retried once on the next call, then left for you. Every attempt is in the activity log as a `scheduler` entry.
- **Overlap.** A lock stops two runs from overlapping.
- **Imports.** The import job reads the exports listed in `[schedule.inbox]`, `inbox/leads.csv` by default, and skips them if they haven't changed. `inbox/` is gitignored.
- **Status.** `mefw schedule` shows each job's last and next run. The weekly cockpit flags any job that has fallen two runs behind.

Call it every 15 minutes from whatever runs scheduled tasks on the operator's machine or server:

```
# cron (Linux/macOS): crontab -e
*/15 * * * * cd /path/to/MarketingEngineer && python -m mefw run-due --client /path/to/client-acme >> /path/to/client-acme/logs/run-due.txt 2>&1
```

```
# systemd timer: mefw-acme.service runs the same command; mefw-acme.timer has
[Timer]
OnCalendar=*:0/15
Persistent=true
```

On Windows, the scheduler needs `fcntl`, like the rest of the core, so run it under WSL with the cron line above. Exports stay on the machine that runs it. Nothing is sent from here, so an unattended run can only import, analyze and draft.

## Autonomy: quality, promotion and demotion

`mefw quality` shows each agent's numbers for the last 28 days (Section 14.3):
- runs, failures, blocked, duplicate and late actions, escalations and serious errors
- for drafting agents: the share approved without edits, typical correction time, unsupported claims caught before review, and the correction rate against the agent's error budget

The weekly cockpit carries the drafting agents' lines.

**Levels.** An agent's level in `profile/mefw.toml` is only where it starts, and only up to Level 1. Every change after that is recorded in `control/autonomy.json`, which is what the runner enforces. Each change is also written to the activity log and as a line in the agent's own change log.

- `mefw promote <agent> --reason ...` raises an agent one level, and only when the Section 11.2 default bar is met. `--check` shows what's missing.
  - Level 0 → 1: successful runs over 14+ days with no recent failures.
  - Level 1 → 2: 20 unedited approvals in a row over 2+ weeks, plus `--playbook` pointing at the written playbook.
  - Level 2 → 3: 30+ days at Level 2 with no serious error, plus `--budget-cap` and `--client-approval`.
- `mefw demote <agent> --kind ...` records a serious error and drops the agent one level (Section 11.3). The kinds are `false_claim`, `opted_out_contact`, `duplicate_send`, `budget_overrun` and `accuracy_complaint`. Use `--kind operator` to step it down for another reason.
- **Error budget.** An agent at Level 2 or above drops back to Level 1 when more than `max_correction_rate` (default 25%) of its last 20 decided drafts were edited or rejected. `mefw quality` enforces this, and so does the scheduled `quality-check` job.
- An unreadable `control/autonomy.json` fails closed: every agent is treated as Level 0.

## Monthly client report

`mefw report make` (agent `client-reporter`, Level 0) drafts the report the client reads, for the last complete month by default (`--month 2026-10` for another). It's separate from the cockpit and has no agent errors, lead IDs or internal decisions.

What it covers:
- **Results:** the north star against last month.
- **How inquiries were handled:** for each segment, time to first reply, share answered within an hour and share that went on to a meeting. Each rate shows its sample size, and small samples are marked.
- **What customers are telling us:** only insight records you've set to `confirmed` or `acted on`, with the customer's own words.
- **What we tested:** experiments closed that month and the ones still running.
- **Follow-up:** messages sent, and quiet leads that came back.
- **What's next,** and **what would help from the client**, such as leads with no won/lost result.

The draft goes to `reports/YYYY-MM-client-report.md`. Its front matter lists anything left out for you to decide on. Edit it, then run `mefw report approve`. Approval refuses a report that still contains placeholders, draft wording, source references, agent names or contact details. It writes `reports/YYYY-MM-client-report.html`, a clean page you can send or print to PDF. An approved report is never overwritten.

Schedule it with `client-reporter = "monthly 1 08:00"`.

## Growth cockpit

`mefw cockpit` (agent `growth-cockpit`, Level 0) writes `cockpit/YYYY-Www.md` using the Section 15 template:

- **North star:** from `[north_star]`, for this week, last week, and the four-week trend.
- **Wins and losses:** deals won and lost with reasons, leads that went cold this week for reasons on our side, experiments heading for keep or kill, and big funnel moves.
- **What changed:** the customer truth headline and rising themes, mentions of alternatives, and each segment's funnel over the last four complete weeks against the four before.
- **Recommended next tests:** proposed briefs, plus the top fixable leak per segment.
- **Agent errors:** failures, refusals and escalations from the activity log.
- **Decisions needed:** approvals, starts, verdicts, new insight records, paused agents and missing outcomes.

Memos are never overwritten. A rerun in the same week gets a suffix.

## Commands

| Command | Does |
|---|---|
| `init DIR --client-id ID` | Create a client workspace from the template |
| `import-csv FILE [--activities FILE]` | Import a lead export; re-importing the same file adds nothing |
| `import-signals FILE [--kind K]` | Import notes, messages or reviews; contact details are scrubbed |
| `truth [--as-of]` | Update customer truth and insight records (Level 0) |
| `experiment new \| list \| approve \| start \| stop \| measure \| close` | Run experiments; approve, start, stop and close are operator actions |
| `cockpit [--as-of]` | Write this week's growth cockpit memo (Level 0) |
| `drafts make \| list \| approve \| reject \| sent \| export \| record` | First-response and re-engagement drafts; everything but `make` is the operator's |
| `opt-out REF [--undo]` | Record that a lead asked not to be contacted |
| `outcome REF won\|lost\|reopened [--reason] [--at]` | Record an outcome by hand |
| `audit-cold [--as-of]` | Run the cold-inquiry audit (Level 0, contacts nobody) |
| `pause` / `resume [--engine E \| --agent A]` | Kill switch |
| `content briefs \| list \| approve \| published \| results` | Content briefs from confirmed insights; approving and recording what's published are the operator's |
| `search import \| analyze \| drafts \| list \| approve \| published \| ai-record` | Search visibility: search data, weekly report, FAQ drafts, AI assistant checks; approving, publishing and AI checks are the operator's |
| `outbound import \| drafts \| list \| approve \| reject \| sent \| outcome \| suppress` | Outbound signals: trigger import, scoring and drafts; approving, sending, outcomes and suppression are the operator's |
| `creative plan \| list \| approve \| start \| results-import \| results \| close` | Creative tests: plans and results by cost per meeting; approving, starting, importing and closing are the operator's, and budgets stay in the ad tool |
| `report make \| approve` | Draft the monthly client report; approve it to get the shareable HTML |
| `quality` | Per-agent quality numbers; enforces the error budget |
| `promote <agent>` / `demote <agent>` | Change an agent's level with your sign-off, or after a serious error |
| `run-due` | Run every scheduled job that's due (call it from cron) |
| `schedule` | Each scheduled job's last and next run |
| `status` | Pause state, agents, ledger and log health |
| `log verify \| render` | Check the hash chain, or write `logs/agent-activity.md` |

All take `--client DIR` (or `$MEFW_CLIENT`).

## Layout

```
mefw/core/          runner, kill switch, activity log, ledger, PII guard, workspace,
                    evidence rules, metrics, customer truth, experiments, cockpit
mefw/adapters/      lead-source interface, lead CSV adapter, signals CSV adapter
mefw/engines/conversion/   cold-inquiry audit, first-response and re-engagement drafts, the draft queue
mefw/engines/content/      content briefs, asset checks, publish log, results
mefw/engines/creative/     test plans, variant checks, ad results, cost per meeting, winners
mefw/engines/outbound/     trigger import, scoring, suppression, trigger-tied drafts, what came back
mefw/engines/search/       search snapshots, opportunity ranking, listings, AI checks, FAQ drafts
mefw/templates/client/   what `init` copies into a new client workspace
templates/          the spec's templates (agent spec, experiment brief, ...)
examples/           sample data generator, coworking profile, sample outputs
tests/              python -m unittest discover -s tests
```

## Adding a lead-tracking tool

Write a class with a `name` and a `records()` method that yields `LeadRecord`s (`mefw/adapters/base.py`), then pass it to `import_records`. The core doesn't change.
