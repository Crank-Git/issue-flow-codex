#!/usr/bin/env python3
"""Plan and apply the project setup for the issue-flow loop.

Port-only script, the mechanics of the `setup` skill (FR-plugin-packaging-11 to 19).

    python3 scripts/setup_project.py plan --project <dir> [--with-default-permissions]
    python3 scripts/setup_project.py apply --project <dir> --accept <file>... [--with-default-permissions]

`plan` prints a unified diff for each file that setup changes and writes nothing.
`apply` writes only the files named by `--accept`. A file name is a path relative to
the project, as the plan shows it. A Codex plugin cannot ship roles, so setup copies
the role files from `<plugin root>/roles/` into `<project>/.codex/agents/`.
"""

import argparse
import difflib
import json
import re
import sys
import tomllib
from pathlib import Path

DEFAULT_CONCURRENCY = 3
# The thread limit holds one slot per worker, one watcher, two worker subagents, and the PM.
THREAD_OVERHEAD = 4
BEGIN = "# issue-flow:begin"
END = "# issue-flow:end"
TABLE_HEADER = re.compile(r"^\s*\[")
# Same text as the block in docs/specs/features/01-plugin-packaging.md, Behaviour rules.
BLOCK_TEMPLATE = """\
# issue-flow:begin (written by $issue-flow:setup — edit with the setup skill)
{permissions_line}[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = {threads}

[permissions.issue_flow]
extends = ":workspace"

[permissions.issue_flow.filesystem.":workspace_roots"]
"." = "write"
".git" = "write"

[permissions.issue_flow.network]
enabled = true
# issue-flow:end"""


class SetupError(Exception):
    pass


def read_concurrency(project):
    path = project / ".issue-flow.json"
    if not path.is_file():
        return DEFAULT_CONCURRENCY
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("concurrency", DEFAULT_CONCURRENCY)
    except json.JSONDecodeError as exc:
        raise SetupError(f".issue-flow.json is not valid JSON: {exc}") from exc
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SetupError(".issue-flow.json: concurrency must be a positive integer")
    return value


def render_block(concurrency, with_default_permissions):
    """Return the config block text, without a trailing newline."""
    line = 'default_permissions = "issue_flow"\n\n' if with_default_permissions else ""
    return BLOCK_TEMPLATE.format(permissions_line=line, threads=concurrency + THREAD_OVERHEAD)


def merge_config(existing, block):
    """Return the config text with the block in place of the old block, or inserted.

    A new block goes before the first table header, so its root key
    `default_permissions` stays a root key (codex-harness.md, fact 12).
    """
    lines = existing.splitlines(keepends=True)
    begins = [i for i, l in enumerate(lines) if l.startswith(BEGIN)]
    ends = [i for i, l in enumerate(lines) if l.rstrip("\n") == END]
    if begins:
        if not ends or ends[0] < begins[0]:
            raise SetupError(f".codex/config.toml: block has no `{END}` line")
        head, tail = lines[:begins[0]], lines[ends[0] + 1:]
        return "".join(head) + block + "\n" + "".join(tail)
    split = next((i for i, l in enumerate(lines) if TABLE_HEADER.match(l)), len(lines))
    head, tail = lines[:split], lines[split:]
    prefix = "".join(head)
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    suffix = "\n" + "".join(tail) if tail else ""
    return prefix + block + "\n" + suffix


def plan_files(project, plugin_root, with_default_permissions):
    """Return {relative path: new text} for each file that setup changes."""
    wanted = {}
    for role in sorted((plugin_root / "roles").glob("*.toml")):
        wanted[f".codex/agents/{role.name}"] = role.read_text(encoding="utf-8")

    config = project / ".codex" / "config.toml"
    existing = config.read_text(encoding="utf-8") if config.is_file() else ""
    block = render_block(read_concurrency(project), with_default_permissions)
    merged = merge_config(existing, block)
    try:
        tomllib.loads(merged)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f".codex/config.toml would not parse as TOML: {exc}") from exc
    wanted[".codex/config.toml"] = merged

    ignore = project / ".gitignore"
    current = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if ".worktrees/" not in current.splitlines():
        sep = "" if not current or current.endswith("\n") else "\n"
        wanted[".gitignore"] = current + sep + ".worktrees/\n"

    changed = {}
    for rel, text in wanted.items():
        path = project / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            changed[rel] = text
    return changed


def apply_files(project, files, accepted):
    """Write each accepted file and return the list of paths written."""
    unknown = [rel for rel in accepted if rel not in files]
    if unknown:
        raise SetupError("not in the plan: " + ", ".join(unknown))
    for rel in accepted:
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[rel], encoding="utf-8")
    return list(accepted)


def print_diffs(project, files):
    for rel, text in files.items():
        path = project / rel
        old = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.is_file() else []
        fromfile = f"a/{rel}" if path.is_file() else "/dev/null"
        sys.stdout.writelines(difflib.unified_diff(old, text.splitlines(keepends=True),
                                                   fromfile=fromfile, tofile=f"b/{rel}"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True, type=Path)
        p.add_argument("--with-default-permissions", action="store_true",
                       help='set default_permissions = "issue_flow" (FR-plugin-packaging-16)')
        # Tests point this at a fixture; a run leaves the default.
        p.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parent.parent)
    sub.choices["apply"].add_argument("--accept", nargs="+", required=True, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        files = plan_files(args.project, args.plugin_root, args.with_default_permissions)
        if args.command == "plan":
            if files:
                print_diffs(args.project, files)
            else:
                print("no changes")
        else:
            for rel in apply_files(args.project, files, args.accept):
                print(json.dumps({"wrote": rel}))
    except SetupError as exc:
        print(f"setup_project: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
