import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.cli import main
from mefw.core import client_report, experiments, scheduler
from mefw.core.ledger import Ledger
from mefw.core.scheduler import Schedule
from mefw.core.workspace import Workspace

AS_OF = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
UTC = timezone.utc

INSIGHT = """## Insight: {title}
- **Status:** {status}
- **Segment:** All leads
- **Date observed:** 2026-10-20
- **Statement:** {statement}
- **Customer language:** "Is there parking? Call me on 555 123 4567" (`notes:N-1`)
- **Evidence:** 6 signals
- **Confidence:** medium
"""


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)
        recs = []
        for i in range(12):  # October: 12 inquiries, 4 won, all answered within 30 minutes
            at = d(f"2026-10-{i + 2:02d}T10:00")
            recs.append(LeadRecord(ref=f"o{i}", inquired_at=at, touches=[(at + timedelta(minutes=30), "out")],
                                   stage_dates={"Tour Booked": at + timedelta(days=2)} if i < 6 else {},
                                   outcome="won" if i < 4 else None,
                                   outcome_at=at + timedelta(days=10) if i < 4 else None))
        for i in range(5):  # September: 5 inquiries, 1 won, slow replies
            at = d(f"2026-09-{i + 2:02d}T10:00")
            recs.append(LeadRecord(ref=f"s{i}", inquired_at=at, touches=[(at + timedelta(hours=5), "out")],
                                   outcome="won" if i == 0 else None,
                                   outcome_at=at + timedelta(days=8) if i == 0 else None))
        self.leads(recs)
        ins = self.root / "customer-truth/insights"
        ins.mkdir(parents=True, exist_ok=True)
        (ins / "parking--all.md").write_text(INSIGHT.format(
            title="Parking", status="confirmed", statement="Prospects keep asking about parking."))
        (ins / "price--all.md").write_text(INSIGHT.format(
            title="Price", status="observed", statement="Price came up 5 times. Draft wording; operator to confirm."))

    def leads(self, records):
        class Src:
            name = "crm"

            def records(_):
                return records
        import_records(self.ws, self.ledger, Src())

    def make(self, *extra):
        return main(["report", "make", "--client", str(self.root), "--as-of", AS_OF.isoformat(), *extra])


class ClientReportTests(Base):
    def test_numbers_and_what_the_client_sees(self):
        data = client_report.build(self.ws, self.ledger, "2026-10", AS_OF)
        self.assertEqual((data["north_star"]["this"], data["north_star"]["before"]), (4, 1))
        (row,) = data["funnel"]
        self.assertEqual((row["inquiries"], row["inquiries_before"]), (12, 5))
        self.assertEqual(row["responded_within_1h"]["text"], "100%")
        self.assertEqual(row["responded_within_1h_before"]["text"], "0%")
        self.assertTrue(row["responded_within_1h_before"]["small"])
        md = client_report.render(data)
        self.assertIn("Prospects keep asking about parking.", md)
        self.assertNotIn("Price came up", md)            # draft insight held back
        self.assertNotIn("notes:N-1", md)                # no internal source references
        self.assertNotIn("555 123 4567", md)             # contact details scrubbed from quotes
        self.assertNotIn("o1", md.split())               # no lead IDs
        self.assertEqual(data["held_insights"], ["price--all"])

    def test_default_month_and_draft_then_approve(self):
        self.assertEqual(self.make(), 0)  # default: October, the last complete month
        path = self.root / "reports/2026-10-client-report.md"
        meta = client_report.load(path)[0]
        self.assertEqual(meta["status"], "draft")
        self.assertIn("price--all", meta["operator_notes"][0])

        path.write_text(path.read_text().replace("## Results", "Call us at 555 987 6543.\n\n## Results"))
        with self.assertRaises(ValueError):
            client_report.approve(self.ws, "2026-10", "op", AS_OF)
        path.write_text(path.read_text().replace("Call us at 555 987 6543.\n\n", "")
                        .replace("## Results", "See `notes:N-1` from first-response-drafter.\n\n## Results"))
        with self.assertRaises(ValueError) as e:
            client_report.approve(self.ws, "2026-10", "op", AS_OF)
        self.assertIn("first-response-drafter", str(e.exception))
        path.write_text(path.read_text().replace("See `notes:N-1` from first-response-drafter.\n\n", ""))

        self.assertEqual(main(["report", "approve", "--client", str(self.root), "--month", "2026-10",
                               "--as-of", AS_OF.isoformat()]), 0)
        html = (self.root / "reports/2026-10-client-report.html").read_text()
        self.assertIn("<h1>", html)
        self.assertIn("<table>", html)
        # Approved reports are left alone, by hand or on schedule.
        before = path.read_text()
        self.assertEqual(self.make(), 0)
        self.assertEqual(path.read_text(), before)

    def test_experiments_closed_this_month(self):
        p = experiments.new(self.ws, self.ledger, "Reply within an hour", "inquiry_to_meeting", "If ..., then ...",
                            d("2026-09-01T09:00"))
        exp = experiments.load(p)[0]["id"]
        experiments.transition(self.ws, exp, "approve", "op", d("2026-09-02T09:00"))
        experiments.transition(self.ws, exp, "start", "op", d("2026-09-03T09:00"))
        experiments.close(self.ws, exp, "keep", "Fast replies lifted tours.", "low", "50% vs. 0%", "op",
                          d("2026-10-28T09:00"), next_test="Try it for offices")
        data = client_report.build(self.ws, self.ledger, "2026-10", AS_OF)
        self.assertEqual(data["tests"]["done"][0]["verdict"], "keep")
        self.assertEqual(data["tests"]["next"], ["Try it for offices"])
        self.assertIn("decided to keep it", data["headline"])
        self.assertEqual(client_report.build(self.ws, self.ledger, "2026-09", AS_OF)["tests"]["done"], [])

    def test_bad_month(self):
        with self.assertRaises(ValueError):
            client_report.month_bounds("Oct 2026")
        with self.assertRaises(ValueError):
            client_report.build(self.ws, self.ledger, "2026-12", AS_OF)


class MonthlyScheduleTests(unittest.TestCase):
    def test_monthly_slots(self):
        s = Schedule.parse("monthly 1 08:00")
        self.assertEqual(s.latest_slot(d("2026-11-02T09:00"), UTC), d("2026-11-01T08:00"))
        self.assertEqual(s.latest_slot(d("2026-11-01T07:00"), UTC), d("2026-10-01T08:00"))
        self.assertEqual(s.latest_slot(d("2026-01-01T07:00"), UTC), d("2025-12-01T08:00"))
        self.assertEqual(s.next_slot(d("2026-12-15T09:00"), UTC), d("2027-01-01T08:00"))
        with self.assertRaises(ValueError):
            Schedule.parse("monthly 31 08:00")

    def test_scheduler_runs_the_report(self):
        tmp = Path(tempfile.mkdtemp())
        root = tmp / "client"
        main(["init", str(root), "--client-id", "acme"])
        profile = root / "profile/mefw.toml"
        text = profile.read_text()
        start, end = text.index("[schedule]"), text.index("[schedule.inbox]")
        profile.write_text(text[:start] + '[schedule]\nclient-reporter = "monthly 1 08:00"\n\n' + text[end:])
        ws = Workspace(root)
        (res,) = scheduler.run_due(ws, AS_OF)
        self.assertEqual((res["job"], res["result"]), ("client-reporter", "ok"))
        self.assertTrue((root / "reports/2026-10-client-report.md").exists())


if __name__ == "__main__":
    unittest.main()
