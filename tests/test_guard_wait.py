"""Tests for hooks/guard-wait.py.

Each case changes `timeout_ms` or the configuration file for a payload recorded from a live
Codex run (tests/fixtures/hooks/pre_tool_use_wait.json). The live run also showed that Codex
applies `updatedInput` to `wait_agent` (docs/specs/pages/codex-harness.md).
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
HOOK = ROOT / "hooks" / "guard-wait.py"
RECORDED = json.loads((ROOT / "tests" / "fixtures" / "hooks" / "pre_tool_use_wait.json").read_text())


class GuardWaitTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)

    def project(self, config=None):
        """Return a temporary project directory, with `config` as its .issue-flow.codex.json text."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        if config is not None:
            (Path(directory.name) / ".issue-flow.codex.json").write_text(config)
        return directory.name

    def payload(self, cwd, timeout_ms=None):
        payload = copy.deepcopy(RECORDED)
        payload["cwd"] = cwd
        if timeout_ms is None:
            payload["tool_input"].pop("timeout_ms")
        else:
            payload["tool_input"]["timeout_ms"] = timeout_ms
        return payload

    def run_hook(self, payload):
        """Return the parsed hook output, or None when the hook printed nothing."""
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True, text=True,
            env=dict(os.environ, PLUGIN_DATA=self.data.name))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def assertCorrected(self, payload, timeout_ms):
        output = self.run_hook(payload)
        self.assertIsNotNone(output)
        decision = output["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "allow")
        self.assertEqual(decision["updatedInput"], {**payload["tool_input"], "timeout_ms": timeout_ms})

    def test_allows_a_matching_timeout(self):
        cwd = self.project('{"version": 1, "waitMs": 10000}')
        self.assertIsNone(self.run_hook(self.payload(cwd, 10000)))

    def test_corrects_a_different_timeout_to_the_configured_value(self):
        cwd = self.project('{"version": 1, "waitMs": 45000}')
        self.assertCorrected(self.payload(cwd, 10000), 45000)

    def test_corrects_an_absent_timeout_to_the_configured_value(self):
        cwd = self.project('{"version": 1, "waitMs": 45000}')
        self.assertCorrected(self.payload(cwd), 45000)

    def test_uses_600000_without_a_configuration_file(self):
        cwd = self.project()
        self.assertCorrected(self.payload(cwd, 10000), 600000)
        self.assertIsNone(self.run_hook(self.payload(cwd, 600000)))

    def test_uses_600000_when_wait_ms_is_not_a_positive_integer(self):
        for config in ('{"waitMs": "fast"}', '{"waitMs": 0}', '{"waitMs": true}', "[]", "not json"):
            with self.subTest(config=config):
                self.assertCorrected(self.payload(self.project(config), 10000), 600000)

    def test_allows_a_payload_that_is_not_json(self):
        self.assertIsNone(self.run_hook("not json"))

    def test_allows_a_payload_that_is_not_an_object(self):
        self.assertIsNone(self.run_hook("[1, 2]"))

    def test_allows_a_tool_input_that_is_not_an_object(self):
        payload = self.payload(self.project(), 10000)
        payload["tool_input"] = "10000"
        self.assertIsNone(self.run_hook(payload))

    def test_ignores_a_tool_other_than_wait_agent(self):
        payload = self.payload(self.project(), 10000)
        payload["tool_name"] = "collaborationlist_agents"
        self.assertIsNone(self.run_hook(payload))

    def test_denies_wait_until_the_stage_a0_lists_run(self):
        payload = self.payload(self.project('{"version": 1, "waitMs": 10000}'), 10000)
        state = Path(self.data.name) / f"wait-timeout-{payload['session_id']}.json"
        state.write_text('{"timed_out": true}')
        output = self.run_hook(payload)
        decision = output["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        reason = decision["permissionDecisionReason"]
        self.assertIn("forge.issue.list.since", reason)
        self.assertIn("forge.pr.list.since", reason)
        self.assertIn("gh issue list", reason)
        self.assertIn("gh pr list", reason)
        self.assertIn("tea issues", reason)
        self.assertIn("tea pulls", reason)

    def pending_payload(self):
        payload = self.payload(self.project('{"version": 1, "waitMs": 10000}'), 10000)
        state = Path(self.data.name) / f"wait-timeout-{payload['session_id']}.json"
        state.write_text('{"timed_out": true}')
        return payload, state

    def test_allows_the_third_wait_after_two_denials_and_names_the_missed_sweep(self):
        payload, state = self.pending_payload()
        for _ in range(2):
            output = self.run_hook(payload)
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        output = self.run_hook(payload)
        self.assertNotIn("deny", json.dumps(output))
        self.assertIn("forge.issue.list.since", output["systemMessage"])
        self.assertFalse(state.exists())
        self.assertIsNone(self.run_hook(payload))

    def test_never_denies_a_subagent_wait(self):
        payload, state = self.pending_payload()
        payload["agent_id"] = "00000000-0000-7000-8000-0000000000a1"
        self.assertIsNone(self.run_hook(payload))
        self.assertTrue(state.exists())

    def test_creates_no_state_when_the_plugin_data_directory_is_missing(self):
        payload, _ = self.pending_payload()
        self.data.cleanup()
        self.assertIsNone(self.run_hook(payload))


if __name__ == "__main__":
    unittest.main()
