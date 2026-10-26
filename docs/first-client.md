# Running a first real client

This is the order to set up a new client, from the first conversation to the first monthly report. It follows the 30-day plan in Section 18 of the operating manual. Every command takes `--client DIR`, or set `MEFW_CLIENT=DIR` once.

Nothing here sends a message, publishes a page or spends money. Agents observe and draft; you approve and send.

## Before you start: agree on the data

Settle these with the client in the first meeting. Write the answers in `profile/business-profile.md` (Section 16).

1. **Where leads are tracked.** A CRM (HubSpot, Pipedrive), coworking software (Nexudus, OfficeRnD), a shared spreadsheet, or an inbox. `mefw onboard presets` lists the tools with a preset and how to export from each. If leads live only in an inbox, start a sheet from [lead-sheet-template.csv](../examples/onboarding/lead-sheet-template.csv).
2. **What leaves their system.** Only IDs, dates, stages, sources and outcomes. Names, emails and phone numbers stay in their tool; the importer refuses those columns. Agree where exports are kept (the `inbox/` folder of the client workspace, which git ignores) and who can see them.
3. **How outcomes come back.** Who marks a lead won or lost, and with what reason. Without outcomes the audit, experiments and reports can't say what worked.
4. **Who approves what.** Facts, drafts, published content and ad tests. Get turnaround times.
5. **Segments.** Coworking members and office tenants buy differently. Ask what they call each group and how long each takes to decide.
6. **Budget.** Any ad spend cap per test, and tool costs. You set budgets in the ad tool; the system only checks plans against the cap.

## Week 1: audit

**1. Create the workspace.**

```bash
python -m mefw init ../client-acme --client-id acme
export MEFW_CLIENT=../client-acme
```

Put it in its own private git repository (Section 17.2). [examples/coworking/](../examples/coworking/) has a filled-in profile and playbooks for a coworking space that also leases offices; copy what fits.

The workspace comes with Claude Code slash commands in `.claude/skills/`. Open Claude Code there and `/mefw-today` tells you what needs you, `/mefw-lead` logs leads from plain words, and `/mefw-review` takes you through drafts. Each one shows you the change before it makes it.

**2. Write the profile.** Fill in `profile/business-profile.md`, `voice.md` and `compliance.md`. In `profile/mefw.toml` set the client's name, timezone, north star, `cycle_days` and segments (`[segments.*]`, with the segment values from their tool under `match`).

**3. Approve the facts.** Add each fact the client signs off to `profile/approved-facts.toml`: prices, terms, opening hours, what's included, how to book a tour. Each needs `approved_by` and `approved_on`, and `topics` so first replies can answer questions about it. Agents may claim nothing else. Start with five to ten; a draft that needs a missing fact says so instead of guessing.

**4. Map their export.** Get a CSV export of the last 6 to 12 months of leads, with the client's personal-data columns left out if possible.

```bash
python -m mefw onboard check inbox/leads.csv            # picks the closest preset and shows what it reads
python -m mefw onboard apply inbox/leads.csv --preset hubspot --stage "Tour Done=meet"
```

`check` shows which column each field comes from, what's missing, which columns look like personal data (never imported), unreadable dates, repeated or blank IDs, and every stage value with where it lands in the funnel (Attract, Inquire, Qualify, Meet, Commit, Retain). Fix what it flags in the export, or place a stage with `--stage "NAME=STAGE"`. `apply` writes the mapping into `profile/mefw.toml`, keeps the old file as `profile/mefw.toml.<time>.bak`, and checks that every row reads before it keeps the change. Nothing is imported yet.

Exports differ by account and version. If a column isn't matched, rename it in the export or map it by hand under `[adapters.csv.columns]`. A stage that only one segment uses goes under `[segments.X.stages]`.

**5. Import.**

```bash
python -m mefw import-csv inbox/leads.csv               # add --activities inbox/activities.csv if there's a message log
python -m mefw import-signals inbox/notes.csv            # call notes, tour notes, reviews, inquiry messages
```

