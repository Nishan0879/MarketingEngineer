import csv
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.adapters.signals_csv import import_signals
from mefw.cli import main
from mefw.core import customer_truth, truth_report
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.conversion import cold_audit

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]

SEGMENTS = """
[segments.members]
label = "Members"
match = ["Freelancer"]
cycle_days = 21

[segments.offices]
label = "Offices"
match = ["Office"]
cycle_days = 90
[segments.offices.stages]
meet = ["Proposal Sent"]
[segments.offices.cold_audit]
cold_after_days = 45
"""

THEMES = """
[customer_truth]
min_mentions = 3
min_group_size = 2

[customer_truth.themes.parking]
label = "Parking"
keywords = ["parking"]

[customer_truth.themes.price]
label = "Price"
keywords = ["price", "expensive"]

[customer_truth.themes.flexibility]
label = "Flexible terms"
keywords = ["month-to-month"]
"""


def ago(days: float) -> datetime:
    return AS_OF - timedelta(days=days)


class Base(unittest.TestCase):
    extra = SEGMENTS + THEMES

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        root = self.tmp / "client"
        main(["init", str(root), "--client-id", "acme"])
        cfg = root / "profile/mefw.toml"
        # Drop the template's example themes so tests control them.
        text = cfg.read_text()
        start = text.index("[customer_truth]")
        end = text.index("# CSV export of notes")
        cfg.write_text(text[:start] + text[end:] + self.extra)
        self.ws = Workspace(root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)

    def lead(self, ref, segment, inquired, **kw):
        class Src:
            name = "crm"

            def records(_):
                return [LeadRecord(ref=ref, inquired_at=inquired, segment=segment, **kw)]
        return import_records(self.ws, self.ledger, Src())

    def signal(self, ref, text, at, kind="tour_note", lead=None, segment=None):
        return self.ledger.add_signal("notes", kind, ref, at, text, segment=segment, lead_ref=lead)


class SegmentTests(Base):
    def test_assignment(self):
        self.assertEqual(self.ws.segment_for("freelancer"), "members")
        self.assertEqual(self.ws.segment_for("Office"), "offices")
        self.assertEqual(self.ws.segment_for("Walk-in"), "unassigned")
        self.assertEqual(self.ws.cycle_days("offices"), 90)

    def test_stage_names_per_segment(self):
        self.assertEqual(self.ws.canonical_stage("Proposal Sent", "Office"), "meet")
        self.assertIsNone(self.ws.canonical_stage("Proposal Sent", "Freelancer"))
        rep = self.lead("m1", "Freelancer", ago(40), current_stage="Proposal Sent")
        self.assertEqual(rep.unknown_stages, {"Proposal Sent": 1})

    def test_audit_uses_segment_thresholds(self):
        # Both quiet for 30 days: cold for members (14-day rule), not yet for offices (45-day rule).
        self.lead("m1", "Freelancer", ago(30))
        self.lead("o1", "Office", ago(30))
        self.lead("x1", "Walk-in", ago(30))
        data = cold_audit.run_audit(self.ws, self.ledger, AS_OF)
        self.assertEqual(list(data["segments"]), ["members", "offices", "unassigned"])
        self.assertEqual(data["segments"]["members"]["cold"]["count"], 1)
        self.assertEqual(data["segments"]["offices"]["judged"], 0)
        md = cold_audit.render_markdown(data, "test")
        self.assertIn("## By segment", md)
        self.assertIn("## Offices", md)


