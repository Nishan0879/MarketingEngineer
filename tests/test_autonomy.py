import json
import unittest
from datetime import timedelta

from mefw.adapters.base import LeadRecord
from mefw.cli import main
from mefw.core import autonomy, cockpit, quality
from mefw.core.errors import LevelTooLow
from mefw.core.runner import Runner
from mefw.engines.conversion import queue, reengage

from test_reengage import AS_OF, Base, ago

AGENT = reengage.AGENT


class AutonomyBase(Base):
    def setUp(self):
        super().setUp()
        p = self.root / "profile/mefw.toml"
        p.write_text(p.read_text().replace('spec = "agents/re-engagement-drafter.md"\nmax_actions_per_day = 25',
                                           'spec = "agents/re-engagement-drafter.md"\nmax_actions_per_day = 100'))
        from mefw.core.workspace import Workspace
        self.ws = Workspace(self.root)
        self.leads([LeadRecord(ref=f"p{i}", inquired_at=ago(60)) for i in range(24)]
                   + [LeadRecord(ref="few", inquired_at=ago(40), touches=[(ago(40) + timedelta(minutes=10), "out")])])
        main(["drafts", "make", "--client", str(self.root), "--at", AS_OF.isoformat(), "--max", "25",
              "--agent", AGENT])
        self.clean = [m for _, m, _ in queue.existing_drafts(self.ws, AGENT) if not m["blocking_issues"]]
        (self.root / "engines/conversion/level2-playbook.md").write_text("Send only never_responded drafts.\n")

    def approve_clean(self, n, edited_every=0):
        for i, m in enumerate(self.clean[:n]):
            path, meta, body = queue.find(self.ws, m["id"])
            if edited_every and i % edited_every == 0:
                path.write_text(path.read_text().replace("we never replied.", "we never got back to you."))
            queue.approve(self.ws, m["id"], "op", AS_OF + timedelta(days=i))

    def spec(self):
        return (self.root / f"agents/{AGENT}.md").read_text()


