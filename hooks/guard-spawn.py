#!/usr/bin/env python3
"""PreToolUse guard: refuse a worker spawn that carries a handoff brief the wrong way.

Wired by `hooks/hooks.json` with the matcher `spawn_agent$`. Codex sends a V2 spawn
to this hook with a `tool_name` that ends in `spawn_agent` (live: `collaborationspawn_agent`)
and a `tool_input` that holds `message`, `agent_type`, and `fork_turns`.

A message is a handoff brief when it carries at least `BRIEF_THRESHOLD` of the
handoff-brief field labels (`issue:`, `branch:`, `base:`, `ci:`, `batch:`, `members:`,
`crossCheck:`, `forge:`, `steRule:`) at the start of a line, at least one of them
issue-flow's own (`crossCheck:`, `members:`, `forge:`, `steRule:`). The match tolerates
the ways a model re-lays the template out: list bullets and numbers, headings, bold,
code, table cells, pretty-printed JSON keys, `=` for `:`, and `cross-check`.

The guard denies a brief unless the call is `agent_type: "issue_worker"` with
`fork_turns: "none"`. Why:

* `fork_turns` omitted means `"all"`. The worker then inherits the whole PM session,
  and nothing in that session tells it to stop after one issue. Measured upstream: a fork
  ran the PM loop for 52 minutes and merged to `dev` with no PM gate. The inherited
  history also inflates the request (openai/codex #58291).
* `agent_type` omitted or `default` starts a subagent with no worker role, so the role
  guard and the role's model do not apply.

Known limits. A brief paraphrased into prose or squeezed onto one line passes: the
guard is a tripwire for the template, not a classifier. A message that quotes the brief
fields one per line, to discuss them, is denied: the reason says to reword it.

Fail open. A parse error, a non-object payload, or a non-object `tool_input` exits 0
with no output. A guard against a runaway worker must never be the reason work cannot
start. Codex rejects an `ask` decision, so the guard has only `deny`.

`ISSUE_FLOW_SPAWN_GUARD=off` disables the guard. Hooks read the environment at session
start, so set it before the session starts.
"""

import json
import os
import re
import sys

# Handoff-brief field labels, matched at the start of a line with any list,
# heading, quote, bold, code, table or JSON markup around them
# (`- **base:**`, `2. ci:`, `| members |`, `"crossCheck": `, `cross-check =`).
BRIEF_FIELD = re.compile(
    r"^[\s>*_`#|\"+-]*(?:\d+[.)][ \t]*)?"
    r"(issue|branch|base|ci|batch|members|cross[-_ ]?check|forge|sterule)"
    r"[*_`\"]*[ \t]*[:=|]",
    re.IGNORECASE | re.MULTILINE,
)
BRIEF_THRESHOLD = 3
# Labels no ad-hoc prompt uses. "Issue / Branch / CI" alone is how anyone
# describes a failing build, so at least one of these must be present too.
ISSUE_FLOW_FIELDS = {"crosscheck", "members", "forge", "sterule"}

REASON = (
    "issue-flow spawn guard: this spawn_agent message is an issue-flow handoff brief "
    "(FIELDS), but the call is wrong: PROBLEMS.\n"
    "\n"
    "Send the brief with `agent_type: \"issue_worker\"` and `fork_turns: \"none\"`. "
    "A worker with `fork_turns` omitted or \"all\" inherits this whole session, "
    "including the PM loop, and nothing in it says to stop after one issue. "
    "A worker with another `agent_type` has no worker role.\n"
    "\n"
    "Not a brief? The message matched the handoff-brief layout. Reword it, or turn this "
    "check off. The guard reads its setting at session start, so set this in the "
    "environment before you start a new session:\n"
    "    ISSUE_FLOW_SPAWN_GUARD=off"
)


def brief_fields(message):
    """The distinct handoff-brief labels in `message`, as written, in order."""
    found = {}
    for match in BRIEF_FIELD.finditer(message):
        key = re.sub(r"[-_ ]", "", match.group(1).lower())
        found.setdefault(key, match.group(1))
    return found


def is_brief(fields):
    return len(fields) >= BRIEF_THRESHOLD and not ISSUE_FLOW_FIELDS.isdisjoint(fields)


def decide(payload):
    """Return the deny reason, or None to stay out of the way."""
    if not str(payload.get("tool_name", "")).endswith("spawn_agent"):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    message = tool_input.get("message")
    if not isinstance(message, str):
        return None
    fields = brief_fields(message)
    if not is_brief(fields):
        return None
    problems = []
    fork_turns = tool_input.get("fork_turns")
    if fork_turns != "none":
        shown = "omitted (means \"all\")" if fork_turns is None else json.dumps(fork_turns)
        problems.append(f"`fork_turns` is {shown}, not \"none\"")
    agent_type = tool_input.get("agent_type")
    if agent_type != "issue_worker":
        shown = "omitted" if agent_type is None else json.dumps(agent_type)
        problems.append(f"`agent_type` is {shown}, not \"issue_worker\"")
    if not problems:
        return None
    listed = ", ".join(f"`{field}:`" for field in fields.values())
    return REASON.replace("FIELDS", listed, 1).replace("PROBLEMS", " and ".join(problems), 1)


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
