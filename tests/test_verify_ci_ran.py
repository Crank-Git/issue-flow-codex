"""Tests for scripts/verify_ci_ran.py. Ported from upstream scripts/test-verify-ci-ran.py.

`decide_ran` is pure. The two exit-code tests run the script without a network call.
"""

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_ci_ran  # noqa: E402

SCRIPT = SCRIPTS / "verify_ci_ran.py"


class DecideRanTest(unittest.TestCase):
    def test_reports_not_ran_when_there_are_no_runs(self):
        self.assertFalse(verify_ci_ran.decide_ran([])["ran"])

    def test_reports_not_ran_for_a_run_with_zero_log_bytes(self):
        # Status alone is not evidence that a run happened.
        result = verify_ci_ran.decide_ran([{"id": 1, "status": "completed", "log_bytes": 0}])
        self.assertFalse(result["ran"])

    def test_reports_ran_for_a_run_with_log_bytes(self):
        result = verify_ci_ran.decide_ran([{"id": 1, "status": "completed", "log_bytes": 5000}])
        self.assertTrue(result["ran"])

    def test_counts_only_the_run_that_has_log_bytes(self):
        result = verify_ci_ran.decide_ran([
            {"id": 1, "status": "completed", "log_bytes": 0},
            {"id": 2, "status": "completed", "log_bytes": 800},
        ])
        self.assertTrue(result["ran"])
        self.assertEqual(len(result.get("runs", [])), 1)

    def test_reports_running_for_a_status_that_is_not_yet_terminal(self):
        # An approval-gated GitHub run or a Gitea "waiting" run must not read as "never ran".
        for status in ("waiting", "requested", "pending"):
            with self.subTest(status=status):
                result = verify_ci_ran.decide_ran([{"id": 1, "status": status, "log_bytes": 0}])
                self.assertFalse(result["ran"])
                self.assertTrue(result.get("running"))


class ExitCodeTest(unittest.TestCase):
    # Exit 5 differs from "still running" and from the infra-retry code, so a caller that
    # polls on the bare exit code does not loop forever on a typo.
    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_exits_5_for_forge_github_without_repo(self):
        proc = self.run_script("--forge", "github", "--sha", "deadbeef")
        self.assertEqual(proc.returncode, 5, proc.stderr)

    def test_exits_5_when_neither_forge_nor_fixture_is_given(self):
        proc = self.run_script("--sha", "deadbeef")
        self.assertEqual(proc.returncode, 5, proc.stderr)


if __name__ == "__main__":
    unittest.main()
