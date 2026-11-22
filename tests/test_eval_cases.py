"""Tests for the eval cases imported from upstream. No test uses the network or Codex."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
WORKER = EVALS / "worker"
CHECKER = EVALS / "checker"
# The `hidden_tests` grader of upstream copies `hidden/` to the checkout root and runs this.
HIDDEN_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "hidden_test*.py"]


def worker_cases():
    return sorted(p for p in WORKER.iterdir() if (p / "case.json").is_file())


def patch_cases():
    return [case for case in worker_cases() if (case / "reference.patch").is_file()]


def load_case(case):
    return json.loads((case / "case.json").read_text(encoding="utf-8"))


def grader_types(case):
    return {grader["type"] for grader in load_case(case)["graders"]}


def run_hidden_tests(case, patch):
    """Copy the fixture and the hidden tests to a temp directory, and run them there.

    The repository tree stays untouched. Returns the completed process.
    """
    fixture = (case / load_case(case)["fixture"]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "checkout"
        shutil.copytree(fixture, work)
        shutil.copytree(case / "hidden", work, dirs_exist_ok=True)
        if patch:
            subprocess.run(["git", "apply", str(case / "reference.patch")], cwd=work,
                           check=True, capture_output=True)
        return subprocess.run(HIDDEN_COMMAND, cwd=work, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


class SuiteTest(unittest.TestCase):
    def test_worker_suite_has_eleven_cases(self):
        self.assertEqual(len(worker_cases()), 11)
        self.assertTrue((WORKER / "_fixture").is_dir())
        self.assertTrue((WORKER / "_fixture_large").is_dir())

    def test_ten_worker_cases_have_a_reference_patch_and_hidden_tests(self):
        names = [case.name for case in patch_cases()]
        self.assertEqual(len(names), 10)
        self.assertNotIn("worker-hard-ambiguous-tax", names)
        for case in patch_cases():
            self.assertTrue(any((case / "hidden").glob("hidden_test*.py")), case.name)

    def test_checker_cases_present(self):
        cases = sorted(p for p in CHECKER.iterdir() if (p / "case.json").is_file())
        self.assertEqual(len(cases), 11)
        self.assertEqual(len([c for c in cases if c.name.startswith("checker-full-")]), 10)
        self.assertTrue((CHECKER / "checker-partial-hard-error-lines" / "partial.patch").is_file())
        for case in cases:
            self.assertEqual(
                grader_types(case) - {"checker_verdict", "refs_unchanged", "gh_log"}, set(),
                case.name)

    def test_case_graders_kept(self):
        for case in worker_cases():
            types = grader_types(case)
            self.assertIn("verdict", types, case.name)
            self.assertIn("gh_log", types, case.name)
            if case in patch_cases():
                self.assertIn("hidden_tests", types, case.name)
                self.assertIn("diff_scope", types, case.name)

    def test_readme_names_source_tag_license(self):
        text = (EVALS / "README.md").read_text(encoding="utf-8")
        for needle in ("Sniper7Kills-LLC/claude-plugins", "issue-flow--v0.21.0", "MIT",
                       "Copyright (c) 2026 Sniper7Kills LLC"):
            self.assertIn(needle, text)

    def test_worker_briefs_are_consistent(self):
        """A `ci: skip` brief names a single-member batch whose type:batch issue is in the tracker.

        Port of upstream `test_briefs_are_consistent` (scripts/test-worker-cases.py, c7b95d2).
        """
        for case in worker_cases():
            data = load_case(case)
            brief = re.search(r"^BRIEF START\n(.*?)^BRIEF END", data["prompt"], re.S | re.M).group(1)
            fields = dict(re.findall(r"^(\w+):\s+(\S.*?)\s*$", brief, re.M))
            with self.subTest(case=case.name):
                self.assertEqual(fields.get("ci"), "skip")
                batch = re.fullmatch(r"batch #(\d+)", fields.get("batch", ""))
                self.assertIsNotNone(batch, fields.get("batch"))
                self.assertEqual(fields.get("members"), "1")
                self.assertTrue(fields.get("crossCheck", "").startswith("n/a"))
                tracker = json.loads((case / data["tracker"]).read_text(encoding="utf-8"))
                tracking = [i for i in tracker["issues"] if i["number"] == int(batch.group(1))]
                self.assertEqual(len(tracking), 1)
                self.assertIn("type:batch", tracking[0]["labels"])
                issue = int(re.search(r"#(\d+)", fields["issue"]).group(1))
                self.assertNotEqual(int(batch.group(1)), issue)

    def test_results_directory_is_ignored_by_git(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("evals/results/", lines)


class HiddenTestsTest(unittest.TestCase):
    def test_reference_patch_passes_hidden_tests(self):
        for case in patch_cases():
            with self.subTest(case=case.name):
                result = run_hidden_tests(case, patch=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hidden_tests_fail_on_bare_fixture(self):
        for case in patch_cases():
            with self.subTest(case=case.name):
                self.assertNotEqual(run_hidden_tests(case, patch=False).returncode, 0)

    def test_the_run_leaves_the_repository_tree_clean(self):
        case = patch_cases()[0]
        run_hidden_tests(case, patch=True)
        status = subprocess.run(["git", "status", "--porcelain", "--", "evals"], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertNotIn("__pycache__", status.stdout)
        self.assertNotIn(".orig", status.stdout)


class FakeGhTest(unittest.TestCase):
    def test_fake_gh_is_executable(self):
        self.assertTrue(os.access(EVALS / "fakegh" / "gh", os.X_OK))

    def test_fake_gh_unknown_command_exits_1_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gh-log.jsonl"
            tracker = WORKER / "worker-easy-negative-qty" / "tracker.json"
            copy = Path(tmp) / "tracker.json"
            shutil.copy(tracker, copy)
            result = subprocess.run(
                [sys.executable, str(EVALS / "fakegh" / "gh"), "gist", "list"],
                capture_output=True, text=True,
                env={**os.environ, "IFE_TRACKER": str(copy), "IFE_GH_LOG": str(log)})
            self.assertEqual(result.returncode, 1)
            entries = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["kind"], "error")
            self.assertEqual(entries[0]["exit"], 1)


if __name__ == "__main__":
    unittest.main()
