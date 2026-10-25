import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.cli import main
from mefw.core import cockpit
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace
from mefw.engines.conversion import first_response, queue, reengage

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

FACTS = """
[facts.tour]
text = "Tours run every weekday and take about 20 minutes."
topics = ["booking"]
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.parking]
text = "Office tenants can reserve parking in the garage next door."
topics = ["parking"]
segments = ["offices"]
approved_by = "Owner"
approved_on = "2026-10-01"

[facts.old_price]
text = "Desks are $199 a month."
topics = ["price"]
approved_by = "Owner"
approved_on = "2026-01-01"
expires_on = "2026-06-30"
"""

PLAYBOOK = """
[first_response]
must_include = ["Reply STOP to opt out."]
subject = "Thanks for getting in touch"
body = \"\"\"Hi there,

{answers}

{fact:tour} Reply STOP to opt out.\"\"\"

[first_response.topics.price]
label = "Price"
keywords = ["price", "how much"]

[first_response.topics.parking]
label = "Parking"
keywords = ["parking"]

[first_response.topics.booking]
label = "Booking a visit"
keywords = ["tour"]

[reengage]
must_include = ["Reply STOP to opt out."]

[reengage.never_responded]
subject = "Sorry we missed you"
body = "Hi there, we never replied. {fact:tour} Reply STOP to opt out."
"""

