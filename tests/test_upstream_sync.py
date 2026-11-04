"""Tests for scripts/upstream_sync.py. No test uses the network."""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import upstream_sync  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "upstream_sync"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def init_repo(path):
    """Track every file under `path`, as `--check` reads `git ls-files`."""
    for args in (["init", "-q"], ["add", "."]):
        subprocess.run(GIT + args, cwd=path, check=True)


def run_main(argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = upstream_sync.main(argv)
    return code, err.getvalue()


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.tree = self.tmp / "tree"
        shutil.copytree(FIXTURES / "tree", self.tree)
        init_repo(self.tree)

    def check(self):
        return run_main(["--check", "--root", str(self.tree)])

    def test_check_passes_when_verbatim_files_match_the_lock(self):
        self.assertEqual(self.check(), (0, ""))

    def test_check_fails_and_names_a_verbatim_file_that_differs_by_one_byte(self):
        (self.tree / "verbatim.txt").write_text("kept as upstreaM\n")
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("verbatim.txt", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_check_fails_when_a_verbatim_file_is_missing(self):
        (self.tree / "verbatim.txt").unlink()
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("verbatim.txt", err)

    def test_check_ignores_patched_and_rewritten_files(self):
        # The fixture hashes of these two files never match the tree.
        self.assertEqual(self.check()[0], 0)

    def test_check_ignores_new_entries(self):
        (self.tree / "new.txt").unlink()
        self.assertEqual(self.check()[0], 0)

    def test_check_fails_and_names_a_tracked_file_with_no_lock_entry(self):
        (self.tree / "stray.txt").write_text("no row\n")
        (self.tree / "other.txt").write_text("no row\n")
        init_repo(self.tree)
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("stray.txt", err)
        self.assertIn("other.txt", err)
        self.assertNotIn("verbatim.txt", err)

    def test_check_does_not_require_a_lock_entry_for_the_lock_itself(self):
        self.assertEqual(self.check(), (0, ""))

    def test_check_ignores_an_untracked_file_with_no_lock_entry(self):
        (self.tree / "scratch.txt").write_text("untracked\n")
        self.assertEqual(self.check(), (0, ""))


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "upstream_repo"
        shutil.copytree(FIXTURES / "upstream", self.repo)
        for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "fixture"],
                     ["tag", "v1"]):
            subprocess.run(GIT + args, cwd=self.repo, check=True)
        self.commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
            capture_output=True, text=True).stdout.strip()
        self.root = self.tmp / "root"
        self.root.mkdir()

    def run_import(self, inventory):
        return run_main(["--import", "v1", "--root", str(self.root),
                         "--repository", str(self.repo),
                         "--inventory", str(FIXTURES / inventory)])

    def test_import_writes_one_lock_entry_per_upstream_file(self):
        self.assertEqual(self.run_import("inventory.md"), (0, ""))
        lock = tomllib.loads((self.root / "upstream.lock").read_text())
        self.assertEqual(lock["tag"], "v1")
        self.assertEqual(lock["commit"], self.commit)
        self.assertEqual([f["path"] for f in lock["file"]], ["a.md", "sub/b.py"])
        self.assertEqual([f["mode"] for f in lock["file"]], ["verbatim", "patched"])
        self.assertEqual((self.root / "sub" / "b.py").read_text(), "print(1)\n")
        init_repo(self.root)
        self.assertEqual(run_main(["--check", "--root", str(self.root)]), (0, ""))

    def test_import_stops_when_an_upstream_file_has_no_mode(self):
        code, err = self.run_import("inventory_partial.md")
        self.assertEqual(code, 1)
        self.assertIn("sub/b.py", err)
        self.assertFalse((self.root / "upstream.lock").exists())
        self.assertFalse((self.root / "a.md").exists())


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.upstream = self.tmp / "upstream"
        source = self.upstream / "issue-flow"
        source.mkdir(parents=True)
        (source / "verbatim.txt").write_text("old verbatim\n")
        (source / "rewritten.txt").write_text("old rewritten\n")
        (source / "deleted.txt").write_text("old deleted\n")
        (source / "dropped.txt").write_text("old dropped\n")
        (source / "old-name.txt").write_text("rename me\n")
        self.commit_tag("v1")
        (source / "verbatim.txt").write_text("new verbatim\n")
        (source / "rewritten.txt").write_text("new rewritten\n")
        (source / "deleted.txt").unlink()
        (source / "dropped.txt").write_text("new dropped\n")
        (source / "old-name.txt").rename(source / "new-name.txt")
        (source / "untracked-upstream.txt").write_text("new file\n")
        (source / "already-locked.txt").write_text("new upstream file with an existing lock entry\n")
        self.commit_tag("v2")
        self.root = self.tmp / "port"
        self.root.mkdir()
        (self.root / "verbatim.txt").write_text("old verbatim\n")
        (self.root / "rewritten.txt").write_text("port version\n")
        (self.root / "already-locked.txt").write_text("port-managed file\n")
        lock = upstream_sync.serialize_lock(str(self.upstream), "v1", self.old_commit, [
            {"path": "verbatim.txt", "mode": "verbatim", "upstream_sha256": upstream_sync.sha256(source / "verbatim.txt"), "notes": ""},
            {"path": "rewritten.txt", "mode": "rewritten", "upstream_sha256": "old", "notes": ""},
            {"path": "deleted.txt", "mode": "dropped", "upstream_sha256": "old", "notes": ""},
            {"path": "dropped.txt", "mode": "dropped", "upstream_sha256": "old", "notes": ""},
            {"path": "old-name.txt", "mode": "patched", "upstream_sha256": "old", "notes": ""},
            {"path": "already-locked.txt", "mode": "patched", "upstream_sha256": "", "notes": ""},
        ])
        (self.root / "upstream.lock").write_text(lock)
        self.commit_port()

    def commit_tag(self, tag):
        for args in (["init", "-q"], ["add", "."] if tag == "v1" else ["add", "-A"],
                     ["commit", "-q", "-m", tag], ["tag", tag]):
            subprocess.run(GIT + args, cwd=self.upstream, check=True)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.upstream,
                                check=True, capture_output=True, text=True).stdout.strip()
        if tag == "v1":
            self.old_commit = commit
        else:
            self.new_commit = commit

    def commit_port(self):
        for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "port"]):
            subprocess.run(GIT + args, cwd=self.root, check=True)

    def run_sync(self, *options):
        return run_main([*options, "--root", str(self.root), "--repository", str(self.upstream)])

    def test_sync_copies_verbatim_and_reports_other_file_changes(self):
        self.assertEqual(self.run_sync("--to", "v2"), (0, ""))
        self.assertEqual((self.root / "verbatim.txt").read_text(), "new verbatim\n")
        report = (self.root / "sync-report.md").read_text()
        self.assertIn("rewritten.txt", report)
        self.assertIn("new rewritten", report)
        self.assertIn("new dropped", report)
        self.assertIn("untracked-upstream.txt", report)
        self.assertNotIn("already-locked.txt", report.split("## Deleted upstream files")[0])
        self.assertIn("deleted.txt", report)
        self.assertIn("old-name.txt", report)
        self.assertIn("new-name.txt", report)
        lock = tomllib.loads((self.root / "upstream.lock").read_text())
        self.assertEqual((lock["tag"], lock["commit"]), ("v2", self.new_commit))
        for entry in lock["file"]:
            path = self.upstream / "issue-flow" / entry["path"]
            if path.exists():
                self.assertEqual(entry["upstream_sha256"], upstream_sync.sha256(path))
        self.assertEqual((self.root / "rewritten.txt").read_text(), "port version\n")
        self.assertFalse((self.root / "deleted.txt").exists())

    def test_report_only_does_not_change_the_port_or_lock(self):
        old_lock = (self.root / "upstream.lock").read_bytes()
        self.assertEqual(self.run_sync("--to", "v2", "--report-only"), (0, ""))
        self.assertEqual((self.root / "upstream.lock").read_bytes(), old_lock)
        self.assertEqual((self.root / "verbatim.txt").read_text(), "old verbatim\n")
        self.assertTrue((self.root / "sync-report.md").exists())

    def test_sync_refuses_a_dirty_tree_without_writing_files(self):
        (self.root / "verbatim.txt").write_text("local edit\n")
        old_lock = (self.root / "upstream.lock").read_bytes()
        self.assertEqual(self.run_sync("--to", "v2"), (1, "upstream_sync: working tree has uncommitted changes\n"))
        self.assertEqual((self.root / "verbatim.txt").read_text(), "local edit\n")
        self.assertEqual((self.root / "upstream.lock").read_bytes(), old_lock)
        self.assertFalse((self.root / "sync-report.md").exists())


class SerializeTest(unittest.TestCase):
    def test_serialize_lock_round_trips_through_tomllib(self):
        entries = [{"path": 'q"uote.md', "mode": "new", "upstream_sha256": "",
                    "notes": "Line one.\nLine two \\ end."}]
        text = upstream_sync.serialize_lock("https://example.invalid/r", "v1", "abc", entries)
        lock = tomllib.loads(text)
        self.assertEqual(lock["file"], entries)
        self.assertEqual((lock["repository"], lock["tag"], lock["commit"]),
                         ("https://example.invalid/r", "v1", "abc"))


if __name__ == "__main__":
    unittest.main()
