import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parent.parent / "skills" / "project-review" / "SKILL.md"


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


if __name__ == "__main__":
    unittest.main()
