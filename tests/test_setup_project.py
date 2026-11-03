"""Tests for scripts/setup_project.py (FR-plugin-packaging-11 to 19).

Each test builds a scratch project and a fixture plugin root in a temporary directory.
"""

import io
import json
import re
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import setup_project  # noqa: E402

ROLE_NAMES = ["code_auditor", "deploy_verifier", "issue_worker",
              "review_scribe", "ux_explorer", "ci_watcher"]


class SetupProjectTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.project = base / "project"
        self.project.mkdir()
        self.plugin = base / "plugin"
        (self.plugin / "roles").mkdir(parents=True)
        for name in ROLE_NAMES:
            (self.plugin / "roles" / f"{name}.toml").write_text(
                f'developer_instructions = "{name}"\n', encoding="utf-8")

    def apply(self, *extra, accept=None):
        files = setup_project.plan_files(self.project, self.plugin,
                                         "--with-default-permissions" in extra)
        chosen = sorted(files) if accept is None else accept
        setup_project.apply_files(self.project, files, chosen)

    def config(self):
        return (self.project / ".codex" / "config.toml").read_text(encoding="utf-8")

    def test_writes_the_block_into_a_missing_config_file(self):
        self.apply()
        text = self.config()
        self.assertTrue(text.startswith("# issue-flow:begin"))
        self.assertTrue(text.endswith("# issue-flow:end\n"))
        parsed = tomllib.loads(text)
        self.assertEqual(parsed["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 7)
        self.assertEqual(parsed["permissions"]["issue_flow"]["extends"], ":workspace")

    def test_writes_six_role_files_the_block_and_the_gitignore_line_and_nothing_else(self):
        self.apply()
        written = sorted(str(p.relative_to(self.project))
                         for p in self.project.rglob("*") if p.is_file())
        expected = sorted([f".codex/agents/{n}.toml" for n in ROLE_NAMES]
                          + [".codex/config.toml", ".gitignore"])
        self.assertEqual(written, expected)
        self.assertEqual((self.project / ".gitignore").read_text(encoding="utf-8"), ".worktrees/\n")

    def test_replaces_the_block_and_keeps_user_lines(self):
        user_before = 'model = "x"\n'
        user_after = '[tui]\ntheme = "dark"\n'
        self.apply()
        block = self.config()
        (self.project / ".codex" / "config.toml").write_text(
            user_before + "\n" + block.replace("= 7", "= 99") + "\n" + user_after, encoding="utf-8")
        self.apply()
        text = self.config()
        self.assertEqual(text.count("# issue-flow:begin"), 1)
        self.assertIn("= 7", text)
        self.assertNotIn("= 99", text)
        self.assertTrue(text.startswith(user_before))
        self.assertTrue(text.endswith(user_after))

    def test_keeps_every_user_line_when_it_adds_the_block(self):
        user = 'model = "x"\n# a note\n\n[tui]\ntheme = "dark"\n'
        (self.project / ".codex").mkdir()
        (self.project / ".codex" / "config.toml").write_text(user, encoding="utf-8")
        self.apply()
        lines = self.config().splitlines()
        for line in user.splitlines():
            if line:
                self.assertIn(line, lines)
        tomllib.loads(self.config())

    def test_puts_default_permissions_before_the_first_table(self):
        (self.project / ".codex").mkdir()
        (self.project / ".codex" / "config.toml").write_text(
            '[tui]\ntheme = "dark"\n', encoding="utf-8")
        self.apply("--with-default-permissions")
        text = self.config()
        self.assertLess(text.index("default_permissions"), text.index("[tui]"))
        self.assertEqual(tomllib.loads(text)["default_permissions"], "issue_flow")

    def test_omits_default_permissions_without_the_flag(self):
        self.apply()
        self.assertNotIn("default_permissions", self.config())

    def test_sets_the_thread_limit_to_concurrency_plus_four(self):
        (self.project / ".issue-flow.json").write_text(json.dumps({"concurrency": 5}), encoding="utf-8")
        self.apply()
        self.assertIn("max_concurrent_threads_per_session = 9", self.config())

    def test_copies_each_role_file(self):
        self.apply()
        for name in ROLE_NAMES:
            self.assertEqual((self.project / ".codex" / "agents" / f"{name}.toml").read_text(encoding="utf-8"),
                             f'developer_instructions = "{name}"\n')

    def test_adds_worktrees_to_gitignore_once(self):
        (self.project / ".gitignore").write_text("node_modules", encoding="utf-8")
        self.apply()
        self.apply()
        self.assertEqual((self.project / ".gitignore").read_text(encoding="utf-8"),
                         "node_modules\n.worktrees/\n")

    def test_writes_only_the_accepted_files(self):
        self.apply(accept=[".gitignore"])
        self.assertFalse((self.project / ".codex").exists())
        self.assertTrue((self.project / ".gitignore").exists())

    def test_rejects_a_file_that_the_plan_does_not_hold(self):
        with self.assertRaises(setup_project.SetupError):
            self.apply(accept=["README.md"])

    def test_plan_shows_a_diff_for_each_changed_file_and_writes_nothing(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_project.main(["plan", "--project", str(self.project),
                                       "--plugin-root", str(self.plugin)])
        self.assertEqual(code, 0)
        self.assertIn("+++ b/.codex/config.toml", out.getvalue())
        self.assertIn("+++ b/.gitignore", out.getvalue())
        self.assertFalse((self.project / ".codex").exists())

    def test_plan_reports_no_changes_after_apply(self):
        self.apply()
        out = io.StringIO()
        with redirect_stdout(out):
            setup_project.main(["plan", "--project", str(self.project),
                                "--plugin-root", str(self.plugin)])
        self.assertEqual(out.getvalue().strip(), "no changes")

    def test_fails_on_a_block_with_no_end_marker(self):
        (self.project / ".codex").mkdir()
        (self.project / ".codex" / "config.toml").write_text("# issue-flow:begin\n", encoding="utf-8")
        with self.assertRaises(setup_project.SetupError):
            self.apply()

    def test_block_text_matches_the_feature_file(self):
        spec = (ROOT / "docs/specs/features/01-plugin-packaging.md").read_text(encoding="utf-8")
        match = re.search(r"```toml\n(# issue-flow:begin.*?# issue-flow:end)\n```", spec, re.S)
        self.assertEqual(setup_project.render_block(3, True) + "\n", match.group(1) + "\n")


if __name__ == "__main__":
    unittest.main()
