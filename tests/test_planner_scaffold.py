"""Contract tests for the project-planner scaffold instructions."""

import unittest
from pathlib import Path


SCAFFOLD = (Path(__file__).resolve().parent.parent / "skills" / "project-planner"
            / "references" / "scaffold.md")


class ProjectScaffoldTest(unittest.TestCase):
    def test_scaffold_describes_the_codex_root_document_and_rule_files(self):
        text = SCAFFOLD.read_text()

        for token in ("### `AGENTS.md`", "docs/rules/ste.md", "docs/rules/quality.md",
                      "docs/rules/external-apis.md", "24 KiB", "issue_flow"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_scaffold_preserves_existing_project_files_until_approval(self):
        text = SCAFFOLD.read_text()

        for token in ("`AGENTS.md` already exists", "`CLAUDE.md` exists",
                      "`.codex/config.toml`", "`.gitignore`", "Move nothing until approval"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_scaffold_includes_run_and_test_skill_templates(self):
        text = SCAFFOLD.read_text()

        self.assertIn(".agents/skills/run/SKILL.md", text)
        self.assertIn(".agents/skills/test/SKILL.md", text)
        self.assertIn("description: Start the app locally", text)
        self.assertIn("description: Run the project test suites", text)

    def test_scaffold_keeps_root_agent_documents_under_the_cap(self):
        text = SCAFFOLD.read_text()

        self.assertIn("root file and every nested `AGENTS.md`\ntogether under 24 KiB", text)
        self.assertIn("move detail into `docs/rules/`", text)

    def test_scaffold_defines_project_skills_and_safe_hooks(self):
        text = SCAFFOLD.read_text()

        for token in (".codex/hooks.json", "trusts", "fast", "idempotent",
                      "non-interactive", "Never delete data", "remote service",
                      "command -v", "Run the project test suites"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_scaffold_defines_dual_harness_files_and_gitignore(self):
        text = SCAFFOLD.read_text()

        for token in ("dual-harness mode", "`CLAUDE.md`", "@AGENTS.md",
                      "`.claude/rules/<name>.md`", "paths:", ".worktrees/",
                      ".issue-flow.local.json", ".claude/settings.local.json",
                      "CLAUDE.local.md"):
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
