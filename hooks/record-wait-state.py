#!/usr/bin/env python3
"""Record PM wait timeouts and the Stage A0 list calls that follow them.

Evidence (the #75 gate run, Codex 0.166.0, tests/fixtures/hooks/gate75_pm_sequence.json):

- A subagent payload carries the PM's `session_id` and adds `agent_id` and `agent_type`.
  Only a payload without `agent_id` is the PM thread, so the hook ignores every other one.
- The PostToolUse `tool_response` of Bash is the raw command output. It has no exit-code
  header and no exit-code field, and a failed command has no marker either. The one
  recorded failure marker is a command that never ran: output that starts with
  `sandbox-exec: sandbox_apply`. So a matching list command counts as done when its
  PostToolUse fires, unless it carries that marker.
- A Gitea MCP call has the tool name `mcp__<server>__<tool>` (references/forge.md).
  `list_issues` is the issue list. `list_issues` with `type: "pulls"`, and
  `list_pull_requests`, are the pull request list.
"""

import json
import re
import sys

from wait_state import clear_pending, mark_listed, write_state


ISSUE_LIST = re.compile(r"(?:^|(?:&&|[;|])\s*)(?:gh\s+issue\s+list|tea\s+issues)(?:\s|$)")
PR_LIST = re.compile(r"(?:^|(?:&&|[;|])\s*)(?:gh\s+pr\s+list|tea\s+pulls)(?:\s|$)")
MCP_ISSUE_LIST = re.compile(r"^mcp__.+__list_issues$")
MCP_PR_LIST = re.compile(r"^mcp__.+__list_pull_requests$")
COMMAND_NEVER_RAN = "sandbox-exec: sandbox_apply"


def record_wait(session_id, response):
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return
    if not isinstance(response, dict) or not isinstance(response.get("timed_out"), bool):
        return
    if response["timed_out"]:
        write_state(session_id, {"timed_out": True})
    else:
        clear_pending(session_id)


def listed_keys(tool_name, tool_input, response):
    """Return the Stage A0 lists that a finished tool call counts as."""
    if tool_name.startswith("mcp__"):
        if MCP_PR_LIST.match(tool_name):
            return ["pr_list"]
        if MCP_ISSUE_LIST.match(tool_name):
            is_pulls = isinstance(tool_input, dict) and tool_input.get("type") == "pulls"
            return ["pr_list" if is_pulls else "issue_list"]
        return []
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if (
        tool_name != "Bash"
        or not isinstance(command, str)
        or (isinstance(response, str) and response.startswith(COMMAND_NEVER_RAN))
    ):
        return []
    return [key for key, pattern in (("issue_list", ISSUE_LIST), ("pr_list", PR_LIST))
            if pattern.search(command)]


def record(payload):
    if (
        not isinstance(payload, dict)
        or payload.get("hook_event_name") != "PostToolUse"
        or "agent_id" in payload
    ):
        return
    tool_name = payload.get("tool_name", "")
    session_id = payload.get("session_id")
    if isinstance(tool_name, str) and tool_name.endswith("wait_agent"):
        record_wait(session_id, payload.get("tool_response"))
        return
    if not isinstance(tool_name, str):
        return
    for key in listed_keys(tool_name, payload.get("tool_input"), payload.get("tool_response")):
        mark_listed(session_id, key)


def main():
    try:
        record(json.load(sys.stdin))
    except Exception:
        return


if __name__ == "__main__":
    main()
