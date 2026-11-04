#!/usr/bin/env python3
"""Open one tracker issue for each new upstream release."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = "upstream.lock"
UPSTREAM = "https://github.com/Sniper7Kills-LLC/claude-plugins"
TAG_PREFIX = "issue-flow--v"
# GitHub rejects an issue body over 65536 characters.
BODY_LIMIT = 60000
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")


class CheckError(Exception):
    """A check failure that the command reports to stderr."""


def version_key(tag):
    """Return a sortable key for a semantic upstream tag."""
    if not tag.startswith(TAG_PREFIX):
        raise CheckError(f"invalid upstream tag: {tag}")
    match = SEMVER.fullmatch(tag[len(TAG_PREFIX):])
    if not match:
        raise CheckError(f"invalid upstream tag: {tag}")
    major, minor, patch, prerelease = match.groups()
    if prerelease and any(part.isdigit() and len(part) > 1 and part.startswith("0")
                          for part in prerelease.split(".")):
        raise CheckError(f"invalid upstream tag: {tag}")
    identifiers = ()
    if prerelease:
        identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                            for part in prerelease.split("."))
    return (int(major), int(minor), int(patch), 1 if prerelease is None else 0, identifiers)


def newer_tags(tags, locked_tag):
    """Return valid upstream tags that are newer than the lock tag."""
    locked_version = version_key(locked_tag)
    newer = []
    for tag in tags:
        try:
            key = version_key(tag)
        except CheckError:
            continue
        if key > locked_version:
            newer.append((key, tag))
    return [tag for _, tag in sorted(newer)]


def tags_from_ls_remote(output):
    return [line.split("\t", 1)[1][len("refs/tags/"):]
            for line in output.splitlines()
            if "\trefs/tags/" in line
            and line.split("\t", 1)[1].startswith(f"refs/tags/{TAG_PREFIX}")]


def run(command, root):
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if result.returncode:
        message = result.stderr.strip() or "command failed"
        raise CheckError(f"{command[0]} failed: {message}")
    return result.stdout


def existing_titles(output):
    pages = json.loads(output)
    if pages and isinstance(pages[0], dict):
        pages = [pages]
    return {issue["title"] for page in pages for issue in page
            if "pull_request" not in issue}


def issue_body(report, tag):
    """Return the report, cut to BODY_LIMIT characters with a note when it is longer."""
    if len(report) <= BODY_LIMIT:
        return report
    note = (f"\nThe full report is too long for an issue body. To write it to `sync-report.md`, "
            f"run `python3 scripts/upstream_sync.py --to {tag} --report-only` locally.\n")
    # Remove each diff block. The section heading names the changed file.
    lines = []
    in_diff = False
    for line in report.splitlines(keepends=True):
        if line.startswith("```diff"):
            in_diff = True
        elif in_diff:
            in_diff = line.rstrip("\n") != "```"
        else:
            lines.append(line)
    body = "".join(lines)
    limit = BODY_LIMIT - len(note)
    if len(body) > limit:
        body = body[:body.rfind("\n", 0, limit) + 1]
    return body + note


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repository", default=None, help="upstream Git URL")
    parser.add_argument("--tracker-repository", default=None, help="owner and repository")
    args = parser.parse_args(argv)
    root = args.root
    try:
        repository = args.repository or UPSTREAM
        with (root / LOCK).open("rb") as handle:
            locked_tag = tomllib.load(handle)["tag"]
        tag_output = run(["git", "ls-remote", "--tags", "--refs", repository], root)
        tags = newer_tags(tags_from_ls_remote(tag_output), locked_tag)
        if not tags:
            return 0

        tracker = args.tracker_repository or os.environ.get("GITHUB_REPOSITORY")
        if not tracker:
            raise CheckError("GITHUB_REPOSITORY is required")
        existing = run(["gh", "api", "--paginate", "--slurp",
                        f"repos/{tracker}/issues?state=all&per_page=100"], root)
        titles = existing_titles(existing)

        with tempfile.TemporaryDirectory() as tmp:
            reports = []
            for tag in tags:
                title = f"Sync upstream {tag}"
                if title in titles:
                    continue
                run([sys.executable, str(ROOT / "scripts" / "upstream_sync.py"),
                     "--to", tag, "--report-only", "--root", str(root),
                     "--repository", repository], root)
                report = root / "sync-report.md"
                if not report.is_file():
                    raise CheckError(f"upstream sync did not write {report.name}")
                body = Path(tmp) / f"{tag}.md"
                body.write_text(issue_body(report.read_text(encoding="utf-8"), tag),
                                encoding="utf-8")
                reports.append((title, body))
            for title, body in reports:
                run(["gh", "issue", "create", "--repo", tracker,
                     "--title", title, "--body-file", str(body)], root)
    except (CheckError, OSError, KeyError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        print(f"upstream_check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
