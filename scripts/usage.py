#!/usr/bin/env python3
"""Report tokens and quota share per thread from local Codex rollout files.

    python3 usage.py --session <session-id>                       # one run, every thread
    python3 usage.py --cwd <dir> --since 2026-11-01T00:00:00Z     # every rollout of a project since then
    python3 usage.py --session <session-id> --json                # the same report as JSON

The script reads files only. It makes no network call.

Where the data comes from (docs/specs/pages/codex-harness.md, fact 30): each thread has
one rollout file under `$CODEX_HOME/sessions/<yyyy>/<mm>/<dd>/`, or under
`~/.codex/sessions/` when `CODEX_HOME` is not set. The `session_meta` line names the
thread (`id`), its root (`session_id`), its `parent_thread_id` (absent on the root), its
`cwd`, `agent_role`, and `agent_path`. Each model call adds an `event_msg` line whose
payload type is `token_count`. The entry format is internal to Codex and can change, so
the parser skips any line or shape it does not know.

The totals of a thread are the cumulative `total_token_usage` of its last `token_count`
event. A model call is a `token_count` event whose totals differ from the event before
it: Codex also writes events that only refresh the quota.

The quota share is the part of the weekly quota that the run used. It reads the
`rate_limits.primary` window of the root threads. `used_percent` covers the whole
account, so a root thread already shows the quota that its subagents use.
"""

import argparse
import collections
import datetime
import glob
import json
import os
import sys

# In real rollouts `resets_at` moves by 1 to 3 s inside one window. Only a move above
# 3600 s starts a new window.
WINDOW_TOLERANCE_S = 3600
TOTAL_FIELDS = (
    ("input", "input_tokens"),
    ("cached_input", "cached_input_tokens"),
    ("output", "output_tokens"),
    ("reasoning", "reasoning_output_tokens"),
)
COUNT_FIELDS = ("calls",) + tuple(name for name, _ in TOTAL_FIELDS)


def parse_time(text):
    """Return an aware datetime for an ISO 8601 string, or None when it does not parse."""
    if not isinstance(text, str):
        return None
    try:
        value = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value


def read_jsonl(path):
    """Return the JSON objects in `path` and the count of lines that do not parse."""
    entries, skipped = [], 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if isinstance(entry, dict):
                entries.append(entry)
            else:
                skipped += 1
    return entries, skipped


def quota_sample(event):
    """Return (used_percent, resets_at) of one `token_count` payload, or None without a quota."""
    limits = event.get("rate_limits")
    primary = limits.get("primary") if isinstance(limits, dict) else None
    if not isinstance(primary, dict):
        return None
    used, resets = primary.get("used_percent"), primary.get("resets_at")
    if not isinstance(used, (int, float)) or not isinstance(resets, (int, float)):
        return None
    return used, resets


def quota_share(samples):
    """Return the quota share of `samples`, a time-ordered list of (used_percent, resets_at).

    The first window counts from its first sample. A later window counts from 0, because
    the quota starts again at 0 when the window resets. A fall inside one window counts 0.
    Return None when there are no samples.
    """
    if not samples:
        return None
    windows = [[samples[0], samples[0]]]
    for previous, current in zip(samples, samples[1:]):
        if abs(current[1] - previous[1]) > WINDOW_TOLERANCE_S:
            windows.append([current, current])
        else:
            windows[-1][1] = current
    share = max(0, windows[0][1][0] - windows[0][0][0])
    for _, last in windows[1:]:
        share += max(0, last[0])
    return share


def last_token_count(path, max_bytes=None):
    """Return the payload of the last `token_count` event in `path`, or None when there is none.

    With `max_bytes`, read only that many bytes from the end of the file.
    """
    with open(path, "rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        start = 0 if max_bytes is None else max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0:
        # The window can begin inside a line.
        lines = lines[1:]
    for line in reversed(lines):
        # Skip the cost of a parse for the many lines that are not token counts.
        if '"token_count"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload")
        if entry.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
            return payload
    return None


def read_rollout(path):
    """Return the summary of one rollout file.

    Keys: path, id, session_id, cwd, role, agent_path, model, calls, input, cached_input,
    output, reasoning, samples [(time, used_percent, resets_at)], last_time, skipped.
    """
    records, skipped = read_jsonl(path)
    row = {"path": str(path), "id": None, "session_id": None, "cwd": None, "role": "root",
           "agent_path": None, "model": None, "samples": [], "last_time": None,
           "skipped": skipped, "calls": 0, **{name: 0 for name, _ in TOTAL_FIELDS}}
    previous = None
    for record in records:
        stamp = parse_time(record.get("timestamp"))
        if stamp is not None and (row["last_time"] is None or stamp > row["last_time"]):
            row["last_time"] = stamp
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "session_meta" and row["id"] is None:
            row.update(id=payload.get("id"), session_id=payload.get("session_id") or payload.get("id"),
                       cwd=payload.get("cwd"), agent_path=payload.get("agent_path"))
            if payload.get("parent_thread_id"):
                row["role"] = payload.get("agent_role") or "unknown"
        elif record.get("type") == "turn_context" and payload.get("model"):
            row["model"] = payload["model"]
        elif record.get("type") == "event_msg" and payload.get("type") == "token_count":
            sample = quota_sample(payload)
            if sample is not None:
                row["samples"].append((stamp, *sample))
            info = payload.get("info")
            totals = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(totals, dict):
                continue
            if totals != previous:
                row["calls"] += 1
                previous = totals
            for name, key in TOTAL_FIELDS:
                row[name] = totals.get(key) or 0
    return row


def sessions_root():
    """Return the directory of the rollout files."""
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "sessions")


