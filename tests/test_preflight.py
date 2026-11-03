"""Tests for hooks/preflight.py. Ported from upstream scripts/test-preflight.py.

Runs the hook as a subprocess fed a SessionStart payload on stdin, against throwaway git
repositories. Three properties matter: the hook is silent everywhere except a repository
that carries `.issue-flow.json`, its digest reports the facts Phase 0 would otherwise
re-derive, and it fails open on anything it does not understand. Forge queries run only
through their skip path, so the suite passes offline and unauthenticated.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "preflight.py"
LABELS_MD = ROOT / "skills" / "issue-flow" / "references" / "labels.md"
# The Codex manifest path.
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
PAYLOAD = {"hook_event_name": "SessionStart", "source": "startup"}


def git(repo, *args):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def make_project(base):
    """Return a repository with a local bare remote, an epic branch, and an issue-flow config."""
    remote = os.path.join(base, "remote.git")
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", remote], check=True)
    repo = os.path.join(base, "project")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("test\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", remote)
    git(repo, "push", "-q", "origin", "main")
    git(repo, "push", "-q", "origin", "main:refs/heads/dev")
    git(repo, "push", "-q", "origin", "main:refs/heads/epic/42-auth")
    write_config(repo, {"version": 1, "forge": {"type": "gitea"}})  # gitea keeps gh off the network
    return repo


def write_config(repo, config):
    with open(os.path.join(repo, ".issue-flow.json"), "w", encoding="utf-8") as handle:
        json.dump(config, handle)


class PreflightTest(unittest.TestCase):
    def setUp(self):
        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        self.base = base.name
        self.project = make_project(self.base)

    def run_hook(self, payload, cwd, env=None):
        """Return the digest text the hook emitted, or None when it stayed silent."""
        environment = dict(os.environ)
        environment.pop("ISSUE_FLOW_PREFLIGHT", None)
        environment.update(env or {})
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True, text=True, cwd=cwd, env=environment, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return None
        specific = json.loads(result.stdout).get("hookSpecificOutput", {})
        self.assertEqual(specific.get("hookEventName"), "SessionStart")
        return specific.get("additionalContext")

    def digest(self):
        return self.run_hook(dict(PAYLOAD, cwd=self.project), self.project) or ""

    def not_a_repo(self):
        path = os.path.join(self.base, "notrepo")
        os.makedirs(path)
        return path

    def test_stays_silent_in_a_repository_without_an_issue_flow_config(self):
        plain = os.path.join(self.base, "plain")
        subprocess.run(["git", "init", "-q", "-b", "main", plain], check=True)
        self.assertIsNone(self.run_hook(dict(PAYLOAD, cwd=plain), plain))

    def test_stays_silent_in_a_directory_that_is_not_a_repository(self):
        not_repo = self.not_a_repo()
        self.assertIsNone(self.run_hook(dict(PAYLOAD, cwd=not_repo), not_repo))

    def test_stays_silent_when_the_kill_switch_is_off(self):
        out = self.run_hook(dict(PAYLOAD, cwd=self.project), self.project,
                            env={"ISSUE_FLOW_PREFLIGHT": "off"})
        self.assertIsNone(out)

    def test_reports_the_facts_phase_0_would_re_derive(self):
        digest = self.digest()
        for expected in ("issue-flow preflight", "remote: origin (fetched", "epic/42-auth",
                         "dev branch: present", "worktrees from an earlier session: none",
                         "forge queries: skipped (forge is gitea"):
            self.assertIn(expected, digest)

    def test_says_so_when_the_config_records_no_plugin_version(self):
        self.assertIn("no pluginVersion recorded", self.digest())

    def test_reports_a_matching_plugin_version(self):
        installed = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
        write_config(self.project, {"version": 1, "forge": {"type": "gitea"},
                                    "pluginVersion": installed})
        self.assertIn(f"plugin version: {installed} (matches the last run)", self.digest())

    def test_flags_a_stale_plugin_version_as_drift(self):
        installed = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
        write_config(self.project, {"version": 1, "forge": {"type": "gitea"},
                                    "pluginVersion": "0.0.1"})
        self.assertIn(f"plugin version: {installed}, project last ran 0.0.1", self.digest())

    def test_reads_the_branch_model_from_the_spec_front_matter(self):
        specs = os.path.join(self.project, "docs", "specs")
        os.makedirs(specs)
        with open(os.path.join(specs, "spec.md"), "w", encoding="utf-8") as handle:
            handle.write("---\nbranch_model: dev-and-live\n---\n# Spec\n")
        self.assertIn("spec branch_model: dev-and-live", self.digest())

    def test_reports_a_worktree_left_by_an_earlier_session_without_calling_it_removable(self):
        worktree = os.path.join(self.base, "leftover")
        git(self.project, "worktree", "add", "-q", "-b", "issue/7-fix", worktree)
        digest = self.digest()
        self.assertIn("issue/7-fix", digest)
        self.assertIn("check each issue's status before removing", digest)
        # "leftover" tells the PM to remove a tree that Phase 0 may keep.
        self.assertNotIn("leftover worktrees", digest)

    def test_still_produces_a_digest_for_malformed_stdin(self):
        self.assertIsNotNone(self.run_hook("{not json", self.project))

    def test_stays_silent_for_malformed_stdin_outside_a_project(self):
        self.assertIsNone(self.run_hook("", self.not_a_repo()))

    def test_keeps_the_git_side_digest_when_the_config_is_unreadable(self):
        with open(os.path.join(self.project, ".issue-flow.json"), "w", encoding="utf-8") as handle:
            handle.write("{broken json")
        self.assertIn("issue-flow preflight", self.digest())


class LabelSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("preflight", HOOK)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_keeps_the_standard_labels_in_sync_with_labels_md(self):
        documented = re.findall(r'^gh label create "([^"]+)"',
                                LABELS_MD.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertTrue(documented, "could not parse the bootstrap labels out of labels.md")
        self.assertEqual(set(documented), set(self.module.STANDARD_LABELS))

    def test_keeps_every_parked_label_in_the_standard_labels(self):
        for parked in self.module.PARKED_LABELS:
            self.assertIn(parked, self.module.STANDARD_LABELS)


if __name__ == "__main__":
    unittest.main()
