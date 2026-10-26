---
name: mefw-lead
description: Log new inquiries or update leads (replied, toured, won, lost) for a MarketingEngineer client from plain words, then import them. Use when the operator says a lead came in, they replied to someone, or a deal closed.
---

# Log leads and outcomes

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Where leads go

The lead sheet is the source of truth, because each import reads the whole file:

- the file in `lead_sheet` under `[operator]` in `profile/mefw.toml`, if it's set
- otherwise the `leads` file under `[schedule.inbox]` (default `inbox/leads.csv`)

If neither exists, ask where they keep the sheet and offer to add `[operator]` with `lead_sheet = "<path>"` to the profile. Column names and allowed values come from the sheet's header and its guide (a `lead-sheet-guide.md` beside it, if there is one). Keep its date format: `2026-10-20 14:30`, in the client's local time.

## Never write personal data

No names, emails, phone numbers, company contacts or addresses in the sheet, even if the operator says them. Leads are known only by their ID (`L-019`). If the operator wants to remember who someone is, that stays in their own tool.

## Steps

1. Work out each change from what the operator said: a new lead (next free ID, created time, source, segment), a reply (first response time, last outbound, outbound count, stage), or an outcome (`Won` or `Lost` with closed date and a few words of reason). If the time, source or segment is unclear, ask. Don't guess an outcome.
2. Show the rows as they'll be written, old values beside new for updated rows, and ask to confirm.
3. Write them to the sheet. Change only the cells you showed.
4. If the sheet isn't the inbox file, copy it there. Then run `import-csv <inbox file>`. Re-importing unchanged rows adds nothing.
5. Say what the ledger took in. If a new lead has no first reply yet, offer to draft one: `drafts make --agent first-response-drafter`, then `/mefw-review`.

If the lead asked not to be contacted, set `Do Not Contact` to `yes` as well as importing, so no draft is ever made for them.