class SelectionError(Exception):
    """The arguments select no rollout."""


def find_rollouts(args, since):
    """Return the summaries of the rollouts the arguments select; raise SelectionError when none match."""
    if not args.session and not args.cwd:
        raise SelectionError("usage.py: give --session, or --cwd with --since")
    root = sessions_root()
    paths = sorted(glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True))
    cwd = os.path.realpath(args.cwd) if args.cwd else None
    selected = []
    for path in paths:
        rollout = read_rollout(path)
        if args.session and args.session not in (rollout["id"], rollout["session_id"]):
            continue
        if cwd and (not rollout["cwd"] or os.path.realpath(rollout["cwd"]) != cwd):
            continue
        if since is not None and (rollout["last_time"] is None or rollout["last_time"] < since):
            continue
        selected.append(rollout)
    if not selected:
        raise SelectionError(f"usage.py: no rollout matches under {root}")
    return selected


def sum_counts(rows):
    return {field: sum(row[field] for row in rows) for field in COUNT_FIELDS}


def build_report(rollouts, since=None):
    """Return the usage report for `rollouts`.

    The shape is the `--json` contract:
    {threads: [{role, agent_path, id, model, calls, input, cached_input, output, reasoning}],
     by_role: [{role, threads, calls, input, cached_input, output, reasoning}],
     totals: {threads, calls, input, cached_input, output, reasoning, skipped_lines},
     quota: {share}}
    `since` limits the quota samples. The thread totals stay cumulative.
    """
    ordered = sorted(rollouts, key=lambda r: (r["role"] != "root", str(r["agent_path"]), str(r["id"])))
    threads = [{"role": r["role"], "agent_path": r["agent_path"], "id": r["id"], "model": r["model"],
                **{field: r[field] for field in COUNT_FIELDS}} for r in ordered]
    groups = collections.OrderedDict()
    for thread in threads:
        groups.setdefault(thread["role"], []).append(thread)
    by_role = [{"role": role, "threads": len(rows), **sum_counts(rows)} for role, rows in groups.items()]
    totals = {"threads": len(threads), **sum_counts(threads), "skipped_lines": sum(r["skipped"] for r in rollouts)}
    samples = sorted(
        (s for r in rollouts if r["role"] == "root" for s in r["samples"]
         if since is None or (s[0] is not None and s[0] >= since)),
        key=lambda s: (s[0] is None, s[0]),
    )
    return {"threads": threads, "by_role": by_role, "totals": totals,
            "quota": {"share": quota_share([(used, resets) for _, used, resets in samples])}}


def format_table(report):
    """Return the report as a plain-text table."""
    headers = ["role", "agent_path", "model", "calls", "input", "cached_input", "output", "reasoning"]
    lines = [headers]
    for thread in report["threads"]:
        lines.append([thread["role"], thread["agent_path"] or "", thread["model"] or ""]
                     + [thread[f] for f in COUNT_FIELDS])
    lines.append([""] * len(headers))
    for group in report["by_role"]:
        lines.append([group["role"], f"{group['threads']} thread(s)", ""] + [group[f] for f in COUNT_FIELDS])
    totals = report["totals"]
    lines.append(["TOTAL", "", ""] + [totals[f] for f in COUNT_FIELDS])
    cells = [[str(cell) for cell in line] for line in lines]
    widths = [max(len(line[i]) for line in cells) for i in range(len(headers))]
    out = []
    for line in cells:
        out.append("  ".join(
            cell.rjust(widths[i]) if i >= 3 else cell.ljust(widths[i])
            for i, cell in enumerate(line)
        ).rstrip())
    out.append("")
    share = report["quota"]["share"]
    out.append("quota: no quota data" if share is None else f"quota: {share:g}% of the weekly quota")
    if totals["skipped_lines"]:
        out.append(f"Skipped {totals['skipped_lines']} line(s) that are not JSON.")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report tokens and quota share per thread.")
    parser.add_argument("--session", help="a session ID: matches `session_id` or `id` of the rollout")
    parser.add_argument("--cwd", help="select the rollouts of this working directory")
    parser.add_argument("--since", help="select rollouts with an event at or after this ISO 8601 time")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    since = None
    if args.since:
        since = parse_time(args.since)
        if since is None:
            parser.error(f"--since is not an ISO 8601 time: {args.since}")
    try:
        rollouts = find_rollouts(args, since)
    except SelectionError as error:
        print(error, file=sys.stderr)
        return 2
    report = build_report(rollouts, since)
    print(json.dumps(report) if args.json else format_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
