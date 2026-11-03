"""Probe hook: log each payload, add SessionStart context, and deny one spawn on request."""

import json
import os
import sys
import time

payload = json.load(sys.stdin)
payload["probe_ts"] = time.time()
with open(os.environ["PROBE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(payload) + "\n")

event = payload.get("hook_event_name")
if event == "SessionStart":
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": "PROBE_TOKEN=" + os.environ["PROBE_TOKEN"],
    }}))
elif (event == "PreToolUse"
      and str(payload.get("tool_name", "")).endswith("spawn_agent")
      and payload.get("tool_input", {}).get("agent_type") == os.environ.get("PROBE_DENY_ROLE")):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "DENIED-" + os.environ["PROBE_TOKEN"],
    }}))
