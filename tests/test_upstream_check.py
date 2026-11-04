"""Tests for the scheduled upstream release check."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import upstream_check  # noqa: E402


class TagTest(unittest.TestCase):
    def test_sorts_semantic_tags_above_the_lock(self):
        tags = ["issue-flow--v1.2.0", "issue-flow--v1.10.0",
                "issue-flow--v1.11.0-rc.01", "release-not-semver"]

        self.assertEqual(upstream_check.newer_tags(tags, "issue-flow--v1.2.0"),
                         ["issue-flow--v1.10.0"])

    def test_sorts_a_release_above_its_prerelease(self):
        tags = ["issue-flow--v2.0.0-rc.1", "issue-flow--v2.0.0"]

        self.assertEqual(upstream_check.newer_tags(tags, "issue-flow--v1.9.0"),
                         ["issue-flow--v2.0.0-rc.1", "issue-flow--v2.0.0"])

    def test_ignores_tags_at_or_below_the_lock(self):
        tags = ["issue-flow--v1.2.0", "issue-flow--v1.1.9", "issue-flow--v1.0.0"]

        self.assertEqual(upstream_check.newer_tags(tags, "issue-flow--v1.2.0"), [])


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "upstream.lock").write_text('tag = "issue-flow--v1.0.0"\n')
        self.calls = []

    def run_main(self, responses):
        def run(command, **kwargs):
            self.calls.append(command)
            response = responses.pop(0)
            return upstream_check.subprocess.CompletedProcess(command, *response)

        err = io.StringIO()
        with patch.object(upstream_check.subprocess, "run", side_effect=run):
            with contextlib.redirect_stderr(err):
                code = upstream_check.main(["--root", str(self.root),
                                            "--tracker-repository", "OWNER/REPO"])
        return code, err.getvalue()

    def test_opens_one_issue_with_the_sync_report_for_a_new_tag(self):
        report = "# Upstream sync: new-commit\n\n## Changes\n"
        created_body = []
        responses = [
            (0, "012345\trefs/tags/issue-flow--v1.1.0\n", ""),
            (0, "[]", ""),
            (0, "", ""),
        ]
        def run(command, **kwargs):
            self.calls.append(command)
            if command[0] == "git":
                return upstream_check.subprocess.CompletedProcess(command, *responses.pop(0))
            if command[:2] == [sys.executable, str(ROOT / "scripts" / "upstream_sync.py")]:
                (self.root / "sync-report.md").write_text(report)
                return upstream_check.subprocess.CompletedProcess(command, 0, "", "")
            if "create" in command:
                created_body.append(Path(command[command.index("--body-file") + 1]).read_text())
            return upstream_check.subprocess.CompletedProcess(command, *responses.pop(0))

        with patch.object(upstream_check.subprocess, "run", side_effect=run):
            with patch.dict("os.environ", {"GITHUB_REPOSITORY": "OWNER/REPO"}):
                self.assertEqual(upstream_check.main(["--root", str(self.root)]), 0)

        create = next(call for call in self.calls if "create" in call)
        self.assertIn("Sync upstream issue-flow--v1.1.0", create)
        self.assertEqual(created_body, [report])

    def test_opens_one_issue_for_each_new_tag(self):
        created = []

        def run(command, **kwargs):
            self.calls.append(command)
            if command[0] == "git":
                output = ("one\trefs/tags/issue-flow--v1.1.0\n"
                          "two\trefs/tags/issue-flow--v1.2.0\n")
                return upstream_check.subprocess.CompletedProcess(command, 0, output, "")
            if command[0] == "gh" and "api" in command:
                return upstream_check.subprocess.CompletedProcess(command, 0, "[]", "")
            if command[0] == sys.executable:
                tag = command[command.index("--to") + 1]
                (self.root / "sync-report.md").write_text(f"report for {tag}\n")
                return upstream_check.subprocess.CompletedProcess(command, 0, "", "")
            if "create" in command:
                created.append((command[command.index("--title") + 1],
                                Path(command[command.index("--body-file") + 1]).read_text()))
            return upstream_check.subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(upstream_check.subprocess, "run", side_effect=run):
            with patch.dict("os.environ", {"GITHUB_REPOSITORY": "OWNER/REPO"}):
                self.assertEqual(upstream_check.main(["--root", str(self.root)]), 0)

        self.assertEqual(created, [
            ("Sync upstream issue-flow--v1.1.0", "report for issue-flow--v1.1.0\n"),
            ("Sync upstream issue-flow--v1.2.0", "report for issue-flow--v1.2.0\n"),
        ])

    def run_with_report(self, report, argv=()):
        created_body = []

        def run(command, **kwargs):
            self.calls.append(command)
            if command[0] == "git":
                output = "one\trefs/tags/issue-flow--v1.1.0\n"
                return upstream_check.subprocess.CompletedProcess(command, 0, output, "")
            if command[0] == "gh" and "api" in command:
                return upstream_check.subprocess.CompletedProcess(command, 0, "[]", "")
            if command[0] == sys.executable:
                (self.root / "sync-report.md").write_text(report)
                return upstream_check.subprocess.CompletedProcess(command, 0, "", "")
            if "create" in command:
                created_body.append(Path(command[command.index("--body-file") + 1]).read_text())
            return upstream_check.subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(upstream_check.subprocess, "run", side_effect=run):
            code = upstream_check.main(["--root", str(self.root),
                                        "--tracker-repository", "OWNER/REPO", *argv])
        self.assertEqual(code, 0)
        return created_body

    def test_cuts_the_diffs_from_a_report_over_the_body_limit(self):
        diff = "".join(f"+line {n}\n" for n in range(20000))
        report = ("# Upstream sync: new-commit\n\n## Changes to ported files\n\n"
                  "### `README.md` (patched)\n\n```diff\n" + diff + "```\n\n"
                  "## New upstream files without lock entries\n\n- `new.md`\n\n"
                  "## Deleted upstream files\n\nNone.\n")
        self.assertGreater(len(report), 65536)

        [body] = self.run_with_report(report)

        self.assertLessEqual(len(body), upstream_check.BODY_LIMIT)
        self.assertIn("### `README.md` (patched)", body)
        self.assertIn("- `new.md`", body)
        self.assertNotIn("+line 1\n", body)
        self.assertIn("python3 scripts/upstream_sync.py --to issue-flow--v1.1.0 --report-only",
                      body)

    def test_cuts_a_report_at_a_line_when_it_is_still_over_the_limit(self):
        report = "# Upstream sync\n\n" + "".join(f"- `file{n}.md`\n" for n in range(10000))

        [body] = self.run_with_report(report)

        self.assertLessEqual(len(body), upstream_check.BODY_LIMIT)
        self.assertIn("--report-only", body)
        self.assertTrue(all(line == "" or line.startswith(("#", "- `", "The full"))
                            or "upstream_sync.py" in line for line in body.splitlines()))

    def test_passes_the_repository_override_to_the_sync_report(self):
        self.run_with_report("report\n", ["--repository", "file:///tmp/upstream"])

        sync = next(call for call in self.calls if call[0] == sys.executable)
        self.assertEqual(sync[sync.index("--repository") + 1], "file:///tmp/upstream")
        ls_remote = next(call for call in self.calls if call[0] == "git")
        self.assertIn("file:///tmp/upstream", ls_remote)

    def test_skips_a_tag_that_already_has_an_issue(self):
        self.assertEqual(self.run_main([
            (0, "012345\trefs/tags/issue-flow--v1.1.0\n", ""),
            (0, '[{"title":"Sync upstream issue-flow--v1.1.0","state":"closed"}]', ""),
        ]), (0, ""))
        self.assertFalse(any("create" in call for call in self.calls))

    def test_stops_without_creating_an_issue_when_upstream_is_unreachable(self):
        code, err = self.run_main([(128, "", "network unreachable")])

        self.assertEqual(code, 1)
        self.assertIn("network unreachable", err)
        self.assertFalse(any("create" in call for call in self.calls))


if __name__ == "__main__":
    unittest.main()
