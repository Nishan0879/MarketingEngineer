import fcntl
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mefw.cli import main
from mefw.core import cockpit, scheduler
from mefw.core.ledger import Ledger
from mefw.core.scheduler import Schedule
from mefw.core.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class ScheduleParsingTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(Schedule.parse("every 2h").minutes, 120)
        self.assertEqual(Schedule.parse("every 30m").minutes, 30)
        self.assertEqual(Schedule.parse("hourly").minutes, 60)
        self.assertEqual(Schedule.parse("Weekly Monday 07:30").weekday, 0)
        for bad in ("every 2 days", "daily 7am", "every 1m", "sometimes"):
            with self.assertRaises(ValueError):
                Schedule.parse(bad)

    def test_slots_follow_the_client_clock(self):
        ny = ZoneInfo("America/New_York")  # UTC-4 in late October
        now = at("2026-10-26T12:30")       # Monday 08:30 in New York
        self.assertEqual(Schedule.parse("daily 09:00").latest_slot(now, ny), at("2026-10-25T13:00"))
        self.assertEqual(Schedule.parse("daily 08:00").latest_slot(now, ny), at("2026-10-26T12:00"))
        self.assertEqual(Schedule.parse("weekly mon 07:00").latest_slot(now, ny), at("2026-10-26T11:00"))
        self.assertEqual(Schedule.parse("weekly fri 07:00").latest_slot(now, ny), at("2026-10-23T11:00"))
        self.assertEqual(Schedule.parse("every 3h").latest_slot(now, ny), at("2026-10-26T10:00"))  # 06:00 local
        self.assertEqual(Schedule.parse("every 3h").next_slot(now, ny), at("2026-10-26T13:00"))
        self.assertEqual(Schedule.parse("daily 08:00").next_slot(now, ny), at("2026-10-27T12:00"))


class Base(unittest.TestCase):
    SCHEDULE = """
[schedule]
import                 = "every 2h"
first-response-drafter = "every 2h"
cold-inquiry-auditor   = "weekly mon 06:00"
growth-cockpit         = "weekly mon 07:00"

[schedule.inbox]
leads = "inbox/leads.csv"
activities = "inbox/activities.csv"
signals = "inbox/signals.csv"
"""

    def setUp(self):
        import importlib.util
        self.tmp = Path(tempfile.mkdtemp())
        spec = importlib.util.spec_from_file_location("make_sample", ROOT / "examples/make_sample.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(self.tmp / "data")
        self.root = self.tmp / "client"
        main(["init", str(self.root), "--client-id", "demo"])
        profile = (ROOT / "examples/coworking/mefw.toml").read_text().replace("{client_id}", "demo")
        profile = profile[:profile.index("[schedule]")] + profile[profile.index("[conversion.cold_audit]"):]
        (self.root / "profile/mefw.toml").write_text(profile + self.SCHEDULE)
        for name in ("approved-facts.toml",):
            shutil.copy(ROOT / "examples/coworking" / name, self.root / "profile" / name)
        shutil.copy(ROOT / "examples/coworking/playbook.toml", self.root / "engines/conversion/playbook.toml")
        (self.root / "inbox").mkdir()
        for src, dst in (("sample_leads.csv", "leads.csv"), ("sample_activities.csv", "activities.csv"),
                         ("sample_signals.csv", "signals.csv")):
            shutil.copy(self.tmp / "data" / src, self.root / "inbox" / dst)
        self.ws = Workspace(self.root)

    def run_due(self, when):
        return {r["job"]: r for r in scheduler.run_due(self.ws, at(when))}


class RunDueTests(Base):
    def test_runs_what_is_due_in_order_once(self):
        first = scheduler.run_due(self.ws, at("2026-10-26T07:05"))
        self.assertEqual([r["job"] for r in first],
                         ["import", "cold-inquiry-auditor", "first-response-drafter", "growth-cockpit"])
        self.assertEqual({r["result"] for r in first}, {"ok"})
        self.assertTrue((self.root / "cockpit/2026-W44.md").exists())
        self.assertEqual(scheduler.run_due(self.ws, at("2026-10-26T07:50")), [])

        later = self.run_due("2026-10-26T08:01")
        self.assertEqual(sorted(later), ["first-response-drafter", "import"])
        self.assertEqual(later["import"]["result"], "skipped")  # exports unchanged
        self.assertIn("unchanged", later["import"]["summary"])

        with open(self.root / "inbox/leads.csv", "a") as f:
            f.write("L-9999,2026-10-26 08:30,Website form,Freelancer,3000,,,,0,New,,,Open,,,\n")
        self.assertEqual(self.run_due("2026-10-26T10:00")["import"]["result"], "ok")
        ledger = Ledger(self.ws.db_path, "demo")
        self.addCleanup(ledger.close)
        self.assertIn("L-9999", {s.ref for s in ledger.states(at("2026-10-26T10:00"))})
        self.assertEqual(main(["log", "verify", "--client", str(self.root)]), 0)

    def test_a_failed_slot_is_retried_once_then_left_for_the_operator(self):
        (self.root / "inbox/leads.csv").write_text("Wrong,Columns\n1,2\n")
        self.assertEqual(self.run_due("2026-10-26T08:01")["import"]["result"], "failed")
        retry = self.run_due("2026-10-26T08:16")
        self.assertEqual(retry["import"]["result"], "failed")
        self.assertIn("gave up", retry["import"]["reason"])
        self.assertNotIn("import", self.run_due("2026-10-26T08:31"))
        # Logged as failures, which the cockpit lists under agent errors.
        self.assertEqual([e["result"] for e in scheduler.history(self.ws) if e["inputs"]["job"] == "import"],
                         ["failed", "failed"])

    def test_guardrails_still_apply(self):
        main(["pause", "--client", str(self.root), "--agent", "growth-cockpit", "--reason", "review"])
        res = self.run_due("2026-10-26T07:05")
        self.assertEqual(res["growth-cockpit"]["result"], "blocked")
        self.assertEqual(res["cold-inquiry-auditor"]["result"], "ok")

    def test_overlapping_runs_are_refused(self):
        lock_path = self.root / scheduler.LOCK
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            res = scheduler.run_due(self.ws, at("2026-10-26T07:05"))
        self.assertEqual(res[0]["summary"], "another scheduled run is still going")
        self.assertEqual(scheduler.history(self.ws), [])

    def test_cockpit_flags_jobs_that_stopped_running(self):
        scheduler.run_due(self.ws, at("2026-10-26T07:05"))
        ledger = Ledger(self.ws.db_path, "demo")
        self.addCleanup(ledger.close)
        self.assertFalse(any("hasn't run" in d for d in cockpit.build(self.ws, ledger, at("2026-10-26T09:00"))["decisions"]))
        stale = cockpit.build(self.ws, ledger, at("2026-10-27T12:00"))["decisions"]
        self.assertTrue(any("`first-response-drafter` (every 2h) hasn't run since 2026-10-26 06:00" in d for d in stale))
        self.assertFalse(any("growth-cockpit` (weekly" in d for d in stale))

    def test_bad_schedule_is_reported(self):
        p = self.root / "profile/mefw.toml"
        p.write_text(p.read_text().replace('growth-cockpit         = "weekly mon 07:00"',
                                           'growth-cockpit = "weekly mon 07:00"\nnewsletter = "daily 08:00"'))
        ws = Workspace(self.root)
        with self.assertRaises(ValueError):
            scheduler.run_due(ws, at("2026-10-26T07:05"))
        self.assertEqual(main(["run-due", "--client", str(self.root), "--at", "2026-10-26T07:05"]), 1)


if __name__ == "__main__":
    unittest.main()
