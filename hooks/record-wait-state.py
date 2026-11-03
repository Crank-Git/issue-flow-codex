#!/usr/bin/env python3
"""Record timeouts and successful Stage A0 list calls."""

import json
import re
import sys

from wait_state import clear_pending, set_pending


STAGE_A0 = re.compile(r"(?:^|(?:&&|[;|])\s*)(?:gh\s+(?:issue|pr)\s+list|tea\s+(?:issues|pulls))(?:\s|$)")


def successful_bash(payload):
    response = payload.get("tool_response")
    return isinstance(response, str) and response.startswith("Exit code: 0\n")


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
            set_pending(session_id)
        else:
            clear_pending(session_id)
        return
    if tool_name != "Bash" or not successful_bash(payload):
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and STAGE_A0.search(command):
        clear_pending(session_id)


def main():
    try:
        record(json.load(sys.stdin))
    except Exception:
        return


if __name__ == "__main__":
    main()
