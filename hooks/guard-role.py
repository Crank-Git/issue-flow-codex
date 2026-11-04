#!/usr/bin/env python3
"""PreToolUse role guard: deny a tool call that the calling subagent's role may not make.

`hooks/hooks.json` registers it for every tool. It reads the payload on stdin and the rules
from `hooks/role-policy.json`. A payload with no `agent_type` comes from the PM thread, and
the guard allows it. Inside a subagent, Codex sets `agent_type` to the role name
(codex-harness fact 10).

A role rule can use these keys:
  tools             regexes searched in `tool_name`
  bash_prefixes     command prefixes denied for the `Bash` tool
  patch_only_under  `apply_patch` may write only below this directory (relative to `cwd`)
  spawn_roles       roles that the `spawn_agent` tool may not start
  patch_only_under_project_worktrees  `apply_patch` may write only below `<cwd>/.worktrees/`
                    or below the system temp directory (the worker's scratch directory)

The worktree rule enforces the `.worktrees/` boundary only. It cannot tell a worker's own
tree from a sibling's tree, because the payload of a spawned worker carries no `task_name`:
only `agent_id` and `agent_type`, and its `cwd` is the PM's project root, never the worktree
(codex-harness fact 21, measured in the #111 gate run). The rule "write only in your own
worktree" belongs to the runbook in `agents/issue-worker.md`. `apply_patch` has no working
directory, so a relative path resolves against the project root and the guard denies it.

The guard is not a security boundary. A shell command can write a file without
`apply_patch`, and the guard does not resolve symlinks.

The guard fails open. Any payload it cannot read exits 0 with no output, which allows the
call. `ISSUE_FLOW_ROLE_GUARD=off` disables it.
"""

import json
import os
import posixpath
import re
import sys
import tempfile
from pathlib import Path

POLICY = Path(__file__).with_name("role-policy.json")
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.MULTILINE)


def has_prefix(command, prefix):
    """Return True when `command` starts with `prefix` as whole words, so `tea` skips `teapot`."""
    command = command.lstrip()
    return command.startswith(prefix) and not command[len(prefix):len(prefix) + 1].isalnum()


def patch_paths(patch_text, cwd):
    """Return (as written, normalized) for each patch path, resolved against `cwd`."""
    return [(path.strip(), posixpath.normpath(posixpath.join(cwd, path.strip())))
            for path in PATCH_PATH.findall(patch_text)]


def outside_scratch(patch_text, cwd, scratch):
    """Return patch paths outside `scratch`, a directory given relative to `cwd`."""
    root = posixpath.normpath(posixpath.join(cwd, scratch))
    return [path for path, resolved in patch_paths(patch_text, cwd)
            if not resolved.startswith(root + "/")]


def outside_worktrees(patch_text, cwd):
    """Return patch paths that an issue_worker may not write.

    Rules, in order, for a path resolved against `cwd`:
      1. inside `<cwd>/.worktrees/`: allowed;
      2. inside `<cwd>` (the project): denied, even when the project lives under a temp directory;
      3. outside `<cwd>` and inside a system temp directory: allowed (scratch);
      4. anything else: denied.
    Both sides go through `os.path.realpath`, so `/tmp` and `/private/tmp` compare equal.
    """
    project = os.path.realpath(cwd)
    worktrees = os.path.join(project, ".worktrees") + "/"
    temp = tuple(os.path.realpath(root) + "/"
                 for root in {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders"})
    denied = []
    for path, resolved in patch_paths(patch_text, cwd):
        real = os.path.realpath(resolved)
        if real.startswith(worktrees):
            continue
        if real == project or real.startswith(project + "/") or not real.startswith(temp):
            denied.append(path)
    return denied


def violation(payload, rule):
    """Return the text of the rule that the call breaks, or None."""
    tool = payload.get("tool_name", "")
    arguments = payload.get("tool_input")
    if not isinstance(arguments, dict):
        arguments = {}
    for pattern in rule.get("tools", []):
        if re.search(pattern, tool):
            return f"the tool {tool} matches the denied pattern {pattern}"
    if tool == "Bash":
        command = arguments.get("command", "")
        for prefix in rule.get("bash_prefixes", []):
            if has_prefix(command, prefix):
                return f"a Bash command may not start with `{prefix}`"
    if tool == "apply_patch":
        cwd = payload.get("cwd", "")
        command = arguments.get("command", "")
        if rule.get("patch_only_under_project_worktrees") and cwd:
            outside = outside_worktrees(command, cwd)
            if outside:
                return ("the worktree rule permits apply_patch only below .worktrees/ or the "
                        f"temp directory, not {', '.join(outside)}; a relative path resolves "
                        f"against the project checkout {cwd}, so give an absolute path")
        else:
            scratch = rule.get("patch_only_under")
            outside = outside_scratch(command, cwd, scratch) if scratch else []
            if outside:
                return f"apply_patch may write only below {scratch}, not {', '.join(outside)}"
    if re.search("spawn_agent$", tool) and arguments.get("agent_type") in rule.get("spawn_roles", []):
        return f"the role may not spawn the role {arguments['agent_type']}"
    return None


def main():
    if os.environ.get("ISSUE_FLOW_ROLE_GUARD") == "off":
        return
    try:
        payload = json.load(sys.stdin)
        role = payload.get("agent_type")
        rule = json.loads(POLICY.read_text(encoding="utf-8")).get(role)
        broken = violation(payload, rule) if rule else None
    except (ValueError, AttributeError, TypeError, OSError):
        return  # fail open
    if broken:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason":
                f"issue-flow role guard: the role {payload['agent_type']} may not do this; {broken}. "
                "Set ISSUE_FLOW_ROLE_GUARD=off to disable the guard.",
        }}))


if __name__ == "__main__":
    main()
