"""Tests for scripts/setup_project.py (FR-plugin-packaging-11 to 19).

Each test builds a scratch project and a fixture plugin root in a temporary directory.
"""

import io
import json
import os
import re
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

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
        self.home = base / "codex-home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

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

        self.assertIn("Per-project mode prints `.codex/` changes for operator application", skill)
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
            "user setup   not used " + str(self.home),
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


class UserSetupTest(unittest.TestCase):
    """The user-level mode writes into a temporary CODEX_HOME, never the operator's ~/.codex."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "codex-home"
        self.home.mkdir()
        self.plugin = base / "plugin"
        (self.plugin / "roles").mkdir(parents=True)
        for name in ROLE_NAMES:
            (self.plugin / "roles" / f"{name}.toml").write_text(
                f'name = "{name.replace("-", "_")}"\ndescription = "{name}"\n', encoding="utf-8")
        (self.plugin / ".codex-plugin").mkdir()
        (self.plugin / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "issue-flow", "version": "0.1.1"}), encoding="utf-8")
        env = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = setup_project.main([*args, "--user", "--plugin-root", str(self.plugin)])
        return code, out.getvalue(), err.getvalue()

    def files(self):
        return {str(p.relative_to(self.home)): p.read_text(encoding="utf-8")
                for p in sorted(self.home.rglob("*")) if p.is_file()}

    def test_apply_writes_the_profile_file_and_the_role_files_into_an_empty_home(self):
        code, out, _ = self.run_main("apply")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(self.files()),
                         sorted(["issue-flow.config.toml"] + [f"agents/{n}.toml" for n in ROLE_NAMES]))
        for name in ROLE_NAMES:
            self.assertEqual(self.files()[f"agents/{name}.toml"],
                             (self.plugin / "roles" / f"{name}.toml").read_text(encoding="utf-8"))
        self.assertIn('{"wrote": "issue-flow.config.toml"}', out.splitlines())

    def test_profile_file_starts_with_default_permissions_and_holds_the_project_profile(self):
        self.run_main("apply")
        text = self.files()["issue-flow.config.toml"]
        self.assertTrue(text.startswith('default_permissions = "issue_flow"\n'))
        parsed = tomllib.loads(text)
        project = tomllib.loads(setup_project.render_block(3, True))
        self.assertEqual(parsed, {"default_permissions": "issue_flow",
                                  "features": project["features"],
                                  "permissions": project["permissions"]})
        self.assertEqual(parsed["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 7)

    def add_codex_state(self, profile_text):
        """Return the profile text with the state that a Codex session saves (codex-harness.md, fact 29)."""
        return (profile_text + '\n[projects."/work/app"]\ntrust_level = "trusted"\n\n'
                '[hooks.state."issue-flow@issue-flow-codex:hooks/hooks.json:pre_tool_use:0:0"]\n'
                'trusted_hash = "sha256:aa"\n\n[tui.model_availability_nux]\n"gpt-6.1-sol" = 1\n')

    def test_check_passes_when_codex_saved_its_state_in_the_profile_file(self):
        self.run_main("apply")
        profile = self.home / "issue-flow.config.toml"
        profile.write_text(self.add_codex_state(profile.read_text(encoding="utf-8")), encoding="utf-8")
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_main("apply")
        self.assertEqual((code, out.strip()), (0, "no changes"))

    def test_apply_accept_rewrites_only_the_owned_keys_of_the_profile_file(self):
        self.run_main("apply")
        profile = self.home / "issue-flow.config.toml"
        saved = self.add_codex_state(profile.read_text(encoding="utf-8").replace("= 7", "= 4"))
        profile.write_text('model = "x"\n' + saved, encoding="utf-8")
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertIn("issue-flow.config.toml           stale", out)
        code, out, _ = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("+max_concurrent_threads_per_session = 7", out)
        self.assertNotIn("-trust_level", out)
        code, _, _ = self.run_main("apply", "--accept", "issue-flow.config.toml")
        self.assertEqual(code, 0)
        parsed = tomllib.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(parsed["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 7)
        self.assertEqual(parsed["model"], "x")
        self.assertEqual(parsed["projects"]["/work/app"]["trust_level"], "trusted")
        self.assertEqual(len(parsed["hooks"]["state"]), 1)
        self.assertEqual(parsed["tui"]["model_availability_nux"], {"gpt-6.1-sol": 1})
        self.assertEqual(self.run_main("check")[0], 0)

    def test_apply_accept_stops_on_a_profile_file_that_is_not_toml(self):
        self.run_main("apply")
        profile = self.home / "issue-flow.config.toml"
        profile.write_text("[broken\n", encoding="utf-8")
        code, _, err = self.run_main("apply", "--accept", "issue-flow.config.toml")
        self.assertEqual(code, 1)
        self.assertIn("repair the file", err)
        self.assertEqual(profile.read_text(encoding="utf-8"), "[broken\n")

    def test_apply_never_writes_config_toml_or_an_approval_policy(self):
        self.run_main("apply")
        self.assertFalse((self.home / "config.toml").exists())
        self.assertNotIn("approval_policy", self.files()["issue-flow.config.toml"])

    def test_apply_keeps_an_existing_config_toml_unchanged(self):
        (self.home / "config.toml").write_text('model = "x"\n', encoding="utf-8")
        self.run_main("apply")
        self.assertEqual((self.home / "config.toml").read_text(encoding="utf-8"), 'model = "x"\n')

    def test_a_second_apply_changes_nothing(self):
        self.run_main("apply")
        before = self.files()
        mtimes = {p: p.stat().st_mtime_ns for p in self.home.rglob("*")}
        code, out, _ = self.run_main("apply")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no changes")
        self.assertEqual(self.files(), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.home.rglob("*")}, mtimes)

    def test_apply_shows_the_diff_and_keeps_a_file_that_differs(self):
        self.run_main("apply")
        role = self.home / "agents" / "issue-worker.toml"
        role.write_text("edited\n", encoding="utf-8")
        code, out, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("--- a/agents/issue-worker.toml", out)
        self.assertIn("-edited", out)
        self.assertEqual(role.read_text(encoding="utf-8"), "edited\n")
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("--accept agents/issue-worker.toml", err)

    def test_apply_replaces_a_file_that_differs_when_the_operator_accepts_it(self):
        self.run_main("apply")
        role = self.home / "agents" / "issue-worker.toml"
        role.write_text("edited\n", encoding="utf-8")
        code, out, _ = self.run_main("apply", "--accept", "agents/issue-worker.toml")
        self.assertEqual(code, 0)
        self.assertEqual(role.read_text(encoding="utf-8"),
                         (self.plugin / "roles" / "issue-worker.toml").read_text(encoding="utf-8"))
        self.assertEqual(out.splitlines(), ['{"wrote": "agents/issue-worker.toml"}'])

    def test_apply_names_every_differing_file_after_one_accept_flag(self):
        self.run_main("apply")
        for name in ("issue-worker", "ci-watcher"):
            (self.home / "agents" / f"{name}.toml").write_text("edited\n", encoding="utf-8")
        _, _, err = self.run_main("apply")
        accepted = err.split("--accept ")[1].split()
        code, _, _ = self.run_main("apply", "--accept", *accepted)
        self.assertEqual(code, 0)
        self.assertEqual(self.run_main("check")[0], 0)

    def test_apply_rejects_an_accepted_file_that_the_plan_does_not_hold(self):
        code, _, err = self.run_main("apply", "--accept", "config.toml")
        self.assertEqual(code, 1)
        self.assertIn("not in the plan: config.toml", err)
        self.assertFalse((self.home / "config.toml").exists())

    def test_plan_shows_a_diff_for_each_file_and_writes_nothing(self):
        code, out, _ = self.run_main("plan")
        self.assertEqual(code, 0)
        self.assertIn("+++ b/issue-flow.config.toml", out)
        self.assertIn("+++ b/agents/ci-watcher.toml", out)
        self.assertEqual(self.files(), {})

    def test_check_reports_each_file_missing_in_an_empty_home(self):
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual(len(lines), 1 + len(ROLE_NAMES))
        self.assertTrue(all(line.split()[1] == "missing" for line in lines))
        self.assertEqual(self.files(), {})

    def test_check_reports_ok_after_apply(self):
        self.run_main("apply")
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 0)
        self.assertIn("issue-flow.config.toml", out)
        self.assertTrue(all(line.split()[1] == "ok" for line in out.splitlines()))

    def test_check_reports_stale_after_one_owned_value_changes_in_the_profile_file(self):
        self.run_main("apply")
        profile = self.home / "issue-flow.config.toml"
        profile.write_text(profile.read_text(encoding="utf-8").replace('".agents" = "write"', '".agents" = "read"'),
                           encoding="utf-8")
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0].split(), ["issue-flow.config.toml", "stale"])

    def test_uses_dot_codex_in_the_home_directory_when_codex_home_is_not_set(self):
        fake_home = self.home.parent / "user"
        fake_home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(fake_home)}):
            del os.environ["CODEX_HOME"]
            self.run_main("apply")
        self.assertTrue((fake_home / ".codex" / "issue-flow.config.toml").is_file())
        self.assertEqual(self.files(), {})

    def test_rejects_project_and_user_together(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            setup_project.main(["plan", "--user", "--project", str(self.home)])

    def check_project(self, project):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_project.main(["check", "--project", str(project),
                                       "--plugin-root", str(self.plugin)])
        return code, out.getvalue()

    def project_rows(self, text):
        return {line[:12].strip(): line[13:].split()[0] for line in text.splitlines()}

    def test_project_check_passes_on_an_empty_project_when_the_user_setup_is_complete(self):
        self.run_main("apply")
        project = self.home.parent / "project"
        project.mkdir()
        code, text = self.check_project(project)
        self.assertEqual(code, 0, text)
        rows = self.project_rows(text)
        self.assertEqual(rows["user setup"], "ok")
        for item in ("roles", "config block", "threads", "profile", "gitignore"):
            self.assertEqual(rows[item], "not", item)
        self.assertIn("roles        not used", text)

    def test_project_check_fails_on_a_stale_project_role_when_the_user_setup_is_complete(self):
        self.run_main("apply")
        project = self.home.parent / "project"
        (project / ".codex" / "agents").mkdir(parents=True)
        (project / ".codex" / "agents" / "issue-worker.toml").write_text("old\n", encoding="utf-8")
        code, text = self.check_project(project)
        self.assertEqual(code, 1)
        self.assertEqual(self.project_rows(text)["roles"], "stale")

    def test_project_check_fails_and_prints_the_user_command_when_neither_level_is_complete(self):
        project = self.home.parent / "project"
        project.mkdir()
        code, text = self.check_project(project)
        self.assertEqual(code, 1)
        self.assertEqual(self.project_rows(text)["user setup"], "missing")
        self.assertIn(f"fix: python3 {self.plugin}/scripts/setup_project.py apply --user",
                      text.splitlines())

    def test_project_check_fails_when_the_user_setup_is_stale_and_the_project_is_empty(self):
        self.run_main("apply")
        (self.home / "agents" / "issue-worker.toml").write_text("old\n", encoding="utf-8")
        project = self.home.parent / "project"
        project.mkdir()
        code, text = self.check_project(project)
        self.assertEqual(code, 1)
        self.assertEqual(self.project_rows(text)["user setup"], "stale")

    def test_rejects_apply_project_without_accept(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            setup_project.main(["apply", "--project", str(self.home)])

    def test_setup_skill_defaults_to_the_user_mode_and_prints_the_terminal_command(self):
        skill = (ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("setup_project.py plan --user", skill)
        self.assertIn("python3 <pluginRoot>/scripts/setup_project.py apply --user", skill)
        self.assertLess(skill.index("apply --user"), skill.index("--project"))

    def test_readme_shows_the_one_time_setup_then_the_per_project_flow(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        marks = ["codex plugin add issue-flow@issue-flow-codex", "/hooks",
                 "setup_project.py apply --user", "codex -p issue-flow -a never",
                 "$issue-flow:project-planner"]
        positions = [readme.index(mark) for mark in marks]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
