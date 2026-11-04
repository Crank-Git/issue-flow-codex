#!/usr/bin/env python3
"""Import an upstream issue-flow tag and check the port against `upstream.lock`.

`--import <tag>` copies every file under `issue-flow/` of the upstream tag to the
same path at the repository root, and writes `upstream.lock`.
`--to <tag>` copies `verbatim` files and updates the lock after it writes a report.
`--check` needs no network. It compares each `verbatim` file with the lock. It also
fails and names each tracked file (`git ls-files`) that has no lock entry. The lock
file needs no entry of its own.

The lock records one `[[file]]` table per path. `mode` is one of `verbatim`,
`patched`, `rewritten`, `dropped`, or `new`. A `new` entry has an empty
`upstream_sha256`, and `--check` ignores it.
"""

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

UPSTREAM_REPOSITORY = "https://github.com/Sniper7Kills-LLC/claude-plugins"
UPSTREAM_PREFIX = "issue-flow"
ROOT = Path(__file__).resolve().parent.parent
INVENTORY = "docs/specs/pages/porting-inventory.md"
LOCK = "upstream.lock"

# A table row of the porting inventory: path, lines, mode, what changes.
ROW = re.compile(
    r"^\| `([^`]+)` \| [\d,]+ \| (verbatim|patched|rewritten|dropped) \| (.*?) \|")


class SyncError(Exception):
    """A failure that `main` reports as one line on stderr."""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toml_string(value):
    # A JSON string with unescaped non-ASCII text is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def serialize_lock(repository, tag, commit, entries):
    """Return the TOML text of a lock. Each entry has path, mode, upstream_sha256, notes."""
    lines = [f"repository = {toml_string(repository)}",
             f"tag = {toml_string(tag)}",
             f"commit = {toml_string(commit)}"]
    for entry in entries:
        lines += ["", "[[file]]"]
        lines += [f"{key} = {toml_string(entry[key])}"
                  for key in ("path", "mode", "upstream_sha256", "notes")]
    return "\n".join(lines) + "\n"


def load_modes(inventory):
    """Return {path: (mode, notes)} from the inventory tables."""
    modes = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            path, mode, notes = match.groups()
            modes[path] = (mode, "" if notes == "none" else notes)
    return modes


def fetch_tag(repository, tag, dest):
    """Clone one tag of `repository` into `dest`. Return the commit hash."""
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", tag, "--", repository, str(dest)],
        capture_output=True, text=True)
    if clone.returncode != 0:
        raise SyncError(f"cannot fetch tag {tag} from {repository}: {clone.stderr.strip()}")
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True)
    return head.stdout.strip()


def cmd_import(root, inventory, repository, tag):
    modes = load_modes(inventory)
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "upstream"
        commit = fetch_tag(repository, tag, clone)
        source = clone / UPSTREAM_PREFIX
        files = sorted(p for p in source.rglob("*") if p.is_file())
        paths = [p.relative_to(source).as_posix() for p in files]
        missing = [p for p in paths if p not in modes]
        if missing:
            raise SyncError("no mode in the porting inventory for: " + ", ".join(missing))
        entries = []
        for file, path in zip(files, paths):
            mode, notes = modes[path]
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, target)
            entries.append({"path": path, "mode": mode,
                            "upstream_sha256": sha256(file), "notes": notes})
    (root / LOCK).write_text(serialize_lock(repository, tag, commit, entries), encoding="utf-8")


def cmd_check(root):
    with (root / LOCK).open("rb") as handle:
        lock = tomllib.load(handle)
    bad = [e["path"] for e in lock["file"]
           if e["mode"] == "verbatim"
           and (not (root / e["path"]).is_file() or sha256(root / e["path"]) != e["upstream_sha256"])]
    if bad:
        raise SyncError("verbatim file differs from the lock: " + ", ".join(bad))
    tracked = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    locked = {e["path"] for e in lock["file"]} | {LOCK}
    unlocked = [path for path in tracked if path not in locked]
    if unlocked:
        raise SyncError("tracked file has no lock entry: " + ", ".join(unlocked))


