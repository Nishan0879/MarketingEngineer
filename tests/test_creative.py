import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.cli import main
from mefw.core import cockpit, scheduler
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.creative import plans, results

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
START = AS_OF + timedelta(days=2)

FACTS = """
[facts.tour]
text = "You can book a tour any weekday."
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.parking]
text = "Tenants can reserve parking next door."
approved_by = "Owner"
approved_on = "2026-10-01"
"""

PLAYBOOK = """
[creative]
channel = "Meta ads"
max_test_budget = 500
daily_per_variant = 10
days = 14
variants = 3
min_qualified = 3
qualified_stage = "qualify"

[creative.angles]
problem = "Say the problem their way."
objection = "Answer the worry."
proof = "Lead with a fact."
"""

INSIGHT = """## Insight: Parking
- **Status:** {status}
- **Segment:** All leads
- **Date observed:** 2026-10-01
- **Statement:** {statement}
- **Customer language:** "No parking for the team" (`notes:N-1`)
- **Evidence:** {n} signals
- **Confidence:** medium
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        (self.root / "profile/approved-facts.toml").write_text(FACTS)
        (self.root / "engines/creative/playbook.toml").write_text(PLAYBOOK)
        ins = self.root / "customer-truth/insights"
        ins.mkdir(parents=True, exist_ok=True)
        (ins / "parking--all.md").write_text(INSIGHT.format(status="confirmed", n=6,
                                                            statement="Teams that drive need parking."))
        (ins / "wifi--all.md").write_text(INSIGHT.format(status="confirmed", n=2, statement="Wifi matters."))
        (ins / "price--all.md").write_text(INSIGHT.format(status="observed", n=9, statement="Price."))
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)
        self.id = "T-20261025-parking--all"

    def plan(self, at=AS_OF):
        return main(["creative", "plan", "--client", str(self.root), "--at", at.isoformat()])

    def write(self, key, **fields):
        path, _, body = plans.find(self.ws, self.id)
        block = re.search(rf"### Variant {key}:.*?(?=### |## Checks)", body, re.S).group(0)
        new = block
        for name, text in fields.items():
            label = {"headline": "Headline", "text": "Main text", "visual": "Visual"}[name]
            new = re.sub(rf"^{label}: .*$", f"{label}: {text}", new, flags=re.M)
        path.write_text(path.read_text().replace(block, new))

    def good(self):
        self.write("A", headline="Your team drives in. Where do they park?",
                   text="Tenants can reserve parking next door.", visual="The garage next door on a weekday.")
        self.write("B", headline="Parking, sorted", text="Tenants can reserve parking next door. "
                                                          "You can book a tour any weekday.")


class PlanTests(Base):
    def test_plan_from_resonating_insight_only(self):
        self.assertEqual(self.plan(), 0)
        ids = [m["id"] for _, m, _ in plans.all_plans(self.ws)]
        self.assertEqual(ids, [self.id])
        _, meta, body = plans.find(self.ws, self.id)
        self.assertEqual([v["tag"] for v in meta["variants"]],
                         [f"mefw-cr-parking-all-1025-{k}" for k in "abc"])
        self.assertIn("$10 a day per variant for 14 days", body)
        self.assertIn("nothing here spends money", body)
        self.assertIn("Click rate is only an early hint", body)
        self.assertEqual(plans.written(meta, body), {})
        # One test per insight at a time.
        self.plan(AS_OF + timedelta(days=90))
        self.assertEqual(len(plans.all_plans(self.ws)), 1)

    def test_scheduled_and_level_zero(self):
        self.assertIn("creative-tester", scheduler.ORDER)
        self.assertEqual(scheduler.command_for(self.ws, "creative-tester", AS_OF)[0][:2], ["creative", "plan"])
        toml = self.root / "profile/mefw.toml"
        text = toml.read_text()
        i = text.index("[agents.creative-tester]")
        toml.write_text(text[:i] + text[i:].replace("level = 1", "level = 0", 1))
        self.assertEqual(self.plan(), 2)
        self.assertEqual(plans.all_plans(self.ws), [])


class ApprovalTests(Base):
    def setUp(self):
        super().setUp()
        self.plan()

    def test_needs_two_variants(self):
        self.write("A", headline="Where do they park?")
        with self.assertRaisesRegex(ValueError, "at least two variants"):
            plans.approve(self.ws, self.id, "op", AS_OF)

    def test_claims_misleading_and_quotes(self):
        self.good()
        self.write("C", headline="Limited time only: free parking",
                   text='"The best office I have ever rented, honestly." Real results.',
                   visual="Before-and-after photos with actors posing as members")
        with self.assertRaises(ValueError) as e:
            plans.approve(self.ws, self.id, "op", AS_OF)
        msg = str(e.exception)
        for expected in ("variant C: receipts", "Limited time only", "Real results", "Before-and-after",
                         "actors posing as members", "testimonial"):
            self.assertIn(expected, msg)
        self.assertNotIn("variant A", msg)

    def test_budget_cap(self):
        self.good()
        self.write("C", headline="See it for yourself", text="You can book a tour any weekday.")
        with self.assertRaisesRegex(ValueError, r"\$420 planned is over the \$400 cap"):
            (self.root / "engines/creative/playbook.toml").write_text(PLAYBOOK.replace("500", "400"))
            plans.approve(self.ws, self.id, "op", AS_OF)
        (self.root / "engines/creative/playbook.toml").write_text(PLAYBOOK.replace("max_test_budget = 500",
                                                                                   "max_test_budget = 0"))
        with self.assertRaisesRegex(ValueError, "set max_test_budget"):
            plans.approve(self.ws, self.id, "op", AS_OF)

    def test_approve_and_start(self):
        self.good()
        with self.assertRaisesRegex(ValueError, "approve it before"):
            plans.start(self.ws, self.id, "op", AS_OF)
        meta = plans.approve(self.ws, self.id, "op", AS_OF)
        self.assertEqual((meta["live_variants"], meta["planned_budget"]), (["a", "b"], 280.0))
        with self.assertRaisesRegex(ValueError, "start it before"):
            results.import_results(self.ws, self.id, self.tmp / "x.csv", AS_OF)
        self.assertEqual(plans.start(self.ws, self.id, "op", START)["status"], "running")


class ResultTests(Base):
    def setUp(self):
        super().setUp()
        self.plan()
        self.good()
        plans.approve(self.ws, self.id, "op", AS_OF)
        plans.start(self.ws, self.id, "op", START)

    def leads(self, tag, n, qualified, meetings, before=False):
        recs = []
        for i in range(n):
            at = START + timedelta(days=-5 if before else 1 + i % 5, hours=i)
            st = {}
            if i < qualified:
                st["Qualified"] = at + timedelta(hours=2)
            if i < meetings:
                st["Tour Booked"] = at + timedelta(days=1)
            recs.append(LeadRecord(ref=f"{tag[-1]}{i}{'x' if before else ''}", inquired_at=at, campaign=tag,
                                   stage_dates=st))

        class Src:
            name = "crm"

            def records(_):
                return recs
        import_records(self.ws, self.ledger, Src())

    def ads(self, a_spend, b_spend, name="ads.csv"):
        f = self.tmp / name
        f.write_text("Ad name,Amount spent,Impressions,Link clicks\n"
                     f"mefw-cr-parking-all-1025-a garage,{a_spend},10000,100\n"
                     f"MEFW-CR-PARKING-ALL-1025-B window,{b_spend},10000,300\n"
                     "brand always on,50,5000,20\n")
        return f

    def measure(self, days=12):
        return results.measure(self.ws, self.ledger, plans.find(self.ws, self.id)[1], START + timedelta(days=days))

    def test_judged_on_cost_not_clicks(self):
        self.leads("mefw-cr-parking-all-1025-a", 6, 4, 2)
        self.leads("mefw-cr-parking-all-1025-a", 3, 3, 3, before=True)  # came in before the test started
        self.leads("mefw-cr-parking-all-1025-b", 5, 3, 1)
        snap = results.import_results(self.ws, self.id, self.ads(120, 150), START + timedelta(days=10))
        self.assertEqual(snap["unmatched_rows"], 1)
        m = self.measure()
        a, b = m["rows"]
        self.assertEqual((a["inquiries"], a["qualified"], a["meetings"]), (6, 4, 2))
        self.assertEqual((a["cost_per_qualified"], a["cost_per_meetings"]), (30.0, 60.0))
        self.assertGreater(b["ctr"], a["ctr"])  # B wins on clicks...
        self.assertEqual(m["suggested"], "keep A")  # ...but A wins on cost per meeting
        report = results.render(self.ws, [m], START + timedelta(days=12))
        self.assertIn("| A (problem) | $120 | 1.0% | 6 | 4 | 2 | 0 | $30 | $60 | – |", report)

    def test_too_early_stop_early_and_over_budget(self):
        self.leads("mefw-cr-parking-all-1025-a", 4, 2, 1)
        results.import_results(self.ws, self.id, self.ads(60, 20), START + timedelta(days=4))
        self.assertEqual(self.measure(5)["suggested"], "too early")
        results.import_results(self.ws, self.id, self.ads(60, 200, "ads2.csv"), START + timedelta(days=9))
        m = self.measure(10)
        self.assertEqual(m["stop"], ["b"])  # spent over 3x A's cost per qualified ($30) with nothing
        self.assertEqual(m["suggested"], "keep A")
        self.assertEqual(m["notes"], [])
        results.import_results(self.ws, self.id, self.ads(100, 200, "ads3.csv"), START + timedelta(days=13))
        self.assertTrue(any("over the approved" in n for n in self.measure(14)["notes"]))
        with self.assertRaisesRegex(ValueError, "already imported"):
            results.import_results(self.ws, self.id, self.ads(1, 1, "ads4.csv"), START + timedelta(days=13))

    def test_close_records_winner_for_next_plan(self):
        self.leads("mefw-cr-parking-all-1025-a", 6, 4, 2)
        results.import_results(self.ws, self.id, self.ads(120, 150), START + timedelta(days=10))
        with self.assertRaisesRegex(ValueError, "lesson"):
            results.close(self.ws, self.ledger, self.id, "a", " ", "op", START + timedelta(days=12))
        with self.assertRaisesRegex(ValueError, "Winner must be"):
            results.close(self.ws, self.ledger, self.id, "c", "x", "op", START + timedelta(days=12))
        results.close(self.ws, self.ledger, self.id, "a", "Their words beat the objection.", "op",
                      START + timedelta(days=12))
        winners = (self.root / plans.WINNERS).read_text()
        self.assertIn("[all] T-20261025-parking--all variant A (problem): \"Your team drives in. Where do they park?\"",
                      winners)
        self.assertIn("$60 per meeting", winners)
        # The next plan for the same audience shows what won.
        self.plan(AS_OF + timedelta(days=70))
        later = [b for _, m, b in plans.all_plans(self.ws) if m["status"] == "plan"]
        self.assertEqual(len(later), 1)
        self.assertIn("What won before for this audience", later[0])

    def test_cockpit(self):
        self.leads("mefw-cr-parking-all-1025-a", 6, 4, 2)
        self.leads("mefw-cr-parking-all-1025-b", 5, 3, 1)
        results.import_results(self.ws, self.id, self.ads(120, 150), START + timedelta(days=10))
        decisions = cockpit.build(self.ws, self.ledger, START + timedelta(days=12))["decisions"]
        self.assertTrue(any("suggested **keep A**" in d for d in decisions))
        decisions = cockpit.build(self.ws, self.ledger, START + timedelta(days=20))["decisions"]
        self.assertTrue(any("Import this week's ad results" in d for d in decisions))


if __name__ == "__main__":
    unittest.main()
