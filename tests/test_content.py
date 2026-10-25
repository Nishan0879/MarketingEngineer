import csv
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.adapters.csv_source import CsvSource
from mefw.cli import main
from mefw.core import scheduler
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.content import briefs as content

AS_OF = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)

FACTS = """
[facts.tour]
text = "Tours run every weekday and take about twenty minutes."
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.unapproved]
text = "Parking is included."
"""

INSIGHT = """## Insight: {title}
- **Status:** {status}
- **Segment:** All leads
- **Date observed:** 2026-10-01
- **Statement:** {statement}
- **Customer language:** "Is there parking near the building? Call me on 555 123 4567" (`notes:N-1`)
- **Evidence:** {evidence} signals
- **Confidence:** medium

## Evidence log
{log}
"""

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        (self.root / "profile/approved-facts.toml").write_text(FACTS)
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)
        ins = self.root / "customer-truth/insights"
        ins.mkdir(parents=True, exist_ok=True)
        self.insight(ins / "parking--all.md", "Parking", "confirmed", "Prospects keep asking about parking.", 6)
        # Created with 2 signals, but the evidence log has since seen 5 on one day.
        self.insight(ins / "noise--all.md", "Noise", "acted on", "Quiet rooms matter.", 2,
                     "- 2026-10-20: 5 signals: `notes:a`, `notes:b`, `notes:c` and 2 more")
        self.insight(ins / "wifi--all.md", "Wifi", "confirmed", "Wifi speed comes up.", 3)
        self.insight(ins / "price--all.md", "Price", "observed", "Price came up.", 9)

    def insight(self, path, title, status, statement, evidence, log="- 2026-10-01: first seen"):
        path.write_text(INSIGHT.format(title=title, status=status, statement=statement, evidence=evidence, log=log))

    def leads(self, records):
        class Src:
            name = "crm"

            def records(_):
                return records
        import_records(self.ws, self.ledger, Src())

    def briefs(self, at=AS_OF):
        return main(["content", "briefs", "--client", str(self.root), "--at", at.isoformat()])

    def write_asset(self, brief_id, text, label="LinkedIn post"):
        path, meta, body = content.find(self.ws, brief_id)
        head, rest = body.split(f"### {label}\n", 1)
        rest = rest.replace(content.WRITE_HERE, text, 1)
        path.write_text(path.read_text().replace(body, head + f"### {label}\n" + rest))


class BriefTests(Base):
    def test_only_confirmed_insights_with_enough_evidence(self):
        cands, passed = content.candidates(self.ws, AS_OF, self.ledger)
        self.assertEqual(sorted(c["insight"] for c in cands), ["noise--all", "parking--all"])
        self.assertEqual(passed, ["wifi--all (3 signals; needs 5)"])
        parking = next(c for c in cands if c["insight"] == "parking--all")
        self.assertEqual(parking["evidence"], 6)
        self.assertNotIn("555", " ".join(parking["quotes"]))  # contact details are scrubbed

    def test_brief_contents_and_refresh(self):
        self.assertEqual(self.briefs(), 0)
        path, meta, body = content.find(self.ws, "C-20261025-parking--all")
        self.assertEqual((meta["status"], meta["tag"], meta["agent"]), ("brief", "mefw-parking-all", content.AGENT))
        self.assertEqual(meta["facts"], ["tour"])  # the unapproved fact isn't offered
        self.assertIn("Tours run every weekday", body)
        self.assertNotIn("Parking is included", body)
        self.assertIn("utm_campaign=mefw-parking-all", body)
        for label in ("LinkedIn post", "Instagram caption", "Email newsletter section", "Landing page FAQ"):
            self.assertIn(f"### {label}", body)
        self.assertEqual(content.assets(self.ws, body), {})

        # Same day again: the runner's dedupe stops a second brief. Within refresh_days: none either.
        self.briefs()
        self.briefs(AS_OF + timedelta(days=10))
        self.assertEqual(len(content.all_briefs(self.ws)), 2)
        self.briefs(AS_OF + timedelta(days=61))
        self.assertEqual(len(content.all_briefs(self.ws)), 4)

    def test_level_zero_writes_nothing(self):
        toml = self.root / "profile/mefw.toml"
        text = toml.read_text()
        start = text.index("[agents.content-brief-writer]")
        toml.write_text(text[:start] + text[start:].replace("level = 1", "level = 0", 1))
        self.briefs()
        self.assertEqual(content.all_briefs(self.ws), [])

    def test_cockpit_asks_for_the_writing(self):
        from mefw.core import cockpit
        self.briefs()
        decisions = cockpit.build(self.ws, self.ledger, AS_OF + timedelta(days=1))["decisions"]
        self.assertTrue(any("Write or drop 2 content brief(s)" in d for d in decisions))

    def test_scheduled(self):
        self.assertIn("content-brief-writer", scheduler.ORDER)
        cmd = scheduler.command_for(self.ws, "content-brief-writer", AS_OF)
        self.assertEqual(cmd[0][:2], ["content", "briefs"])


