#!/usr/bin/env python3
"""Plan and apply the project setup for the issue-flow loop.

Port-only script, the mechanics of the `setup` skill (FR-plugin-packaging-11 to 19, 40 to 48).

    python3 scripts/setup_project.py plan --user
    python3 scripts/setup_project.py apply --user [--accept <file>...]
    python3 scripts/setup_project.py check --user
    python3 scripts/setup_project.py plan --project <dir> [--with-default-permissions]
    python3 scripts/setup_project.py apply --project <dir> --accept <file>... [--with-default-permissions]
    python3 scripts/setup_project.py check --project <dir>

`--user` works in `$CODEX_HOME`, or in `~/.codex` when the variable is not set. It
writes `issue-flow.config.toml`, which `codex -p issue-flow` layers on the user config,
and copies the role files into `agents/`. It never writes `config.toml`.
`apply --user` writes each missing file. It replaces a file that differs only when
`--accept` names the file; else it prints the diff and exits 1.

A rerun keeps a `default_permissions = "issue_flow"` line that the block already holds.
`--without-default-permissions` drops it. Without either flag, `plan` and `apply` decide
from the file.

`plan` prints a unified diff for each file that setup changes and writes nothing.
`apply` writes only the files named by `--accept`. A file name is a path relative to
the project, as the plan shows it. A Codex plugin cannot ship roles, so setup copies
the role files from `<plugin root>/roles/` into `<project>/.codex/agents/`.
`check` prints one status line for each item, writes nothing, and exits 1 when an item
is `missing` or `stale` (docs/specs/features/01-plugin-packaging.md, Screens & states).
"""

import argparse
import difflib
import json
import os
import re
import sys
import tomllib
from pathlib import Path

from build_roles import LITERAL_DELIMITER, toml_basic

DEFAULT_CONCURRENCY = 3
# The thread limit holds one slot per worker, one watcher, two worker subagents, and the PM.
THREAD_OVERHEAD = 4
BEGIN = "# issue-flow:begin"
END = "# issue-flow:end"
TABLE_HEADER = re.compile(r"^\s*\[")
PROFILE = """\
[permissions.issue_flow]
extends = ":workspace"

[permissions.issue_flow.filesystem.":workspace_roots"]
"." = "write"
".git" = "write"
".agents" = "write"

[permissions.issue_flow.network]
enabled = true"""
FEATURES = """\
[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = {threads}"""
# Same text as the block in docs/specs/features/01-plugin-packaging.md, Behaviour rules.
BLOCK_TEMPLATE = """\
# issue-flow:begin (written by $issue-flow:setup — edit with the setup skill)
{permissions_line}""" + FEATURES + "\n\n" + PROFILE + """
# issue-flow:end"""


PERMISSIONS_LINE = 'default_permissions = "issue_flow"'
# `codex -p issue-flow` layers this file on the user config (codex-harness.md, fact 25).
USER_PROFILE_FILE = "issue-flow.config.toml"
# The user-level mode has no run configuration, so it uses the default concurrency.
USER_PROFILE = (PERMISSIONS_LINE + "\n\n"
                + FEATURES.format(threads=DEFAULT_CONCURRENCY + THREAD_OVERHEAD) + "\n\n"
                + PROFILE + "\n")


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


def block_lines(existing):
    """Return the lines from the begin marker to the end marker, or [] when there is no block."""
    lines = existing.splitlines()
    begin = next((i for i, l in enumerate(lines) if l.startswith(BEGIN)), None)
    if begin is None:
        return []
    end = next((i for i in range(begin, len(lines)) if lines[i] == END), None)
    if end is None:
        raise SetupError(f".codex/config.toml: block has no `{END}` line")
    return lines[begin:end + 1]


def resolve_default_permissions(existing, requested):
    """Return whether the block carries the profile line: the operator's choice, else the file's."""
    if requested is not None:
        return requested
    return PERMISSIONS_LINE in block_lines(existing)


def render_block(concurrency, with_default_permissions):
    """Return the config block text, without a trailing newline."""
    line = PERMISSIONS_LINE + "\n\n" if with_default_permissions else ""
    return BLOCK_TEMPLATE.format(permissions_line=line, threads=concurrency + THREAD_OVERHEAD)


