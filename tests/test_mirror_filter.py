"""Tests for skills/repo-mirror/scripts/mirror_filter.py.

Ported from upstream scripts/test-mirror-filter.py.

Builds a small real source repository with spec files, an issue reference before and
after the cutover, a tag, and a branch that is not mirrored. Needs git-filter-repo on
PATH. No test uses a network or touches the working repository.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "skills" / "repo-mirror" / "scripts"
          / "mirror_filter.py")
CUTOVER = 1_800_000_000


def git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{date} +0000"
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def commit(repo, files, message, date):
    for path, text in files.items():
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(text)
        git(repo, "add", path)
    git(repo, "commit", "-q", "-m", message, date=date)


def mirror(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def build(root):
    source = os.path.join(root, "source")
    os.makedirs(source)
    git(source, "init", "-q", "-b", "main")
    commit(source, {"main.go": "a\n", "docs/specs/spec.md": "secret\n", "CLAUDE.md": "c\n"},
           "Add the core (#3)", CUTOVER - 100)
    commit(source, {"docs/specs/features/x.md": "secret\n"}, "Spec only", CUTOVER - 50)
    commit(source, {"internal/CLAUDE.md": "n\n", "main.go": "b\n"},
           "Closes #12 and see owner/other#4", CUTOVER + 100)
    git(source, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    git(source, "switch", "-q", "-c", "issue/7-wip")
    commit(source, {"wip.go": "w\n"}, "WIP", CUTOVER + 200)
    git(source, "tag", "-a", "wip-tag", "-m", "a tag on an unmirrored branch")
    git(source, "switch", "-q", "main")
    config = os.path.join(root, "config.json")
    with open(config, "w") as handle:
        json.dump({
            "private": "owner/repo-private",
            "public": "owner/repo",
            "branches": ["main"],
            "exclude": ["docs/specs/", "CLAUDE.md", "glob:*/CLAUDE.md"],
            "cutover": CUTOVER,
        }, handle)
    return source, config


def build_private_paths(root):
    source = os.path.join(root, "private-paths")
    os.makedirs(source)
    git(source, "init", "-q", "-b", "main")
    commit(source, {
        "main.go": "public\n",
        "AGENTS.md": "private\n",
        "nested/AGENTS.md": "private\n",
        ".codex/config.toml": "private\n",
        ".agents/skills/private/SKILL.md": "private\n",
        "docs/rules/quality.md": "private\n",
    }, "Add source files", CUTOVER)
    config = os.path.join(root, "default-config.json")
    with open(config, "w") as handle:
        json.dump({
            "private": "owner/repo-private",
            "public": "owner/repo",
            "branches": ["main"],
        }, handle)
    return source, config


class MirrorFilterTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.source, self.config = build(self.root)

    def run_filter(self, name, config=None, source=None):
        out = os.path.join(self.root, name)
        result = mirror("filter", "--config", config or self.config,
                        "--source", source or self.source, "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        return out

    def test_removes_the_excluded_paths_from_all_history(self):
        first = self.run_filter("first")
        files = set(git(first, "log", "--all", "--format=", "--name-only").split())
        self.assertEqual(files, {"main.go"})

    def test_default_exclusions_drop_codex_private_paths(self):
        source, config = build_private_paths(self.root)
        out = self.run_filter("private-paths-mirror", config=config, source=source)
        files = set(git(out, "log", "--all", "--format=", "--name-only").split())
        self.assertEqual(files, {"main.go"})

    def test_check_finds_codex_private_paths_in_source_history(self):
        source, config = build_private_paths(self.root)
        check = mirror("check", "--config", config, "--repo", source)
        self.assertEqual(check.returncode, 1)
        for path in ("AGENTS.md", "nested/AGENTS.md", ".codex/config.toml",
                     ".agents/skills/private/SKILL.md", "docs/rules/quality.md"):
            self.assertIn(f"LEAK {path}", check.stdout)

    def test_prunes_a_commit_that_touches_only_excluded_paths(self):
        first = self.run_filter("first")
        self.assertEqual(git(first, "rev-list", "--count", "main"), "2")

    def test_mirrors_only_the_configured_branches(self):
        first = self.run_filter("first")
        self.assertEqual(git(first, "for-each-ref", "--format=%(refname)", "refs/heads/"),
                         "refs/heads/main")

    def test_mirrors_only_tags_on_a_mirrored_branch(self):
        first = self.run_filter("first")
        self.assertEqual(git(first, "tag"), "v1.0.0")

    def test_removes_replace_refs(self):
        first = self.run_filter("first")
        self.assertEqual(git(first, "for-each-ref", "refs/replace/"), "")

    def test_rewrites_only_references_after_the_cutover(self):
        first = self.run_filter("first")
        messages = git(first, "log", "--format=%s", "main").splitlines()
        self.assertEqual(messages[0], "Closes owner/repo-private#12 and see owner/other#4")
        self.assertEqual(messages[1], "Add the core (#3)")

    def test_check_passes_on_the_filtered_repository(self):
        first = self.run_filter("first")
        check = mirror("check", "--config", self.config, "--repo", first)
        self.assertEqual(check.returncode, 0, check.stdout)

    def test_check_fails_on_the_source_and_names_the_nested_claude_file(self):
        check = mirror("check", "--config", self.config, "--repo", self.source)
        self.assertEqual(check.returncode, 1)
        self.assertIn("LEAK internal/CLAUDE.md", check.stdout)

    def test_gives_the_same_hashes_on_a_second_run(self):
        first = self.run_filter("first")
        second = self.run_filter("second")
        self.assertEqual(git(first, "rev-parse", "main", "v1.0.0"),
                         git(second, "rev-parse", "main", "v1.0.0"))

    def test_appends_a_new_source_commit_without_rewriting_the_mirror(self):
        first = self.run_filter("first")
        old_head = git(first, "rev-parse", "main")
        commit(self.source, {"main.go": "c\n", "docs/specs/spec.md": "more\n"}, "Next", CUTOVER + 300)
        third = self.run_filter("third")
        self.assertEqual(git(third, "rev-parse", "main~1"), old_head)

    def test_rewrites_no_reference_when_the_cutover_is_zero(self):
        with open(self.config) as handle:
            data = json.load(handle)
        data["cutover"] = 0
        unset = os.path.join(self.root, "unset.json")
        with open(unset, "w") as handle:
            json.dump(data, handle)
        fourth = self.run_filter("fourth", config=unset)
        self.assertNotIn("owner/repo-private#", git(fourth, "log", "--format=%s", "main"))

    def test_stats_counts_the_spec_paths(self):
        stats = mirror("stats", "--config", self.config, "--source", self.source)
        self.assertIn("     2  docs/specs/", stats.stdout)

    def test_check_reports_paths_that_only_a_merge_commit_adds_or_that_are_not_ascii(self):
        repo = os.path.join(self.root, "blind")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, {"a.go": "a\n"}, "Base", CUTOVER)
        git(repo, "switch", "-q", "-c", "side")
        commit(repo, {"b.go": "b\n"}, "Side", CUTOVER + 1)
        git(repo, "switch", "-q", "main")
        commit(repo, {"c.go": "c\n"}, "Main", CUTOVER + 2)
        git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
        commit(repo, {"docs/specs/merge-only.md": "s\n"}, "Merge side", CUTOVER + 3)
        commit(repo, {"docs/specs/résumé.md": "s\n"}, "Accent", CUTOVER + 4)
        git(repo, "rm", "-q", "docs/specs/résumé.md")
        git(repo, "commit", "-q", "-m", "Remove them", date=CUTOVER + 5)
        result = mirror("check", "--config", self.config, "--repo", repo)
        for path in ("docs/specs/merge-only.md", "docs/specs/résumé.md"):
            self.assertIn(f"LEAK {path}", result.stdout)

    def test_prefers_origins_copy_of_a_branch_over_a_stale_local_branch(self):
        checkout = os.path.join(self.root, "checkout")
        subprocess.run(["git", "clone", "-q", self.source, checkout], check=True)
        commit(self.source, {"main.go": "newest\n"}, "Newest", CUTOVER + 400)
        git(checkout, "fetch", "-q", "origin")
        out = self.run_filter("from-checkout", source=checkout)
        self.assertEqual(git(out, "log", "-1", "--format=%s", "main"), "Newest")


if __name__ == "__main__":
    unittest.main()
