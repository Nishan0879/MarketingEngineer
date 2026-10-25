import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.adapters.base import LeadRecord, import_records
from mefw.cli import main
from mefw.core import cockpit, experiments, metrics
from mefw.core.ledger import Ledger
from mefw.core.workspace import Workspace

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)  # a Sunday, ISO week 43
ROOT = Path(__file__).resolve().parents[1]


def ago(days: float) -> datetime:
    return AS_OF - timedelta(days=days)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "acme"])
        self.ws = Workspace(self.root)
        self.ledger = Ledger(self.ws.db_path, "acme")
        self.addCleanup(self.ledger.close)

    def leads(self, records):
        class Src:
            name = "crm"

            def records(_):
                return records
        import_records(self.ws, self.ledger, Src())

    def cohort(self, prefix, start_days_ago, n, met, channel="Web"):
        """n leads spread over 10 days from start_days_ago, the first `met` of them toured."""
        recs = []
        for i in range(n):
            at = ago(start_days_ago - i * 10 / n)
            recs.append(LeadRecord(ref=f"{prefix}{i}", inquired_at=at, channel=channel,
                                   stage_dates={"Tour Booked": at + timedelta(days=2)} if i < met else {}))
        self.leads(recs)


class MetricTests(Base):
    def test_rates_only_count_mature_leads(self):
        self.cohort("old", 60, 10, met=5)
        self.cohort("new", 5, 10, met=0)  # too recent to judge on tours
        v = metrics.compute("inquiry_to_meeting", self.ledger.states(AS_OF), AS_OF, 30)
        self.assertEqual((v.value, v.n), (0.5, 10))

    def test_change_is_signed_so_positive_is_better(self):
        up = metrics.relative_change("inquiry_to_meeting", metrics.Value(0.6, 10), metrics.Value(0.5, 10))
        faster = metrics.relative_change("first_response_minutes", metrics.Value(30, 10), metrics.Value(60, 10))
        self.assertAlmostEqual(up, 0.2)
        self.assertAlmostEqual(faster, 0.5)


class ExperimentTests(Base):
    def make(self, **kw):
        path = experiments.new(self.ws, self.ledger, "Reply within an hour", "inquiry_to_meeting",
                               "If we reply within an hour, more prospects will tour.", ago(80),
                               min_leads=10, min_window_days=14, baseline_days=40, **kw)
        return experiments.load(path)[0]["id"]

    def test_lifecycle_and_suggested_verdicts(self):
        self.cohort("base", 110, 20, met=6)   # baseline window: 30% toured
        exp = self.make()
        with self.assertRaises(ValueError):
            experiments.transition(self.ws, exp, "start", "op", ago(79))  # must be approved first
        experiments.transition(self.ws, exp, "approve", "op", ago(79))
        experiments.transition(self.ws, exp, "start", "op", ago(70))
        self.cohort("test", 65, 20, met=10)   # experiment window: 50% toured

        _, meta, _ = experiments.find(self.ws, exp)
        early = experiments.measure(self.ws, self.ledger, meta, ago(64))
        self.assertEqual(early["suggested"], "inconclusive")  # window and volume not met yet

        res = experiments.measure(self.ws, self.ledger, meta, AS_OF)
        self.assertEqual((res["test"]["n"], res["baseline"]["n"]), (20, 20))
        self.assertAlmostEqual(res["change"], 0.5 / 0.3 - 1)
        self.assertEqual(res["suggested"], "keep")
        experiments.log_measurement(self.ws, exp, res)
        experiments.log_measurement(self.ws, exp, res)  # once per day
        path, _, body = experiments.find(self.ws, exp)
        self.assertEqual(body.count("suggested **keep**"), 1)

        dest = experiments.close(self.ws, exp, "keep", "Replying within an hour lifted tours for members.",
                                 "low", "50% vs. 30%", "op", AS_OF)
        self.assertFalse(path.exists())
        self.assertIn("- **Verdict:** keep", dest.read_text())
        self.assertIn("lifted tours", (self.root / "experiments/lessons.md").read_text())

    def test_changed_criteria_block_a_verdict(self):
        self.cohort("base", 110, 20, met=6)
        exp = self.make()
        experiments.transition(self.ws, exp, "approve", "op", ago(79))
        experiments.transition(self.ws, exp, "start", "op", ago(70))
        self.cohort("test", 65, 20, met=10)
        path, meta, body = experiments.find(self.ws, exp)
        meta["keep_if"] = 0.9  # moving the goalposts after approval
        path.write_text(experiments.dump(meta, body))
        res = experiments.measure(self.ws, self.ledger, experiments.find(self.ws, exp)[1], AS_OF)
        self.assertEqual(res["suggested"], "inconclusive")
        self.assertIn("criteria changed after approval", res["reason"])

    def test_holdout_compares_channels_over_same_dates(self):
        exp = self.make(channels=["Web"], comparison="holdout")
        experiments.transition(self.ws, exp, "approve", "op", ago(79))
        experiments.transition(self.ws, exp, "start", "op", ago(70))
        self.cohort("web", 65, 12, met=6, channel="Web")
        self.cohort("ig", 65, 12, met=3, channel="Instagram")
        res = experiments.measure(self.ws, self.ledger, experiments.find(self.ws, exp)[1], AS_OF)
        self.assertEqual((res["test"]["value"], res["baseline"]["value"]), (0.5, 0.25))

    def test_holdout_needs_channels(self):
        with self.assertRaises(ValueError):
            self.make(comparison="holdout")


