+++
id = "T-20261025-parking--offices"
status = "closed"
agent = "creative-tester"
insight = "parking--offices"
segment = "offices"
created = "2026-10-25T12:00:00+00:00"
channel = "Meta ads"
variants = [{ "key" = "a", "angle" = "problem", "tag" = "mefw-cr-parking-offices-1025-a" }, { "key" = "b", "angle" = "objection", "tag" = "mefw-cr-parking-offices-1025-b" }, { "key" = "c", "angle" = "proof", "tag" = "mefw-cr-parking-offices-1025-c" }]
daily_per_variant = 25.0
days = 14
facts = ["office_flex", "office_parking", "tour_booking"]
approved_by = "operator"
approved_at = "2026-10-25T13:00:00+00:00"
live_variants = ["a", "b"]
planned_budget = 700.0
budget_cap = 1500.0
quote_permission = false
started_by = "operator"
started_at = "2026-10-27T09:00:00+00:00"
closed_by = "operator"
closed_at = "2026-11-09T13:00:00+00:00"
winner = "a"
lesson = "Naming the parking problem in their words beat answering it as an objection, despite fewer clicks."
final = { "a" = { "spend" = 312.4, "qualified" = 7, "meetings" = 4, "commits" = 1 }, "b" = { "spend" = 298.75, "qualified" = 5, "meetings" = 2, "commits" = 0 } }
+++
## Creative test: Parking (Office leases (B2B))

- **Hypothesis:** if the ads lead with what this audience keeps telling us (Teams that drive in pass on offices with nowhere to park), more of the people who click will become qualified inquiries and meetings, at a lower cost per meeting.
- **Insight:** `customer-truth/insights/parking--offices.md` (confidence low, 11 signals)
- **Audience:** Office leases (B2B), on Meta ads
- **Their words** (for language; don't quote anyone in an ad without their permission):
  - "No parking for the team"
  - "Needs somewhere quiet for calls; worried about noise in the open area. Asked whether we have reserved parking spots; we don't."
  - "Felt the monthly cost was too much compared with working from home. Loved the space but parking is a dealbreaker for their staff."
  - "Team is growing to 12 next year; needs room to expand. Main concern was parking. Team of six drives in and the garage is full by 9."
- **Facts you may claim** (nothing else: no prices, numbers, results or promises that aren't here):
  - `office_flex`: Private offices are available on 6- or 12-month terms, and teams can move to a larger office as they grow.
  - `office_parking`: Office tenants can reserve parking spaces in the garage next door.
  - `tour_booking`: You can book a tour any weekday, and it takes about 20 minutes.
- **Judged on:** cost per qualified inquiry, cost per meeting and cost per commitment. Click rate is only an early hint.
- **Budget plan:** $25 a day per variant for 14 days, $350 per variant. The total must stay under the cap of $1500. You set budgets in the ad tool yourself; nothing here spends money.
- **Stop rules:** call a winner once every variant has 5 qualified inquiries. Stop a variant early when it has spent three times the leader's cost per qualified inquiry with none.

## Variants

Write the variants you want to run (two at least). Put each variant's tag in its ad name and its `utm_campaign`, so results and inquiries can be matched to it. Leave a variant as it is to skip it.

### Variant A: problem

_Angle: Say the problem the way customers say it, then show it solved, using approved facts only._
_Tag: `mefw-cr-parking-offices-1025-a`_

Headline: Your team drives in. Where do they park?
Main text: Office tenants can reserve parking spaces in the garage next door. You can book a tour any weekday, and it takes about 20 minutes.
Visual: The garage entrance next door, shot on a weekday morning.
Landing page: /offices

### Variant B: objection

_Angle: Take the most common worry head on and answer it with an approved fact._
_Tag: `mefw-cr-parking-offices-1025-b`_

Headline: Parking sorted before you sign
Main text: Office tenants can reserve parking spaces in the garage next door. Private offices are available on 6- or 12-month terms, and teams can move to a larger office as they grow.
Visual: A real office in the building with the garage visible from the window.
Landing page: /offices

### Variant C: proof

_Left out._

## Checks

- ✅ variants A, B: facts, claims, banned language, sensitive data, required text, misleading imagery or urgency, no quotations
- ✅ budget: $700 planned, cap $1500
- Approved by operator on 2026-10-25. Build the ads with each variant's tag, set the budgets yourself, then `mefw creative start T-20261025-parking--offices`.
