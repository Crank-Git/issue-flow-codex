"""Store the task names that one PM session has spawned.

Codex sets `PLUGIN_DATA` for plugin hooks but does not create the directory, so the writer
creates it first (docs/specs/pages/codex-harness.md, fact 17). The file holds
`{"names": [...]}`, one file for each session.
"""

import json
import os
from pathlib import Path
from uuid import UUID


def state_path(session_id):
    """Return the session file path when the session id and plugin data exist."""
    data_root = os.environ.get("PLUGIN_DATA")
    if not data_root or not isinstance(session_id, str):
        return None
    try:
        UUID(session_id)
    except ValueError:
        return None
    return Path(data_root) / f"spawns-{session_id}.json"


def read_names(session_id):
    """Return the spawned names as a list. A missing or broken file gives an empty list.

    Returns None when no file path exists, so the caller can skip the rules that need history.
    """
    path = state_path(session_id)
    if path is None:
        return None
    try:
        names = json.loads(path.read_text())["names"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [name for name in names if isinstance(name, str)] if isinstance(names, list) else []


def record(session_id, task_name):
    """Add `task_name` to the session file. Raises OSError when the file cannot be written."""
    path = state_path(session_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"names": read_names(session_id) + [task_name]}) + "\n")