def render_role(role):
    """Return role TOML with model fields at the document root."""
    instructions = role["developer_instructions"]
    if LITERAL_DELIMITER in instructions:
        raise SetupError("role developer_instructions contains the TOML literal delimiter")
    return "\n".join([
        f"name = {toml_basic(role['name'])}",
        f"description = {toml_basic(role['description'])}",
        f"model = {toml_basic(role['model'])}",
        f"model_reasoning_effort = {toml_basic(role['model_reasoning_effort'])}",
        f"developer_instructions = {LITERAL_DELIMITER}",
        instructions.rstrip("\n") + "\n" + LITERAL_DELIMITER,
    ]) + "\n"


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
    codex_path = project / ".issue-flow.codex.json"
    try:
        codex = json.loads(codex_path.read_text(encoding="utf-8")) if codex_path.is_file() else {}
    except json.JSONDecodeError as exc:
        raise SetupError(f".issue-flow.codex.json is not valid JSON: {exc}") from exc
    if not isinstance(codex, dict):
        raise SetupError(".issue-flow.codex.json must contain an object")
    for key in ("workerModel", "workerEffort", "helperModel"):
        if key in codex and not isinstance(codex[key], str):
            raise SetupError(f".issue-flow.codex.json: {key} must be a string")
    for role in sorted((plugin_root / "roles").glob("*.toml")):
        text = role.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise SetupError(f"role source is not valid TOML: {role}: {exc}") from exc
        if role.stem == "issue-worker":
            parsed["model"] = codex.get("workerModel", parsed["model"])
            parsed["model_reasoning_effort"] = codex.get("workerEffort", parsed["model_reasoning_effort"])
        elif role.stem in ("code-auditor", "deploy-verifier", "review-scribe", "ux-explorer", "ci-watcher"):
            parsed["model"] = codex.get("helperModel", parsed["model"])
        text = render_role(parsed)
        wanted[f".codex/agents/{role.name}"] = text

    config = project / ".codex" / "config.toml"
    existing = config.read_text(encoding="utf-8") if config.is_file() else ""
    block = render_block(read_concurrency(project),
                         resolve_default_permissions(existing, with_default_permissions))
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


def print_diffs(project, files, with_default_permissions):
    config = project / ".codex" / "config.toml"
    if (".codex/config.toml" in files and with_default_permissions is None and config.is_file()
            and PERMISSIONS_LINE in block_lines(config.read_text(encoding="utf-8"))):
        print(f'note: .codex/config.toml keeps {PERMISSIONS_LINE} (already set)')
    for rel, text in files.items():
        path = project / rel
        old = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.is_file() else []
        fromfile = f"a/{rel}" if path.is_file() else "/dev/null"
        sys.stdout.writelines(difflib.unified_diff(old, text.splitlines(keepends=True),
                                                   fromfile=fromfile, tofile=f"b/{rel}"))


def check_report(project, plugin_root):
    """Return (item, status, detail) rows for the project, reading only."""
    version = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    rows = []

    wanted = sorted((plugin_root / "roles").glob("*.toml"))
    copies = [project / ".codex" / "agents" / r.name for r in wanted]
    codex_path = project / ".issue-flow.codex.json"
    codex = json.loads(codex_path.read_text(encoding="utf-8")) if codex_path.is_file() else {}
    matching = 0
    for source, copy in zip(wanted, copies):
        if not copy.is_file():
            continue
        try:
            source_role = tomllib.loads(source.read_text(encoding="utf-8"))
            tomllib.loads(copy.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            print(f"setup_project: malformed role copy: {copy}", file=sys.stderr)
            continue
        if source.stem == "issue-worker":
            source_role["model"] = codex.get("workerModel", source_role["model"])
            source_role["model_reasoning_effort"] = codex.get(
                "workerEffort", source_role["model_reasoning_effort"])
        elif source.stem in ("code-auditor", "deploy-verifier", "review-scribe", "ux-explorer", "ci-watcher"):
            source_role["model"] = codex.get("helperModel", source_role["model"])
        matching += render_role(source_role) == copy.read_text(encoding="utf-8")
    # A present copy that differs is stale even when other copies are absent: Codex loads it.
    present = sum(c.is_file() for c in copies)
    status = "stale" if matching < present else "missing" if present < len(wanted) else "ok"
    rows.append(("roles", status, f"{matching} of {len(wanted)} match plugin {version}"))

    config = project / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    block = block_lines(text)
    expected_threads = read_concurrency(project) + THREAD_OVERHEAD
    expected_block = render_block(read_concurrency(project), PERMISSIONS_LINE in block).splitlines()
    rows.append(("config block", "missing" if not block else "ok" if block == expected_block else "stale", ""))

    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f".codex/config.toml does not parse as TOML: {exc}") from exc
    threads = parsed.get("features", {}).get("multi_agent_v2", {}).get("max_concurrent_threads_per_session")
    key = "max_concurrent_threads_per_session"
    if threads is None:
        rows.append(("threads", "missing", f"{key} is not set"))
    elif threads == expected_threads:
        rows.append(("threads", "ok", f"{key} = {threads}"))
    else:
        rows.append(("threads", "stale", f"{key} = {threads}, expected {expected_threads}"))

    if parsed.get("default_permissions") == "issue_flow":
        rows.append(("profile", "ok", "default_permissions = issue_flow"))
    else:
        rows.append(("profile", "missing", "default_permissions is not set to issue_flow"))

    ignore = project / ".gitignore"
    listed = ignore.is_file() and ".worktrees/" in ignore.read_text(encoding="utf-8").splitlines()
    rows.append(("gitignore", "ok" if listed else "missing", ""))
    rows.append(("hooks", "unknown", "run /hooks to see the trust state"))
    return rows


