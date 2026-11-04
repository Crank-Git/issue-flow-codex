#!/usr/bin/env python3
"""Create and remove the git worktree of one worker.

    python3 scripts/worktree.py create --project . --task worker_19 \
        --branch issue/19-slug --base origin/epic/3-worker-dispatch [--remote origin]
    python3 scripts/worktree.py remove --project . --task worker_19 [--merged]

`create` prints one JSON line: {"path", "branch", "base_sha"}. It reuses the
branch when the branch exists, and else creates it from --base. It copies each
file that `.worktreeinclude` names and git ignores, so a tracked file is never
overwritten. When no ignore rule covers `.worktrees/`, it adds the line to the
local git exclude file.

`remove` exits 1 and changes nothing when the worktree has an uncommitted
change or a commit that no remote-tracking ref holds. Otherwise it removes the
worktree and deletes its branch. `remove` also exits 1 when the worktree is not
on a branch. With `--merged`, `remove` skips the commit check: the PM passes it
only after it has verified the sub-merge. It still refuses uncommitted changes.

Every failure exits nonzero with one line on stderr.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


class WorktreeError(Exception):
    pass


def git(cwd, *args):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
        raise WorktreeError(f"git {args[0]} failed: {detail[-1] if detail else 'no output'}")
    return result.stdout.strip()


def included_ignored_files(project):
    """Return the untracked files that `.worktreeinclude` matches and git ignores."""
    include = project / ".worktreeinclude"
    if not include.is_file():
        return []
    listed = git(project, "ls-files", "-z", "-o", "-i", f"--exclude-from={include}")
    names = [name for name in listed.split("\0") if name]
    if not names:
        return []
    # `check-ignore` exits 1 when no path is ignored, so git() cannot run it.
    ignored = subprocess.run(["git", "-C", str(project), "check-ignore", "-z", "--stdin"],
                             input="\0".join(names) + "\0", capture_output=True, text=True)
    return [name for name in ignored.stdout.split("\0") if name]


def cmd_create(args):
    project = Path(args.project).resolve()
    tree = project / ".worktrees" / args.task
    git(project, "fetch", args.remote)
    base_sha = git(project, "rev-parse", "--verify", f"{args.base}^{{commit}}")
    has_branch = subprocess.run(
        ["git", "-C", str(project), "show-ref", "--verify", "--quiet",
         f"refs/heads/{args.branch}"]).returncode == 0
    # A project set up at the user level has no `.worktrees/` line in `.gitignore`.
    # The local exclude file hides the worktrees from `git status` without a tracked change.
    if subprocess.run(["git", "-C", str(project), "check-ignore", "-q", f".worktrees/{args.task}"]
                      ).returncode != 0:
        exclude = project / git(project, "rev-parse", "--git-path", "info/exclude")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        sep = "" if not current or current.endswith("\n") else "\n"
        exclude.write_text(current + sep + ".worktrees/\n", encoding="utf-8")
    if has_branch:
        git(project, "worktree", "add", str(tree), args.branch)
    else:
        git(project, "worktree", "add", "-b", args.branch, str(tree), base_sha)
    for name in included_ignored_files(project):
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((project / name).read_bytes())
    print(json.dumps({"path": str(tree), "branch": args.branch, "base_sha": base_sha}))


def cmd_remove(args):
    project = Path(args.project).resolve()
    tree = project / ".worktrees" / args.task
    if git(tree, "status", "--porcelain"):
        raise WorktreeError(f"{tree} has uncommitted changes")
    branch = git(tree, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise WorktreeError(f"{tree} is not on a branch")
    # A commit that no remote-tracking ref holds is lost when the branch goes.
    # After a verified squash sub-merge the branch commits are on no remote ref,
    # so the PM passes --merged to skip this check.
    if not args.merged and git(tree, "rev-list", "--count", "HEAD", "--not", "--remotes") != "0":
        raise WorktreeError(f"{tree} has commits that no remote holds")
    # `-f -f` overrides the lock that the harness leaves on a worker's tree.
    git(project, "worktree", "remove", "-f", "-f", str(tree))
    git(project, "branch", "-D", branch)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--project", required=True)
    create.add_argument("--task", required=True)
    create.add_argument("--branch", required=True)
    create.add_argument("--base", required=True)
    create.add_argument("--remote", default="origin")
    remove = sub.add_parser("remove")
    remove.add_argument("--project", required=True)
    remove.add_argument("--task", required=True)
    remove.add_argument("--merged", action="store_true")
    args = parser.parse_args()
    try:
        {"create": cmd_create, "remove": cmd_remove}[args.command](args)
    except WorktreeError as error:
        print(f"worktree.py: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