Re-importing the same file adds nothing, so a fresh full export each week is fine. The import warns about stages it can't place; add them and import again.

**6. Run the baseline.**

```bash
python -m mefw audit-cold --as-of 2026-11-01T12:00
python -m mefw truth
python -m mefw cockpit
```

The cold-inquiry audit is usually the first finding worth showing the client: how fast leads get a reply, how many never do, and how many go quiet with too few follow-ups, by segment. Customer truth groups what customers say into themes, with their words.

## Week 2: build growth memory

**7. Confirm what's true.** Read `customer-truth/what-the-market-is-telling-us.md` with the client. Open each insight record under `customer-truth/insights/` and set its status to `confirmed` (or leave it `observed`). Only confirmed insights with enough evidence feed content and ad tests.

**8. Write the playbooks.** Each engine reads its own playbook from `engines/<engine>/playbook.toml`; copy the coworking examples and change them:

- `conversion/playbook.toml`: first-reply topics and keywords, follow-up templates per reason and segment, the opt-out line.
- `content/playbook.toml`: angles and channels.
- `search/playbook.toml`: brand terms, places, listings, the prompts to ask AI assistants.
- `outbound/playbook.toml`: the ideal company (size, area, industry), trigger types and templates, the daily send limit.
- `creative/playbook.toml`: the budget cap for one test, angles, channel and stop rules.

Leave out the engines the client hasn't chosen; their agents have nothing to do.

## Week 3: ship one machine

**9. Pick one engine and run it at Level 1.** For most coworking clients that's conversion: first replies and follow-ups.

```bash
python -m mefw drafts make
python -m mefw drafts list
python -m mefw drafts approve <id>        # reruns every check on the text as you edited it
python -m mefw drafts export              # CSV for the client's own sending tool
python -m mefw drafts sent <id>           # once it's actually sent
```

Reject a bad draft with `--reason`; the reason becomes a correction the next drafts follow.

**10. Start one experiment.** `mefw experiment new` with a hypothesis, segment and metric, then `approve` and `start`. Its decision rule is locked when you approve it.

**11. Put it on a schedule.** Set the jobs you want under `[schedule]` in `profile/mefw.toml`, drop each new export in `inbox/`, and call `mefw run-due` every 15 minutes from cron (see the README). `mefw schedule` shows what ran.

## Week 4: prove a result

**12. Review weekly.** The cockpit (`cockpit/YYYY-MM-DD.md`) lists the decisions waiting on you: drafts to review, briefs to write, tests to close, imports gone stale. Record outcomes as they happen, or let the next export carry them.

**13. Report to the client.** `mefw report make`, edit it, then `mefw report approve` for the HTML copy to send. It asks the client for what's missing, such as leads with no won/lost result.

**14. Write the case study.** "Audited the client's growth. Found an insight they didn't know about. Turned it into an engine or experiment, which produced a result. Here's what we learned and what's next." Choose the next experiment.

## After the first month

- Start each day with `/mefw-today` in Claude Code, or `mefw today` in a terminal.
- `mefw quality` shows each agent's numbers. `mefw promote <agent> --check` shows what's left before Level 2; promotion always needs your sign-off.
- `mefw pause` stops everything at once; `mefw resume` starts it again.
- `mefw log verify` proves the activity log hasn't been edited.

## If something goes wrong

| Message | What to do |
|---|---|
| `Field '...' looks like personal data` | That column can't be mapped. Map the lead's ID instead. |
| `... is missing mapped columns` | The export changed. Run `mefw onboard check` on it and `apply` again. |
| `Unrecognized timestamp` | Export dates as `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`. |
| `Unmapped stages: ...` | Add the names to `[funnel.stages]`, or use `--stage` on `onboard apply`. |
| `Stopped: ...` | A guardrail stopped an agent: the kill switch, its level, its daily cap or a broken log. `mefw status` says which. |
