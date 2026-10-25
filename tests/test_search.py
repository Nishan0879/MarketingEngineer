import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.cli import main
from mefw.core import cockpit, scheduler
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.search import analysis, data, pages

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

FACTS = """
[facts.tour]
text = "You can book a tour any weekday."
topics = ["booking"]
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.parking]
text = "Office tenants can reserve parking spaces next door."
topics = ["parking"]
segments = ["offices"]
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.old_offer]
text = "Half off your first month."
approved_by = "Owner"
approved_on = "2026-01-01"
expires_on = "2026-06-30"
"""

CONVERSION = """
[first_response.topics.parking]
label = "Parking"
keywords = ["parking", "garage"]

[first_response.topics.booking]
label = "Booking a visit"
keywords = ["tour", "visit"]

[first_response.topics.price]
label = "Price"
keywords = ["price", "how much"]
"""

SEARCH = """
[search]
brand_terms = ["acme works"]
min_impressions = 10
max_query_repeats = 2
search_channels = ["Google"]

[search.intent]
high = ["near me", "price", "tour", "for rent"]
medium = ["best"]

[search.topics.offices]
label = "Private offices"
keywords = ["private office"]

[search.pages."/offices"]
label = "Private offices"
topics = ["offices"]

[search.pages."/visit"]
label = "Visit"
topics = ["booking"]

[search.listings.google]
label = "Google Business Profile"
checked_on = "2026-10-01"

[search.listings.google.fields.booking]
fact = "tour"
says = "You can book a tour any weekday"

[search.listings.google.fields.offer]
fact = "old_offer"
says = "Half off your first month."

[search.listings.yelp]
label = "Yelp"
checked_on = "2026-03-01"

[search.listings.yelp.fields.parking]
fact = "parking"
says = "Free parking."

[search.ai]
assistants = ["ChatGPT", "Claude"]

[search.ai.prompts]
best = "Best coworking in town?"
"""

QUERIES = [
    ("acme works", 200, 500, "40%", 1.1),
    ("private office for rent", 10, 900, "1.1%", 12.0),
    ("coworking parking near me", 2, 300, "0.67%", 8.0),
    ("how much is a private office", 1, 100, "1%", 30.0),
    ("book a tour", 30, 100, "30%", 2.0),
    ("remote work tips", 0, 80, "0%", 55.0),
    ("rare query", 0, 5, "0%", 9.0),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        (self.root / "profile/approved-facts.toml").write_text(FACTS)
        (self.root / "engines/conversion/playbook.toml").write_text(CONVERSION)
        (self.root / "engines/search/playbook.toml").write_text(SEARCH)
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)

    def export(self, rows=QUERIES, name="queries.csv"):
        f = self.tmp / name
        with f.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Top queries", "Clicks", "Impressions", "CTR", "Position"])
            w.writerows(rows)
        return f

    def imp(self, period_end="2026-10-24", rows=QUERIES):
        return main(["search", "import", "--client", str(self.root), str(self.export(rows)),
                     "--period-end", period_end, "--at", AS_OF.isoformat()])

    def signals(self, rows):
        f = self.tmp / "signals.csv"
        with f.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Note ID", "Type", "Date", "Lead ID", "Segment", "Text"])
            w.writerows(rows)
        main(["import-signals", "--client", str(self.root), str(f)])


class ImportTests(Base):
    def test_snapshot_is_scrubbed_and_never_overwritten(self):
        rows = [*QUERIES, ("call 555 123 4567 about offices", 0, 40, "0%", 20.0)]
        self.assertEqual(self.imp(rows=rows), 0)
        (snap,) = data.snapshots(self.ws)
        self.assertEqual(snap["period_end"], "2026-10-24")
        q = next(r for r in snap["queries"] if "offices" in r["query"])
        self.assertNotIn("555", q["query"])
        self.assertEqual(next(r for r in snap["queries"] if r["query"] == "book a tour")["ctr"], 0.3)
        self.assertEqual(self.imp(rows=rows), 0)  # same export again: nothing new
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            data.import_snapshot(self.ws, self.export(QUERIES[:2]), date(2026, 10, 24))

    def test_needs_search_console_columns(self):
        f = self.tmp / "bad.csv"
        f.write_text("Query,Visits\nx,1\n")
        with self.assertRaisesRegex(ValueError, "Search Console"):
            data.import_snapshot(self.ws, f, date(2026, 10, 24))