PROFILE_SEGMENTS = """
[segments.members]
match = ["Member"]

[segments.offices]
match = ["Office"]
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
        profile = self.root / "profile/mefw.toml"
        profile.write_text(profile.read_text() + PROFILE_SEGMENTS)
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)
        self.leads([
            LeadRecord(ref="office", inquired_at=ago(1), segment="Office"),
            LeadRecord(ref="member", inquired_at=ago(2), segment="Member"),
            LeadRecord(ref="plain", inquired_at=ago(0.5), segment="Member"),
            LeadRecord(ref="replied", inquired_at=ago(2), touches=[(ago(2) + timedelta(minutes=5), "out")]),
            LeadRecord(ref="booked", inquired_at=ago(2), stage_dates={"Tour Booked": ago(1)}),
            LeadRecord(ref="optout", inquired_at=ago(1), opted_out=True),
            LeadRecord(ref="upset", inquired_at=ago(1)),
            LeadRecord(ref="old", inquired_at=ago(40)),  # cold: re-engagement's job
        ])
        self.msg("office", "How much is an office? Is there parking for the team?")
        self.msg("member", "What's the price for a desk? Can I come for a tour?")
        self.msg("upset", "Third time asking, I will leave a complaint.")

    def leads(self, records):
        class Src:
            name = "crm"

            def records(_):
                return records
        import_records(self.ws, self.ledger, Src())

    def msg(self, ref, text):
        self.ledger.add_signal("notes", "inquiry_message", f"n-{ref}", ago(1), text, lead_ref=ref)

    def make(self, agent="first-response-drafter"):
        return main(["drafts", "make", "--client", str(self.root), "--at", AS_OF.isoformat(), "--agent", agent])

    def drafts(self, agent=first_response.AGENT):
        return {m["lead"]: (p, m, b) for p, m, b in queue.existing_drafts(self.ws, agent)}


class FirstResponseTests(Base):
    def test_who_gets_a_first_response(self):
        self.assertEqual(self.make(), 0)
        d = self.drafts()
        self.assertEqual(sorted(d), ["member", "office", "plain"])
        # Longest waiting first: the order candidates come in.
        cands, skipped = first_response.candidates(self.ws, self.ledger, AS_OF)
        self.assertEqual([c.state.ref for c in cands], ["member", "office", "plain"])
        self.assertEqual(sorted((s["ref"], s["why"][:10]) for s in skipped),
                         [("optout", "opted out"), ("upset", "needs a hu")])

    def test_answers_come_only_from_usable_facts(self):
        self.make()
        d = self.drafts()
        _, office, body = d["office"]
        self.assertEqual(office["topics_asked"], ["price", "parking"])
        self.assertIn("reserve parking in the garage", body)
        # The price fact expired, so price is left for the operator instead of guessed.
        self.assertEqual(office["unanswered"], ["price"])
        self.assertIn("{answer needed: Price}", body)
        self.assertNotIn("$199", queue.message_text(body))
        self.assertTrue(any("answer needed" in x for x in office["blocking_issues"]))
        self.assertIn("expired", body)

        _, member, body = d["member"]
        # Parking is approved for offices only; members didn't ask, and the tour fact isn't repeated.
        self.assertNotIn("parking", queue.message_text(body).lower())
        self.assertEqual(queue.message_text(body).count("Tours run every weekday"), 1)

        _, plain, body = d["plain"]
        self.assertEqual((plain["topics_asked"], plain["blocking_issues"]), ([], []))

    def test_operator_must_fill_the_gap_and_receipts_still_apply(self):
        self.make()
        path, meta, _ = self.drafts()["office"]
        with self.assertRaises(ValueError):
            queue.approve(self.ws, meta["id"], "op", AS_OF)
        path.write_text(path.read_text().replace("{answer needed: Price}", "Offices start at $900 a month."))
        with self.assertRaises(ValueError) as e:
            queue.approve(self.ws, meta["id"], "op", AS_OF)
        self.assertIn("$900", str(e.exception))
        path.write_text(path.read_text().replace("Offices start at $900 a month.",
                                                 "I'll send you the current office options today."))
        approved = queue.approve(self.ws, meta["id"], "op", AS_OF)
        self.assertTrue(approved["edited"])
        queue.mark_sent(self.ws, self.ledger, meta["id"], "op", AS_OF + timedelta(hours=1))
        (state,) = [s for s in self.ledger.states(AS_OF + timedelta(hours=2)) if s.ref == "office"]
        self.assertEqual(state.touches_out, 1)
        # Answered now: no second first response.
        main(["drafts", "make", "--client", str(self.root), "--at", (AS_OF + timedelta(hours=2)).isoformat()])
        self.assertEqual(len(queue.existing_drafts(self.ws, first_response.AGENT)), 3)

    def test_track_records_are_per_agent(self):
        self.make()
        _, meta, _ = self.drafts()["plain"]
        queue.approve(self.ws, meta["id"], "op", AS_OF)
        self.assertEqual(first_response.track_record(self.ws)["streak"], 1)
        self.assertEqual(reengage.track_record(self.ws)["decided"], 0)
        _, member, _ = self.drafts()["member"]
        queue.reject(self.ws, member["id"], "Too stiff", "op", AS_OF)
        self.assertIn("| first-response-drafter | Rejected", (self.root / "rules/corrections.md").read_text())

    def test_one_message_in_flight_per_lead_across_agents(self):
        self.assertEqual(main(["drafts", "make", "--client", str(self.root), "--at", AS_OF.isoformat()]), 0)
        leads = [m["lead"] for _, m, _ in queue.existing_drafts(self.ws)]
        self.assertEqual(sorted(leads), ["member", "office", "old", "plain"])
        self.assertEqual(len(leads), len(set(leads)))

    def test_kill_switch_and_missing_template(self):
        main(["pause", "--client", str(self.root), "--agent", first_response.AGENT, "--reason", "review"])
        self.assertEqual(self.make(), 2)
        self.assertEqual(queue.existing_drafts(self.ws), [])
        main(["resume", "--client", str(self.root), "--agent", first_response.AGENT])
        pb = self.root / "engines/conversion/playbook.toml"
        pb.write_text(PLAYBOOK.split("[reengage]")[0].replace("[first_response]", "[first_response_off]"))
        self.assertEqual(self.make(), 0)
        self.assertEqual(queue.existing_drafts(self.ws), [])

    def test_cockpit_flags_waiting_first_responses(self):
        self.make()
        data = cockpit.build(self.ws, self.ledger, AS_OF)
        self.assertTrue(any(d.startswith("Release 3 first response(s)") and "waited 2 days" in d
                            for d in data["decisions"]))


if __name__ == "__main__":
    unittest.main()
