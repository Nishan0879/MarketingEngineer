import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mefw.cli import main
from mefw.core.activity_log import ActivityLog
from mefw.core.control import Control
from mefw.core.errors import (DuplicateAction, LevelTooLow, LogTampered, NoSpec,
                              OutsideWorkspace, Paused, RateLimited, SensitiveData)
from mefw.core.ledger import Ledger
from mefw.core.pii import assert_field_allowed, scrub
from mefw.core.runner import Runner
from mefw.core.workspace import Workspace

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
AGENT = "cold-inquiry-auditor"


def make_ws(tmp: Path, **agent_overrides) -> Workspace:
    root = tmp / "client"
    assert main(["init", str(root), "--client-id", "acme"]) == 0
    if agent_overrides:
        cfg = root / "profile/mefw.toml"
        text = cfg.read_text()
        for k, v in agent_overrides.items():
            text = text.replace(f"\n{k} = ", f"\n{k} = {v}  # was ", 1)
        cfg.write_text(text)
    return Workspace(root)


class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log = ActivityLog(self.tmp / "log.jsonl", "acme")

    def test_chain_verifies(self):
        for i in range(3):
            self.log.append("a", "x", "ok", {"i": i})
        self.assertEqual(self.log.verify(), 3)

    def test_edit_is_detected(self):
        self.log.append("a", "x", "ok")
        self.log.append("a", "y", "ok")
        lines = self.log.path.read_text().splitlines()
        e = json.loads(lines[0])
        e["result"] = "failed"
        lines[0] = json.dumps(e, sort_keys=True)
        self.log.path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(LogTampered):
            self.log.verify()

    def test_deletion_is_detected(self):
        for i in range(3):
            self.log.append("a", "x", "ok", {"i": i})
        lines = self.log.path.read_text().splitlines()
        self.log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
        with self.assertRaises(LogTampered):
            self.log.verify()


