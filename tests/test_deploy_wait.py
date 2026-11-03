"""Tests for scripts/deploy_wait.py. The status command, forge calls, and the clock are faked."""

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deploy_wait  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def wait_command(lines, max_seconds=240):
    clock = FakeClock()
    queue = list(lines)

    def status(timeout):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    result = deploy_wait.wait_command(status, SHA, max_seconds, 30, clock.time, clock.sleep)
    return result, clock


class CommandModeTest(unittest.TestCase):
    def test_deploy_wait_reads_the_command_mode_status_line(self):
        result, _ = wait_command([f"running J1 {SHA}", f"succeeded J1 {SHA}"])
        self.assertEqual(result, {"state": "succeeded", "url": None, "jobId": "J1", "sha": SHA})

    def test_reports_failed_and_rolled_back_states(self):
        for state in ("failed", "rolled-back"):
            result, _ = wait_command([f"{state} J2 {SHA}"])
            self.assertEqual(result["state"], state)

    def test_returns_pending_when_the_deploy_is_still_running_at_the_deadline(self):
        result, clock = wait_command([f"running J1 {SHA}"], max_seconds=60)
        self.assertEqual(result["state"], "pending")
        self.assertLessEqual(clock.now, 60)

    def test_returns_superseded_when_the_newest_deploy_is_another_commit(self):
        result, _ = wait_command([f"running J9 {OTHER}"], max_seconds=60)
        self.assertEqual(result["state"], "superseded")
        self.assertEqual(result["sha"], OTHER)

    def test_returns_missing_when_the_status_line_is_empty(self):
        result, _ = wait_command([""], max_seconds=60)
        self.assertEqual(result["state"], "missing")

    def test_rejects_a_status_line_with_fewer_than_three_fields(self):
        with self.assertRaises(deploy_wait.WaitError):
            wait_command(["succeeded"])


class ActionsModeTest(unittest.TestCase):
    def wait(self, runs):
        clock = FakeClock()
        return deploy_wait.wait_actions(lambda timeout: runs, SHA, 60, 30, clock.time, clock.sleep)

    def test_deploy_wait_reads_an_actions_run(self):
        result = self.wait([{"status": "completed", "conclusion": "success", "url": "u"}])
        self.assertEqual(result, {"state": "succeeded", "url": "u", "jobId": None, "sha": SHA})

    def test_maps_a_red_actions_run_to_failed(self):
        result = self.wait([{"status": "completed", "conclusion": "failure", "url": "u"}])
        self.assertEqual(result["state"], "failed")

    def test_maps_no_actions_run_to_missing(self):
        self.assertEqual(self.wait([])["state"], "missing")

    def test_reports_a_skipped_deploy_run_as_not_succeeded(self):
        result = self.wait([{"status": "completed", "conclusion": "skipped", "url": "u"}])
        self.assertEqual(result["state"], "missing")


class CommandLineTest(unittest.TestCase):
    def test_exits_nonzero_with_one_stderr_line_when_command_mode_has_no_status_cmd(self):
        done = subprocess.run([sys.executable, str(SCRIPTS / "deploy_wait.py"), "--mode", "command", "--sha", SHA],
                              capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)

    def test_exits_1_with_one_stderr_line_on_a_status_command_with_a_bad_quote(self):
        done = subprocess.run([sys.executable, str(SCRIPTS / "deploy_wait.py"), "--mode", "command",
                               "--status-cmd", "echo 'unclosed", "--sha", SHA],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
