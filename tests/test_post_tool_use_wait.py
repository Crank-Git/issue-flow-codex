"""Tests for hooks/record-wait-state.py.

Every input is a payload recorded from a live Codex run and then sanitized
(tests/fixtures/hooks/gate75_pm_sequence.json, post_tool_use_bash_stage_a0_denied.json).
The recorded Bash result is the raw command output with no exit-code header, so no test
here depends on an "Exit code" line.
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
HOOK = ROOT / "hooks" / "record-wait-state.py"
FIXTURES = ROOT / "tests" / "fixtures" / "hooks"
SEQUENCE = json.loads((FIXTURES / "gate75_pm_sequence.json").read_text())
SANDBOX_DENIED = json.loads((FIXTURES / "post_tool_use_bash_stage_a0_denied.json").read_text())


def first(predicate):
    return copy.deepcopy(next(event for event in SEQUENCE if predicate(event)))


def post(event):
    return event["hook_event_name"] == "PostToolUse" and "agent_id" not in event


def timed_out(event):
    return "timed_out\":true" in event.get("tool_response", "") and post(event)


TIMEOUT = first(timed_out)
COMPLETE = first(lambda e: post(e) and "timed_out\":false" in e.get("tool_response", ""))
LIST_BOTH = first(lambda e: post(e) and e["tool_name"] == "Bash")
WORKER_SLEEP = first(lambda e: e["hook_event_name"] == "PostToolUse" and "agent_id" in e)
ISSUE_LIST = "gh issue list --repo owner/testbed --state all --search 'updated:>=2026-11-03T00:00:00Z'"
PR_LIST = "gh pr list --repo owner/testbed --state open --search 'updated:>=2026-11-03T00:00:00Z'"


def as_command(event, command):
    event["tool_input"] = {"command": command}
    return event


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

    def pending(self):
        self.state.write_text('{"timed_out": true}')

    def test_the_recorded_bash_result_has_no_exit_code_header(self):
        self.assertFalse(LIST_BOTH["tool_response"].startswith("Exit code"))

    def test_records_a_pm_wait_timeout(self):
        self.run_hook(TIMEOUT)
        self.assertEqual(json.loads(self.state.read_text()), {"timed_out": True})

    def test_creates_a_missing_plugin_data_directory(self):
        missing = Path(self.data.name) / "not" / "created" / "yet"
        self.env["PLUGIN_DATA"] = str(missing)
        self.run_hook(TIMEOUT)
        self.assertTrue((missing / self.state.name).exists())

    def test_ignores_a_worker_wait_timeout(self):
        worker = dict(TIMEOUT, agent_id=WORKER_SLEEP["agent_id"], agent_type="issue_worker")
        self.run_hook(worker)
        self.assertFalse(self.state.exists())

    def test_leaves_no_flag_after_a_completed_wait(self):
        self.pending()
        self.run_hook(COMPLETE)
        self.assertFalse(self.state.exists())

    def test_keeps_the_flag_when_the_command_never_ran(self):
        self.pending()
        self.run_hook(dict(SANDBOX_DENIED, session_id=TIMEOUT["session_id"]))
        self.assertTrue(self.state.exists())

    def test_ignores_a_bash_command_that_is_not_a_stage_a0_list(self):
        self.pending()
        self.run_hook(as_command(copy.deepcopy(LIST_BOTH), "gh issue view 75"))
        self.assertTrue(self.state.exists())

    def test_keeps_the_flag_until_both_pm_lists_run(self):
        self.pending()
        self.run_hook(as_command(copy.deepcopy(LIST_BOTH), ISSUE_LIST))
        self.assertTrue(self.state.exists())
        self.run_hook(as_command(copy.deepcopy(LIST_BOTH), PR_LIST))
        self.assertFalse(self.state.exists())

    def test_clears_the_flag_after_one_command_that_runs_both_lists(self):
        self.pending()
        self.run_hook(LIST_BOTH)
        self.assertFalse(self.state.exists())

    def test_a_worker_list_call_does_not_clear_the_pm_flag(self):
        self.pending()
        worker = dict(LIST_BOTH, agent_id=WORKER_SLEEP["agent_id"], agent_type="issue_worker")
        self.run_hook(worker)
        self.assertTrue(self.state.exists())

    def test_counts_a_gitea_mcp_issue_list_and_pull_request_list(self):
        self.pending()
        for name, arguments in (
            ("mcp__gitea__list_issues", {"state": "all"}),
            ("mcp__gitea__list_pull_requests", {"state": "open"}),
        ):
            self.run_hook(dict(LIST_BOTH, tool_name=name, tool_input=arguments, tool_response="[]"))
        self.assertFalse(self.state.exists())

    def test_counts_list_issues_with_type_pulls_as_the_pull_request_list(self):
        self.pending()
        self.run_hook(dict(LIST_BOTH, tool_name="mcp__gitea__list_issues",
                           tool_input={"type": "pulls"}, tool_response="[]"))
        self.assertTrue(self.state.exists())
        self.run_hook(dict(LIST_BOTH, tool_name="mcp__gitea__list_issues",
                           tool_input={"state": "all"}, tool_response="[]"))
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
