# Issue #75 live probe, 2026-11-03

The probe confirmed that `PostToolUse` reports `wait_agent` timeouts. It did not prove five timeout and sweep cycles because Bash commands failed in the nested Codex session.

## Setup

- Codex CLI 0.166.0 used `gpt-6-luna` for the root and child.
- Each model run used an isolated `CODEX_HOME`. Its `auth.json` was a symlink. The operator's `~/.codex` stayed unchanged.
- The isolated config used the `gitw` permission profile from `docs/specs/pages/codex-harness.md`. The profile extends `:workspace`, grants write access to the workspace and `.git`, and enables network access.
- The run used the `Crank-Git/issue-flow-codex` remote repository.

## Attempts

Two setup attempts failed before a model run. The first selected `issue-flow-timeout-probe`, but the local plugin is named `issue-flow-probe`. The second returned `File name too long (os error 63)` because the temporary home was under the worktree. The selector and scratch path were corrected.

| Model run | Result |
|---|---|
| Capture | The run recorded two PostToolUse `collaborationwait_agent` payloads with `timed_out: true`. Bash returned `sandbox-exec: sandbox_apply: Operation not permitted` for `sleep 35` and the Stage A0 list command. |
| Proof | Bash returned `sandbox-exec: sandbox_apply: Operation not permitted` for `sleep 100`. Both waits completed without a timeout. The run produced zero timeout and sweep cycles. |

The capture payloads are in `tests/fixtures/hooks/post_tool_use_wait_timeout.json`, `post_tool_use_wait_complete.json`, and `post_tool_use_bash_stage_a0_denied.json`. The fixtures omit transient paths and encrypted tool messages.

The profile loaded in the isolated config, but the nested shell still failed. The existing conformance harness uses this profile with no sandbox override. The probe did not use `danger-full-access`. One approved model run remains unused.

## Live gate proof, after the hook fix (2026-11-03)

The operator approved one `gpt-6-luna` run (plus one retry for a harness failure, not used). The gate harness ran it from outside the worker sandbox, on Codex 0.166.0, with the plugin installed from `batch/96-loop-corrections` at `ce10557`. PM session `01a1a3c9-aa22-7042-a7bb-15b052fee7ff`, `waitMs` 10000, a slow worker fixture, test bed issue #29.

- `PLUGIN_DATA` is set for plugin hooks: a log-only hook in the installed plugin copy recorded it on all 25 calls (`<CODEX_HOME>/plugins/data/issue-flow-issue-flow-codex`). Codex created the directory when the first timeout landed. A user-level hook gets no value.
- 13 `wait_agent` calls: 11 timed out, 1 was denied, 1 completed.
- **C2 passes.** At 23:42:45.678 the PM called `wait_agent` right after the first timeout, with no list call. The guard denied it at 23:42:45.756 with the reason: "Run forge.issue.list.since and forge.pr.list.since before the next wait_agent call. Use gh issue list and gh pr list, or tea issues and tea pulls." The PM then ran `gh issue list` and `gh pr list` in one command at 23:42:56.461, and the next `wait_agent` at 23:42:59.909 was allowed.
- **C1 passes.** Each of the 11 timeouts was followed by both list calls before the next allowed `wait_agent`. Timeouts 2 to 11 needed no deny.
- The escape hatch did not fire. No port defect was found.

The first gate run (session `01a1a3bb-33e0-7ae1-b9f0-c1cb940b3593`, before the fix) failed both criteria: the state directory was never created, the clear rule expected an `Exit code: 0` header that the live payload does not have, and subagent payloads carry the PM's `session_id`. The fix (D1 to D7 in PR #100) addressed all three.
