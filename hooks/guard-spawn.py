#!/usr/bin/env python3
"""PreToolUse guard: refuse a spawn that inherits the PM session, has no plugin role, or breaks a spawn limit.

Wired by `hooks/hooks.json` with the matcher `spawn_agent$`. Codex sends a V2 spawn to
this hook with a `tool_name` that ends in `spawn_agent` (live: `collaborationspawn_agent`)
and a `tool_input` with `task_name`, `fork_turns`, `message`, and `agent_type` (only when set).

Two rules apply to every spawn, both on readable fields:

1. Deny a spawn whose `fork_turns` is not `"none"`. An omitted `fork_turns` means `"all"`.
   A subagent then inherits the whole PM session, and nothing in that session tells it to
   stop after one issue. Upstream measured a fork that ran the PM loop for 52 minutes and
   merged to `dev` with no PM gate. The inherited history also inflates every request
   (openai/codex #58291).
2. Deny a spawn whose `task_name` is a worker name (`worker_<n>`, `worker_<n>_c1`, `worker_<n>_c2`,
   `worker_<n>_e1`, or `worker_<n>_e1_c1`; FR-worker-dispatch-10 and -11) unless `agent_type` is `issue_worker`. Without the role,
   the role guard and the role's model do not apply.

A payload with no `agent_id` is a PM spawn (codex-harness fact 19). A PM spawn also meets
the limits of docs/specs/features/07-spawn-limits.md: a role allowlist, a `task_name` pattern
for each role, no reused name, and no gap in a worker chain or a fix chain. `hooks/spawn_state.py` keeps the
names of the session in `$PLUGIN_DATA`. Without `PLUGIN_DATA`, the reuse and chain rules
do not apply.

The run budget (docs/specs/features/09-run-budget.md) is a further PM rule. With `runBudgetPercent`
set in `.issue-flow.codex.json`, the guard denies `issue_worker` and `explorer` spawns once the
run share of the weekly quota reaches it. It reads the last 1 MiB of the `transcript_path` rollout
and keeps samples in `hooks/budget_state.py`.

The guard never reads `message`. Upstream detected a handoff brief by its field labels in
the prompt, but live Codex 0.166.0 delivers `tool_input.message` to the hook as an encrypted
token (docs/specs/pages/codex-harness.md, fact 13), so a label match cannot fire.

Fail open: a parse error, a non-object payload, or a non-object `tool_input` exits 0 with
no output. A state file that cannot be written allows the spawn and prints one line to
stderr. A guard against a runaway worker must never be the reason work cannot start.
Codex rejects an `ask` decision, so the guard only denies.

`ISSUE_FLOW_SPAWN_GUARD=off` disables the guard. Hooks read the environment at session
start, so set it before the session starts.
"""

import json
import os
import re
import sys
from pathlib import Path

from budget_state import record_sample
from spawn_state import read_names, record, state_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import usage  # noqa: E402

WORKER_NAME = re.compile(r"worker_\d+(_c\d+)?")

# Each pattern is a full match. `<n>`, `<pr>` and `<k>` are decimal, `<sha7>` is 7 hex digits.
ROLE_PATTERNS = {
    "issue_worker": (r"worker_\d+(_c1|_c2|_e1|_e1_c1)?|fix_\d+(_[2-9]|_[1-9]\d+)?",
                     "worker_<n>, worker_<n>_c1, worker_<n>_c2, worker_<n>_e1, worker_<n>_e1_c1, "
                     "fix_<n>, fix_<n>_<k>"),
    "criteria_checker": (r"check_\d+(_[234])?", "check_<n>, check_<n>_2, check_<n>_3, check_<n>_4"),
    "ci_watcher": (r"(ci_\d+|deploy_[0-9a-f]{7}|suite_\d+)(_r2)?",
                   "ci_<pr>, ci_<pr>_r2, deploy_<sha7>, deploy_<sha7>_r2, suite_<n>, suite_<n>_r2"),
    "deploy_verifier": (r"verify_deploy_[0-9a-f]{7}", "verify_deploy_<sha7>"),
    "explorer": (r"(locate_\d+_\d+|docs_\d+|crosscheck_\d+|batchreview_\d+|survey_\d+|deploylog_[0-9a-f]{7})",
                 "locate_<n>_<k>, docs_<n>, crosscheck_<n>, batchreview_<n>, survey_<k>, deploylog_<sha7>"),
    "code_auditor": (r"code_auditor", "code_auditor"),
    "ux_explorer": (r"ux_[a-z0-9_]+", "ux_<slug>"),
    "review_scribe": (r"review_scribe(_\d+|_[a-z0-9-]+)?",
                      "review_scribe, review_scribe_<k>, review_scribe_<slug>"),
}

# FR-run-budget-25: the budget stops new work. The gate roles stay free so that live work can finish.
BUDGET_ROLES = {"issue_worker", "explorer"}
TAIL_BYTES = 1 << 20

# FR-spawn-limits-12: a worker name needs a spawn of its predecessor.
WORKER_PARTS = re.compile(r"(worker_\d+)(_c1|_c2|_e1_c1|_e1)?")
WORKER_PREDECESSOR = {"_c1": "", "_e1": "", "_c2": "_c1", "_e1_c1": "_e1"}
# The fix chain of the batch gate: `fix_<n>_2` needs `fix_<n>`, `fix_<n>_<k>` needs `fix_<n>_<k-1>`.
FIX_PARTS = re.compile(r"(fix_\d+)(?:_(\d+))?")

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

