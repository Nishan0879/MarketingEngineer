# Growth Cockpit — example-coworking — Week 2026-W43

_Built 2026-10-25 by `growth-cockpit` (Level 0) from the ledger, customer truth, experiment briefs and the activity log._

## North star

Signed memberships and office leases: **3** this week (last week: 1, 4-week trend: down, 8 vs. 15 the 4 weeks before)

This week by segment: Members (B2C) 3.

## Wins

- 3 committed (Members (B2C)): `L-1022`, `L-1043`, `L-1197`

## Losses

- 2 went cold (Office leases (B2B)) — we stopped following up too early: `L-1204`, `L-1281`
- 1 went cold (Members (B2C)) — prospect wrote last and we never answered: `L-1048`
- 1 went cold (Members (B2C)) — we stopped following up too early: `L-1060`
- 1 went cold (Office leases (B2B)) — prospect wrote last and we never answered: `L-1069`
- 1 went cold (Members (B2C)) — first response came too late: `L-1074`
- EXP-example-coworking-001 Answer every inquiry within 1 hour: 37% vs. 42% (-11% is at or below the kill bar (0%))
- Members (B2C): inquiry → meeting 35% (n=26) vs. 44% the 4 weeks before
- Office leases (B2B): inquiry → meeting 25% (n=12) vs. 30% the 4 weeks before

## What changed

- **Market / customers:** Office leases (B2B): Parking came up 15 times in the last 30 days (about 9.3 per period before). Rising: internet (Members (B2C), 8 vs. ~4.7); parking (Office leases (B2B), 15 vs. ~9.3); parking (No matching segment, 6 vs. ~1.3); flexible terms (No matching segment, 3 vs. ~0.7).
- **Competitors:** 4 mentions (Members (B2C)) `notes:N-5317`, `notes:N-5179`, `notes:N-5030`, `L-1091 (lost reason)`; 5 mentions (Office leases (B2B)) `notes:N-5079`, `notes:N-5371`, `notes:N-5316`, `notes:N-5007` and 1 more
- **Funnel** (last 4 complete weeks vs. the 4 before): Members (B2C): inquiry → meeting 35% (n=26) vs. 44% (n=34); first response 31 min vs. 45 min; Office leases (B2B): inquiry → meeting 25% (n=12) vs. 30% (n=23); first response 7.2 h vs. 40 min.

## Recommended next tests

1. **EXP-example-coworking-002 Reserved parking offer for office tours** (Office leases (B2B)), brief at `experiments/active/EXP-example-coworking-002-reserved-parking-offer-for-office-tours.md`. Customer fit (_/5) + Evidence strength (_/5) + Business impact (_/5) − Effort (_/5) = _
2. **Prospect wrote last and we never answered** (Members (B2C), 25 leads). Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents. Priority score: Customer fit _/5 + Evidence strength _/5 + Business impact _/5 − Effort _/5.
3. **We stopped following up too early** (Office leases (B2B), 12 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked. Priority score: Customer fit _/5 + Evidence strength _/5 + Business impact _/5 − Effort _/5.

Running or approved:

- EXP-example-coworking-001 Answer every inquiry within 1 hour: 37% vs. 42%, day 64, suggested kill (-11% is at or below the kill bar (0%))

## Agent errors

- None this week.

## Decisions needed from the operator

- [ ] Verdict for EXP-example-coworking-001: suggested **kill** (-11% is at or below the kill bar (0%)). `mefw experiment close EXP-example-coworking-001 --verdict ...`
- [ ] Approve or drop EXP-example-coworking-002 (Reserved parking offer for office tours): `mefw experiment approve EXP-example-coworking-002`
- [ ] Review 11 new insight record(s) in `customer-truth/insights/` (keep, reword or retire): competitor--members, competitor--offices, flexibility--offices, flexibility--unassigned, growth--offices, internet--members, location--members, parking--offices, parking--unassigned, price--members, price--offices
- [ ] Members (B2C): only 47% of leads past the sales cycle have an outcome. Ask the client to close them out with reasons.
- [ ] Office leases (B2B): only 48% of leads past the sales cycle have an outcome. Ask the client to close them out with reasons.
