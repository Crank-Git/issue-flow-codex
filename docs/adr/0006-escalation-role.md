# 0006 — Escalate through a role of its own

Date: 2026-11-22
Status: accepted

## Context

FR-criteria-check-29 had the PM spawn `issue_worker` with a spawn `model` and `reasoning_effort` to escalate a worker. Probe P14 tested this on codex-cli 0.167.1. It spawned the role `escalation_probe`, whose role file sets `gpt-6-luna`, with spawn `model: "gpt-6.1-sol"` and `reasoning_effort: "high"`. Both turns ran on `gpt-6-luna`. The PreToolUse hook saw both fields. Codex ignored them (codex-harness.md, fact 31).

## Decision

The escalation uses the role `issue_worker_escalated`. `scripts/build_roles.py` builds `roles/issue-worker-escalated.toml` from `agents/issue-worker.md`, with model `gpt-6.1-sol` and effort `high`. `scripts/setup_project.py` applies `escalationModel` and `escalationEffort` to that file, and `workerModel` never reaches it. The role guard gives the new role the policy of `issue_worker`. The spawn guard allows `worker_<n>_e1` and `worker_<n>_e1_c1` only for the new role, and denies `model` and `reasoning_effort` on every worker spawn. The conformance probe P14 spawns a probe role whose file sets the escalation model, and passes when the rollout shows that model.

## Alternatives considered

- **A spawn `model` override.** Codex ignores it when the role file sets a model, so it cannot work.
- **A role file with no `model`.** The spawn model could then apply. The same role file would also serve the normal worker, so a normal spawn could not keep its model, and a role file without a model takes the PM model. This also moves the default model away from the one that setup writes, so it was rejected.

## Consequences

- The escalation model and effort live in a role file. A change to `escalationModel` needs a new setup run, as a change to `workerModel` does.
- The agent instructions stay in one file, `agents/issue-worker.md`. The two role files differ only in name, description, model, and effort.
- The spawn guard counts both roles in the cap of five workers for one issue.
- The run budget stops `issue_worker_escalated` spawns as it stops `issue_worker` spawns.
