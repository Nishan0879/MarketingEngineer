+++
id = "O-20261025-northwind-design"
status = "pending"
agent = "outbound-drafter"
account = "Northwind Design"
account_key = "northwind-design"
account_ref = ""
event = "hiring"
trigger = "c89ca7e393e5"
detail = "is hiring four designers in Example City"
score = 8.9
created = "2026-10-25T12:00:00+00:00"
facts = ["office_flex", "tour_booking"]
body_hash = "e0ca23fb43c38022"
blocking_issues = []
outcomes = []
+++
## Message

Subject: Room for the people Northwind Design is hiring

Hi,

I saw that Northwind Design is hiring four designers in Example City. Private offices are available on 6- or 12-month terms, and teams can move to a larger office as they grow. You can book a tour any weekday, and it takes about 20 minutes.

If the timing's wrong, just reply and we won't get in touch again.

Example Coworking, 1 Example Street, Example City

## Why this company, why now
- 2026-10-20: Hiring: is hiring four designers in Example City (https://jobs.example.test/northwind)
- Score 8.9: fit 1.0 (12 people, Example City), reason 1.0, right now 0.89
- In your tool: not linked

## Who to contact
Pick the right person in your own tool. No names or contact details are kept here.

## Checks
- ✅ tied to the trigger, no fake personalization, facts, claims, banned language, sensitive data, required text

_Edit the message if needed, then `mefw outbound approve O-20261025-northwind-design` or `mefw outbound reject O-20261025-northwind-design --reason "..."`. Send it from your own tool, then `mefw outbound sent O-20261025-northwind-design`._
