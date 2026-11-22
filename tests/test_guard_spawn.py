"""Tests for hooks/guard-spawn.py.

Each case changes `fork_turns`, `task_name`, or `agent_type` in a payload recorded from a
live Codex run (tests/fixtures/hooks/pre_tool_use_spawn.json). The recorded `message` is
an encrypted token, so the guard cannot read it and no test sets it.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard-spawn.py"
SESSION_ID = "01a1a281-0d5d-7003-8c3a-dbc52a350578"
RECORDED = json.loads((ROOT / "tests" / "fixtures" / "hooks" / "pre_tool_use_spawn.json").read_text())


def spawn(**changes):
    """Return the recorded spawn payload with `tool_input` keys changed. A None value removes the key."""
    payload = copy.deepcopy(RECORDED)
    for key, value in changes.items():
        if value is None:
            payload["tool_input"].pop(key, None)
        else:
            payload["tool_input"][key] = value
    return payload


def subagent(**changes):
    """Return a spawn payload from a subagent: it has `agent_id`."""
    return {**spawn(**changes), "agent_id": "01a1a281-2222-7003-8c3a-dbc52a350578"}


class GuardSpawnTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        self.plugin_data = Path(self.data.name) / "plugin-data"

    def run_hook(self, payload, env=None):
        """Return the parsed hook output, or None when the hook printed nothing."""
        environment = {k: v for k, v in os.environ.items() if k != "ISSUE_FLOW_SPAWN_GUARD"}
        environment["PLUGIN_DATA"] = str(self.plugin_data)
        environment.update(env or {})
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def assertDenied(self, payload, env=None):
        output = self.run_hook(payload, env)
        self.assertIsNotNone(output)
        decision = output["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        return decision["permissionDecisionReason"]

    def assertAllowed(self, payload, env=None):
        self.assertIsNone(self.run_hook(payload, env))

    def test_denies_the_recorded_payload_without_agent_type(self):
        self.assertDenied(RECORDED)

    def test_denies_a_spawn_with_fork_turns_all(self):
        reason = self.assertDenied(spawn(fork_turns="all"))
        self.assertIn('fork_turns "none"', reason)

    def test_denies_a_spawn_with_fork_turns_omitted(self):
        reason = self.assertDenied(spawn(fork_turns=None))
        self.assertIn('fork_turns "none"', reason)

    def test_denies_a_worker_task_name_without_agent_type_issue_worker(self):
        for name in ("worker_17", "worker_17_c2"):
            with self.subTest(task_name=name):
                reason = self.assertDenied(subagent(task_name=name))
                self.assertIn('agent_type "issue_worker"', reason)

    def test_denies_a_worker_task_name_with_another_agent_type(self):
        self.assertDenied(subagent(task_name="worker_17", agent_type="default"))
        self.assertDenied(spawn(task_name="worker_17", agent_type="default"))

    def test_allows_a_worker_task_name_with_issue_worker_and_none(self):
        self.assertAllowed(spawn(task_name="worker_17", agent_type="issue_worker"))

    def test_allows_a_non_worker_spawn_from_a_subagent_with_fork_turns_none(self):
        for name in ("reviewer", "worker_x", "worker_17_c", "xworker_17"):
            with self.subTest(task_name=name):
                self.assertAllowed(subagent(task_name=name))

    def test_allows_a_payload_whose_tool_input_is_a_string(self):
        self.assertAllowed({**RECORDED, "tool_input": "x"})

    def test_allows_a_payload_whose_tool_input_is_missing(self):
        self.assertAllowed({k: v for k, v in RECORDED.items() if k != "tool_input"})

    def test_allows_malformed_json(self):
        self.assertAllowed("{not json")

    def test_allows_empty_input(self):
        self.assertAllowed("")

    def test_ignores_a_tool_that_is_not_a_spawn(self):
        self.assertAllowed({**RECORDED, "tool_name": "Bash", "tool_input": {"command": "ls"}})

    def test_matches_the_plain_tool_name_spawn_agent(self):
        self.assertDenied({**spawn(fork_turns="all"), "tool_name": "spawn_agent"})

    def names(self):
        return json.loads((self.plugin_data / f"spawns-{SESSION_ID}.json").read_text())["names"]

    def test_denies_default_agent_type_names_allowlist(self):
        reason = self.assertDenied(spawn(agent_type="default"))
        self.assertIn("issue_worker", reason)
        self.assertIn("review_scribe", reason)
        reason = self.assertDenied(spawn(task_name="x_1", agent_type="default"))
        self.assertIn("not a plugin role", reason)
        self.assertIn("x_1", reason)

    def test_denies_missing_agent_type_suite_12(self):
        reason = self.assertDenied(spawn(task_name="suite_12"))
        self.assertIn("omitted", reason)

    def test_denies_explorer_review_12_sources(self):
        reason = self.assertDenied(spawn(task_name="review_12_sources", agent_type="explorer"))
        self.assertIn("locate_<n>_<k>", reason)

    def test_allows_each_role_name_pattern(self):
        cases = [("criteria_checker", "check_4_3"), ("ci_watcher", "suite_12_r2"),
                 ("ci_watcher", "deploy_abc1234"), ("deploy_verifier", "verify_deploy_abc1234"),
                 ("explorer", "batchreview_9"), ("code_auditor", "code_auditor"),
                 ("ux_explorer", "ux_sign_in2"), ("review_scribe", "review_scribe_2")]
        for agent_type, name in cases:
            with self.subTest(task_name=name):
                self.assertAllowed(spawn(task_name=name, agent_type=agent_type))

    def test_subagent_default_gets_no_allowlist_deny(self):
        self.assertAllowed(subagent(task_name="helper_1", agent_type="default"))

    def test_denies_second_worker_42(self):
        self.assertAllowed(spawn(task_name="worker_42", agent_type="issue_worker"))
        reason = self.assertDenied(spawn(task_name="worker_42", agent_type="issue_worker"))
        self.assertIn("earlier spawn", reason)

    def test_denies_c2_without_c1(self):
        reason = self.assertDenied(spawn(task_name="worker_42_c2", agent_type="issue_worker"))
        self.assertIn("worker_42_c1", reason)

    def test_denies_chain_names_without_their_predecessor(self):
        for name in ("worker_42_c1", "worker_42_e1", "worker_42_e1_c1"):
            with self.subTest(task_name=name):
                self.assertDenied(spawn(task_name=name, agent_type="issue_worker"))

    def test_allows_the_full_five_name_chain(self):
        for name in ("worker_42", "worker_42_c1", "worker_42_c2", "worker_42_e1", "worker_42_e1_c1"):
            with self.subTest(task_name=name):
                self.assertAllowed(spawn(task_name=name, agent_type="issue_worker"))

    def test_denies_c3_names_status_blocked(self):
        reason = self.assertDenied(spawn(task_name="worker_42_c3", agent_type="issue_worker"))
        self.assertIn("status:blocked", reason)

    def test_records_name_and_creates_plugin_data(self):
        self.assertFalse(self.plugin_data.exists())
        self.assertAllowed(spawn(task_name="suite_12", agent_type="ci_watcher"))
        self.assertEqual(self.names(), ["suite_12"])

    def test_does_not_record_a_denied_or_subagent_spawn(self):
        self.assertDenied(spawn(task_name="suite_12"))
        self.assertAllowed(subagent(task_name="helper_1", agent_type="default"))
        self.assertFalse(self.plugin_data.exists())

    def test_off_silences_all_new_denies(self):
        off = {"ISSUE_FLOW_SPAWN_GUARD": "off"}
        for payload in (spawn(task_name="suite_12"), spawn(task_name="worker_42_c2", agent_type="issue_worker"),
                        spawn(task_name="worker_42_c3", agent_type="issue_worker")):
            self.assertAllowed(payload, off)
        self.assertFalse(self.plugin_data.exists())

    def test_unwritable_state_allows_with_stderr(self):
        blocker = Path(self.data.name) / "file"
        blocker.write_text("x")
        environment = {**os.environ, "PLUGIN_DATA": str(blocker / "sub")}
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(spawn(task_name="suite_12", agent_type="ci_watcher")),
            capture_output=True, text=True, env=environment)
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_sessions_have_separate_files(self):
        other = {**spawn(task_name="worker_42", agent_type="issue_worker"),
                 "session_id": "01a1a281-9999-7003-8c3a-dbc52a350578"}
        self.assertAllowed(spawn(task_name="worker_42", agent_type="issue_worker"))
        self.assertAllowed(other)
        self.assertEqual(len(list(self.plugin_data.glob("spawns-*.json"))), 2)

    def test_skips_reuse_and_chain_rules_without_plugin_data(self):
        environment = {k: v for k, v in os.environ.items() if k != "PLUGIN_DATA"}
        for name in ("worker_42_c2", "worker_42_c2"):
            result = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(spawn(task_name=name, agent_type="issue_worker")),
                capture_output=True, text=True, env=environment)
            self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_off_allows_a_denied_spawn(self):
        for value in ("off", "OFF", "0", "false", "no"):
            with self.subTest(value=value):
                self.assertAllowed(spawn(fork_turns="all"), {"ISSUE_FLOW_SPAWN_GUARD": value})

    def test_denies_for_an_unrecognized_setting(self):
        self.assertDenied(spawn(fork_turns="all"), {"ISSUE_FLOW_SPAWN_GUARD": "anything"})


if __name__ == "__main__":
    unittest.main()
