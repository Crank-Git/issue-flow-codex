"""Tests for release tag selection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release_tag  # noqa: E402


class ReleaseTagTest(unittest.TestCase):
    def test_returns_a_tag_when_the_manifest_version_changes(self):
        old = b'{"version":"0.1.0"}'
        new = b'{"version":"0.1.1"}'

        self.assertEqual(release_tag.tag_for_change(old, new), "issue-flow-codex--v0.1.1")

    def test_returns_no_tag_when_the_manifest_version_is_unchanged(self):
        manifest = b'{"version":"0.1.0"}'

        self.assertIsNone(release_tag.tag_for_change(manifest, manifest))

    def test_returns_a_tag_when_the_manifest_is_new_on_main(self):
        current = b'{"version":"0.1.0"}'

        self.assertEqual(release_tag.tag_for_change(b"", current), "issue-flow-codex--v0.1.0")

    def test_rejects_a_changed_manifest_with_an_invalid_version(self):
        old = b'{"version":"0.1.0"}'
        new = b'{"version":"next"}'

        with self.assertRaisesRegex(ValueError, "invalid manifest version"):
            release_tag.tag_for_change(old, new)


class ReleaseDocsTest(unittest.TestCase):
    def test_workflow_limits_tagging_to_main_manifest_changes(self):
        workflow = (ROOT / ".github" / "workflows" / "tag-release.yml").read_text()

        self.assertIn("branches:\n      - main", workflow)
        self.assertIn("paths:\n      - .codex-plugin/plugin.json", workflow)
        self.assertIn("permissions:\n  contents: write", workflow)
        self.assertIn("git tag \"$tag\"", workflow)
        self.assertIn("git push origin \"$tag\"", workflow)
        self.assertIn("git cat-file -e", workflow)
        self.assertNotIn("gh release create", workflow)

    def test_readme_documents_codex_setup_hook_trust_and_skill_invocations(self):
        readme = (ROOT / "README.md").read_text()

        self.assertIn("codex plugin marketplace add Crank-Git/issue-flow-codex", readme)
        self.assertIn("codex plugin add issue-flow@issue-flow-codex", readme)
        self.assertIn("run `/hooks` and trust the issue-flow hooks", readme)
        for skill in ("project-planner", "project-inherit", "spec-update",
                      "spec-to-issues", "issue-flow", "project-review", "repo-mirror"):
            self.assertIn(f"`$issue-flow:{skill}`", readme)


if __name__ == "__main__":
    unittest.main()
