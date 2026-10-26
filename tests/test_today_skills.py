import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mefw import skills
from mefw.cli import main

ROOT = Path(__file__).resolve().parents[1]


def run(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "client"
        run("init", str(self.root), "--client-id", "acme")


class TodayTests(Base):
    def test_lists_what_needs_the_operator_without_logging_anything(self):
        log = self.root / "logs/agent-activity.jsonl"
        before = log.read_text()
        code, out = run("today", "--client", str(self.root), "--at", "2026-10-26T12:00")
        self.assertEqual(code, 0)
        self.assertIn("Activity log: OK", out)
        self.assertIn("Paused: nothing", out)
        self.assertEqual(log.read_text(), before)

    def test_paused_and_waiting_work_shows_up(self):
        run("pause", "--client", str(self.root), "--agent", "cold-inquiry-auditor", "--reason", "checking data")
        code, out = run("today", "--client", str(self.root), "--at", "2026-10-26T12:00", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["paused"], ["cold-inquiry-auditor (checking data)"])
        self.assertTrue(any("cold-inquiry-auditor" in d and "paused" in d for d in data["decisions"]))
        self.assertTrue(data["activity_log_ok"])

    def test_a_broken_log_is_reported(self):
        log = self.root / "logs/agent-activity.jsonl"
        log.write_text(log.read_text().replace("Workspace created", "Edited"))
        code, out = run("today", "--client", str(self.root), "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["activity_log_ok"])


class SkillTests(Base):
    def test_shipped_skills_are_well_formed(self):
        shipped = skills.shipped()
        self.assertIn("mefw-today", shipped)
        for name, text in shipped.items():
            front = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(front, name)
            self.assertEqual(front.group(1), name)
            self.assertLessEqual(len(front.group(2)), 1024)
            self.assertIn("## Running mefw", text)
        # every subcommand a skill names must exist in the CLI
        cli = (ROOT / "mefw/cli.py").read_text()
        for name, text in shipped.items():
            for cmd in set(re.findall(r"`((?:drafts|outbound|search|content|creative|report) [a-z-]+)", text)):
                group, action = cmd.split()
                self.assertIn(f'"{action}"', cli, f"{name} names `{cmd}`")

    def test_init_installs_them_in_the_workspace(self):
        for name in skills.shipped():
            self.assertTrue((self.root / ".claude/skills" / name / "SKILL.md").exists())

    def test_install_updates_ours_and_leaves_other_skills_alone(self):
        dest = self.root / ".claude/skills"
        (dest / "mefw-today/SKILL.md").write_text("old")
        (dest / "mefw-retired").mkdir()
        (dest / "mefw-retired/SKILL.md").write_text("gone")
        (dest / "their-skill").mkdir()
        (dest / "their-skill/SKILL.md").write_text("keep")
        states = dict(skills.install(dest))
        self.assertEqual(states["mefw-today"], "updated")
        self.assertEqual(states["mefw-review"], "unchanged")
        self.assertEqual(states["mefw-retired"], "removed")
        self.assertFalse((dest / "mefw-retired").exists())
        self.assertEqual((dest / "their-skill/SKILL.md").read_text(), "keep")

    def test_install_for_the_user(self):
        home = self.tmp / "home"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            code, out = run("skills", "install", "--user")
        self.assertEqual(code, 0)
        self.assertTrue((home / ".claude/skills/mefw-today/SKILL.md").exists())
        self.assertIn("/mefw-today", out)


if __name__ == "__main__":
    unittest.main()
