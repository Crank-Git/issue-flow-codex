"""Tests for scripts/verify_claim.py. Ported from upstream scripts/test-verify-claim.py.

Builds a tiny real git repository with two commits. The second commit adds a symbol.
No test touches a network or the working repository.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verify_claim  # noqa: E402


def git(repo, *args, env=None):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def build_repo(root):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    commits = []
    for name, text in (("a.py", "print('hello')\n"), ("b.py", "def new_helper():\n    return 1\n")):
        with open(os.path.join(repo, name), "w") as handle:
            handle.write(text)
        git(repo, "add", name)
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", name, env=env)
        commits.append(git(repo, "rev-parse", "HEAD"))
    return repo, commits[0], commits[1]


class VerifyClaimTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.mkdtemp(prefix="verify-claim-test-")
        self.addCleanup(shutil.rmtree, work)
        self.repo, self.first_sha, self.second_sha = build_repo(work)

    def test_finds_a_symbol_at_head(self):
        code, payload = verify_claim.check(self.repo, "HEAD", "def new_helper", None)
        self.assertEqual(code, 0)
        self.assertTrue(payload["found"])

    def test_does_not_find_a_symbol_at_the_commit_before_it_was_added(self):
        code, payload = verify_claim.check(self.repo, self.first_sha, "def new_helper", None)
        self.assertEqual(code, 0)
        self.assertFalse(payload["found"])

    def test_reports_a_stale_ref_when_the_ref_differs_from_the_expected_sha(self):
        code, payload = verify_claim.check(self.repo, self.first_sha, "def new_helper", self.second_sha)
        self.assertEqual(code, 3)
        self.assertTrue(payload.get("stale"))

    def test_exits_2_for_a_ref_that_does_not_resolve(self):
        code, _ = verify_claim.check(self.repo, "does-not-exist-ref", "def new_helper", None)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
