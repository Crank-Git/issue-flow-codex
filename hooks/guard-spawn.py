#!/usr/bin/env python3
"""PreToolUse guard: refuse a worker spawn that inherits the PM session or has no worker role.

Wired by `hooks/hooks.json` with the matcher `spawn_agent$`. Codex sends a V2 spawn to
this hook with a `tool_name` that ends in `spawn_agent` (live: `collaborationspawn_agent`)
and a `tool_input` with `task_name`, `fork_turns`, `message`, and `agent_type` (only when set).

Two rules, both on readable fields:

1. Deny a spawn whose `fork_turns` is not `"none"`. An omitted `fork_turns` means `"all"`.
   A subagent then inherits the whole PM session, and nothing in that session tells it to
   stop after one issue. Upstream measured a fork that ran the PM loop for 52 minutes and
   merged to `dev` with no PM gate. The inherited history also inflates every request
   (openai/codex #58291).
2. Deny a spawn whose `task_name` is a worker name (`worker_<n>` or `worker_<n>_c<k>`,
   FR-worker-dispatch-10 and -11) unless `agent_type` is `issue_worker`. Without the role,
   the role guard and the role's model do not apply.

The guard never reads `message`. Upstream detected a handoff brief by its field labels in
the prompt, but live Codex 0.166.0 delivers `tool_input.message` to the hook as an encrypted
token (docs/specs/pages/codex-harness.md, fact 13), so a label match cannot fire.

Fail open: a parse error, a non-object payload, or a non-object `tool_input` exits 0 with
no output. A guard against a runaway worker must never be the reason work cannot start.
Codex rejects an `ask` decision, so the guard only denies.

`ISSUE_FLOW_SPAWN_GUARD=off` disables the guard. Hooks read the environment at session
start, so set it before the session starts.
"""

import json
import os
import re
import sys

WORKER_NAME = re.compile(r"worker_\d+(_c\d+)?")

FORK_REASON = (
    "issue-flow spawn guard: this spawn_agent call has fork_turns FORK_TURNS. A subagent "
    "with fork_turns \"all\" (the default) inherits this whole session, including the PM "
    "loop, and nothing in it says to stop after one issue. Call spawn_agent again and "
    "pass fork_turns \"none\"."
)

ROLE_REASON = (
    "issue-flow spawn guard: task_name TASK_NAME is a worker name, but agent_type is "
    "AGENT_TYPE. Call spawn_agent again and pass agent_type \"issue_worker\"."
)


def decide(payload):
    """Return the deny reason, or None to stay out of the way."""
    if not str(payload.get("tool_name", "")).endswith("spawn_agent"):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    fork_turns = tool_input.get("fork_turns")
    if fork_turns != "none":
        shown = "omitted (it means \"all\")" if fork_turns is None else json.dumps(fork_turns)
        return FORK_REASON.replace("FORK_TURNS", shown, 1)
    task_name = tool_input.get("task_name")
    agent_type = tool_input.get("agent_type")
    if isinstance(task_name, str) and WORKER_NAME.fullmatch(task_name) and agent_type != "issue_worker":
        shown = "omitted" if agent_type is None else json.dumps(agent_type)
        return ROLE_REASON.replace("TASK_NAME", task_name, 1).replace("AGENT_TYPE", shown, 1)
    return None


def main():
    if os.environ.get("ISSUE_FLOW_SPAWN_GUARD", "").strip().lower() in {"off", "0", "false", "no"}:
        return
    try:
        payload = json.load(sys.stdin)
        reason = decide(payload) if isinstance(payload, dict) else None
    except Exception:  # fail open, see the module docstring
        return
    if not reason:
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