class LevelTests(AutonomyBase):
    def test_profile_alone_cannot_go_above_level_1(self):
        p = self.root / "profile/mefw.toml"
        p.write_text(p.read_text().replace('spec = "agents/re-engagement-drafter.md"',
                                           'spec = "agents/re-engagement-drafter.md"\nlevel = 2', 1)
                     .replace("level = 1                     # drafts only; a human approves and sends\n"
                              'spec = "agents/re-engagement-drafter.md"', 'spec = "agents/re-engagement-drafter.md"'))
        from mefw.core.workspace import Workspace
        ws = Workspace(self.root)
        self.assertEqual(ws.config.agents[AGENT].level, 2)
        self.assertEqual(autonomy.level(ws, AGENT), 1)

    def test_promotion_to_level_2_needs_track_record_and_playbook(self):
        at = AS_OF + timedelta(days=30)
        self.assertTrue(any("no approved or rejected drafts" in m for m in autonomy.promotion_check(self.ws, AGENT, at)))
        self.approve_clean(20)
        self.assertTrue(any("--playbook" in m for m in autonomy.promotion_check(self.ws, AGENT, at)))
        with self.assertRaises(ValueError):
            autonomy.promote(self.ws, AGENT, "op", "ready", at, playbook="missing.md")
        r = autonomy.promote(self.ws, AGENT, "op", "20 clean approvals", at,
                             playbook="engines/conversion/level2-playbook.md")
        self.assertEqual((r["from"], r["level"]), (1, 2))
        self.assertEqual(autonomy.level(self.ws, AGENT), 2)
        self.assertIn("promoted from Level 1 to Level 2 by op: 20 clean approvals", self.spec())
        # The runner now allows Level 2 actions for this agent.
        runner = Runner(self.ws)
        self.addCleanup(runner.close)
        self.assertEqual(runner.run(AGENT, "send", "act", "send:test", lambda: {}).status, "ok")

    def test_serious_error_demotes_one_level(self):
        self.approve_clean(20)
        autonomy.promote(self.ws, AGENT, "op", "ready", AS_OF + timedelta(days=30),
                         playbook="engines/conversion/level2-playbook.md")
        r = autonomy.report_serious_error(self.ws, AGENT, "opted_out_contact", "emailed L-9", "op",
                                          AS_OF + timedelta(days=31))
        self.assertEqual((r["from"], r["level"]), (2, 1))
        self.assertIn("demoted from Level 2 to Level 1", self.spec())
        runner = Runner(self.ws)
        self.addCleanup(runner.close)
        with self.assertRaises(LevelTooLow):
            runner.run(AGENT, "send", "act", "send:again", lambda: {})
        with self.assertRaises(ValueError):
            autonomy.report_serious_error(self.ws, AGENT, "oops", "", "op", AS_OF)

    def test_error_budget(self):
        self.approve_clean(20)
        autonomy.promote(self.ws, AGENT, "op", "ready", AS_OF + timedelta(days=30),
                         playbook="engines/conversion/level2-playbook.md")
        self.assertEqual(autonomy.enforce_error_budget(self.ws, AS_OF + timedelta(days=30)), [])
        # Three more drafts, all edited: 3 of the last 20 are corrections (15%), under the 25% budget.
        more = self.clean[20:23]
        for i, m in enumerate(more):
            path, _, _ = queue.find(self.ws, m["id"])
            path.write_text(path.read_text().replace("we never replied.", "we never got back to you."))
            queue.approve(self.ws, m["id"], "op", AS_OF + timedelta(days=31 + i))
        self.assertEqual(autonomy.enforce_error_budget(self.ws, AS_OF + timedelta(days=34)), [])
        p = self.root / "profile/mefw.toml"
        p.write_text(p.read_text().replace("max_actions_per_day = 100\n", "max_actions_per_day = 100\nmax_correction_rate = 0.1\n", 1))
        from mefw.core.workspace import Workspace
        ws = Workspace(self.root)
        (d,) = autonomy.enforce_error_budget(ws, AS_OF + timedelta(days=34))
        self.assertEqual((d["agent"], d["level"]), (AGENT, 1))
        self.assertIn("correction rate 15%", d["reason"])

    def test_level_0_and_level_3_bars(self):
        cockpit_agent = "growth-cockpit"
        self.assertTrue(autonomy.promotion_check(self.ws, cockpit_agent, AS_OF))
        main(["cockpit", "--client", str(self.root)])
        main(["cockpit", "--client", str(self.root), "--as-of", (AS_OF - timedelta(days=1)).isoformat()])
        from datetime import datetime, timezone
        later = datetime.now(timezone.utc) + timedelta(days=15)
        self.assertEqual(autonomy.promotion_check(self.ws, cockpit_agent, later), [])

        self.approve_clean(20)
        autonomy.promote(self.ws, AGENT, "op", "ready", AS_OF + timedelta(days=30),
                         playbook="engines/conversion/level2-playbook.md")
        missing = autonomy.promotion_check(self.ws, AGENT, AS_OF + timedelta(days=40))
        self.assertEqual(len(missing), 3)  # 30 days at Level 2, budget cap, client approval
        self.assertEqual(autonomy.promotion_check(self.ws, AGENT, AS_OF + timedelta(days=61), budget_cap=500,
                                                  client_approval="email from owner, 2026-12-20"), [])

    def test_unreadable_autonomy_file_fails_closed(self):
        (self.root / "control").mkdir(exist_ok=True)
        (self.root / "control/autonomy.json").write_text("{not json")
        self.assertEqual(autonomy.level(self.ws, AGENT), 0)
        runner = Runner(self.ws)
        self.addCleanup(runner.close)
        with self.assertRaises(LevelTooLow):
            runner.run(AGENT, "draft_reengagement", "draft", "k", lambda: {})

    def test_cli(self):
        c = ["--client", str(self.root)]
        self.assertEqual(main(["promote", AGENT, *c, "--check"]), 0)
        self.assertEqual(main(["promote", AGENT, *c, "--reason", "x"]), 1)  # refused: bar not met
        self.assertEqual(main(["demote", AGENT, *c, "--kind", "operator", "--note", "pausing drafts"]), 0)
        self.assertEqual(autonomy.level(self.ws, AGENT), 0)
        self.assertEqual(main(["quality", *c]), 0)
        self.assertEqual(main(["log", "verify", *c]), 0)


class QualityTests(AutonomyBase):
    def test_scorecard_and_cockpit(self):
        self.approve_clean(4, edited_every=2)  # 2 edited, 2 clean
        self.assertEqual(self.drafts()["few"][1]["leak"], "few_followups")
        _, few, _ = self.drafts()["few"]
        queue.reject(self.ws, few["id"], "Expired promo", "op", AS_OF + timedelta(hours=3))
        rows = {r["agent"]: r for r in quality.scorecard(self.ws, AS_OF + timedelta(days=5))}
        r = rows[AGENT]
        self.assertEqual(r["decided"], 5)
        self.assertAlmostEqual(r["unedited_rate"], 2 / 5)
        self.assertEqual(r["claims_caught"], 1)  # the expired-fact draft
        self.assertEqual(r["correction_n"], 5)
        self.assertTrue(r["over_budget"])        # 3 of 5 corrected > 25%
        self.assertIn("| re-engagement-drafter |", quality.render(list(rows.values()), 28))

        data = cockpit.build(self.ws, self.ledger, AS_OF + timedelta(days=5))
        self.assertTrue(any("over its 25% budget" in d for d in data["decisions"]))
        md = cockpit.render(data)
        self.assertIn("approved without edits", md)


if __name__ == "__main__":
    unittest.main()
