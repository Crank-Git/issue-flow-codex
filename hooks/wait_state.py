"""Store timeout state for one Codex session."""

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


def is_pending(session_id):
    path = state_path(session_id)
    if path is None:
        return False
    try:
        return json.loads(path.read_text()).get("timed_out") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_pending(session_id):
    path = state_path(session_id)
    if path is not None:
        path.write_text('{"timed_out": true}\n')


def clear_pending(session_id):
    path = state_path(session_id)
    if path is not None:
        path.unlink(missing_ok=True)