class TruthTests(Base):
    def test_signals_are_scrubbed_deduped_and_append_only(self):
        self.assertTrue(self.signal("n1", "Call jo@example.com about parking", ago(1)))
        self.assertFalse(self.signal("n1", "Call jo@example.com about parking", ago(1)))
        (s,) = self.ledger.signals(AS_OF)
        self.assertNotIn("example.com", s["text"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.ledger.db.execute("DELETE FROM signals")

    def test_rising_theme_and_insight_record(self):
        for i in range(4):
            self.signal(f"new{i}", "Main concern was parking for the team.", ago(5 + i), segment="Office")
        self.signal("old1", "Asked about parking.", ago(50), segment="Office")
        data = customer_truth.run_truth(self.ws, self.ledger, AS_OF)
        offices = data["segments"]["offices"]
        parking = next(t for t in offices["trends"] if t["theme"] == "parking")
        self.assertEqual((parking["current"], parking["direction"]), (4, "rising"))
        self.assertIn("Parking came up 4 times", data["headline"])
        self.assertEqual(len(parking["quotes"]), 1)  # identical wording is quoted once

        out = truth_report.write_outputs(self.ws, data, "test")
        rec = self.ws.root / "customer-truth/insights/parking--offices.md"
        self.assertIn("customer-truth/insights/parking--offices.md", out["insights"])
        self.assertIn("**Status:** observed", rec.read_text())

        # The operator edits the record; a later run appends evidence and keeps the edit.
        rec.write_text(rec.read_text().replace("Draft wording; operator to confirm.", "Confirmed by owner."))
        self.signal("new9", "Parking again.", AS_OF - timedelta(hours=1), segment="Office")
        later = customer_truth.run_truth(self.ws, self.ledger, AS_OF + timedelta(days=1))
        truth_report.write_insights(self.ws, later)
        text = rec.read_text()
        self.assertIn("Confirmed by owner.", text)
        self.assertEqual(text.count("\n- 2026-10-2"), 2)

    def test_objections_and_won_vs_lost(self):
        for i in range(3):
            self.lead(f"w{i}", "Freelancer", ago(60), outcome="won", outcome_at=ago(40))
            self.signal(f"wn{i}", "Wants month-to-month.", ago(59), kind="inquiry_message", lead=f"w{i}")
            self.lead(f"l{i}", "Freelancer", ago(60), outcome="lost", outcome_at=ago(40), lost_reason="Too expensive")
            self.signal(f"ln{i}", "Asked about the price twice.", ago(59), kind="inquiry_message", lead=f"l{i}")
        members = customer_truth.run_truth(self.ws, self.ledger, AS_OF)["segments"]["members"]
        self.assertEqual(members["objections"][0]["theme"], "price")
        self.assertEqual(members["objections"][0]["count"], 3)
        rows = {r["theme"]: r for r in members["won_vs_lost"]["rows"]}
        self.assertEqual((rows["flexibility"]["won"], rows["flexibility"]["lost"]), (3, 0))
        self.assertEqual((rows["price"]["won"], rows["price"]["lost"]), (0, 3))
        self.assertEqual(members["won_vs_lost"]["confidence"], "low")

    def test_untagged_signal_is_an_open_question(self):
        for i in range(4):
            self.signal(f"u{i}", "Lovely coffee.", ago(2), segment="Freelancer")
        data = customer_truth.run_truth(self.ws, self.ledger, AS_OF)
        qs = data["segments"]["members"]["open_questions"]
        self.assertTrue(any("match no theme" in q["text"] for q in qs))
        self.assertIn("No lost notes in the data. Where do they live?", data["open_questions"])

    def test_signals_csv_mapping(self):
        p = self.tmp / "notes.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Type", "Note ID", "Date", "Text", "Lead ID", "Segment"])
            w.writerow(["Tour", "N-1", "2026-10-20 10:00", "Parking?", "", "Office"])
            w.writerow(["Mystery", "N-2", "2026-10-20 10:00", "Hello", "", "Office"])
        rep = import_signals(self.ledger, p, self.ws.config.signals_csv)
        self.assertEqual((rep.rows, rep.new, rep.skipped), (2, 1, ["N-2"]))


class NoThemesTests(Base):
    extra = ""

    def test_headline_asks_for_themes(self):
        self.signal("n1", "anything", ago(1))
        data = customer_truth.run_truth(self.ws, self.ledger, AS_OF)
        self.assertIn("No themes configured", data["headline"])


class CoworkingExampleTests(unittest.TestCase):
    def test_example_profile_end_to_end(self):
        import importlib.util
        tmp = Path(tempfile.mkdtemp())
        spec = importlib.util.spec_from_file_location("make_sample", ROOT / "examples/make_sample.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(tmp / "data")
        client = tmp / "client"
        main(["init", str(client), "--client-id", "demo"])
        profile = (ROOT / "examples/coworking/mefw.toml").read_text().replace("{client_id}", "demo")
        (client / "profile/mefw.toml").write_text(profile)
        d = tmp / "data"
        c = ["--client", str(client)]
        self.assertEqual(main(["import-csv", *c, str(d / "sample_leads.csv"),
                               "--activities", str(d / "sample_activities.csv")]), 0)
        self.assertEqual(main(["import-signals", *c, str(d / "sample_signals.csv")]), 0)
        self.assertEqual(main(["audit-cold", *c, "--as-of", "2026-10-25T12:00"]), 0)
        self.assertEqual(main(["truth", *c, "--as-of", "2026-10-25T12:00"]), 0)
        truth = (client / "customer-truth/what-the-market-is-telling-us.md").read_text()
        self.assertIn("Office leases (B2B): Parking came up", truth)
        audit = next((client / "engines/conversion/audits").glob("*.md")).read_text()
        self.assertIn("## Members (B2C)", audit)
        self.assertEqual(main(["log", "verify", *c]), 0)


if __name__ == "__main__":
    unittest.main()
