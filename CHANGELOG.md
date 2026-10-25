# Changelog

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
