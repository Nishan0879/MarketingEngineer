# Changelog

## 0.9.0 — 2026-10-25
- Content engine (Section 9.1). New Level 1 agent `content-brief-writer` and `mefw content briefs`. It writes a brief per confirmed insight once it has enough evidence (`[content] min_evidence`, default 5), and refreshes it at most every `refresh_days` (default 60). A brief has:
  - what customers said, in their words, with contact details scrubbed
  - the approved facts usable for the segment
  - angles and a section per channel from `engines/content/playbook.toml`
  - a tracking tag for links
- `mefw content approve` checks every written asset for unapproved claims, banned language, sensitive data and required text. It blocks quotations unless the operator confirms permission with `--quote-permission`.
- `mefw content published` records where each approved asset went live. `mefw content results` compares inquiries carrying the brief's tag with the rest of the segment.
- Leads gain an optional `campaign` field. Map it in the CSV adapter. Existing ledgers are migrated on open.
- Front matter supports inline tables.
- The cockpit lists briefs waiting to be written and approved briefs not yet published.
- Scheduler: `content-brief-writer` runs after customer truth.

## 0.8.0 — 2026-10-25
- Per-agent quality numbers (Section 14.3), from `mefw quality` and in the cockpit:
  - runs, and failed, blocked, duplicate and late actions
  - escalations and serious errors
  - for drafting agents: approval without edits, correction time, unsupported claims caught, and correction rate against the error budget
- Levels are recorded in `control/autonomy.json` and enforced by the runner. The profile sets only the starting level, capped at 1. An unreadable file fails closed.
- `mefw promote` raises an agent one level, and only when the Section 11.2 default bar is met. Level 2 needs a written playbook. Level 3 needs a budget cap and the client's approval. Each change goes to the activity log and the agent's change log.
- `mefw demote` records a serious error (Section 11.3) and drops the agent one level.
- Error budget: an agent at Level 2+ drops back to Level 1 when its correction rate over its last 20 drafts goes above `max_correction_rate`. It is enforced by `mefw quality` and the new scheduled `quality-check` job.
- The cockpit lists demotions and agents over their error budget.

## 0.7.0 — 2026-10-25
- Monthly client report (Section 18 week 4; answers the Section 22 question of what the client sees). It is separate from the internal cockpit.
- New Level 0 agent `client-reporter`. It drafts `reports/YYYY-MM-client-report.md` with:
  - results against last month
  - inquiry handling per segment, with sample sizes and small samples marked
  - confirmed insights only, in the customer's words with source references removed
  - experiments closed and running
  - follow-up sent and quiet leads that came back
  - what's next, and what would help from the client
- `mefw report approve` refuses placeholders, draft wording, source references, agent names and contact details. It writes a printable HTML copy. An approved report is never overwritten.
- Scheduler: `monthly <day> HH:MM` schedules, and `client-reporter` runs last in the order.
- Optional `[client] name` for the report title.

## 0.6.0 — 2026-10-25
- Scheduled runs (Section 19, "Scheduled workflows"; answers the Section 22 question of where agents run day to day). A `[schedule]` table in the profile sets each job's schedule in the client's timezone (`every 2h`, `daily 07:00`, `weekly mon 07:00`).
- `mefw run-due`, called every 15 minutes by cron or a systemd timer, runs each job whose latest slot hasn't run, in a fixed order, through the same commands and guardrails as running them by hand. Missed slots aren't replayed. A failed slot is retried once. A lock prevents overlapping runs. Every attempt is logged.
- Scheduled imports from `[schedule.inbox]` (default `inbox/`, gitignored), skipped when the exports haven't changed.
- `mefw schedule` shows last and next runs. The cockpit flags jobs that have fallen two runs behind and a `[schedule]` table it can't read.

## 0.5.0 — 2026-10-25
- New Level 1 agent `first-response-drafter` (Section 9.3): drafts the first reply to every open inquiry nobody has answered, longest waiting first, until the lead goes cold.
- It answers the questions a lead asked only from approved facts tagged with that topic. Topics and their keywords live in `[first_response.topics]` of the playbook; facts get an optional `topics` list.
- A question with no usable fact becomes an `{answer needed: <topic>}` line that blocks approval until the operator writes the answer, so the agent never guesses. Receipts still apply to what the operator writes.
- Shared approval queue (`engines/conversion/queue.py`) for every drafting agent. Track records toward Level 2 are kept per agent, and a lead has at most one draft in flight across agents.
- `mefw drafts make` runs both drafting agents (`--agent` picks one). The cockpit lists first responses waiting and how long the oldest lead has waited.

## 0.4.0 — 2026-10-25
- Approved facts as data (`profile/approved-facts.toml`): approver, date, optional expiry and segments.
- Opt-outs: consent events in the ledger from a do-not-contact column or `mefw opt-out`.
- Conversion engine's first Level 1 agent, `re-engagement-drafter`. It drafts follow-ups for leads that went cold on our side from the operator's playbook and approved facts, and checks them for unapproved claims, expired facts, banned language, sensitive-data requests and required opt-out text. It skips opted-out, decided and escalation-worthy leads.
- Approval queue: approve (rechecks edited text and records edits), reject (adds a correction), export, and mark sent (records the outbound touch).
- Track record toward Level 2 per Section 11.2; the cockpit lists pending drafts and flags when the bar is met.
- CLI errors print a message instead of a traceback.

## 0.3.0 — 2026-10-25
- Funnel metrics shared by experiments and the cockpit. Only mature leads are counted, and every value has its sample size.
- Experiments (Section 13): briefs with TOML front matter, a proposed → approved → running → completed/stopped lifecycle, decision criteria locked by hash at approval, before/after and holdout comparisons, suggested verdicts once the minimum window and volume are met, operator-only verdicts, and a lessons file.
- Weekly growth cockpit memo (Sections 8.3 and 15): north star, wins, losses, what changed, recommended tests, agent errors and operator decisions.
- New Level 0 agents `experiment-tracker` and `growth-cockpit` with job specs; `[north_star]` in the profile.

## 0.2.0 — 2026-10-25
- Segments: each can have its own cycle length, stage names and audit thresholds (Section 7). The cold-inquiry audit now reports each segment separately.
- Customer truth (Section 8.2): signal store (append-only, scrubbed), signals CSV adapter, keyword theme tagging, rising/falling themes, objections, won vs. lost themes with confidence labels, open questions.
- Writes `what-the-market-is-telling-us.md`, dated snapshots, and insight records (Section 8.6) that are created once and only appended to afterwards.
- New Level 0 agent `customer-truth-analyst` with job spec.
- Example profile and sample data for a coworking space that also leases offices.

## 0.1.0 — 2026-10-25
- Core: runner that enforces activity log integrity, kill switch, job spec, autonomy level, daily caps, dedupe and error escalation in code.
- Lead/outcome ledger with append-only events and outcome recording.
- CSV adapter with config-driven column mapping and personal-data refusal.
- Conversion engine: cold-inquiry audit (Level 0).
- Client workspace template following Section 17.2.
