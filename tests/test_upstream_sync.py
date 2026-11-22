"""Tests for scripts/upstream_sync.py. No test uses the network."""

import contextlib
import hashlib
import io
import os
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

    def test_check_reports_a_missing_lock_as_one_line(self):
        (self.tree / "upstream.lock").unlink()

        code, err = self.check()

        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("upstream_sync: "))
        self.assertEqual(len(err.splitlines()), 1)

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


class UpstreamPathTest(unittest.TestCase):
    """An entry with `upstream_path` maps to a file outside `issue-flow/`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.upstream = self.tmp / "upstream"
        case = self.upstream / "evals" / "worker" / "case"
        case.mkdir(parents=True)
        (self.upstream / "evals" / "fakegh").mkdir()
        (case / "case.json").write_text('{"v": 1}\n')
        (self.upstream / "evals" / "fakegh" / "gh").write_text("#!/bin/sh\nexit 1\n")
        (self.upstream / "evals" / "fakegh" / "gh").chmod(0o755)
        (self.upstream / "evals" / "other").mkdir()
        (self.upstream / "evals" / "other" / "skip.txt").write_text("not imported\n")
        (self.upstream / "issue-flow").mkdir()
        (self.upstream / "issue-flow" / "keep.md").write_text("keep\n")
        self.old_commit = self.commit("v1")
        (case / "case.json").write_text('{"v": 2}\n')
        self.new_commit = self.commit("v2")
        self.root = self.tmp / "port"
        self.root.mkdir()
        (self.root / "keep.md").write_text("keep\n")
        entries = [{"path": "keep.md", "mode": "verbatim",
                    "upstream_sha256": hashlib.sha256(b"keep\n").hexdigest(), "notes": ""}]
        (self.root / "upstream.lock").write_text(
            upstream_sync.serialize_lock(str(self.upstream), "v1", self.old_commit, entries))
        init_repo(self.root)
        subprocess.run(GIT + ["commit", "-q", "-m", "port"], cwd=self.root, check=True)

    def commit(self, tag):
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", tag], ["tag", tag]):
            subprocess.run(GIT + args, cwd=self.upstream, check=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.upstream, check=True,
                              capture_output=True, text=True).stdout.strip()

    def lock(self):
        return tomllib.loads((self.root / "upstream.lock").read_text())

    def run_tool(self, *options):
        return run_main([*options, "--root", str(self.root), "--repository", str(self.upstream)])

    def commit_port(self):
        subprocess.run(GIT + ["add", "-A"], cwd=self.root, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "evals"], cwd=self.root, check=True)

    def test_serialize_writes_upstream_path_only_when_an_entry_has_one(self):
        entries = [{"path": "a", "mode": "new", "upstream_sha256": "", "notes": ""},
                   {"path": "b", "mode": "verbatim", "upstream_sha256": "x", "notes": "",
                    "upstream_path": "evals/b"}]
        text = upstream_sync.serialize_lock("r", "v1", "c", entries)
        self.assertEqual(tomllib.loads(text)["file"], entries)
        self.assertEqual(text.count("upstream_path"), 1)

    def test_import_evals_copies_the_case_files_and_appends_lock_entries(self):
        before = self.lock()["file"]
        self.assertEqual(self.run_tool("--import-evals", "v1"), (0, ""))
        files = self.lock()["file"]
        self.assertEqual(files[:len(before)], before)
        added = {entry["path"]: entry for entry in files[len(before):]}
        self.assertEqual(sorted(added), ["evals/fakegh/gh", "evals/worker/case/case.json"])
        entry = added["evals/worker/case/case.json"]
        self.assertEqual((entry["mode"], entry["upstream_path"]),
                         ("verbatim", "evals/worker/case/case.json"))
        self.assertEqual(entry["upstream_sha256"], hashlib.sha256(b'{"v": 1}\n').hexdigest())
        self.assertTrue(os.access(self.root / "evals" / "fakegh" / "gh", os.X_OK))
        self.assertFalse((self.root / "evals" / "other").exists())
        init_repo(self.root)
        self.assertEqual(self.run_tool("--check"), (0, ""))

    def test_import_evals_refuses_a_tag_other_than_the_lock_tag(self):
        code, err = self.run_tool("--import-evals", "v2")
        self.assertEqual(code, 1)
        self.assertIn("v1", err)
        self.assertFalse((self.root / "evals").exists())

    def test_sync_copies_a_verbatim_file_from_its_upstream_path(self):
        self.run_tool("--import-evals", "v1")
        self.commit_port()
        self.assertEqual(self.run_tool("--to", "v2"), (0, ""))
        target = self.root / "evals" / "worker" / "case" / "case.json"
        self.assertEqual(target.read_text(), '{"v": 2}\n')
        entry = next(e for e in self.lock()["file"] if e["path"] == "evals/worker/case/case.json")
        self.assertEqual(entry["upstream_sha256"], hashlib.sha256(b'{"v": 2}\n').hexdigest())
        self.assertEqual(entry["upstream_path"], "evals/worker/case/case.json")
        self.assertEqual(self.run_tool("--check"), (0, ""))

    def test_sync_reports_a_changed_patched_file_that_has_an_upstream_path(self):
        self.run_tool("--import-evals", "v1")
        lock = self.lock()
        for entry in lock["file"]:
            if entry["path"] == "evals/worker/case/case.json":
                entry["mode"] = "patched"
        (self.root / "upstream.lock").write_text(
            upstream_sync.serialize_lock(lock["repository"], lock["tag"], lock["commit"], lock["file"]))
        self.commit_port()
        self.assertEqual(self.run_tool("--to", "v2", "--report-only"), (0, ""))
        report = (self.root / "sync-report.md").read_text()
        self.assertIn("evals/worker/case/case.json", report)
        self.assertIn('+{"v": 2}', report)


class SerializeTest(unittest.TestCase):
    def test_serialize_lock_round_trips_through_tomllib(self):
        entries = [{"path": 'q"uote.md', "mode": "new", "upstream_sha256": "",
                    "notes": "Line one.\nLine two \\ end."}]
        text = upstream_sync.serialize_lock("https://example.invalid/r", "v1", "abc", entries)
        lock = tomllib.loads(text)
        self.assertEqual(lock["file"], entries)
        self.assertEqual((lock["repository"], lock["tag"], lock["commit"]),
                         ("https://example.invalid/r", "v1", "abc"))


class RealLockTest(unittest.TestCase):
    """Read the repository's own `upstream.lock`."""

    @classmethod
    def setUpClass(cls):
        with (ROOT / "upstream.lock").open("rb") as handle:
            cls.lock = tomllib.load(handle)
        cls.files = {entry["path"]: entry for entry in cls.lock["file"]}

    def test_lock_names_v0_21_0(self):
        self.assertEqual(self.lock["tag"], "issue-flow--v0.21.0")
        self.assertEqual(self.lock["commit"], "39f2261b11cc1a5c6cf75ee1310bc2419767644f")

    def test_lock_modes_for_new_upstream_files(self):
        self.assertEqual(self.files["agents/criteria-checker.md"]["mode"], "rewritten")
        self.assertEqual(self.files["scripts/pricing.json"]["mode"], "dropped")
        self.assertIn("price per token", self.files["scripts/pricing.json"]["notes"])
        self.assertEqual(self.files["scripts/usage.py"]["mode"], "rewritten")


if __name__ == "__main__":
    unittest.main()
