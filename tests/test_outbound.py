import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.cli import main
from mefw.core import cockpit, scheduler
from mefw.core.errors import SensitiveData
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.outbound import drafts as outbound, signals

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

FACTS = """
[facts.terms]
text = "Private offices come on 6- or 12-month terms."
approved_by = "Owner"
approved_on = "2026-10-01"
"""

PLAYBOOK = """
[outbound]
fresh_days = 40
recontact_days = 90
min_score = 4.0
daily_send_limit = 2
must_include = ["Reply STOP and we won't write again.", "1 Main Street"]

[outbound.icp]
employees = [3, 60]
locations = ["Springfield"]

[outbound.events.hiring]
label = "Hiring"
weight = 3
subject = "Room for {company}"
body = "Hi, I saw that {company} {detail}. {fact:terms} Reply STOP and we won't write again. 1 Main Street"

[outbound.events.new_business]
label = "New business"
weight = 1
subject = "Hello {company}"
body = "Hi, I saw that {company} {detail}. Reply STOP and we won't write again. 1 Main Street"

[outbound.events.funding]
label = "Funding"
weight = 2
"""

HEADER = ["Company", "Event", "Date", "Detail", "Source", "Employees", "Location", "Industry", "Account ID"]
ROWS = [
    ["Acme Design", "hiring", "2026-10-20", "is hiring 4 designers", "https://jobs.test/acme", "12", "Springfield", "", ""],
    ["Big Corp", "hiring", "2026-10-21", "is hiring 40 staff", "", "500", "Springfield", "", ""],
    ["Far Away Ltd", "hiring", "2026-10-21", "is hiring 2 people", "", "10", "Shelbyville", "", ""],
    ["Old News Co", "hiring", "2026-08-01", "is hiring 3 people", "", "10", "Springfield", "", ""],
    ["Small Start", "new_business", "2026-10-23", "just opened, call 555 123 4567", "", "", "Springfield", "", ""],
    ["Cash Inc", "funding", "2026-10-22", "raised a seed round", "", "20", "Springfield", "", ""],
    ["Mystery", "rebrand", "2026-10-22", "changed its name", "", "20", "Springfield", "", ""],
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        (self.root / "profile/approved-facts.toml").write_text(FACTS)
        (self.root / "engines/outbound/playbook.toml").write_text(PLAYBOOK)
        self.ws = Workspace(self.root)

    def csv(self, rows=ROWS, header=HEADER):
        f = self.tmp / "triggers.csv"
        with f.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        return f

    def cli(self, *args):
        return main(["outbound", args[0], "--client", str(self.root), *args[1:]])


class WatchScoreTests(Base):
    def test_import_company_data_only(self):
        rep = signals.import_triggers(self.ws, self.csv(), AS_OF)
        self.assertEqual((rep["new"], rep["unknown_events"]), (6, {"rebrand": 1}))
        small = next(t for t in signals.triggers(self.ws) if t["account"] == "Small Start")
        self.assertNotIn("555", small["detail"])
        self.assertEqual(signals.import_triggers(self.ws, self.csv(), AS_OF)["new"], 0)  # append-only, no repeats
        with self.assertRaises(SensitiveData):
            signals.import_triggers(self.ws, self.csv([["x"] * 10], HEADER + ["Contact Email"]), AS_OF)

    def test_score_fit_reason_now(self):
        signals.import_triggers(self.ws, self.csv(), AS_OF)
        ranked, dropped = signals.score(self.ws, AS_OF)
        self.assertEqual([a["account"] for a in ranked], ["Acme Design", "Cash Inc"])
        self.assertEqual(dropped, {"poor fit": 2, "no recent trigger": 1, "score below min_score": 1})
        acme = ranked[0]
        self.assertEqual((acme["fit"], acme["reason"]), (1.0, 1.0))
        self.assertEqual(acme["now"], 0.88)  # five whole days of forty gone
        # Two weeks on, the same trigger is weaker.
        later, _ = signals.score(self.ws, AS_OF + timedelta(days=14))
        self.assertLess(later[0]["score"], acme["score"])

    def test_suppression(self):
        signals.import_triggers(self.ws, self.csv(), AS_OF)
        signals.suppress(self.ws, "Acme Design", "existing customer", "op", AS_OF)
        ranked, dropped = signals.score(self.ws, AS_OF)
        self.assertNotIn("Acme Design", [a["account"] for a in ranked])
        self.assertEqual(dropped["suppressed"], 1)
        with self.assertRaisesRegex(ValueError, "Say why"):
            signals.suppress(self.ws, "Cash Inc", " ", "op", AS_OF)
        signals.suppress(self.ws, "Acme Design", "they asked us back", "op", AS_OF, lift=True)
        self.assertIn("Acme Design", [a["account"] for a in signals.score(self.ws, AS_OF)[0]])


class DraftTests(Base):
    def setUp(self):
        super().setUp()
        signals.import_triggers(self.ws, self.csv(), AS_OF)
        self.cli("drafts", "--at", AS_OF.isoformat())
        self.id = "O-20261025-acme-design"

    def test_drafts_tied_to_the_trigger(self):
        ids = sorted(m["id"] for _, m, _ in outbound.all_drafts(self.ws))
        self.assertEqual(ids, [self.id])  # funding has no template: noted, not drafted
        _, meta, body = outbound.find(self.ws, self.id)
        self.assertEqual(meta["blocking_issues"], [])  # "4" and "1 Main Street" are theirs and required, not claims
        self.assertIn("I saw that Acme Design is hiring 4 designers.", body)
        self.assertIn("No names or contact details", body)
        report = (self.root / "engines/outbound/reports/2026-10-25.md").read_text()
        self.assertIn("| Acme Design | ", report)
        self.assertIn(self.id, report)
        # One draft in flight per company: running again writes nothing new.
        self.cli("drafts", "--at", (AS_OF + timedelta(days=1)).isoformat())
        self.assertEqual(len(outbound.all_drafts(self.ws)), 1)

    def edit(self, old, new):
        path = outbound.find(self.ws, self.id)[0]
        path.write_text(path.read_text().replace(old, new))

    def test_approval_checks(self):
        self.edit("I saw that Acme Design is hiring 4 designers.", "Big fan of your work!")
        with self.assertRaises(ValueError) as e:
            outbound.approve(self.ws, self.id, "op", AS_OF)
        self.assertIn("no longer mentions the trigger", str(e.exception))
        self.assertIn("pretends to know the reader", str(e.exception))
        self.edit("Big fan of your work!", "I saw that Acme Design is hiring 4 designers. First month free.")
        with self.assertRaisesRegex(ValueError, "receipts"):
            outbound.approve(self.ws, self.id, "op", AS_OF)
        self.edit(" First month free.", "")
        self.edit(" 1 Main Street", "")
        with self.assertRaisesRegex(ValueError, "1 Main Street"):
            outbound.approve(self.ws, self.id, "op", AS_OF)
        self.edit("write again.", "write again. 1 Main Street")
        meta = outbound.approve(self.ws, self.id, "op", AS_OF)
        self.assertEqual(meta["status"], "approved")

    def test_send_limit_outcomes_and_opt_out(self):
        outbound.approve(self.ws, self.id, "op", AS_OF)
        # Fill today's limit with two other sent drafts.
        for n in (1, 2):
            p = self.root / f"engines/outbound/drafts/O-20261025-other{n}.md"
            p.write_text(outbound.find(self.ws, self.id)[0].read_text()
                         .replace(self.id, f"O-20261025-other{n}").replace('"acme-design"', f'"other{n}"')
                         .replace('status = "approved"', 'status = "sent"\nsent_at = "2026-10-25T09:00:00+00:00"'))
        with self.assertRaisesRegex(ValueError, "daily_send_limit"):
            outbound.mark_sent(self.ws, self.id, "op", AS_OF)
        outbound.mark_sent(self.ws, self.id, "op", AS_OF + timedelta(days=1))
        with self.assertRaisesRegex(ValueError, "Outcome must be"):
            outbound.record_outcome(self.ws, self.id, "maybe", "op", AS_OF)
        self.cli("outcome", self.id, "opted_out", "--at", (AS_OF + timedelta(days=2)).isoformat())
        self.assertIn("acme-design", signals.suppressed(self.ws))
        lrn = outbound.learn(self.ws, AS_OF + timedelta(days=3))
        self.assertEqual(lrn["by_event"]["Hiring"]["sent"], 3)
        self.assertEqual(lrn["by_event"]["Hiring"]["opted_out"], 1)

    def test_suppressing_withdraws_open_drafts(self):
        self.cli("suppress", "Acme Design", "--reason", "client asked", "--at", AS_OF.isoformat())
        self.assertEqual(outbound.find(self.ws, self.id)[1]["status"], "withdrawn")
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            outbound.approve(self.ws, self.id, "op", AS_OF)

    def test_learn_counts_qualified_not_volume(self):
        outbound.approve(self.ws, self.id, "op", AS_OF)
        outbound.mark_sent(self.ws, self.id, "op", AS_OF)
        outbound.record_outcome(self.ws, self.id, "replied", "op", AS_OF + timedelta(days=1))
        outbound.record_outcome(self.ws, self.id, "meeting", "op", AS_OF + timedelta(days=3))
        lrn = outbound.learn(self.ws, AS_OF + timedelta(days=4))
        self.assertEqual({k: lrn["total"][k] for k in ("sent", "replied", "qualified", "meetings")},
                         {"sent": 1, "replied": 1, "qualified": 1, "meetings": 1})
        self.assertEqual(lrn["by_band"]["7 and up"]["qualified_rate"], 1.0)

    def test_cockpit_scheduler_and_level(self):
        ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(ledger.close)
        decisions = cockpit.build(self.ws, ledger, AS_OF + timedelta(days=1))["decisions"]
        self.assertTrue(any("Review 1 outbound draft(s)" in d for d in decisions))
        self.assertIn("outbound-drafter", scheduler.ORDER)
        self.assertEqual(scheduler.command_for(self.ws, "outbound-drafter", AS_OF)[0][:2], ["outbound", "drafts"])
        log = [json.loads(ln) for ln in self.ws.log_path.read_text().splitlines() if ln.strip()]
        self.assertTrue(any(e["agent"] == outbound.AGENT and e["action"] == "outbound_draft" for e in log))


class LevelTests(Base):
    def test_level_zero_drafts_nothing(self):
        toml = self.root / "profile/mefw.toml"
        text = toml.read_text()
        start = text.index("[agents.outbound-drafter]")
        toml.write_text(text[:start] + text[start:].replace("level = 1", "level = 0", 1))
        signals.import_triggers(self.ws, self.csv(), AS_OF)
        self.assertEqual(self.cli("drafts", "--at", AS_OF.isoformat()), 2)
        self.assertEqual(outbound.all_drafts(self.ws), [])


if __name__ == "__main__":
    unittest.main()
