"""Tests for scripts/build_roles.py (FR-worker-dispatch-12).

Each fixture is a small repository in a temporary directory.
"""

import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_roles  # noqa: E402
import validate_manifests  # noqa: E402

AGENT = """---
name: issue-worker
description: >
  Builds one issue
  inside a worktree.
model: gpt-6.1-sol
---

You are a worker. Run `git status` and keep a 'quote' and a \\ backslash.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / "agents").mkdir()
        (self.repo / "agents" / "issue-worker.md").write_text(AGENT, encoding="utf-8")
        (self.repo / "agents" / "other-agent.md").write_text(
            AGENT.replace("issue-worker", "other-agent"), encoding="utf-8")

    def role(self):
        build_roles.write(self.repo)
        text = (self.repo / "roles" / "issue-worker.toml").read_text(encoding="utf-8")
        return tomllib.loads(text)


class TestBuildRoles(Fixture):
    def test_writes_the_role_name_with_underscores(self):
        self.assertEqual(self.role()["name"], "issue_worker")

    def test_puts_the_markdown_body_in_developer_instructions(self):
        instructions = self.role()["developer_instructions"]
        self.assertIn("Run `git status` and keep a 'quote' and a \\ backslash.", instructions)
        self.assertNotIn("name: issue-worker", instructions)

    def test_sets_the_issue_worker_model_and_effort(self):
        role = self.role()
        self.assertEqual(role["model"], "gpt-6.1-sol")
        self.assertEqual(role["model_reasoning_effort"], "medium")

    def test_joins_the_folded_description_into_one_line(self):
        self.assertEqual(self.role()["description"], "Builds one issue inside a worktree.")

    def test_builds_only_ported_agents(self):
        build_roles.write(self.repo)
        self.assertEqual([p.name for p in (self.repo / "roles").iterdir()],
                         ["issue-worker.toml"])

    def test_check_passes_on_a_fresh_role_file(self):
        build_roles.write(self.repo)
        self.assertEqual(build_roles.stale(self.repo), [])

    def test_check_fails_on_a_stale_role_file(self):
        build_roles.write(self.repo)
        agent = self.repo / "agents" / "issue-worker.md"
        agent.write_text(AGENT + "A new line.\n", encoding="utf-8")
        self.assertEqual(build_roles.stale(self.repo), ["roles/issue-worker.toml"])
        self.assertEqual(build_roles.main(["--check", "--root", str(self.repo)]), 1)

    def test_check_fails_when_the_role_file_is_missing(self):
        self.assertEqual(build_roles.stale(self.repo), ["roles/issue-worker.toml"])


class TestRepositoryRole(unittest.TestCase):
    def test_built_role_file_is_current(self):
        self.assertEqual(build_roles.stale(ROOT), [])

    def test_manifest_validation_passes_on_the_built_role(self):
        self.assertEqual(validate_manifests.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()