def user_status(plugin_root):
    """Return (Codex home, {path: wanted text}, {path: ok | missing | stale}) for the user setup.

    The Codex home is `$CODEX_HOME`, else `~/.codex`.
    """
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    wanted = {USER_PROFILE_FILE: USER_PROFILE}
    for role in sorted((plugin_root / "roles").glob("*.toml")):
        wanted[f"agents/{role.name}"] = role.read_text(encoding="utf-8")
    status = {}
    for rel, text in wanted.items():
        path = home / rel
        if not path.is_file():
            status[rel] = "missing"
        else:
            status[rel] = "ok" if path.read_text(encoding="utf-8") == text else "stale"
    return home, wanted, status


def run_user(command, plugin_root, accept):
    """Run `plan`, `apply`, or `check` on the Codex home and return the exit code."""
    home, wanted, status = user_status(plugin_root)
    if command == "check":
        for rel in wanted:
            print(f"{rel:<32} {status[rel]}")
        return int(any(s != "ok" for s in status.values()))
    files = {rel: text for rel, text in wanted.items() if status[rel] != "ok"}
    if not files:
        print("no changes")
        return 0
    if command == "plan":
        print_diffs(home, files, None)
        return 0
    accepted = [rel for rel in files if status[rel] == "missing"]
    accepted += [rel for rel in accept if rel not in accepted]
    for rel in apply_files(home, files, accepted):
        print(json.dumps({"wrote": rel}))
    pending = {rel: text for rel, text in files.items() if rel not in accepted}
    if pending:
        print_diffs(home, pending, None)
        print(f"setup_project: {len(pending)} file(s) differ; to replace, rerun apply --user "
              f"--accept {' '.join(pending)}",
              file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "check"):
        p = sub.add_parser(name)
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument("--project", type=Path)
        target.add_argument("--user", action="store_true",
                            help="set up $CODEX_HOME (default ~/.codex) for every project")
        if name != "check":
            group = p.add_mutually_exclusive_group()
            group.add_argument("--with-default-permissions", action="store_true", default=None,
                               help='set default_permissions = "issue_flow" (FR-plugin-packaging-16)')
            group.add_argument("--without-default-permissions", action="store_false",
                               dest="with_default_permissions",
                               help="drop the default_permissions line")
        # Tests point this at a fixture; a run leaves the default.
        p.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parent.parent)
    sub.choices["apply"].add_argument("--accept", nargs="+", default=[], metavar="FILE")
    args = parser.parse_args(argv)
    if args.command == "apply" and args.project and not args.accept:
        parser.error("apply --project needs --accept")
    try:
        if args.user:
            return run_user(args.command, args.plugin_root, getattr(args, "accept", []))
        if args.command == "check":
            rows = check_report(args.project, args.plugin_root)
            home, _, user = user_status(args.plugin_root)
            user_ok = all(s == "ok" for s in user.values())
            project_ok = not any(s in ("missing", "stale") for _, s, _ in rows)
            # A complete user-level setup makes the project files optional (ADR 0005).
            if user_ok:
                rows = [(item, "not used", "") if s == "missing" else (item, s, detail)
                        for item, s, detail in rows]
                user_row = "ok"
            elif project_ok:
                user_row = "not used"
            else:
                user_row = "missing" if "missing" in user.values() else "stale"
            rows.insert(len(rows) - 1, ("user setup", user_row, str(home)))
            for item, status, detail in rows:
                print(f"{item:<12} {status:<8} {detail}".rstrip())
            failed = any(status in ("missing", "stale") for _, status, _ in rows)
            if failed and not user_ok:
                print(f"fix: python3 {args.plugin_root}/scripts/setup_project.py apply --user")
            return int(failed)
        files = plan_files(args.project, args.plugin_root, args.with_default_permissions)
        if args.command == "plan":
            if files:
                print_diffs(args.project, files, args.with_default_permissions)
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
