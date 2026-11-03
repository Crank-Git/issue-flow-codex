"""Store timeout state for the PM thread of one Codex session.

Codex sets `PLUGIN_DATA` for plugin hooks but does not create the directory, so every writer
here creates it first (docs/specs/pages/codex-harness.md). The state file holds `timed_out`,
the Stage A0 list calls seen since (`issue_list`, `pr_list`), and `denials`, the number of
times the guard denied a `wait_agent` call for this timeout.
"""

import json
import os
from pathlib import Path
from uuid import UUID


def state_path(session_id):
    """Return the session state path when the session id and plugin data exist."""
    data_root = os.environ.get("PLUGIN_DATA")
    if not data_root or not isinstance(session_id, str):
        return None
    try:
        UUID(session_id)
    except ValueError:
        return None
    return Path(data_root) / f"wait-timeout-{session_id}.json"


def read_state(session_id):
    """Return the pending state as a dict, or None when no timeout is pending."""
    path = state_path(session_id)
    if path is None:
        return None
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("timed_out") is not True:
        return None
    return state


def write_state(session_id, state):
    path = state_path(session_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state) + "\n")


def clear_pending(session_id):
    path = state_path(session_id)
    if path is not None:
        path.unlink(missing_ok=True)


def mark_listed(session_id, key):
    state = read_state(session_id)
    if state is None:
        return
    state[key] = True
    if state.get("issue_list") and state.get("pr_list"):
        clear_pending(session_id)
    else:
        write_state(session_id, state)


def count_denial(session_id):
    """Return how many denials this timeout has had before the current call, then add one."""
    state = read_state(session_id)
    denials = state.get("denials", 0)
    write_state(session_id, {**state, "denials": denials + 1})
    return denials
