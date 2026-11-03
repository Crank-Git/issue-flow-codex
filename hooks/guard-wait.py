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

Fail open: a parse error, a non-object payload, or a non-object `tool_input` exits 0 with no
output. An unreadable or invalid configuration file counts as absent, and the default applies.
"""

import json
import sys
from pathlib import Path

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


def main():
    try:
        payload = json.load(sys.stdin)
        corrected = decide(payload) if isinstance(payload, dict) else None
    except Exception:  # fail open, see the module docstring
        return
    if corrected is None:
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": corrected,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
