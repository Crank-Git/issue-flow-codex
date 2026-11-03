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
        self.assertEqual(run_main(["--check", "--root", str(self.root)]), (0, ""))

    def test_import_stops_when_an_upstream_file_has_no_mode(self):
        code, err = self.run_import("inventory_partial.md")
        self.assertEqual(code, 1)
        self.assertIn("sub/b.py", err)
        self.assertFalse((self.root / "upstream.lock").exists())
        self.assertFalse((self.root / "a.md").exists())


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