class ApprovalTests(Base):
    def setUp(self):
        super().setUp()
        self.briefs()
        self.id = "C-20261025-parking--all"

    def test_nothing_written(self):
        with self.assertRaisesRegex(ValueError, "Nothing written"):
            content.approve(self.ws, self.id, "op", AS_OF)

    def test_claims_quotes_and_approval(self):
        self.write_asset(self.id, "Parking worries? Free parking for everyone. Parking is included.")
        with self.assertRaises(ValueError) as e:
            content.approve(self.ws, self.id, "op", AS_OF)
        self.assertIn("receipts", str(e.exception))
        self.assertIn("facts", str(e.exception))  # an unapproved fact pasted in by hand

        path = content.find(self.ws, self.id)[0]
        path.write_text(path.read_text().replace(
            "Parking worries? Free parking for everyone. Parking is included.",
            '"Is there parking near the building?" We hear it a lot. '
            "Tours run every weekday and take about twenty minutes."))
        with self.assertRaisesRegex(ValueError, "testimonial"):
            content.approve(self.ws, self.id, "op", AS_OF)

        meta = content.approve(self.ws, self.id, "op", AS_OF, quote_permission=True)
        self.assertEqual((meta["status"], meta["approved_assets"]), ("approved", ["linkedin"]))
        self.assertIn("permission confirmed", content.find(self.ws, self.id)[2])

    def test_publish_only_approved_channels_and_results(self):
        self.write_asset(self.id, "Tours run every weekday and take about twenty minutes. Come and see.")
        content.approve(self.ws, self.id, "op", AS_OF)
        with self.assertRaisesRegex(ValueError, "No approved instagram"):
            content.published(self.ws, self.id, "instagram", "https://x.test/p", "op", AS_OF)
        content.published(self.ws, self.id, "linkedin", "https://x.test/p", "op", AS_OF)
        _, meta, _ = content.find(self.ws, self.id)
        self.assertEqual(meta["status"], "published")
        self.assertEqual(meta["published"][0]["channel"], "linkedin")  # stored as a table, read back as one

        def lead(ref, days, campaign=None, meet=False, before=False):
            at = AS_OF + timedelta(days=-3 if before else days)
            return LeadRecord(ref=ref, inquired_at=at, campaign=campaign,
                              stage_dates={"Tour Booked": at + timedelta(days=1)} if meet else {})
        self.leads([lead("t1", 1, "mefw-parking-all", meet=True), lead("t2", 2, "MEFW-PARKING-ALL"),
                    lead("t0", 0, "mefw-parking-all", before=True),  # came in before publishing
                    lead("o1", 1), lead("o2", 2), lead("o3", 3, meet=True), lead("o4", 4, "other-tag")])
        (row,) = content.results(self.ws, self.ledger, AS_OF + timedelta(days=10))
        self.assertEqual((row["inquiries"], row["meetings"], row["meet_rate"]), (2, 1, 0.5))
        self.assertEqual((row["others"], row["others_meet_rate"]), (4, 0.25))
        md = content.render_results([row], AS_OF)
        self.assertIn("| linkedin | 2 | 1 | 0 | 50% | 25% of 4 |", md)


class CampaignFieldTests(Base):
    def test_csv_campaign_column(self):
        f = self.tmp / "leads.csv"
        with f.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Lead ID", "Created At", "UTM Campaign"])
            w.writerow(["L1", "2026-10-20 10:00", "mefw-parking-all"])
            w.writerow(["L2", "2026-10-20 11:00", ""])
        cfg = {"source": "crm", "columns": {"ref": "Lead ID", "inquired_at": "Created At", "campaign": "UTM Campaign"}}
        import_records(self.ws, self.ledger, CsvSource(f, cfg))
        camps = {s.ref: s.campaign for s in self.ledger.states(AS_OF)}
        self.assertEqual(camps, {"L1": "mefw-parking-all", "L2": None})

    def test_old_ledger_gains_the_column(self):
        self.ledger.close()
        db = sqlite3.connect(self.ws.db_path)
        db.execute("ALTER TABLE leads DROP COLUMN campaign")
        db.commit()
        db.close()
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)
        self.leads([LeadRecord(ref="x", inquired_at=AS_OF, campaign="mefw-a")])
        self.assertEqual(self.ledger.states(AS_OF)[0].campaign, "mefw-a")


if __name__ == "__main__":
    unittest.main()
