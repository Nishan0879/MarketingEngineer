import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import import_records
from mefw.adapters.csv_source import CsvSource
from mefw.cli import main
from mefw.core.errors import SensitiveData
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.conversion import cold_audit

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def ts(days_ago: float, hours: float = 0) -> str:
    return (AS_OF - timedelta(days=days_ago) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")


HEADER = ["Lead ID", "Created At", "Source", "Segment", "Value", "First Response At", "Last Outbound At",
          "Last Inbound At", "Outbound Count", "Stage", "Qualified At", "Tour Booked At", "Status",
          "Closed At", "Lost Reason"]


def row(ref, created, first=None, last_out=None, last_in=None, n_out=0, stage="New Inquiry",
        tour=None, status="Open", closed=None, reason=""):
    return [ref, created, "Website form", "Small team", "1000", first or "", last_out or "", last_in or "",
            str(n_out), stage, "", tour or "", status, closed or "", reason]


class ColdAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)

    def load(self, rows):
        p = self.tmp / "leads.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(rows)
        return import_records(self.ws, self.ledger, CsvSource(p, self.ws.config.csv))

    def test_each_leak_is_classified(self):
        self.load([
            row("never", ts(40)),
            row("waiting", ts(40), first=ts(40, 0.2), last_out=ts(40, 0.2), last_in=ts(39), n_out=1),
            row("slow", ts(40), first=ts(37), last_out=ts(30), n_out=3),
            row("few", ts(40), first=ts(40, 0.2), last_out=ts(40, 0.2), n_out=1),
            row("stalled", ts(40), first=ts(40, 0.2), last_out=ts(30), n_out=4, stage="Tour Booked", tour=ts(35)),
            row("quiet", ts(40), first=ts(40, 0.2), last_out=ts(30), n_out=4),
            row("recent", ts(3)),                                   # too new to call cold
            row("won", ts(40), first=ts(40, 0.2), n_out=1, status="Won", closed=ts(20)),
            row("lost", ts(40), status="Lost", closed=ts(20), reason="Price"),
        ])
        data = cold_audit.run_audit(self.ws, self.ledger, AS_OF)["segments"]["all"]
        by = {k: v for k, v in data["cold"]["by_leak"].items() if v}
        self.assertEqual(by, {
            "never_responded": ["never"], "ball_in_our_court": ["waiting"],
            "slow_first_response": ["slow"], "few_followups": ["few"],
            "stalled_after_meeting": ["stalled"], "went_quiet": ["quiet"],
        })
        self.assertEqual(data["cold"]["fixable"], 4)
        self.assertEqual(data["lost_reasons"], [["price", ["lost"]]])
        # Six cold leads is below the default minimum of ten: no headline claim.
        self.assertTrue(data["headline"].startswith("Not enough evidence"))

    def test_empty_ledger(self):
        data = cold_audit.run_audit(self.ws, self.ledger, AS_OF)
        self.assertTrue(data["headline"].startswith("Not enough evidence"))
        self.assertIn("Not enough evidence", cold_audit.render_markdown(data, "test"))

    def test_import_is_idempotent(self):
        rows = [row("a", ts(40), first=ts(40, 1), n_out=1)]
        first = self.load(rows)
        again = self.load(rows)
        self.assertGreater(first.new_events, 0)
        self.assertEqual(again.new_events, 0)

    def test_personal_data_column_refused(self):
        cfg = dict(self.ws.config.csv, columns=dict(self.ws.config.csv["columns"], ref="Email"))
        with self.assertRaises(SensitiveData):
            CsvSource(self.tmp / "x.csv", cfg)

    def test_confidence_labels(self):
        self.assertEqual(cold_audit.confidence([5, 50], 10)[0], "not enough evidence")
        self.assertEqual(cold_audit.confidence([12, 50, 3], 10)[0], "low")
        self.assertEqual(cold_audit.confidence([40, 50], 10)[0], "medium")


class EndToEndTests(unittest.TestCase):
    def test_sample_run(self):
        tmp = Path(tempfile.mkdtemp())
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_sample", ROOT / "examples/make_sample.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(tmp / "data")
        client = tmp / "client"
        self.assertEqual(main(["init", str(client), "--client-id", "demo"]), 0)
        self.assertEqual(main(["import-csv", "--client", str(client), str(tmp / "data/sample_leads.csv"),
                               "--activities", str(tmp / "data/sample_activities.csv")]), 0)
        self.assertEqual(main(["audit-cold", "--client", str(client), "--as-of", "2026-10-25T12:00"]), 0)
        report = next((client / "engines/conversion/audits").glob("*.md")).read_text()
        self.assertIn("biggest fixable leak", report)
        self.assertEqual(main(["pause", "--client", str(client), "--reason", "test"]), 0)
        self.assertEqual(main(["audit-cold", "--client", str(client), "--as-of", "2026-10-26T12:00"]), 2)
        self.assertEqual(main(["log", "verify", "--client", str(client)]), 0)


if __name__ == "__main__":
    unittest.main()
