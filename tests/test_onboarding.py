import csv
import io
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from mefw.adapters import onboarding
from mefw.cli import main
from mefw.core.ledger import Ledger
from mefw.core.workspace import FUNNEL, Workspace

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "examples/onboarding/lead-sheet-template.csv"

HUBSPOT = [
    ["Record ID", "Deal Name", "Create Date", "Deal Stage", "Close Date", "Amount", "Pipeline", "Original Source",
     "Closed Lost Reason", "Contact Email"],
    ["101", "Acme desk", "2026-09-01 10:00", "Appointment Scheduled", "", "500", "Sales Pipeline", "Organic search",
     "", "a@b.test"],
    ["102", "Beta office", "2026-09-03 11:00", "Closed Won", "2026-09-20 12:00", "2000", "Sales Pipeline",
     "Paid search", "", ""],
    ["103", "Gamma", "2026-09-05 11:00", "Closed Lost", "2026-09-21 12:00", "300", "Sales Pipeline", "Referrals",
     "Price", ""],
    ["104", "Delta", "2026-09-06 11:00", "Tour Done", "", "300", "Sales Pipeline", "Referrals", "", ""],
]

PIPEDRIVE = [
    ["Deal - ID", "Deal - Title", "Deal - Deal created", "Deal - Stage", "Deal - Status", "Deal - Lost reason",
     "Person - Phone"],
    ["7", "Desk for Ann", "2026-09-01 10:00:00", "Lead In", "open", "", "555 0100"],
    ["8", "Office", "2026-09-02 10:00:00", "Proposal Made", "won", "", ""],
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        self.ws = Workspace(self.root)

    def csv(self, rows, name="export.csv"):
        f = self.tmp / name
        with f.open("w", newline="") as fh:
            csv.writer(fh).writerows(rows)
        return f


class PresetTests(unittest.TestCase):
    def test_every_preset_is_complete(self):
        presets = onboarding.list_presets()
        self.assertEqual(set(presets), {"spreadsheet", "hubspot", "pipedrive", "nexudus", "officernd"})
        for name, p in presets.items():
            with self.subTest(name):
                self.assertTrue(p["preset"]["label"] and p["preset"]["export"])
                for f in onboarding.REQUIRED:
                    self.assertTrue(p["columns"][f])
                self.assertLessEqual(set(p["columns"]), set(onboarding.LEAD_FIELDS))
                self.assertLessEqual(set(p["stages"]), set(FUNNEL))
                self.assertTrue(p["outcome_values"]["won"] and p["outcome_values"]["lost"])
                # No alias may name a personal-data column.
                for aliases in p["columns"].values():
                    self.assertFalse([a for a in aliases if onboarding.BLOCKED_FIELDS.search(a)])

    def test_resolve_ignores_case_and_punctuation_and_never_maps_personal_data(self):
        p = onboarding.load_preset("pipedrive")
        cols, _ = onboarding.resolve(p, ["deal: id", "DEAL CREATED", "Stage", "Person - Phone"])
        self.assertEqual(cols, {"ref": "deal: id", "inquired_at": "DEAL CREATED", "stage": "Stage"})
        p = {"columns": {"ref": ["Email", "Lead ID"], "inquired_at": ["Created"]}}
        self.assertEqual(onboarding.resolve(p, ["Email", "Lead ID", "Created"])[0]["ref"], "Lead ID")
        with self.assertRaisesRegex(KeyError, "Choose one of"):
            onboarding.load_preset("salesforce")


class CheckTests(Base):
    def test_template_matches_the_spreadsheet_preset_fully(self):
        rep = onboarding.check(TEMPLATE)
        self.assertEqual(rep["preset"], "spreadsheet")
        self.assertEqual(rep["missing"], [])
        self.assertEqual(rep["unused"], [])
        self.assertEqual(set(rep["stage_dates"]), {"Qualified", "Tour Booked"})
        self.assertEqual(rep["unmapped_stages"], [])
        self.assertTrue(rep["ready"])

    def test_hubspot_export_is_recognised(self):
        rep = onboarding.check(self.csv(HUBSPOT))
        self.assertEqual(rep["preset"], "hubspot")
        self.assertEqual(rep["columns"]["stage"], "Deal Stage")
        self.assertEqual(rep["columns"]["outcome"], "Deal Stage")
        self.assertEqual(rep["personal"], ["Contact Email"])
        self.assertNotIn("Contact Email", rep["columns"].values())
        self.assertEqual(rep["stages"]["Closed Lost"][0], "lost")
        self.assertEqual(rep["unmapped_stages"], ["Tour Done"])
        self.assertEqual({v: o for v, (o, _) in rep["outcomes"].items()}["Closed Won"], "won")
        self.assertIn("Contact Email", onboarding.render(rep))
        # The client's own stage names count once they're in the profile.
        self.assertIn("Tour Done", onboarding.check(self.csv(HUBSPOT), ws=self.ws)["unmapped_stages"])

    def test_pipedrive_prefixed_headers(self):
        rep = onboarding.check(self.csv(PIPEDRIVE))
        self.assertEqual(rep["preset"], "pipedrive")
        self.assertEqual((rep["columns"]["ref"], rep["columns"]["outcome"]), ("Deal - ID", "Deal - Status"))
        self.assertEqual(rep["personal"], ["Person - Phone"])
        self.assertTrue(rep["ready"])

    def test_problems_are_reported(self):
        rows = [["Lead ID", "Created At", "Stage", "Closed At"],
                ["L1", "2026-10-01", "New", ""], ["L1", "2026-10-02", "Mystery", "next week"],
                ["", "2026-10-03", "New", ""]]
        rep = onboarding.check(self.csv(rows), "spreadsheet")
        self.assertEqual((rep["duplicate_refs"], rep["blank_refs"]), (1, 1))
        self.assertEqual(rep["bad_dates"]["outcome_at"]["examples"], ["next week"])
        self.assertEqual(rep["unmapped_stages"], ["Mystery"])
        self.assertFalse(rep["ready"])
        rep = onboarding.check(self.csv([["Stage", "Created At"], ["New", "2026-10-01"]]), "spreadsheet")
        self.assertEqual(rep["missing_required"], ["ref"])
        self.assertIn("Not ready", onboarding.render(rep))


class ApplyTests(Base):
    def profile(self):
        return tomllib.loads((self.root / "profile/mefw.toml").read_text())

    def test_apply_then_import(self):
        f = self.csv(HUBSPOT)
        self.assertEqual(main(["onboard", "apply", str(f), "--preset", "hubspot", "--stage", "Tour Done=meet",
                               "--client", str(self.root)]), 0)
        prof = self.profile()
        csv_cfg = prof["adapters"]["csv"]
        self.assertEqual(csv_cfg["source"], "crm")
        self.assertEqual(csv_cfg["columns"]["ref"], "Record ID")
        self.assertNotIn("first_response_at", csv_cfg["columns"])  # nothing left mapped to a missing column
        self.assertEqual(csv_cfg["stage_dates"], {})
        self.assertEqual(csv_cfg["outcome_values"], {"won": ["Closed Won"], "lost": ["Closed Lost"]})
        stages = prof["funnel"]["stages"]
        self.assertIn("Tour Done", stages["meet"])
        self.assertIn("Appointment Scheduled", stages["meet"])
        self.assertEqual(stages["inquire"], ["New", "New Inquiry", "Lead"])  # the operator's names are kept
        self.assertEqual(len(list((self.root / "profile").glob("mefw.toml.*.bak"))), 1)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["import-csv", str(f), "--client", str(self.root)]), 0)
        self.assertNotIn("Unmapped", out.getvalue())  # "Closed Lost" is an outcome, not a stage
        ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(ledger.close)
        states = {s.ref: s for s in ledger.states(datetime(2026, 10, 25, tzinfo=timezone.utc))}
        self.assertEqual((states["102"].outcome, states["103"].outcome), ("won", "lost"))
        self.assertTrue(states["104"].reached("meet"))
        self.assertIn('"onboard"', self.ws.log_path.read_text())

    def test_template_end_to_end(self):
        self.assertEqual(main(["onboard", "apply", str(TEMPLATE), "--preset", "spreadsheet",
                               "--client", str(self.root)]), 0)
        self.assertEqual(self.profile()["adapters"]["csv"]["stage_dates"],
                         {"Qualified": "Qualified At", "Tour Booked": "Tour Booked At"})
        self.assertEqual(main(["import-csv", str(TEMPLATE), "--client", str(self.root)]), 0)

    def test_refuses_and_leaves_the_profile_alone(self):
        before = (self.root / "profile/mefw.toml").read_text()
        bad = self.csv([["Stage", "Created At"], ["New", "2026-10-01"]])
        with self.assertRaisesRegex(ValueError, "can't be imported yet"):
            onboarding.apply(self.ws, bad, "spreadsheet")
        with self.assertRaisesRegex(ValueError, "isn't a funnel stage"):
            onboarding.apply(self.ws, self.csv(HUBSPOT), "hubspot", {"Tour Done": "visit"})
        self.assertEqual(main(["onboard", "apply", str(bad), "--preset", "spreadsheet", "--client", str(self.root)]), 1)
        self.assertEqual((self.root / "profile/mefw.toml").read_text(), before)
        self.assertEqual(list((self.root / "profile").glob("*.bak")), [])

    def test_check_exit_code(self):
        self.assertEqual(main(["onboard", "check", str(TEMPLATE)]), 0)
        self.assertEqual(main(["onboard", "check", str(self.csv([["Stage"], ["New"]]))]), 1)
        self.assertEqual(main(["onboard", "presets"]), 0)


if __name__ == "__main__":
    unittest.main()
