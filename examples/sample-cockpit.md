# Growth Cockpit — example-coworking — Week 2026-W43

_Built 2026-10-25 by `growth-cockpit` (Level 0) from the ledger, customer truth, experiment briefs and the activity log._

## North star

Signed memberships and office leases: **5** this week (last week: 1, 4-week trend: down, 7 vs. 13 the 4 weeks before)

This week by segment: Members (B2C) 5.

## Wins

- 5 committed (Members (B2C)): `L-1042`, `L-1062`, `L-1195`, `L-1266`, `L-1293`
- Office leases (B2B): inquiry → meeting 35% (n=17) vs. 21% the 4 weeks before

## Losses

- 1 lost (Office leases (B2B)) — no parking for the team: `L-1022`
- 3 went cold (Members (B2C)) — never got a response from us: `L-1013`, `L-1091`, `L-1245`
- 2 went cold (Members (B2C)) — prospect wrote last and we never answered: `L-1031`, `L-1202`
- 2 went cold (Members (B2C)) — first response came too late: `L-1071`, `L-1283`
- 2 went cold (Office leases (B2B)) — first response came too late: `L-1213`, `L-1224`
- 1 went cold (Members (B2C)) — we stopped following up too early: `L-1194`
- 1 went cold (Office leases (B2B)) — we stopped following up too early: `L-1277`
- EXP-example-coworking-001 Answer every inquiry within 1 hour: 30% vs. 34% (-10% is at or below the kill bar (0%))
- Members (B2C): inquiry → meeting 29% (n=35) vs. 39% the 4 weeks before

## What changed

- **Market / customers:** Office leases (B2B): Parking came up 11 times in the last 30 days (about 6.3 per period before). Rising: quiet space for calls (Members (B2C), 7 vs. ~4.7); parking (Office leases (B2B), 11 vs. ~6.3); parking (No matching segment, 4 vs. ~2.3).
- **Competitors:** 10 mentions (Members (B2C)) `notes:N-5142`, `notes:N-5143`, `notes:N-5049`, `notes:N-5248` and 6 more; 2 mentions (Office leases (B2B)) `notes:N-5262`, `L-1308 (lost reason)`
- **Funnel** (last 4 complete weeks vs. the 4 before): Members (B2C): inquiry → meeting 29% (n=35) vs. 39% (n=38); first response 41 min vs. 17.4 h; Office leases (B2B): inquiry → meeting 35% (n=17) vs. 21% (n=19); first response 33 min vs. 3.0 h.

## Recommended next tests

1. **EXP-example-coworking-002 Reserved parking offer for office tours** (Office leases (B2B)), brief at `experiments/active/EXP-example-coworking-002-reserved-parking-offer-for-office-tours.md`. Customer fit (_/5) + Evidence strength (_/5) + Business impact (_/5) − Effort (_/5) = _
2. **First response came too late** (Members (B2C), 31 leads). Cut speed to first response for one channel (start with the slowest) and compare its inquiry → meeting rate with the baseline period. Priority score: Customer fit _/5 + Evidence strength _/5 + Business impact _/5 − Effort _/5.
3. **We stopped following up too early** (Office leases (B2B), 14 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked. Priority score: Customer fit _/5 + Evidence strength _/5 + Business impact _/5 − Effort _/5.

Running or approved:

- EXP-example-coworking-001 Answer every inquiry within 1 hour: 30% vs. 34%, day 64, suggested kill (-10% is at or below the kill bar (0%))

## Agent errors

- None this week.

## Decisions needed from the operator

- [ ] Verdict for EXP-example-coworking-001: suggested **kill** (-10% is at or below the kill bar (0%)). `mefw experiment close EXP-example-coworking-001 --verdict ...`
- [ ] Approve or drop EXP-example-coworking-002 (Reserved parking offer for office tours): `mefw experiment approve EXP-example-coworking-002`
- [ ] Review 10 new insight record(s) in `customer-truth/insights/` (keep, reword or retire): competitor--members, competitor--offices, flexibility--offices, growth--offices, location--members, parking--offices, parking--unassigned, price--members, price--offices, quiet--members
- [ ] Review 10 pending re-engagement draft(s): `mefw drafts list`
- [ ] Members (B2C): only 33% of leads past the sales cycle have an outcome. Ask the client to close them out with reasons.
- [ ] Office leases (B2B): only 49% of leads past the sales cycle have an outcome. Ask the client to close them out with reasons.
