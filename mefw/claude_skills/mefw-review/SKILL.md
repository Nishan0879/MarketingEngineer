---
name: mefw-review
description: Walk the operator through pending MarketingEngineer drafts one at a time (first replies, follow-ups, outbound, search, content, creative) to approve, edit or reject. Use when the operator wants to review or clear drafts.
---

# Review drafts

## Running mefw

- **Client workspace:** `$MEFW_CLIENT` if it's set. Otherwise the current folder if it has `profile/mefw.toml`, else a folder one level down or one level up that has one. If you find more than one, ask which client.
- **Command:** if `python3 -c "import mefw"` works, run `python3 -m mefw <command> --client <workspace>`. Otherwise find the MarketingEngineer checkout, the folder holding `mefw/cli.py` (`$MEFW_HOME`, or a sibling such as `../marketingengineer`), and run `PYTHONPATH=<checkout> python3 -m mefw <command> --client <workspace>`. If you can't find it, ask where it is.
- mefw never sends a message, publishes a page or spends money, and neither do you here. The operator sends from their own tools.

## Order

First replies to new leads first (speed to first response matters most), then follow-ups, then outbound, search, content and creative. The operator can name one engine or one draft ID to start there.

| Engine | List | Draft files | Approve | Reject |
|---|---|---|---|---|
| First replies (`F-`) and follow-ups (`D-`) | `drafts list` | `engines/conversion/drafts/<id>.md` | `drafts approve <id>` | `drafts reject <id> --reason "..."` |
| Outbound (`O-`) | `outbound list` | `engines/outbound/drafts/<id>.md` | `outbound approve <id>` | `outbound reject <id> --reason "..."` |
| Search (`S-`) | `search list` | `engines/search/drafts/<id>.md` | `search approve <id>` | none: leave it, or delete the file if the operator says so |
| Content (`C-`) | `content list` | `engines/content/briefs/<id>.md` | `content approve <id>` | none |
| Creative | `creative list` | `engines/creative/plans/<id>.md` | `creative approve <id>` | none |

## For each draft

1. Read the draft file. Show the operator the message as it stands, then in one or two lines: who it's for (the lead's ID, segment and channel, never a name), why it was drafted, and any failed check (lines marked ❌, or `{answer needed: ...}`).
2. Ask: approve, edit, reject or skip. Wait for the answer. Never approve or reject on your own judgment.
3. **Edit:** change only the message section of the file, as the operator words it. A price, number or promise must come from `profile/approved-facts.toml`; if it isn't there, say so and ask them to add the fact or drop the claim. Show the edited text, then approve only if they say so.
4. **Approve:** run the approve command. If it refuses, show the reason in plain words and go back to step 3. Add `--quote-permission` only when the operator confirms the quoted person agreed.
5. **Reject:** ask for a short reason if they didn't give one, and pass it with `--reason`. It becomes a correction the drafting agent learns from.
6. Move to the next draft.

## When you're done

Say how many were approved, edited, rejected and skipped. Approved drafts still need sending: the operator copies each into their own tool (email, Peerspace, Google Voice and so on), sends it, then you record it with `drafts sent <id>` or `outbound sent <id>` once they confirm it went out. Never mark a draft sent before they say it was sent.
