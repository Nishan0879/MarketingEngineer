# Changelog

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
