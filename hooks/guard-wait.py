#!/usr/bin/env python3
"""PreToolUse guard: make every `wait_agent` call use the configured `waitMs`.

Wired by `hooks/hooks.json` with the matcher `wait_agent$`. The PM is a model, and a model
does not always pass the `timeout_ms` that the skill asks for. The Epic 2 run measured a PM
that waited with its own value (docs/specs/spec.md, 2026-11-03). FR-worker-dispatch-20 needs
`timeout_ms` to equal `waitMs` from `.issue-flow.codex.json` in the payload `cwd`
(default 600000).

When `tool_input.timeout_ms` differs or is absent, the guard allows the call with
`updatedInput`: the same `tool_input` and the configured `timeout_ms`. Codex then runs the
corrected call, and the model needs no second turn.

A pending timeout (hooks/wait_state.py) makes the guard deny a PM `wait_agent` call until the
Stage A0 list calls run. The guard ignores subagent payloads, which carry `agent_id`. After two
denials it allows the next call with a `systemMessage` that names the missed sweep.

Fail open: a parse error, a non-object payload, or a non-object `tool_input` exits 0 with no
output. An unreadable or invalid configuration file counts as absent, and the default applies.
"""

import json
import sys
from pathlib import Path

from wait_state import clear_pending, count_denial, read_state

DEFAULT_WAIT_MS = 600000


def wait_ms(cwd):
    """Return `waitMs` from `.issue-flow.codex.json` in `cwd`, or the default when it is unusable."""
    try:
        value = json.loads((Path(cwd) / ".issue-flow.codex.json").read_text()).get("waitMs")
    except (OSError, ValueError, AttributeError, TypeError):
        return DEFAULT_WAIT_MS
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_WAIT_MS


def decide(payload):
    """Return the corrected `tool_input`, or None when the call already uses the configured timeout."""
    if not str(payload.get("tool_name", "")).endswith("wait_agent"):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    configured = wait_ms(payload.get("cwd") or ".")
    if tool_input.get("timeout_ms") == configured:
        return None
    return {**tool_input, "timeout_ms": configured}


DENY_REASON = (
    "Run forge.issue.list.since and forge.pr.list.since before the next wait_agent call. "
    "Use gh issue list and gh pr list, or tea issues and tea pulls."
)
MISSED_SWEEP = (
    "issue-flow: the Stage A0 sweep was skipped after a wait_agent timeout. The guard denied "
    "wait_agent twice and now allows it. Run forge.issue.list.since and forge.pr.list.since now."
)


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        output = {}
        is_pm_wait = str(payload.get("tool_name", "")).endswith("wait_agent") and "agent_id" not in payload
        state = read_state(payload.get("session_id")) if is_pm_wait else None
        if state is not None:
            # Two denials without a sweep mean the hook state or the sweep detection is wrong.
            # Allow the call so that a hook bug cannot deadlock the loop.
            if state.get("denials", 0) < 2:
                count_denial(payload.get("session_id"))
                json.dump(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": DENY_REASON,
                        }
                    },
                    sys.stdout,
                )
                return
            clear_pending(payload.get("session_id"))
            output["systemMessage"] = MISSED_SWEEP
        corrected = decide(payload)
    except Exception:  # fail open, see the module docstring
        return
    if corrected is not None:
        output["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": corrected,
        }
    if output:
        json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
