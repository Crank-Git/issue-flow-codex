import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parent.parent / "skills" / "project-review" / "SKILL.md"
SCRIBE = Path(__file__).resolve().parent.parent / "agents" / "review-scribe.md"


class ProjectReviewPlaywrightPreflightTest(unittest.TestCase):
    def test_missing_playwright_server_prints_add_command_and_stops(self):
        text = SKILL.read_text()
        preflight = text.split("# Phase 0 — Preflight", 1)[1].split("# Phase 1 — E2E baseline", 1)[0]

        self.assertIn("`codex mcp list`", preflight)
        self.assertIn("`playwright`", preflight)
        self.assertIn("codex mcp add playwright -- npx -y @playwright/mcp@0.0.84", preflight)
        self.assertIn("stop before you spawn a browser role", preflight)
        self.assertNotIn("runs `codex mcp add`", preflight)
        self.assertLess(preflight.index("codex mcp list"), preflight.index("spawn"))
        self.assertIn("https://github.com/microsoft/playwright-mcp/releases", preflight)


class ProjectReviewDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL.read_text()

    def section(self, start, end):
        return self.text.split(start, 1)[1].split(end, 1)[0]

    def test_browser_roles_use_codex_spawn_and_final_answer_contract(self):
        phase = self.section("# Phase 2 — Fan out the reviewers", "# Phase 3 — Gather & file")

        self.assertIn("list_agents", phase)
        self.assertIn('fork_turns: "none"', phase)
        self.assertIn("spawn_agent", phase)
        self.assertIn("wait_agent", phase)
        self.assertIn("FINAL_ANSWER", phase)
        self.assertIn("Run only one browser-driving subagent at a", phase)
        self.assertIn("`ux_explorer`", phase)
        self.assertIn("`deploy_verifier`", phase)

    def test_skill_uses_codex_dispatch_primitives(self):
        self.assertIn("spawn_agent", self.text)
        self.assertIn("followup_task", self.text)
        self.assertNotIn("SendMessage", self.text)
        self.assertNotIn("AskUserQuestion", self.text)
        self.assertNotIn('isolation: "worktree"', self.text)

    def test_explorer_files_stay_under_task_scratch_directory(self):
        phase = self.section("# Phase 2 — Fan out the reviewers", "# Phase 3 — Gather & file")

        self.assertIn(".worktrees/review/ux_<flow_slug_with_underscores>/", phase)
        self.assertIn("screenshots", phase)
        self.assertIn("notesFile", phase)
        self.assertIn("The role writes only", phase)
        self.assertIn("its walkthrough under", phase)

    def test_app_start_failure_stops_without_filing(self):
        phase = self.section("# Phase 0 — Preflight", "# Phase 1 — E2E baseline")

        self.assertIn("If the sandbox app does not start", phase)
        self.assertIn("file nothing", phase)

    def test_unreachable_explorer_is_reported_without_a_finding(self):
        phase = self.section("# Phase 2 — Fan out the reviewers", "# Phase 3 — Gather & file")

        self.assertIn("cannot reach `SANDBOX_URL`", phase)
        self.assertIn("returns\n`blocked` or `partial`", phase)
        self.assertIn("unreachable", phase)
        self.assertIn("not add a finding", phase)

    def test_scribe_uses_the_project_worktree_script(self):
        phase = self.section("# Phase 4 — Deliverables PR", "# Phase 5 — Report & hand off")

        self.assertIn("scripts/worktree.py create", phase)
        self.assertIn('fork_turns: "none"', phase)
        self.assertIn("FINAL_ANSWER", phase)
        self.assertIn("worktree.py remove", phase)

    def test_scribe_uses_the_worktree_that_the_pm_creates(self):
        text = SCRIBE.read_text()

        self.assertIn("worktree:      <absolute path created by the PM with scripts/worktree.py>", text)
        self.assertIn("workdir", text)
        self.assertIn("scripts/worktree.py", text)
        self.assertNotIn('isolation: "worktree"', text)
        self.assertNotIn(".claude/worktrees/", text)

    def test_filing_gate_keeps_only_qualifying_findings_as_issues(self):
        phase = self.section("# Phase 3 — Gather & file", "# Phase 4 — Deliverables PR")

        self.assertIn("finding-policy.md", phase)
        self.assertIn("a guard that guards nothing", phase)
        self.assertIn("recorded only", phase)

    def test_teardown_stops_sandbox_and_mcp_processes(self):
        phase = self.section("# Phase 5 — Report & hand off", "# Hard rules")

        self.assertIn("Stop any sandbox you launched", phase)
        self.assertIn("MCP server processes", phase)
        self.assertIn("stop step", phase)
        self.assertIn("worktree.py remove", phase)


if __name__ == "__main__":
    unittest.main()
