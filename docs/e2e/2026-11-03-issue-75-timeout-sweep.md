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
