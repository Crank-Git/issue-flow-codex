"""Tests for scripts/ci_wait.py. Forge calls and the clock are faked; no test touches a network."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ci_wait  # noqa: E402

URL = "https://example.test/runs/1"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run(status, conclusion=None):
    return {"status": status, "conclusion": conclusion, "url": URL}


def wait_for(runs, max_seconds=240):
    clock = FakeClock()
    calls = []

    def fetch(timeout):
        calls.append(timeout)
        return runs(clock.now) if callable(runs) else runs

    result = ci_wait.wait(fetch, max_seconds, 30, clock.time, clock.sleep)
    return result, clock, calls


class WaitTest(unittest.TestCase):
    def test_returns_success_for_a_green_run(self):
        result, _, _ = wait_for([run("completed", "success")])
        self.assertEqual(result, {"state": "success", "url": URL})

    def test_returns_failure_for_a_red_run(self):
        result, _, _ = wait_for([run("completed", "success"), run("completed", "failure")])
        self.assertEqual(result, {"state": "failure", "url": URL})

    def test_returns_pending_before_the_window_ends(self):
        result, clock, _ = wait_for([run("in_progress")], max_seconds=90)
        self.assertEqual(result["state"], "pending")
        self.assertEqual(clock.now, 90)

    def test_returns_success_when_a_run_finishes_during_the_window(self):
        def runs(now):
            return [run("completed", "success")] if now >= 60 else [run("in_progress")]

        result, clock, _ = wait_for(runs)
        self.assertEqual(result["state"], "success")
        self.assertEqual(clock.now, 60)

    def test_returns_missing_when_no_run_exists(self):
        result, _, _ = wait_for([], max_seconds=60)
        self.assertEqual(result, {"state": "missing", "url": None})

    def test_ends_within_max_seconds(self):
        _, clock, calls = wait_for([run("queued")], max_seconds=100)
        self.assertLessEqual(clock.now, 100)
        self.assertTrue(all(timeout <= 100 for timeout in calls))

    def test_treats_a_skipped_run_as_green(self):
        result, _, _ = wait_for([run("completed", "skipped")])
        self.assertEqual(result["state"], "success")


class ParseTest(unittest.TestCase):
    def test_reads_github_runs_from_gh_json(self):
        body = '[{"databaseId": 7, "status": "completed", "conclusion": "success", "url": "u"}]'
        self.assertEqual(ci_wait.parse_github(body),
                         [{"status": "completed", "conclusion": "success", "url": "u"}])

    def test_reads_gitea_runs_from_the_api_object(self):
        body = '{"workflow_runs": [{"status": "completed", "conclusion": "failure", "html_url": "h"}]}'
        self.assertEqual(ci_wait.parse_gitea(body),
                         [{"status": "completed", "conclusion": "failure", "url": "h", "path": ""}])

    def test_rejects_a_gitea_reply_without_a_run_list(self):
        with self.assertRaises(ci_wait.WaitError):
            ci_wait.parse_gitea('{"message": "not found"}')


class CommandLineTest(unittest.TestCase):
    def test_exits_nonzero_with_one_stderr_line_on_a_bad_invocation(self):
        done = subprocess.run([sys.executable, str(SCRIPTS / "ci_wait.py"), "--forge", "github", "--sha", "abc"],
                              capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)
        self.assertEqual(done.stdout, "")

    def test_exits_1_with_one_stderr_line_on_malformed_gh_output(self):
        with tempfile.TemporaryDirectory() as bin_dir:
            fake = Path(bin_dir) / "gh"
            fake.write_text("#!/bin/sh\necho 'not json'\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
            done = subprocess.run([sys.executable, str(SCRIPTS / "ci_wait.py"), "--forge", "github",
                                   "--repo", "o/r", "--sha", "abc", "--max-seconds", "5"],
                                  capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)
        self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()
