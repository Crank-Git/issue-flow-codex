# 0003 — Run the loop under a permission profile, not full access

Date: 2026-11-03
Status: accepted

## Context

Workers must create worktrees, commit, and push. The default `workspace-write` sandbox keeps `.git` read-only and blocks network access. A live test on Codex 0.166.0 showed both failures. The same test showed that a permission profile with `".git" = "write"` and network enabled allows the three operations, and that subagents inherit the profile. The alternative is `danger-full-access`, which removes the sandbox.

## Decision

The setup skill writes the permission profile `issue_flow`. It extends `:workspace`, makes the project root and `.git` writable, and enables network access. The loop never asks for `danger-full-access`.

## Consequences

- Writes stay inside the project root and the temporary directories.
- Network access is open to every host. A later change can narrow it with the profile's domain list.
- Worktrees must live inside the project root, at `.worktrees/`.