class CockpitTests(Base):
    def test_memo_sections_and_numbers(self):
        self.leads([
            LeadRecord(ref="w1", inquired_at=ago(20), value=1000, outcome="won", outcome_at=ago(2)),
            LeadRecord(ref="w2", inquired_at=ago(30), outcome="won", outcome_at=ago(9)),
            LeadRecord(ref="l1", inquired_at=ago(30), outcome="lost", outcome_at=ago(1), lost_reason="Price"),
            # Quiet since 16.5 days ago with no reply from us: crossed the 14-day line this week.
            LeadRecord(ref="c1", inquired_at=ago(16.5)),
        ])
        experiments.new(self.ws, self.ledger, "Parking offer", "meeting_to_commit", "If ..., then ...", AS_OF)
        data = cockpit.build(self.ws, self.ledger, AS_OF)
        self.assertEqual(data["week"], "2026-W43")
        self.assertEqual((data["north_star"]["this_week"], data["north_star"]["last_week"]), (1, 1))
        self.assertEqual([x["ref"] for x in data["lost"]], ["l1"])
        self.assertEqual([x["ref"] for x in data["newly_cold"]], ["c1"])
        self.assertTrue(any("Approve or drop EXP-acme-001" in d for d in data["decisions"]))
        md = cockpit.render(data)
        for heading in ("## North star", "## Wins", "## Losses", "## What changed",
                        "## Recommended next tests", "## Agent errors", "## Decisions needed from the operator"):
            self.assertIn(heading, md)

        first = cockpit.write(self.ws, data)
        second = cockpit.write(self.ws, data)
        self.assertEqual((first, second), ("cockpit/2026-W43.md", "cockpit/2026-W43-2.md"))

    def test_agent_errors_show_up(self):
        main(["pause", "--client", str(self.root), "--agent", "growth-cockpit", "--reason", "testing"])
        self.assertEqual(main(["cockpit", "--client", str(self.root), "--as-of", AS_OF.isoformat()]), 2)
        main(["resume", "--client", str(self.root), "--agent", "growth-cockpit"])
        data = cockpit.build(self.ws, self.ledger, datetime.now(timezone.utc))
        self.assertTrue(any(e["result"] == "blocked" for e in data["agent_errors"]))


class CliEndToEndTests(unittest.TestCase):
    def test_coworking_example_full_loop(self):
        import importlib.util
        tmp = Path(tempfile.mkdtemp())
        spec = importlib.util.spec_from_file_location("make_sample", ROOT / "examples/make_sample.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(tmp / "data")
        client = tmp / "client"
        main(["init", str(client), "--client-id", "demo"])
        (client / "profile/mefw.toml").write_text(
            (ROOT / "examples/coworking/mefw.toml").read_text().replace("{client_id}", "demo"))
        c, d = ["--client", str(client)], tmp / "data"
        self.assertEqual(main(["import-csv", *c, str(d / "sample_leads.csv"),
                               "--activities", str(d / "sample_activities.csv")]), 0)
        self.assertEqual(main(["import-signals", *c, str(d / "sample_signals.csv")]), 0)
        self.assertEqual(main(["experiment", "new", *c, "--name", "Fast replies", "--segment", "members",
                               "--metric", "inquiry_to_meeting", "--hypothesis", "If ..., then ...",
                               "--at", "2026-08-20T09:00"]), 0)
        for action, at in (("approve", "2026-08-21T09:00"), ("start", "2026-08-22T09:00")):
            self.assertEqual(main(["experiment", action, *c, "EXP-demo-001", "--at", at]), 0)
        self.assertEqual(main(["experiment", "measure", *c, "--at", "2026-10-25T12:00"]), 0)
        self.assertEqual(main(["cockpit", *c, "--as-of", "2026-10-25T12:00"]), 0)
        memo = (client / "cockpit/2026-W43.md").read_text()
        self.assertIn("Signed memberships and office leases", memo)
        self.assertIn("EXP-demo-001", memo)
        self.assertEqual(main(["experiment", "close", *c, "EXP-demo-001", "--verdict", "iterate",
                               "--confidence", "low", "--lesson", "Speed alone didn't move tours."]), 0)
        self.assertEqual(main(["log", "verify", *c]), 0)


if __name__ == "__main__":
    unittest.main()
