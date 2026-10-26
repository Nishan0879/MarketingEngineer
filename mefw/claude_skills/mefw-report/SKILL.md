---
name: mefw-report
description: Build the weekly growth cockpit memo or the monthly client report for a MarketingEngineer client, summarize it, and approve the client report when the operator says so. Use for weekly review or month-end reporting.
---

# Weekly memo and monthly report

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Weekly cockpit (for the operator)

1. Run `cockpit`. It writes `cockpit/YYYY-Www.md` and never overwrites an older memo.
2. Read the memo and give the operator: the north star this week against last week, wins and losses with reasons, the biggest leak per segment, and the decisions it lists. Five to ten lines.
3. Offer to work through the decisions one at a time.

## Monthly client report (for the client)

1. Run `report make` (add `--month YYYY-MM` for a month other than the last complete one). It writes `reports/YYYY-MM-client-report.md`.
2. Read it. Show the operator the results section and anything listed as left out in the front matter for them to decide on.
3. Help them edit it in their words. Every number must come from the draft; don't add results, quotes or claims it doesn't have.
4. Run `report approve` only when the operator says the report is ready. If approval refuses (placeholders, draft wording, agent names, contact details left in), show what to fix.
5. Give them the path of the HTML copy. They send it to the client themselves.