class AnalysisTests(Base):
    def setUp(self):
        super().setUp()
        self.imp()

    def test_ranking_and_what_exists(self):
        pb = data.load_playbook(self.ws)
        ranked, brand = analysis.opportunities(self.ws, pb, data.snapshots(self.ws)[-1])
        by = {r["query"]: r for r in ranked}
        self.assertEqual([q["query"] for q in brand], ["acme works"])
        self.assertNotIn("rare query", by)  # under min_impressions
        # Both high intent and on a topic; page one beats page two despite fewer impressions.
        self.assertEqual([r["query"] for r in ranked[:2]], ["coworking parking near me", "private office for rent"])
        self.assertIn("Improve /offices", by["private office for rent"]["action"])
        self.assertEqual(by["coworking parking near me"]["topic"], "parking")
        self.assertIn("New FAQ entry", by["coworking parking near me"]["action"])
        self.assertIsNone(by["remote work tips"]["topic"])
        # Already in the top 3: little left to gain, so it ranks below queries in reach.
        self.assertLess(by["book a tour"]["score"], by["coworking parking near me"]["score"])

    def test_gaps_listings_ai_and_results(self):
        self.signals([
            ["N-1", "inquiry_message", "2026-10-10 10:00", "", "", "Is there parking for the team?"],
            ["N-2", "review", "2026-10-11 10:00", "", "", "Great place but parking is hard."],
            ["N-3", "lost_note", "2026-10-12 10:00", "", "", "Price too high"],  # our words, not theirs
            ["N-4", "inquiry_message", "2026-05-01 10:00", "", "", "How much is it?"],  # too old
        ])
        d = analysis.analyze(self.ws, self.ledger, AS_OF)
        self.assertEqual([(g["topic"], g["asked"]) for g in d["gaps"]], [("parking", 2)])

        google, yelp = d["listings"]
        self.assertEqual(len(google["problems"]), 1)  # booking matches (case and full stop aside)
        self.assertIn("expired", google["problems"][0])
        self.assertTrue(any("check it again" in p for p in yelp["problems"]))
        self.assertTrue(any("update it to" in p for p in yelp["problems"]))

        self.assertEqual(len(d["ai"]["due"]), 2)
        main(["search", "ai-record", "--client", str(self.root), "--assistant", "chatgpt", "--prompt", "best",
              "--mentioned", "yes", "--cited", "https://acme.test/", "--at", AS_OF.isoformat()])
        with self.assertRaisesRegex(ValueError, "No prompt"):
            data.record_ai_check(self.ws, "Claude", "nope", False, None, "op", AS_OF)
        with self.assertRaisesRegex(ValueError, "isn't in"):
            data.record_ai_check(self.ws, "Bard", "best", False, None, "op", AS_OF)
        ai = analysis.ai_summary(self.ws, data.load_playbook(self.ws), AS_OF)
        self.assertEqual(ai["rows"], [{"assistant": "ChatGPT", "checked": 1, "mentioned": 1, "cited": 1}])
        self.assertEqual(ai["due"], [("Claude", "best")])

        def lead(ref, days, channel, meet=False):
            at = AS_OF - timedelta(days=days)
            return LeadRecord(ref=ref, inquired_at=at, channel=channel,
                              stage_dates={"Tour Booked": at + timedelta(hours=1)} if meet else {})

        class Src:
            name = "crm"

            def records(_):
                return [lead("a", 3, "google", meet=True), lead("b", 5, "Google"), lead("c", 4, "Referral"),
                        lead("d", 40, "Google")]
        import_records(self.ws, self.ledger, Src())
        r = analysis.analyze(self.ws, self.ledger, AS_OF)["results"]
        self.assertEqual((r["now"]["inquiries"], r["now"]["meetings"], r["before"]["inquiries"]), (2, 1, 1))
        self.assertEqual(r["trend"][0]["brand_clicks"], 200)

    def test_cli_report_level_zero(self):
        self.assertEqual(main(["search", "analyze", "--client", str(self.root), "--at", AS_OF.isoformat()]), 0)
        text = (self.root / "engines/search/reports/2026-10-25.md").read_text()
        for heading in ("## Opportunities", "## Questions buyers ask", "## Listings", "## AI assistants", "## Results"):
            self.assertIn(heading, text)
        self.assertIn("Brand searches: 200 clicks", text)


