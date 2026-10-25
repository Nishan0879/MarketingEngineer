import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.adapters.csv_source import CsvSource
from mefw.cli import main
from mefw.core.facts import load_facts
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.conversion import reengage
from mefw.engines.conversion.checks import banned_phrases, check_text

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

FACTS = """
[facts.tour]
text = "Tours run every weekday and take about 20 minutes."
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.old_promo]
text = "First month is half price."
approved_by = "Owner"
approved_on = "2026-01-01"
expires_on = "2026-06-30"

[facts.unapproved]
text = "We have 40 desks."
"""

PLAYBOOK = """
[reengage]
must_include = ["Reply STOP to opt out."]

[reengage.never_responded]
subject = "Sorry we missed you"
body = "Hi there, we never replied. {fact:tour} Reply STOP to opt out."

[reengage.few_followups]
subject = "Checking in"
body = "Hi there. {fact:old_promo} Reply STOP to opt out."
"""


def ago(days: float) -> datetime:
    return AS_OF - timedelta(days=days)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        (self.root / "profile/approved-facts.toml").write_text(FACTS)
        (self.root / "engines/conversion/playbook.toml").write_text(PLAYBOOK)
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)

    def leads(self, records):
        class Src:
            name = "crm"

            def records(_):
                return records
        import_records(self.ws, self.ledger, Src())

    def make(self):
        return main(["drafts", "make", "--client", str(self.root), "--at", AS_OF.isoformat()])

    def drafts(self):
        return {m["lead"]: (p, m, b) for p, m, b in reengage.existing_drafts(self.ws)}


class FactTests(Base):
    def test_fact_validity(self):
        facts = load_facts(self.ws)
        today = date(2026, 10, 25)
        self.assertIsNone(facts["tour"].problem(today))
        self.assertIn("expired", facts["old_promo"].problem(today))
        self.assertIn("no approval", facts["unapproved"].problem(today))


class CheckTests(Base):
    def check(self, text):
        return [i.check for i in check_text(self.ws, text, load_facts(self.ws), "all", date(2026, 10, 25),
                                            ["Reply STOP to opt out."])]

    def test_claims_must_come_from_valid_facts(self):
        ok = "Tours run every weekday and take about 20 minutes. Reply STOP to opt out."
        self.assertEqual(self.check(ok), [])
        self.assertIn("receipts", self.check("Desks from $199 this week. Reply STOP to opt out."))
        self.assertIn("receipts", self.check("We have 40 desks. Reply STOP to opt out."))  # not approved
        self.assertIn("receipts", self.check("First month is half price, guaranteed. Reply STOP to opt out."))

    def test_banned_language_sensitive_data_required_text(self):
        bl = self.root / "rules/banned-language.md"
        bl.write_text(bl.read_text() + "| just circling back | Checking in | 2026-10-01 |\n")
        self.assertEqual(banned_phrases(self.ws), ["just circling back"])
        self.assertIn("voice", self.check("Just circling back! Reply STOP to opt out."))
        self.assertIn("compliance", self.check("Send your card number to hold a desk. Reply STOP to opt out."))
        self.assertIn("compliance", self.check("Hi there."))


