"""Tests for hooks/guard-wait.py.

Each case changes `timeout_ms` or the configuration file for a payload recorded from a live
Codex run (tests/fixtures/hooks/pre_tool_use_wait.json). The live run also showed that Codex
applies `updatedInput` to `wait_agent` (docs/specs/pages/codex-harness.md).
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard-wait.py"
RECORDED = json.loads((ROOT / "tests" / "fixtures" / "hooks" / "pre_tool_use_wait.json").read_text())


class GuardWaitTest(unittest.TestCase):
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
            capture_output=True, text=True)
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


if __name__ == "__main__":
    unittest.main()
