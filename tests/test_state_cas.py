"""Tests for scripts/state_cas.py. Ported from upstream scripts/test-state-cas.py.

A local bare repository stands in for "origin". Local clones stand in for workers.
No test uses a network.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import state_cas  # noqa: E402


def args_for(repo, key, expect, value=None):
    return types.SimpleNamespace(repo=repo, remote="origin", key=key, expect=expect, value=value)


class StateCasTest(unittest.TestCase):
    def setUp(self):
        # `cmd_set` and `cmd_delete` print one JSON result line each.
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        self.work = tempfile.mkdtemp(prefix="state-cas-test-")
        self.addCleanup(shutil.rmtree, self.work)
        bare = os.path.join(self.work, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        self.clone_a = os.path.join(self.work, "a")
        self.clone_b = os.path.join(self.work, "b")
        subprocess.run(["git", "clone", "-q", bare, self.clone_a], check=True)
        subprocess.run(["git", "clone", "-q", bare, self.clone_b], check=True)

    def claim(self, repo, key, owner):
        return state_cas.cmd_set(args_for(repo, key, "absent", json.dumps({"owner": owner})))

    def test_reads_an_absent_key_as_none(self):
        parent, current = state_cas.fetch_current(self.clone_a, "origin", "issue-17")
        self.assertIsNone(current)
        self.assertIsNone(parent)

    def test_creates_a_key_when_it_is_absent(self):
        self.assertEqual(self.claim(self.clone_a, "issue-17", "worker-a"), 0)

    def test_rejects_a_stale_expect_on_the_same_clone(self):
        self.claim(self.clone_a, "issue-17", "worker-a")
        self.assertEqual(self.claim(self.clone_a, "issue-17", "worker-x"), 2)

    def test_rejects_a_create_that_lost_a_race_between_two_clones(self):
        self.assertEqual(self.claim(self.clone_b, "race-key", "worker-b"), 0)
        # clone_a never fetched worker-b's write and still thinks the key is absent.
        self.assertEqual(self.claim(self.clone_a, "race-key", "worker-a"), 2)

    def test_accepts_a_set_that_expects_the_current_value(self):
        self.claim(self.clone_b, "race-key", "worker-b")
        _, current = state_cas.fetch_current(self.clone_a, "origin", "race-key")
        takeover = args_for(self.clone_a, "race-key", json.dumps(current),
                            json.dumps({"owner": "worker-a", "took_over": True}))
        self.assertEqual(state_cas.cmd_set(takeover), 0)

    def add_worktrees(self):
        # `isolation: "worktree"` gives every worker a linked worktree of one clone.
        trees = []
        for name in ("wt-a", "wt-b"):
            path = os.path.join(self.work, name)
            subprocess.run(["git", "worktree", "add", "-q", path], cwd=self.clone_a, check=True)
            trees.append(path)
        return trees

    def test_pushes_two_worktrees_to_different_keys_without_clobbering(self):
        # Both commits exist before either push. A push by ref name would let the second
        # update-ref overwrite the first worker's ref, so the first would push the wrong commit.
        tree_a, tree_b = self.add_worktrees()
        commit_a = state_cas.write_commit(tree_a, "shared-key-a", {"owner": "worker-a"}, None)
        commit_b = state_cas.write_commit(tree_b, "shared-key-b", {"owner": "worker-b"}, None)
        push_a = state_cas.run(
            ["git", "push", "origin", f"{commit_a}:{state_cas.ref_name('shared-key-a')}"], tree_a)
        push_b = state_cas.run(
            ["git", "push", "origin", f"{commit_b}:{state_cas.ref_name('shared-key-b')}"], tree_b)
        self.assertEqual((push_a.returncode, push_b.returncode), (0, 0))
        _, value_a = state_cas.fetch_current(self.clone_a, "origin", "shared-key-a")
        _, value_b = state_cas.fetch_current(self.clone_a, "origin", "shared-key-b")
        self.assertEqual(value_a, {"owner": "worker-a"})
        self.assertEqual(value_b, {"owner": "worker-b"})

    def test_rejects_the_second_push_to_a_contended_key(self):
        tree_a, tree_b = self.add_worktrees()
        commit_a = state_cas.write_commit(tree_a, "contended-key", {"owner": "worker-a"}, None)
        commit_b = state_cas.write_commit(tree_b, "contended-key", {"owner": "worker-b"}, None)
        ref = state_cas.ref_name("contended-key")
        push_a = state_cas.run(["git", "push", "origin", f"{commit_a}:{ref}"], tree_a)
        push_b = state_cas.run(["git", "push", "origin", f"{commit_b}:{ref}"], tree_b)
        self.assertEqual(push_a.returncode, 0)
        self.assertNotEqual(push_b.returncode, 0)
        self.assertTrue(state_cas.is_ref_rejection(push_b.stderr.decode()), push_b.stderr)
        _, value = state_cas.fetch_current(self.clone_a, "origin", "contended-key")
        self.assertEqual(value, {"owner": "worker-a"})

    def test_deletes_a_key_whose_value_matches_the_expected_value(self):
        self.claim(self.clone_a, "issue-17", "worker-a")
        delete = args_for(self.clone_a, "issue-17", json.dumps({"owner": "worker-a"}))
        self.assertEqual(state_cas.cmd_delete(delete), 0)
        _, after = state_cas.fetch_current(self.clone_a, "origin", "issue-17")
        self.assertIsNone(after)

    def test_rejects_a_delete_whose_lease_went_stale_before_the_push(self):
        # The remote value changes between the caller's read and its delete push. A blind
        # `git push <remote> :<ref>` would erase worker-b's live claim. The lease must refuse it.
        self.claim(self.clone_a, "issue-17", "worker-a")
        parent_before_race, _ = state_cas.fetch_current(self.clone_a, "origin", "issue-17")
        takeover = args_for(self.clone_b, "issue-17", json.dumps({"owner": "worker-a"}),
                            json.dumps({"owner": "worker-b"}))
        self.assertEqual(state_cas.cmd_set(takeover), 0)
        ref = state_cas.ref_name("issue-17")
        stale = state_cas.run(
            ["git", "push", f"--force-with-lease={ref}:{parent_before_race}", "origin", f":{ref}"],
            self.clone_a)
        self.assertNotEqual(stale.returncode, 0)
        _, still_claimed = state_cas.fetch_current(self.clone_a, "origin", "issue-17")
        self.assertEqual(still_claimed, {"owner": "worker-b"})


if __name__ == "__main__":
    unittest.main()
