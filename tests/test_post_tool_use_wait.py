"""Tests for hooks/record-wait-state.py."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "record-wait-state.py"
FIXTURES = ROOT / "tests" / "fixtures" / "hooks"
TIMEOUT = json.loads((FIXTURES / "post_tool_use_wait_timeout.json").read_text())
COMPLETE = json.loads((FIXTURES / "post_tool_use_wait_complete.json").read_text())
FAILED_LIST = json.loads((FIXTURES / "post_tool_use_bash_stage_a0_denied.json").read_text())


class RecordWaitStateTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        self.env = dict(os.environ, PLUGIN_DATA=self.data.name)
        self.state = Path(self.data.name) / f"wait-timeout-{TIMEOUT['session_id']}.json"

    def run_hook(self, payload):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_records_a_wait_timeout(self):
        self.run_hook(TIMEOUT)
        self.assertEqual(json.loads(self.state.read_text()), {"timed_out": True})

    def test_leaves_no_flag_after_a_completed_wait(self):
        self.state.write_text('{"timed_out": true}')
        self.run_hook(COMPLETE)
        self.assertFalse(self.state.exists())

    def test_keeps_the_flag_when_the_stage_a0_command_fails(self):
        self.state.write_text('{"timed_out": true}')
        self.run_hook(FAILED_LIST)
        self.assertTrue(self.state.exists())

    def test_clears_the_flag_after_a_successful_stage_a0_call(self):
        payload = dict(FAILED_LIST)
        payload["tool_response"] = "Exit code: 0\nWall time: 0.1 seconds\nOutput:\n"
        self.state.write_text('{"timed_out": true}')
        self.run_hook(payload)
        self.assertFalse(self.state.exists())

    def test_ignores_a_bash_command_that_is_not_a_stage_a0_list(self):
        payload = dict(FAILED_LIST)
        payload["tool_input"] = {"command": "gh issue view 75"}
        self.state.write_text('{"timed_out": true}')
        self.run_hook(payload)
        self.assertTrue(self.state.exists())

    def test_keeps_the_flag_until_both_stage_a0_lists_succeed(self):
        payload = dict(FAILED_LIST)
        payload["tool_input"] = {"command": "gh issue list --state all"}
        payload["tool_response"] = "Exit code: 0\nWall time: 0.1 seconds\nOutput:\n"
        self.state.write_text('{"timed_out": true}')
        self.run_hook(payload)
        self.assertTrue(self.state.exists())
        payload["tool_input"] = {"command": "gh pr list --state open"}
        self.run_hook(payload)
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
