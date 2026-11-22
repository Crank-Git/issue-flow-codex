"""Store the quota samples of one PM session for the run budget.

The file `$PLUGIN_DATA/budget-<session_id>.json` holds `{"samples": [[used_percent, resets_at], ...]}`.
The first sample is the start of the run. Each later sample is the last sample of one quota
window, so the last value of an old window survives when `resets_at` moves to a new window
(`scripts/usage.py` `quota_share` counts each later window from 0).
"""

import json
import sys
from pathlib import Path

from spawn_state import state_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import usage  # noqa: E402


def read_samples(session_id):
    """Return the stored samples as (used_percent, resets_at) pairs. A missing or broken file gives an empty list."""
    path = state_path(session_id, "budget")
    if path is None:
        return []
    try:
        samples = json.loads(path.read_text())["samples"]
        return [(used, resets) for used, resets in samples]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def add_sample(samples, sample):
    """Return `samples` with `sample` added.

    The start sample stays. A sample in the window of the last sample replaces it.
    """
    if len(samples) > 1 and abs(sample[1] - samples[-1][1]) <= usage.WINDOW_TOLERANCE_S:
        return samples[:-1] + [sample]
    return samples + [sample]


def record_sample(session_id, sample):
    """Store `sample` and return all samples. Raises OSError when the file cannot be written.

    The caller has a state path: `state_path` is not None.
    """
    samples = add_sample(read_samples(session_id), sample)
    path = state_path(session_id, "budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"samples": samples}) + "\n")
    return samples
