"""Offline tests for scripts/conformance.py. No test starts a live Codex session."""

import io
import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import conformance  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "conformance"


class ReportTest(unittest.TestCase):
    def test_report_line_holds_id_verdict_and_evidence(self):
        self.assertEqual(
            conformance.format_line("P1", True, "plugin skill listed"),
            "P1  pass  plugin skill listed",
        )
        self.assertEqual(
            conformance.format_line("P7", False, "git worktree add exited 0"),
            "P7  fail  git worktree add exited 0",
        )

    def test_report_line_keeps_evidence_on_one_line(self):
        line = conformance.format_line("P2", False, "first\nsecond")
        self.assertNotIn("\n", line)


class RunProbeTest(unittest.TestCase):
    def test_marks_a_probe_fail_with_timeout_evidence(self):
        def probe():
            raise conformance.ProbeTimeout(90)

        self.assertEqual(
            conformance.run_probe("P4", probe),
            ("P4", False, "timeout after 90 s"),
        )

    def test_returns_the_probe_verdict(self):
        self.assertEqual(
            conformance.run_probe("P1", lambda: (True, "listed")),
            ("P1", True, "listed"),
        )


class RolloutQuotaTest(unittest.TestCase):
    def test_reads_quota_of_a_rollout_under_the_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "sessions" / "2026" / "11" / "20"
            day.mkdir(parents=True)
            event = {"type": "event_msg", "payload": {"type": "token_count", "info": None,
                     "rate_limits": {"primary": {"used_percent": 4.5, "resets_at": 1795000000}}}}
            (day / "rollout-a.jsonl").write_text(json.dumps(event) + "\n")
            self.assertEqual(conformance.rollout_quota(tmp), (4.5, 1795000000))

    def test_returns_none_without_a_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(conformance.rollout_quota(tmp))


class RolloutModelsTest(unittest.TestCase):
    def test_reads_the_turn_context_models_of_each_rollout_under_the_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "sessions" / "2026" / "11" / "20"
            day.mkdir(parents=True)
            lines = [{"type": "session_meta", "payload": {"id": "x"}},
                     {"type": "turn_context", "payload": {"model": "gpt-6-luna"}}]
            (day / "rollout-a.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
            (day / "rollout-b.jsonl").write_text(
                json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}) + "\n")
            self.assertEqual(conformance.rollout_models(tmp), ["gpt-6-luna", "gpt-6.1-sol"])

    def test_returns_an_empty_list_without_a_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(conformance.rollout_models(tmp), [])


class EscalationResultTest(unittest.TestCase):
    def test_passes_when_a_turn_ran_on_the_role_file_model(self):
        ok, text = conformance.escalation_result(["gpt-6-luna", "gpt-6.1-sol"], set())
        self.assertTrue(ok)
        self.assertIn("gpt-6.1-sol", text)

    def test_fails_when_no_turn_ran_on_the_role_file_model(self):
        ok, _ = conformance.escalation_result(["gpt-6-luna", "gpt-6-luna"], set())
        self.assertFalse(ok)

    def test_keeps_the_old_observation_and_the_spawn_fields_in_the_report_text(self):
        _, text = conformance.escalation_result([], {"reasoning_effort", "model"})
        self.assertIn("['model', 'reasoning_effort']", text)
        self.assertIn("does not override the role file model", text)


class MainTest(unittest.TestCase):
    def test_exits_2_when_codex_is_not_on_path(self):
        err = io.StringIO()
        with mock.patch("shutil.which", return_value=None), redirect_stderr(err):
            self.assertEqual(conformance.main([]), 2)
        self.assertIn("codex", err.getvalue())
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)

    def test_exits_2_when_codex_is_not_logged_in(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="Not logged in")
        err = io.StringIO()
        with mock.patch("shutil.which", return_value="/bin/codex"), \
                mock.patch("subprocess.run", return_value=failed), \
                redirect_stderr(err):
            self.assertEqual(conformance.main([]), 2)
        self.assertIn("logged in", err.getvalue())


class AuthLinkTest(unittest.TestCase):
    def test_links_auth_json_and_never_copies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "operator" / "auth.json"
            source.parent.mkdir()
            source.write_text("secret")
            home = Path(tmp) / "home"
            home.mkdir()
            conformance.link_auth(home, source)
            link = home / "auth.json"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), source.resolve())


class HookLogTest(unittest.TestCase):
    def test_reads_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "hooks.jsonl"
            log.write_text('{"hook_event_name": "PreToolUse"}\n\n{"agent_type": "x"}\n')
            self.assertEqual(
                conformance.read_hook_log(log),
                [{"hook_event_name": "PreToolUse"}, {"agent_type": "x"}],
            )

    def test_returns_an_empty_list_when_no_hook_ran(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(conformance.read_hook_log(Path(tmp) / "none.jsonl"), [])


class FixtureTest(unittest.TestCase):
    def test_marketplace_lists_the_probe_plugin(self):
        market = json.loads((FIXTURES / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(market["plugins"][0]["name"], conformance.PLUGIN)
        self.assertEqual(market["name"], conformance.MARKETPLACE)

    def test_probe_plugin_manifest_names_the_plugin(self):
        manifest = json.loads(
            (FIXTURES / "plugin/.codex-plugin/plugin.json").read_text()
        )
        self.assertEqual(manifest["name"], conformance.PLUGIN)

    def test_hooks_file_parses_and_covers_the_logged_events(self):
        hooks = json.loads((FIXTURES / "plugin/hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(
            set(hooks), {"SessionStart", "PreToolUse", "PostToolUse"}
        )

    def test_each_role_file_names_its_role(self):
        for role in ("echo_worker", "git_worker", "escalated_probe"):
            data = tomllib.loads((FIXTURES / "roles" / f"{role}.toml").read_text())
            self.assertEqual(data["name"], role)
            self.assertTrue(data["developer_instructions"])

    def test_escalated_probe_role_sets_the_escalation_model(self):
        data = tomllib.loads((FIXTURES / "roles" / "escalated_probe.toml").read_text())
        self.assertEqual(data["model"], conformance.ESCALATION_MODEL)


if __name__ == "__main__":
    unittest.main()
