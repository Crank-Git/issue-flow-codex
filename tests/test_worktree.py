"""Tests for scripts/worktree.py.

A local bare repository stands in for the remote. No test uses a network.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "worktree.py"
BRANCH = "issue/19-demo"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


class WorktreeTest(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="worktree-test-"))
        self.addCleanup(shutil.rmtree, self.work)
        bare = self.work / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        self.project = self.work / "project"
        subprocess.run(["git", "clone", "-q", str(bare), str(self.project)],
                       check=True, capture_output=True)
        git(self.project, "config", "user.email", "test@example.invalid")
        git(self.project, "config", "user.name", "Test")
        (self.project / ".gitignore").write_text(".worktrees/\n.env\n")
        (self.project / "tracked.txt").write_text("tracked\n")
        (self.project / ".worktreeinclude").write_text(".env\ntracked.txt\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "init")
        git(self.project, "push", "-q", "origin", "HEAD:main")
        git(self.project, "fetch", "-q", "origin")
        self.tree = self.project / ".worktrees" / "worker_19"

    def create(self):
        return run_script("create", "--project", str(self.project), "--task", "worker_19",
                          "--branch", BRANCH, "--base", "origin/main")

    def remove(self):
        return run_script("remove", "--project", str(self.project), "--task", "worker_19")

    def test_creates_the_worktree_on_the_branch_from_the_base(self):
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.tree, "rev-parse", "--abbrev-ref", "HEAD"), BRANCH)
        self.assertEqual(git(self.tree, "rev-parse", "HEAD"),
                         git(self.project, "rev-parse", "origin/main"))

    def test_prints_one_json_line_with_path_branch_and_base_sha(self):
        result = self.create()
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["path"], str(self.tree.resolve()))
        self.assertEqual(data["branch"], BRANCH)
        self.assertEqual(data["base_sha"], git(self.project, "rev-parse", "origin/main"))

    def test_copies_an_ignored_file_that_worktreeinclude_names(self):
        (self.project / ".env").write_text("SECRET=1\n")
        self.create()
        self.assertEqual((self.tree / ".env").read_text(), "SECRET=1\n")

    def test_does_not_copy_a_tracked_file_that_worktreeinclude_names(self):
        (self.project / "tracked.txt").write_text("edited in the main checkout\n")
        self.create()
        self.assertEqual((self.tree / "tracked.txt").read_text(), "tracked\n")

    def test_excludes_the_worktrees_directory_when_no_ignore_rule_covers_it(self):
        (self.project / ".gitignore").write_text(".env\n")
        git(self.project, "commit", "-q", "-am", "drop the worktrees line")
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.project, "status", "--porcelain"), "")
        self.assertEqual((self.project / ".gitignore").read_text(), ".env\n")
        exclude = (self.project / ".git" / "info" / "exclude").read_text()
        self.assertEqual(exclude.splitlines().count(".worktrees/"), 1)

    def test_leaves_the_exclude_file_unchanged_when_gitignore_covers_the_worktrees(self):
        exclude = self.project / ".git" / "info" / "exclude"
        before = exclude.read_text() if exclude.exists() else None
        self.create()
        self.assertEqual(exclude.read_text() if exclude.exists() else None, before)

    def test_refuses_to_remove_a_worktree_with_an_uncommitted_file(self):
        self.create()
        (self.tree / "new.txt").write_text("x\n")
        result = self.remove()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(self.tree.exists())

    def test_refuses_to_remove_a_worktree_with_an_unpushed_commit(self):
        self.create()
        git(self.tree, "config", "user.email", "test@example.invalid")
        git(self.tree, "config", "user.name", "Test")
        (self.tree / "new.txt").write_text("x\n")
        git(self.tree, "add", "new.txt")
        git(self.tree, "commit", "-q", "-m", "work")
        result = self.remove()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.tree.exists())

    def test_removes_a_clean_pushed_worktree_and_its_branch(self):
        self.create()
        git(self.tree, "push", "-q", "origin", BRANCH)
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.tree.exists())
        self.assertEqual(git(self.project, "branch", "--list", BRANCH), "")

    def commit_work(self):
        git(self.tree, "config", "user.email", "test@example.invalid")
        git(self.tree, "config", "user.name", "Test")
        (self.tree / "new.txt").write_text("x\n")
        git(self.tree, "add", "new.txt")
        git(self.tree, "commit", "-q", "-m", "work")

    def test_removes_a_squash_merged_worktree_with_merged_after_the_remote_branch_is_gone(self):
        self.create()
        self.commit_work()
        git(self.tree, "push", "-q", "origin", BRANCH)
        git(self.project, "fetch", "-q", "origin")
        git(self.project, "push", "-q", "origin", "--delete", BRANCH)
        git(self.project, "fetch", "-q", "--prune", "origin")
        self.assertEqual(self.remove().returncode, 1)
        result = run_script("remove", "--project", str(self.project), "--task", "worker_19",
                            "--merged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.tree.exists())
        self.assertEqual(git(self.project, "branch", "--list", BRANCH), "")

    def test_still_refuses_uncommitted_changes_with_merged(self):
        self.create()
        (self.tree / "new.txt").write_text("x\n")
        result = run_script("remove", "--project", str(self.project), "--task", "worker_19",
                            "--merged")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(self.tree.exists())

    def test_refuses_a_worktree_with_a_detached_head(self):
        self.create()
        git(self.tree, "checkout", "-q", "--detach")
        result = self.remove()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(self.tree.exists())

    def test_reuses_an_existing_branch_that_has_no_worktree(self):
        git(self.project, "branch", BRANCH, "origin/main")
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.tree, "rev-parse", "--abbrev-ref", "HEAD"), BRANCH)

    def test_fails_with_one_stderr_line_when_the_base_is_missing(self):
        result = run_script("create", "--project", str(self.project), "--task", "worker_19",
                            "--branch", BRANCH, "--base", "origin/nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(result.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
