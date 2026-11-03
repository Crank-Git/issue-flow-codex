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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard-spawn.py"
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


class GuardSpawnTest(unittest.TestCase):
    def run_hook(self, payload, env=None):
        """Return the parsed hook output, or None when the hook printed nothing."""
        environment = {k: v for k, v in os.environ.items() if k != "ISSUE_FLOW_SPAWN_GUARD"}
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

    def test_allows_the_recorded_payload(self):
        self.assertAllowed(RECORDED)

    def test_denies_a_spawn_with_fork_turns_all(self):
        reason = self.assertDenied(spawn(fork_turns="all"))
        self.assertIn('fork_turns "none"', reason)

    def test_denies_a_spawn_with_fork_turns_omitted(self):
        reason = self.assertDenied(spawn(fork_turns=None))
        self.assertIn('fork_turns "none"', reason)

    def test_denies_a_worker_task_name_without_agent_type_issue_worker(self):
        for name in ("worker_17", "worker_17_c2"):
            with self.subTest(task_name=name):
                reason = self.assertDenied(spawn(task_name=name))
                self.assertIn('agent_type "issue_worker"', reason)

    def test_denies_a_worker_task_name_with_another_agent_type(self):
        self.assertDenied(spawn(task_name="worker_17", agent_type="default"))

    def test_allows_a_worker_task_name_with_issue_worker_and_none(self):
        self.assertAllowed(spawn(task_name="worker_17_c1", agent_type="issue_worker"))

    def test_allows_a_non_worker_spawn_with_fork_turns_none(self):
        for name in ("reviewer", "worker_x", "worker_17_c", "xworker_17"):
            with self.subTest(task_name=name):
                self.assertAllowed(spawn(task_name=name))

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

    def test_off_allows_a_denied_spawn(self):
        for value in ("off", "OFF", "0", "false", "no"):
            with self.subTest(value=value):
                self.assertAllowed(spawn(fork_turns="all"), {"ISSUE_FLOW_SPAWN_GUARD": value})

    def test_denies_for_an_unrecognized_setting(self):
        self.assertDenied(spawn(fork_turns="all"), {"ISSUE_FLOW_SPAWN_GUARD": "anything"})


if __name__ == "__main__":
    unittest.main()
