#!/usr/bin/env python3
"""Record timeouts and successful Stage A0 list calls."""

import json
import re
import sys

from wait_state import clear_pending, mark_listed, state_path


ISSUE_LIST = re.compile(r"(?:^|(?:&&|[;|])\s*)(?:gh\s+issue\s+list|tea\s+issues)(?:\s|$)")
PR_LIST = re.compile(r"(?:^|(?:&&|[;|])\s*)(?:gh\s+pr\s+list|tea\s+pulls)(?:\s|$)")


def record(payload):
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PostToolUse":
        return
    tool_name = payload.get("tool_name", "")
    session_id = payload.get("session_id")
    if isinstance(tool_name, str) and tool_name.endswith("wait_agent"):
        response = payload.get("tool_response")
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except ValueError:
                return
        if not isinstance(response, dict) or not isinstance(response.get("timed_out"), bool):
            return
        if response["timed_out"]:
            path = state_path(session_id)
            if path is not None:
                path.write_text('{"timed_out": true}\n')
        else:
            clear_pending(session_id)
        return
    response = payload.get("tool_response")
    if (
        tool_name != "Bash"
        or not isinstance(response, str)
        or not response.startswith("Exit code: 0\n")
    ):
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    if ISSUE_LIST.search(command):
        mark_listed(session_id, "issue_list")
    if PR_LIST.search(command):
        mark_listed(session_id, "pr_list")


def main():
    try:
        record(json.load(sys.stdin))
    except Exception:
        return


if __name__ == "__main__":
    main()
