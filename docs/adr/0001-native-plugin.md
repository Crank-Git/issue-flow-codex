# 0001 — Run the PM inside Codex as a native plugin

Date: 2026-11-03
Status: accepted

## Context

Two designs can run issue-flow on Codex:

- A native plugin. The PM is a Codex skill. It spawns workers with the multi-agent V2 tools.
- An external orchestrator. A Python or TypeScript program is the PM. It starts each worker as a `codex exec --worktree` process.

The external design gives each worker a harness worktree and a process exit as the completion signal. But it moves the PM logic out of the upstream skill text and into code. Each upstream release would then need a code port, not a text port.

A live test on Codex 0.166.0 showed that `wait_agent` returns when a subagent finishes, and that the PM then receives the subagent's final answer. The operator rejected the external design as a workaround.

## Decision

The PM runs inside Codex as the `issue-flow` skill of a native plugin. The PM keeps its turn open with `wait_agent`. The PM creates worktrees with a script.

## Consequences

- The upstream skill text stays the source of truth, so a sync is mostly a text change.
- The PM depends on V2 tool names and behavior. The conformance suite checks them on each Codex release.
- The PM must not end its turn while subagents are live, because Codex does not wake an idle PM.