class DraftTests(Base):
    def setUp(self):
        super().setUp()
        self.leads([
            LeadRecord(ref="never", inquired_at=ago(40), value=500),
            LeadRecord(ref="few", inquired_at=ago(40), touches=[(ago(40) + timedelta(minutes=10), "out")]),
            LeadRecord(ref="optout", inquired_at=ago(40), opted_out=True),
            LeadRecord(ref="upset", inquired_at=ago(40)),
            LeadRecord(ref="won", inquired_at=ago(40), outcome="won", outcome_at=ago(30)),
            LeadRecord(ref="fresh", inquired_at=ago(3)),
        ])
        self.ledger.add_signal("notes", "inquiry_message", "n1", ago(40), "I want to make a complaint.",
                               lead_ref="upset")

    def test_who_gets_drafted(self):
        self.assertEqual(self.make(), 0)
        d = self.drafts()
        self.assertEqual(sorted(d), ["few", "never"])
        self.assertEqual(d["never"][1]["blocking_issues"], [])
        self.assertIn("Tours run every weekday", d["never"][2])
        # The template for "few" uses an expired fact: drafted, but flagged and unapprovable.
        self.assertTrue(any("expired" in x for x in d["few"][1]["blocking_issues"]))
        with self.assertRaises(ValueError):
            reengage.approve(self.ws, d["few"][1]["id"], "op", AS_OF)
        log = [e for e in reengage_log(self.root) if e["action"] == "skip_lead"]
        self.assertEqual(sorted((e["inputs"]["lead"], e["output"]["reason"][:10]) for e in log),
                         [("optout", "opted out"), ("upset", "needs a hu")])

    def test_one_draft_per_lead_per_cold_spell(self):
        self.make()
        self.make()
        self.assertEqual(len(reengage.existing_drafts(self.ws)), 2)

    def test_edit_detection_rejection_and_sending(self):
        self.make()
        path, meta, body = self.drafts()["never"]
        path.write_text(path.read_text().replace("we never replied.", "we never replied, sorry."))
        approved = reengage.approve(self.ws, meta["id"], "op", AS_OF)
        self.assertTrue(approved["edited"])

        # An edit that adds an unapproved claim can't be approved.
        _, few, _ = self.drafts()["few"]
        reengage.reject(self.ws, few["id"], "Uses an expired promo", "op", AS_OF)
        self.assertIn("Uses an expired promo", (self.root / "rules/corrections.md").read_text())

        reengage.mark_sent(self.ws, self.ledger, meta["id"], "op", AS_OF + timedelta(hours=1))
        (state,) = [s for s in self.ledger.states(AS_OF + timedelta(days=1)) if s.ref == "never"]
        self.assertEqual(state.touches_out, 1)
        rec = reengage.track_record(self.ws)
        self.assertEqual((rec["edited"], rec["rejected"], rec["streak"]), (1, 1, 0))

    def test_opt_out_after_drafting_blocks_sending(self):
        self.make()
        _, meta, _ = self.drafts()["never"]
        reengage.approve(self.ws, meta["id"], "op", AS_OF)
        self.assertEqual(main(["opt-out", "--client", str(self.root), "never", "--at", AS_OF.isoformat()]), 0)
        with self.assertRaises(ValueError):
            reengage.mark_sent(self.ws, self.ledger, meta["id"], "op", AS_OF + timedelta(hours=1))

    def test_level_and_kill_switch_apply(self):
        main(["pause", "--client", str(self.root), "--engine", "conversion", "--reason", "review"])
        self.assertEqual(self.make(), 2)
        self.assertEqual(reengage.existing_drafts(self.ws), [])

    def test_promotion_threshold(self):
        for i in range(21):
            self.leads([LeadRecord(ref=f"p{i}", inquired_at=ago(60))])
        main(["drafts", "make", "--client", str(self.root), "--at", AS_OF.isoformat(), "--max", "25"])
        clean = [m for _, m, _ in reengage.existing_drafts(self.ws) if not m["blocking_issues"]][:20]
        for i, m in enumerate(clean):
            reengage.approve(self.ws, m["id"], "op", AS_OF + timedelta(days=i))
        rec = reengage.track_record(self.ws)
        self.assertEqual((rec["streak"], rec["streak_days"], rec["meets_threshold"]), (20, 19, True))


class CsvOptOutTests(Base):
    def test_csv_opt_out_column(self):
        cfg = dict(self.ws.config.csv)
        cfg["columns"] = {"ref": "Lead ID", "inquired_at": "Created At", "opted_out": "Do Not Contact"}
        cfg["stage_dates"] = {}
        p = self.tmp / "leads.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Lead ID", "Created At", "Do Not Contact"])
            w.writerow(["a", "2026-09-01 10:00", "Yes"])
            w.writerow(["b", "2026-09-01 10:00", ""])
        import_records(self.ws, self.ledger, CsvSource(p, cfg))
        states = {s.ref: s.opted_out for s in self.ledger.states(AS_OF)}
        self.assertEqual(states, {"a": True, "b": False})


def reengage_log(root: Path) -> list[dict]:
    from mefw.core.activity_log import ActivityLog
    return ActivityLog(root / "logs/agent-activity.jsonl", "acme").entries()


if __name__ == "__main__":
    unittest.main()
