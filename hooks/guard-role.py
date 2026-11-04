#!/usr/bin/env python3
"""PreToolUse role guard: deny a tool call that the calling subagent's role may not make.

`hooks/hooks.json` registers it for every tool. It reads the payload on stdin and the rules
from `hooks/role-policy.json`. A payload with no `agent_type` comes from the PM thread, and
the guard allows it. Inside a subagent, Codex sets `agent_type` to the role name
(codex-harness fact 10).

A rule for a role has up to four keys:
  tools             regexes searched in `tool_name`
  bash_prefixes     command prefixes denied for the `Bash` tool
  patch_only_under  `apply_patch` may write only below this directory (relative to `cwd`)
  spawn_roles       roles that the `spawn_agent` tool may not start

The guard is not a security boundary: a shell command can write a file without
`apply_patch`.

The guard fails open. Any payload it cannot read exits 0 with no output, which allows the
call. `ISSUE_FLOW_ROLE_GUARD=off` disables it.
"""

import json
import os
import posixpath
import re
import sys
from pathlib import Path

POLICY = Path(__file__).with_name("role-policy.json")
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.MULTILINE)


def has_prefix(command, prefix):
    """Return True when `command` starts with `prefix` as whole words, so `tea` skips `teapot`."""
    command = command.lstrip()
    return command.startswith(prefix) and not command[len(prefix):len(prefix) + 1].isalnum()


def outside_scratch(patch_text, cwd, scratch):
    """Return the patch paths that fall outside `scratch`, a directory relative to `cwd`."""
    root = posixpath.normpath(posixpath.join(cwd, scratch))
    outside = []
    for path in PATCH_PATH.findall(patch_text):
        resolved = posixpath.normpath(posixpath.join(cwd, path.strip()))
        if not resolved.startswith(root + "/"):
            outside.append(path.strip())
    return outside


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
    scratch = rule.get("patch_only_under")
    if scratch and tool == "apply_patch":
        outside = outside_scratch(arguments.get("command", ""), payload.get("cwd", ""), scratch)
        if outside:
            if payload.get("agent_type") == "issue_worker":
                return ("the worktree rule permits apply_patch only under the project worktrees "
                        f"directory (.worktrees/), not {', '.join(outside)}")
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