ALLOWLIST_REASON = (
    "issue-flow spawn guard: agent_type AGENT_TYPE is not a plugin role (task_name TASK_NAME). "
    "Allowed agent_type values: " + ", ".join(ROLE_PATTERNS) + ". Call spawn_agent again "
    "with one of them."
)

PATTERN_REASON = (
    "issue-flow spawn guard: task_name TASK_NAME does not match agent_type AGENT_TYPE. "
    "Allowed patterns: PATTERNS."
)

CAP_NOTE = (
    " One issue uses at most five workers. Label the issue status:blocked and comment with "
    "the chain of remaining notes."
)

REUSE_REASON = (
    "issue-flow spawn guard: task_name TASK_NAME was used by an earlier spawn in this session "
    "(agent_type AGENT_TYPE). Allowed patterns: PATTERNS. Use the next name of the chain."
)

CHAIN_REASON = (
    "issue-flow spawn guard: task_name TASK_NAME needs an earlier spawn of PREDECESSOR in "
    "this session (agent_type AGENT_TYPE). Allowed patterns: PATTERNS."
)

BUDGET_REASON = (
    "issue-flow spawn guard: this run used SHARE% of the weekly quota. The run budget is BUDGET%. "
    "Launch no new work. Drain the run: gate each live worker, post the status digest, park the "
    "open issues, and end the turn."
)


def fill(template, task_name, agent_type, patterns="", predecessor=""):
    """Return `template` with its placeholders replaced."""
    return (template.replace("TASK_NAME", str(task_name)).replace("AGENT_TYPE", agent_type)
            .replace("PATTERNS", patterns).replace("PREDECESSOR", predecessor))


def chain_predecessor(task_name):
    """Return the name that must be spawned before `task_name`, or "" when it starts a chain."""
    fix = FIX_PARTS.fullmatch(task_name)
    if fix:
        step = int(fix.group(2) or 1)
        return "" if step == 1 else fix.group(1) if step == 2 else f"{fix.group(1)}_{step - 1}"
    parts = WORKER_PARTS.fullmatch(task_name)
    return parts.group(1) + WORKER_PREDECESSOR[parts.group(2)] if parts.group(2) else ""


def check_pm_spawn(tool_input, used_names):
    """Return the deny reason for a PM spawn, or None. `used_names` is None without state."""
    task_name = tool_input.get("task_name")
    agent_type = tool_input.get("agent_type")
    shown_type = "omitted" if agent_type is None else json.dumps(agent_type)
    if agent_type not in ROLE_PATTERNS:
        return fill(ALLOWLIST_REASON, task_name, shown_type)
    pattern, patterns = ROLE_PATTERNS[agent_type]
    if not isinstance(task_name, str) or not re.fullmatch(pattern, task_name):
        note = CAP_NOTE if agent_type == "issue_worker" else ""
        return fill(PATTERN_REASON, task_name, shown_type, patterns) + note
    if used_names is None:
        return None
    if task_name in used_names:
        return fill(REUSE_REASON, task_name, shown_type, patterns)
    predecessor = chain_predecessor(task_name) if agent_type == "issue_worker" else ""
    if predecessor and predecessor not in used_names:
        return fill(CHAIN_REASON, task_name, shown_type, patterns, predecessor)
    return None


def budget_percent(cwd):
    """Return `runBudgetPercent` from `.issue-flow.codex.json` in `cwd`, or None when there is no usable budget."""
    try:
        value = json.loads((Path(cwd) / ".issue-flow.codex.json").read_text()).get("runBudgetPercent")
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100:
        return value
    return None


def check_budget(payload, agent_type):
    """Return the budget deny reason for a PM spawn, or None.

    Every PM spawn records the quota sample, also without a budget, so that a budget turned on
    later has a baseline. Any error allows the spawn.
    """
    if state_path(payload.get("session_id"), "budget") is None:
        return None
    try:
        event = usage.last_token_count(payload["transcript_path"], TAIL_BYTES)
    except (OSError, KeyError, TypeError):
        return None
    sample = usage.quota_sample(event) if event else None
    if sample is None:
        return None
    try:
        samples = record_sample(payload["session_id"], sample)
    except OSError as error:
        print(f"issue-flow spawn guard: cannot record the quota sample: {error}", file=sys.stderr)
        return None
    budget = budget_percent(payload.get("cwd", ""))
    share = usage.quota_share(samples)
    if budget is None or agent_type not in BUDGET_ROLES or share < budget:
        return None
    return BUDGET_REASON.replace("SHARE", f"{share:.1f}".removesuffix(".0")).replace("BUDGET", str(budget))


def decide(payload, used_names=None):
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
    if "agent_id" in payload:
        return None
    # The budget rule runs before `record`, so a spawn denied for the budget records no name.
    return check_pm_spawn(tool_input, used_names) or check_budget(payload, agent_type)


def record_allowed(payload):
    """Record the task name of an allowed PM spawn. A write error allows the spawn."""
    tool_input = payload.get("tool_input")
    if (not isinstance(tool_input, dict) or "agent_id" in payload
            or not str(payload.get("tool_name", "")).endswith("spawn_agent")):
        return
    try:
        record(payload.get("session_id"), tool_input.get("task_name"))
    except OSError as error:
        print(f"issue-flow spawn guard: cannot record the spawn: {error}", file=sys.stderr)


def main():
    if os.environ.get("ISSUE_FLOW_SPAWN_GUARD", "").strip().lower() in {"off", "0", "false", "no"}:
        return
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        reason = decide(payload, read_names(payload.get("session_id")))
    except Exception:  # fail open, see the module docstring
        return
    if not reason:
        record_allowed(payload)
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
