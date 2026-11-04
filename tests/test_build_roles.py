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


WATCHER = AGENT.replace("issue-worker", "ci-watcher").replace("gpt-6.1-sol", "gpt-6-luna")
REVIEW_ROLES = {
    "ux-explorer": ("gpt-6.1-sol", "medium"),
    "deploy-verifier": ("gpt-6-luna", "low"),
    "review-scribe": ("gpt-6.1-sol", "medium"),
    "code-auditor": ("gpt-6-luna", "low"),
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / "agents").mkdir()
        (self.repo / "agents" / "issue-worker.md").write_text(AGENT, encoding="utf-8")
        (self.repo / "agents" / "ci-watcher.md").write_text(WATCHER, encoding="utf-8")
        (self.repo / "agents" / "other-agent.md").write_text(
            AGENT.replace("issue-worker", "other-agent"), encoding="utf-8")
        for stem in ("ux-explorer", "deploy-verifier", "review-scribe", "code-auditor"):
            source = ROOT / "agents" / f"{stem}.md"
            (self.repo / "agents" / f"{stem}.md").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8")

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

    def test_sets_the_ci_watcher_model(self):
        build_roles.write(self.repo)
        role = tomllib.loads((self.repo / "roles" / "ci-watcher.toml").read_text(encoding="utf-8"))
        self.assertEqual(role["name"], "ci_watcher")
        self.assertEqual(role["model"], "gpt-6-luna")

    def test_joins_the_folded_description_into_one_line(self):
        self.assertEqual(self.role()["description"], "Builds one issue inside a worktree.")

    def test_builds_only_ported_agents(self):
        build_roles.write(self.repo)
        self.assertEqual(sorted(p.name for p in (self.repo / "roles").iterdir()),
                         ["ci-watcher.toml", "code-auditor.toml", "deploy-verifier.toml",
                          "issue-worker.toml", "review-scribe.toml", "ux-explorer.toml"])

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
        self.assertEqual(sorted(build_roles.stale(self.repo)),
                         ["roles/ci-watcher.toml", "roles/code-auditor.toml",
                          "roles/deploy-verifier.toml", "roles/issue-worker.toml",
                          "roles/review-scribe.toml", "roles/ux-explorer.toml"])

    def test_builds_only_supported_roles(self):
        self.assertEqual(set(build_roles.PORTED), {
            "issue-worker", "ci-watcher", "ux-explorer", "deploy-verifier",
            "review-scribe", "code-auditor",
        })


class TestRepositoryRole(unittest.TestCase):
    def test_built_role_file_is_current(self):
        self.assertEqual(build_roles.stale(ROOT), [])

    def test_ci_watcher_role_file_uses_gpt_6_luna(self):
        role = tomllib.loads((ROOT / "roles" / "ci-watcher.toml").read_text(encoding="utf-8"))
        self.assertEqual(role["name"], "ci_watcher")
        self.assertEqual(role["model"], "gpt-6-luna")

    def test_project_review_roles_use_the_configured_models(self):
        for stem, (model, effort) in REVIEW_ROLES.items():
            with self.subTest(stem=stem):
                role = tomllib.loads((ROOT / "roles" / f"{stem}.toml").read_text())
                self.assertEqual(role["name"], stem.replace("-", "_"))
                self.assertEqual((role["model"], role["model_reasoning_effort"]),
                                 (model, effort))

    def test_browser_roles_name_playwright_tools_with_codex_names(self):
        tools = {
            "ux-explorer": (
                "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
                "browser_take_screenshot", "browser_console_messages", "browser_fill_form",
            ),
            "deploy-verifier": (
                "browser_navigate", "browser_snapshot", "browser_take_screenshot",
                "browser_console_messages",
            ),
        }
        for stem, names in tools.items():
            with self.subTest(stem=stem):
                instructions = tomllib.loads(
                    (ROOT / "roles" / f"{stem}.toml").read_text())["developer_instructions"]
                for name in names:
                    self.assertIn(f"mcp__playwright__{name}", instructions)
                self.assertNotIn("ToolSearch", instructions)

    def test_manifest_validation_passes_on_the_built_role(self):
        self.assertEqual(validate_manifests.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()
