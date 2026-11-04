"""Replay the PM hook sequence recorded in the #75 gate run through the guard and the recorder.

tests/fixtures/hooks/gate75_pm_sequence.json holds the sanitized PreToolUse and PostToolUse
payloads of one live Codex 0.166.0 run: the PM's `wait_agent` calls, the PM's Stage A0 list
calls, and one worker's `sleep 30` calls (they carry `agent_id`). Each PreToolUse `wait_agent`
payload goes to the guard. Each PostToolUse payload goes to the recorder.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "guard-wait.py"
RECORDER = ROOT / "hooks" / "record-wait-state.py"
SEQUENCE = json.loads((ROOT / "tests" / "fixtures" / "hooks" / "gate75_pm_sequence.json").read_text())


class ReplayTest(unittest.TestCase):
    def replay(self):
        """Return one entry per PM PreToolUse wait: (call id, whether the guard denied it)."""
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        env = dict(os.environ, PLUGIN_DATA=str(Path(data.name) / "not-created-yet"))
        verdicts = []
        for event in SEQUENCE:
            is_wait = event["tool_name"].endswith("wait_agent")
            if event["hook_event_name"] == "PreToolUse" and is_wait and "agent_id" not in event:
                result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                        capture_output=True, text=True, env=env)
                verdicts.append((event["tool_use_id"], '"deny"' in result.stdout))
            elif event["hook_event_name"] == "PostToolUse":
                subprocess.run([sys.executable, str(RECORDER)], input=json.dumps(event),
                               capture_output=True, text=True, env=env)
        return verdicts

    def test_denies_only_the_wait_that_followed_a_timeout_with_no_list_call(self):
        denied = [call for call, was_denied in self.replay() if was_denied]
        self.assertEqual(len(denied), 1)
        first_timeout = next(e for e in SEQUENCE if e["hook_event_name"] == "PostToolUse"
                             and "timed_out\":true" in e.get("tool_response", ""))
        wait_after_first_timeout = next(
            e for e in SEQUENCE if e["hook_event_name"] == "PreToolUse"
            and e["tool_name"].endswith("wait_agent")
            and SEQUENCE.index(e) > SEQUENCE.index(first_timeout))
        self.assertEqual(denied, [wait_after_first_timeout["tool_use_id"]])


if __name__ == "__main__":
    unittest.main()