def git_output(args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise SyncError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def upstream_paths(repository, commit):
    listing = git_output(["ls-tree", "-r", "--name-only", commit, UPSTREAM_PREFIX], cwd=repository)
    return {path[len(UPSTREAM_PREFIX) + 1:] for path in listing.splitlines()
            if path.startswith(UPSTREAM_PREFIX + "/")}


def source_text(repository, commit, path):
    result = subprocess.run(["git", "show", f"{commit}:{UPSTREAM_PREFIX}/{path}"],
                            cwd=repository, capture_output=True)
    if result.returncode:
        raise SyncError(f"cannot read {path} at {commit}")
    return result.stdout.decode("utf-8", errors="replace").splitlines(keepends=True)


def sync_report(repository, old_commit, new_commit, old_paths, new_paths, entries):
    modes = {entry["path"]: entry["mode"] for entry in entries}
    lines = [f"# Upstream sync: {new_commit}", "", "## Changes to ported files", ""]
    changed = []
    for path in sorted(old_paths & new_paths & modes.keys()):
        if modes[path] not in {"patched", "rewritten", "dropped"}:
            continue
        old = source_text(repository, old_commit, path)
        new = source_text(repository, new_commit, path)
        if old == new:
            continue
        changed.append(path)
        lines += [f"### `{path}` ({modes[path]})", "", "```diff"]
        lines.extend(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"))
        lines += ["```", ""]
    if not changed:
        lines.append("No changes.")
    added = sorted((new_paths - old_paths) - modes.keys())
    deleted = sorted(old_paths - new_paths)
    lines += ["", "## New upstream files without lock entries", ""]
    lines.extend(f"- `{path}`" for path in added)
    if not added:
        lines.append("None.")
    lines += ["", "## Deleted upstream files", ""]
    lines.extend(f"- `{path}`" for path in deleted)
    if not deleted:
        lines.append("None.")
    return "\n".join(lines).rstrip() + "\n"


def cmd_sync(root, repository, tag, report_only):
    status = git_output(["-C", str(root), "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise SyncError("working tree has uncommitted changes")
    with (root / LOCK).open("rb") as handle:
        lock = tomllib.load(handle)
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "upstream"
        clone_result = subprocess.run(["git", "clone", "--quiet", "--", repository, str(clone)],
                                      capture_output=True, text=True)
        if clone_result.returncode:
            raise SyncError(f"cannot fetch upstream repository {repository}: {clone_result.stderr.strip()}")
        new_commit = git_output(["rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=clone)
        old_commit = lock["commit"]
        old_paths = upstream_paths(clone, old_commit)
        new_paths = upstream_paths(clone, new_commit)
        entries = lock["file"]
        report = sync_report(clone, old_commit, new_commit, old_paths, new_paths, entries)
        updated_entries = []
        for entry in entries:
            updated = dict(entry)
            path = entry["path"]
            if path in new_paths:
                result = subprocess.run(
                    ["git", "show", f"{new_commit}:{UPSTREAM_PREFIX}/{path}"],
                    cwd=clone, capture_output=True)
                if result.returncode:
                    raise SyncError(f"cannot read {path} at {new_commit}")
                content = result.stdout
                updated["upstream_sha256"] = hashlib.sha256(content).hexdigest()
                if entry["mode"] == "verbatim":
                    target = root / path
                    if not report_only:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
            updated_entries.append(updated)
        (root / "sync-report.md").write_text(report, encoding="utf-8")
        if not report_only:
            (root / LOCK).write_text(serialize_lock(lock["repository"], tag, new_commit,
                                                     updated_entries), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--import", dest="tag", metavar="TAG", help="import this upstream tag")
    action.add_argument("--to", dest="sync_tag", metavar="TAG", help="sync to this upstream tag")
    action.add_argument("--check", action="store_true", help="compare verbatim files with the lock")
    parser.add_argument("--report-only", action="store_true", help="write the report without changing port files or the lock")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--inventory", type=Path, help=f"default: <root>/{INVENTORY}")
    parser.add_argument("--repository", default=UPSTREAM_REPOSITORY, help="upstream git URL or path")
    args = parser.parse_args(argv)
    try:
        if args.tag:
            cmd_import(args.root, args.inventory or args.root / INVENTORY, args.repository, args.tag)
        elif args.sync_tag:
            cmd_sync(args.root, args.repository, args.sync_tag, args.report_only)
        else:
            if args.report_only:
                raise SyncError("--report-only requires --to")
            cmd_check(args.root)
    except SyncError as error:
        print(f"upstream_sync: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
