# 0005 — Set up Codex once per machine with a user-level profile file

Date: 2026-11-04
Status: accepted

## Context

Before this decision, each project needed `git init`, `$issue-flow:setup`, operator application of the `.codex/` files, and a new session before the first skill could run. The operator ruled on #126 that setup is one time per machine. Live tests on Codex 0.166.0 showed three facts. `codex -p <name>` layers `$CODEX_HOME/<name>.config.toml` on the user config. A role file in `$CODEX_HOME/agents/` loads in a project that has no `.codex/`. A `codex exec -p issue-flow` session with the `issue_flow` profile in that file ran `git init`, a commit, and `git ls-remote` in an empty directory.

## Decision

The setup skill defaults to a user-level mode. `scripts/setup_project.py apply --user` writes `issue-flow.config.toml` and the role files in `agents/` in the Codex home. The file holds `default_permissions = "issue_flow"` and the same `issue_flow` profile as the per-project config block. The script never writes `config.toml` and never sets `approval_policy`. The operator starts each project session with `codex -p issue-flow -a never`. Per-project setup stays available as an option.

## Consequences

- A new project needs no setup step. The operator runs one command per machine, and again after each plugin update.
- The profile grants `.git` writes and network access only to a session that starts with `-p issue-flow`. A plain `codex` session keeps the default sandbox. This is the trade-off: the operator must remember the flag, or the loop runs without the profile and the PM's sandbox probe stops it.
- The approval policy stays a separate `-a never` flag, so the profile file never weakens approvals.
- The user-level mode sets no thread limit and no per-project models. A project that needs them uses per-project setup.
- A legacy `[profiles.issue-flow]` table in `config.toml` makes `-p issue-flow` fail. The operator removes the table.