class DraftTests(Base):
    def setUp(self):
        super().setUp()
        self.imp()

    def drafts(self, at=AS_OF):
        return main(["search", "drafts", "--client", str(self.root), "--at", at.isoformat(), "--max", "5"])

    def test_drafts_answer_only_from_facts(self):
        self.drafts()
        ids = [m["id"] for _, m, _ in pages.all_drafts(self.ws)]
        self.assertEqual(sorted(ids), ["S-20261025-booking", "S-20261025-offices", "S-20261025-parking",
                                       "S-20261025-price"])
        _, meta, body = pages.find(self.ws, "S-20261025-parking")
        self.assertEqual((meta["page"], meta["facts"]), ("new", ["parking"]))
        self.assertIn("For offices: Office tenants can reserve parking spaces next door.", body)
        _, meta, body = pages.find(self.ws, "S-20261025-offices")
        self.assertEqual(meta["page"], "/offices")
        self.assertIn("{answer needed: private offices}", body)
        self.assertIn("### How much is a private office?", pages.find(self.ws, "S-20261025-price")[2])
        with self.assertRaisesRegex(ValueError, "answer needed"):
            pages.approve(self.ws, "S-20261025-offices", "op", AS_OF)
        # One draft per topic per refresh window.
        self.drafts(AS_OF + timedelta(days=7))
        self.assertEqual(len(pages.all_drafts(self.ws)), 4)

    def edit(self, draft_id, text):
        path, _, body = pages.find(self.ws, draft_id)
        faq = pages.faq_text(body)
        path.write_text(path.read_text().replace(faq, faq.split("\n", 1)[0] + "\n\n" + text, 1))

    def test_checks_and_publishing(self):
        self.drafts()
        did = "S-20261025-booking"
        self.edit(did, "You can book a tour any weekday. Book a tour, book a tour, book a tour today.")
        with self.assertRaisesRegex(ValueError, "stuffing"):
            pages.approve(self.ws, did, "op", AS_OF)
        self.edit(did, "You can book a tour any weekday. If you're happy with your visit, leave us a review!")
        with self.assertRaisesRegex(ValueError, "review gating"):
            pages.approve(self.ws, did, "op", AS_OF)
        self.edit(did, "You can book a tour any weekday. Free coffee on every visit.")
        with self.assertRaisesRegex(ValueError, "receipts"):
            pages.approve(self.ws, did, "op", AS_OF)
        self.edit(did, 'You can book a tour any weekday. "The best place I have ever worked in town."')
        with self.assertRaisesRegex(ValueError, "testimonial"):
            pages.approve(self.ws, did, "op", AS_OF)
        self.edit(did, "You can book a tour any weekday. We like showing people around ourselves.")
        with self.assertRaisesRegex(ValueError, "approve it before"):
            pages.published(self.ws, did, "https://acme.test/visit", "op", AS_OF)
        pages.approve(self.ws, did, "op", AS_OF)
        pages.published(self.ws, did, "https://acme.test/visit", "op", AS_OF + timedelta(days=1))
        self.assertEqual(pages.find(self.ws, did)[1]["status"], "published")

        # Next period: the query moved up.
        self.imp("2026-11-21", [("book a tour", 40, 120, "33%", 1.4)])
        moves = analysis.analyze(self.ws, self.ledger, datetime(2026, 11, 22, tzinfo=timezone.utc))["movement"]
        self.assertEqual([(m["query"], m["before"], m["now"]) for m in moves], [("book a tour", 2.0, 1.4)])

    def test_cockpit_and_schedule(self):
        self.drafts()
        decisions = cockpit.build(self.ws, self.ledger, AS_OF + timedelta(days=1))["decisions"]
        self.assertTrue(any("Review 4 search draft(s)" in d for d in decisions))
        self.assertTrue(any("Fix the Yelp listing" in d for d in decisions))
        self.assertTrue(any("AI assistant check(s)" in d for d in decisions))
        for job in ("search-analyst", "search-page-drafter"):
            self.assertIn(job, scheduler.ORDER)
            self.assertEqual(scheduler.command_for(self.ws, job, AS_OF)[0][0], "search")

    def test_level_zero_drafter_writes_nothing(self):
        toml = self.root / "profile/mefw.toml"
        text = toml.read_text()
        start = text.index("[agents.search-page-drafter]")
        toml.write_text(text[:start] + text[start:].replace("level = 1", "level = 0", 1))
        self.assertEqual(self.drafts(), 2)
        self.assertEqual(pages.all_drafts(self.ws), [])


if __name__ == "__main__":
    unittest.main()