class ControlTests(unittest.TestCase):
    def test_scopes(self):
        c = Control(Path(tempfile.mkdtemp()) / "pause.json")
        c.check("conversion", "a")
        c.pause("engine", "conversion", "testing", "op")
        with self.assertRaises(Paused):
            c.check("conversion", "a")
        c.check("content", "b")
        c.resume("engine", "conversion")
        c.check("conversion", "a")

    def test_corrupt_file_fails_closed(self):
        p = Path(tempfile.mkdtemp()) / "pause.json"
        p.write_text("{not json")
        with self.assertRaises(Paused):
            Control(p).check("conversion", "a")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def runner(self, **overrides):
        self.ws = make_ws(self.tmp, **overrides)
        r = Runner(self.ws)
        self.addCleanup(r.close)
        return r

    def results(self, r):
        return [e["result"] for e in r.log.entries() if e["agent"] == AGENT]

    def test_happy_path_and_dedupe(self):
        r = self.runner()
        calls = []
        job = lambda: calls.append(1) or {"summary": "done"}
        self.assertEqual(r.run(AGENT, "audit", "observe", "k1", job).status, "ok")
        self.assertEqual(r.run(AGENT, "audit", "observe", "k1", job).status, "duplicate")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.results(r), ["ok", "skipped_duplicate"])

    def test_kill_switch_blocks_and_logs(self):
        r = self.runner()
        r.control.pause("client", None, "holiday", "op")
        with self.assertRaises(Paused):
            r.run(AGENT, "audit", "observe", "k1", lambda: {})
        self.assertEqual(self.results(r), ["blocked"])

    def test_no_spec_no_run(self):
        r = self.runner()
        (self.ws.root / "agents/cold-inquiry-auditor.md").unlink()
        with self.assertRaises(NoSpec):
            r.run(AGENT, "audit", "observe", "k1", lambda: {})

    def test_unknown_agent_no_run(self):
        r = self.runner()
        with self.assertRaises(NoSpec):
            r.run("ghost", "audit", "observe", "k1", lambda: {})

    def test_level_enforced(self):
        r = self.runner()
        with self.assertRaises(LevelTooLow):
            r.run(AGENT, "send", "act", "k1", lambda: {})

    def test_daily_cap(self):
        r = self.runner(max_actions_per_day=2)
        r.run(AGENT, "audit", "observe", "k1", lambda: {})
        r.run(AGENT, "audit", "observe", "k2", lambda: {})
        with self.assertRaises(RateLimited):
            r.run(AGENT, "audit", "observe", "k3", lambda: {})

    def test_observe_failure_can_retry(self):
        r = self.runner()
        def boom():
            raise RuntimeError("flaky")
        with self.assertRaises(RuntimeError):
            r.run(AGENT, "audit", "observe", "k1", boom)
        res = r.run(AGENT, "audit", "observe", "k1", lambda: {"summary": "ok"})
        self.assertEqual((res.status, res.key), ("ok", "k1#retry1"))

    def test_unsafe_retry_refused_and_agent_paused(self):
        r = self.runner(level=2)
        # Above Level 1 only a recorded promotion counts (autonomy.py), never the profile alone.
        with self.assertRaises(LevelTooLow):
            r.run(AGENT, "send", "act", "send:L-0", lambda: {})
        (self.ws.root / "control").mkdir(exist_ok=True)
        (self.ws.root / "control/autonomy.json").write_text(json.dumps({AGENT: {"level": 2, "since": "2026-10-01"}}))
        def boom():
            raise RuntimeError("timeout after sending?")
        with self.assertRaises(RuntimeError):
            r.run(AGENT, "send", "act", "send:L-1", boom)
        with self.assertRaises(DuplicateAction):
            r.run(AGENT, "send", "act", "send:L-1", lambda: {})
        with self.assertRaises(Paused):
            r.control.check("conversion", AGENT)

    def test_repeated_failures_pause_agent(self):
        r = self.runner()
        def boom():
            raise RuntimeError("bad")
        for k in ("a", "b"):
            with self.assertRaises(RuntimeError):
                r.run(AGENT, "audit", "observe", k, boom)
        self.assertIn("escalated", [e["result"] for e in r.log.entries()])
        with self.assertRaises(Paused):
            r.run(AGENT, "audit", "observe", "c", lambda: {})

    def test_tampered_log_stops_everything(self):
        r = self.runner()
        r.run(AGENT, "audit", "observe", "k1", lambda: {})
        r.log.path.write_text(r.log.path.read_text().replace('"ok"', '"failed"', 1))
        with self.assertRaises(LogTampered):
            r.run(AGENT, "audit", "observe", "k2", lambda: {})

    def test_paths_stay_in_workspace(self):
        self.runner()
        with self.assertRaises(OutsideWorkspace):
            self.ws.path("../other-client/data/ledger.db")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.l = Ledger(Path(tempfile.mkdtemp()) / "ledger.db", "acme")
        self.addCleanup(self.l.close)
        self.lead = self.l.upsert_lead("crm", "L-1")

    def test_events_are_append_only(self):
        self.l.add_event(self.lead, "inquired", T0, "crm")
        with self.assertRaises(sqlite3.DatabaseError):
            self.l.db.execute("DELETE FROM lead_events")
        with self.assertRaises(sqlite3.DatabaseError):
            self.l.db.execute("UPDATE lead_events SET at = 'x'")

    def test_same_event_recorded_once(self):
        self.assertTrue(self.l.add_event(self.lead, "inquired", T0, "crm"))
        self.assertFalse(self.l.add_event(self.lead, "inquired", T0, "crm"))

    def test_lost_needs_reason(self):
        with self.assertRaises(ValueError):
            self.l.record_outcome(self.lead, "lost", T0, "op")
        self.l.record_outcome(self.lead, "lost", T0, "op", reason="price")

    def test_latest_outcome_wins(self):
        self.l.add_event(self.lead, "inquired", T0, "crm")
        self.l.record_outcome(self.lead, "lost", T0 + timedelta(days=1), "op", reason="price")
        self.l.record_outcome(self.lead, "reopened", T0 + timedelta(days=2), "op")
        self.l.record_outcome(self.lead, "won", T0 + timedelta(days=3), "op")
        (s,) = self.l.states(T0 + timedelta(days=10))
        self.assertEqual((s.outcome, s.lost_reason), ("won", None))
        (s,) = self.l.states(T0 + timedelta(days=1, hours=1))
        self.assertEqual((s.outcome, s.lost_reason), ("lost", "price"))


class PiiTests(unittest.TestCase):
    def test_blocked_columns(self):
        for col in ("Email", "Phone Number", "Full Name", "Credit Score"):
            with self.assertRaises(SensitiveData):
                assert_field_allowed(col)
        assert_field_allowed("Lead ID")

    def test_scrub(self):
        out = scrub("Call me on +1 (555) 123-4567 or jo@example.com")
        self.assertNotIn("555", out)
        self.assertNotIn("example.com", out)


if __name__ == "__main__":
    unittest.main()
