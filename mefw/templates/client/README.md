# client-{client_id}

Marketing memory for {client_id}, run with MarketingEngineerFW.

## Status
- **Enabled engines:** conversion (cold-inquiry audit, Level 0)
- **Kill switch:** `mefw status` shows it; `mefw pause` / `mefw resume` change it.

## Where things are
- `profile/` business profile, approved facts, voice, compliance, and `mefw.toml` (machine settings)
- `agents/` job specs; an agent without a spec does not run
- `engines/conversion/audits/` cold-inquiry audits
- `logs/agent-activity.jsonl` append-only, hash-chained activity log (`mefw log verify`)
- `data/ledger.db` lead and outcome ledger (lead IDs only, no personal data; not committed)

## Tools
Lead tracking: _not set yet_
