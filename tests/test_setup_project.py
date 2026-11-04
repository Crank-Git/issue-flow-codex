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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import setup_project  # noqa: E402

ROLE_NAMES = ["code-auditor", "deploy-verifier", "issue-worker",
              "review-scribe", "ux-explorer", "ci-watcher"]


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
            role_name = name.replace("-", "_")
            (self.plugin / "roles" / f"{name}.toml").write_text(
                f'name = "{role_name}"\ndescription = "{name}"\nmodel = "plugin-model"\n'
                f'model_reasoning_effort = "medium"\n'
                f'developer_instructions = "{name}"\n', encoding="utf-8")
        (self.plugin / ".codex-plugin").mkdir()
        (self.plugin / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "issue-flow", "version": "0.1.0"}), encoding="utf-8")

    def apply(self, *extra, accept=None):
        flag = True if "--with-default-permissions" in extra else (
            False if "--without-default-permissions" in extra else None)
        files = setup_project.plan_files(self.project, self.plugin, flag)
        chosen = sorted(files) if accept is None else accept
        setup_project.apply_files(self.project, files, chosen)

    def config(self):
        return (self.project / ".codex" / "config.toml").read_text(encoding="utf-8")

    def test_setup_skill_routes_codex_changes_to_the_operator(self):
        skill = (ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Prints `.codex/` changes for operator application", skill)
        self.assertIn("The operator applies accepted `.codex/` changes outside Codex", skill)
        self.assertIn("Start a new `codex` session after applying `.codex/config.toml`", skill)

    def test_writes_the_block_into_a_missing_config_file(self):
        self.apply()
        text = self.config()
        self.assertTrue(text.startswith("# issue-flow:begin"))
        self.assertTrue(text.endswith("# issue-flow:end\n"))
        parsed = tomllib.loads(text)
        self.assertEqual(parsed["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 7)
        self.assertEqual(parsed["permissions"]["issue_flow"]["extends"], ":workspace")
        filesystem = parsed["permissions"]["issue_flow"]["filesystem"][":workspace_roots"]
        self.assertEqual(filesystem["."], "write")
        self.assertEqual(filesystem[".git"], "write")
        self.assertEqual(filesystem[".agents"], "write")
        self.assertNotIn(".codex", filesystem)

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
                             f'name = "{name.replace("-", "_")}"\ndescription = "{name}"\n'
                             f'model = "plugin-model"\n'
                             f'model_reasoning_effort = "medium"\n'
                             f"developer_instructions = '''\n{name}\n'''\n")

    def test_applies_configured_worker_model_and_effort_to_worker_role(self):
        (self.project / ".issue-flow.codex.json").write_text(
            json.dumps({"workerModel": "gpt-6-luna", "workerEffort": "low",
                        "helperModel": "gpt-6.1-sol"}), encoding="utf-8")
        self.apply()
        role = tomllib.loads((self.project / ".codex" / "agents" / "issue-worker.toml").read_text())
        self.assertEqual(role["model"], "gpt-6-luna")
        self.assertEqual(role["model_reasoning_effort"], "low")
        watcher = tomllib.loads((self.project / ".codex" / "agents" / "ci-watcher.toml").read_text())
        self.assertEqual(watcher["model"], "gpt-6.1-sol")
        self.assertEqual(watcher["model_reasoning_effort"], "medium")
        helper = tomllib.loads((self.project / ".codex" / "agents" / "code-auditor.toml").read_text())
        self.assertEqual(helper["model"], "gpt-6.1-sol")
        self.apply("--with-default-permissions")
        code, text = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("roles        ok", text)

    def test_applies_helper_model_only_to_helper_roles(self):
        (self.project / ".issue-flow.codex.json").write_text(
            json.dumps({"helperModel": "gpt-6.1-sol"}), encoding="utf-8")
        self.apply()
        for name in ("code-auditor", "deploy-verifier", "review-scribe", "ux-explorer"):
            role = tomllib.loads((self.project / ".codex" / "agents" / f"{name}.toml").read_text())
            self.assertEqual(role["model"], "gpt-6.1-sol")
        for name in ("issue-worker", "ci-watcher"):
            role = tomllib.loads((self.project / ".codex" / "agents" / f"{name}.toml").read_text())
            self.assertEqual(role["model"], "gpt-6.1-sol" if name == "ci-watcher" else "plugin-model")

    def test_preserves_model_like_text_in_developer_instructions(self):
        role = self.plugin / "roles" / "issue-worker.toml"
        role.write_text(
            'name = "issue_worker"\n'
            'description = "Issue worker"\n'
            "developer_instructions = '''Use this example:\nmodel = x\n'''\n"
            'model = "plugin-model"\n'
            'model_reasoning_effort = "medium"\n', encoding="utf-8")
        self.apply()
        rendered = (self.project / ".codex" / "agents" / "issue-worker.toml").read_text()
        parsed = tomllib.loads(rendered)
        self.assertEqual(parsed["developer_instructions"], "Use this example:\nmodel = x\n")

    def test_writes_configured_models_at_document_root(self):
        (self.project / ".issue-flow.codex.json").write_text(
            json.dumps({"workerModel": "gpt-6-luna", "workerEffort": "low"}), encoding="utf-8")
        self.apply()
        rendered = (self.project / ".codex" / "agents" / "issue-worker.toml").read_text()
        parsed = tomllib.loads(rendered)
        self.assertEqual(parsed["model"], "gpt-6-luna")
        self.assertEqual(parsed["model_reasoning_effort"], "low")

    def test_applies_helper_model_to_watcher_role(self):
        (self.project / ".issue-flow.codex.json").write_text(
            json.dumps({"helperModel": "gpt-6-luna"}), encoding="utf-8")

        self.apply()

        watcher = tomllib.loads((self.project / ".codex" / "agents" / "ci-watcher.toml").read_text())
        self.assertEqual(watcher["model"], "gpt-6-luna")

    def test_applies_only_the_config_file_after_concurrency_changes(self):
        self.apply("--with-default-permissions")
        (self.project / ".issue-flow.json").write_text(json.dumps({"concurrency": 5}), encoding="utf-8")
        files = setup_project.plan_files(self.project, self.plugin, None)
        written = setup_project.apply_files(self.project, files, [".codex/config.toml"])
        self.assertEqual(written, [".codex/config.toml"])
        code, text = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("threads      ok       max_concurrent_threads_per_session = 9", text)

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

    def test_keeps_default_permissions_on_a_rerun_when_it_is_already_present(self):
        self.apply("--with-default-permissions")
        self.apply()
        self.assertEqual(tomllib.loads(self.config())["default_permissions"], "issue_flow")

    def test_drops_default_permissions_when_the_operator_rejects_it(self):
        self.apply("--with-default-permissions")
        self.apply("--without-default-permissions")
        self.assertNotIn("default_permissions", self.config())

    def test_plan_says_when_it_keeps_default_permissions(self):
        self.apply("--with-default-permissions")
        (self.project / ".codex" / "config.toml").write_text(
            self.config().replace("= 7", "= 99"), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            setup_project.main(["plan", "--project", str(self.project),
                                "--plugin-root", str(self.plugin)])
        self.assertIn('note: .codex/config.toml keeps default_permissions = "issue_flow"', out.getvalue())

    def run_check(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_project.main(["check", "--project", str(self.project),
                                       "--plugin-root", str(self.plugin)])
        return code, out.getvalue()

    def test_check_reports_ok_for_a_set_up_project_except_hooks(self):
        self.apply("--with-default-permissions")
        code, text = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(text.splitlines(), [
            "roles        ok       6 of 6 match plugin 0.1.0",
            "config block ok",
            "threads      ok       max_concurrent_threads_per_session = 7",
            "profile      ok       default_permissions = issue_flow",
            "gitignore    ok",
            "hooks        unknown  run /hooks to see the trust state",
        ])

    def test_check_reports_missing_profile_and_exits_1(self):
        self.apply()
        code, text = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("profile      missing  default_permissions is not set to issue_flow", text)

    def test_check_reports_stale_after_one_byte_changes_in_a_role_file(self):
        self.apply("--with-default-permissions")
        role = self.project / ".codex" / "agents" / "issue-worker.toml"
        role.write_bytes(role.read_bytes() + b" ")
        code, text = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("roles        stale    5 of 6 match plugin 0.1.0", text)

    def test_check_reports_stale_when_a_role_model_differs_from_config(self):
        (self.project / ".issue-flow.codex.json").write_text(
            json.dumps({"workerModel": "gpt-6-luna"}), encoding="utf-8")
        self.apply("--with-default-permissions")
        role = self.project / ".codex" / "agents" / "issue-worker.toml"
        role.write_text(role.read_text().replace('model = "gpt-6-luna"', 'model = "wrong-model"'))

        code, text = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn("roles        stale", text)

    def test_check_reports_malformed_role_as_stale(self):
        self.apply("--with-default-permissions")
        role = self.project / ".codex" / "agents" / "issue-worker.toml"
        role.write_text("model = [invalid")
        code, text = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("roles        stale", text)

    def test_check_writes_one_stderr_line_for_a_malformed_role(self):
        self.apply("--with-default-permissions")
        role = self.project / ".codex" / "agents" / "issue-worker.toml"
        role.write_text("model = [invalid")
        err = io.StringIO()
        with redirect_stderr(err):
            self.run_check()
        self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_plan_reports_malformed_plugin_role_toml_on_one_stderr_line(self):
        role = self.plugin / "roles" / "issue-worker.toml"
        role.write_text("model = [invalid", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            code = setup_project.main(["plan", "--project", str(self.project),
                                       "--plugin-root", str(self.plugin)])
        self.assertEqual(code, 1)
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.assertIn("setup_project:", err.getvalue())

    def test_check_reports_missing_roles_on_an_empty_project(self):
        code, text = self.run_check()
        self.assertEqual(code, 1)
        lines = text.splitlines()
        self.assertEqual(lines[0], "roles        missing  0 of 6 match plugin 0.1.0")
        self.assertTrue(lines[1].startswith("config block missing"))
        self.assertTrue(lines[2].startswith("threads      missing"))
        self.assertTrue(lines[4].startswith("gitignore    missing"))

    def test_check_reports_stale_threads_when_the_concurrency_changes(self):
        self.apply("--with-default-permissions")
        (self.project / ".issue-flow.json").write_text(json.dumps({"concurrency": 5}), encoding="utf-8")
        code, text = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("threads      stale    max_concurrent_threads_per_session = 7, expected 9", text)
        self.assertIn("config block stale", text)

    def test_check_reports_stale_block_for_a_config_written_before_the_agents_rule(self):
        self.apply("--with-default-permissions")
        config = self.project / ".codex" / "config.toml"
        old = config.read_text(encoding="utf-8")
        self.assertIn('".agents" = "write"\n', old)
        config.write_text(old.replace('".agents" = "write"\n', ""), encoding="utf-8")
        code, text = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("config block stale", text)

    def test_check_writes_no_file(self):
        before = sorted(self.project.rglob("*"))
        self.run_check()
        self.assertEqual(sorted(self.project.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
