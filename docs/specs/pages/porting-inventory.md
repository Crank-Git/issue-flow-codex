---
id: porting-inventory
title: Porting inventory
---

# Porting inventory

This page maps each upstream file at `issue-flow--v0.17.0` to its port mode. The
initial `upstream.lock` takes its modes from this table (FR-foundation-6). Line counts
are upstream counts. The column "Feature" names the feature file that ports the file.

Upstream total: 39 files, 10,343 lines.

| Mode | Files | Lines |
|---|---|---|
| verbatim | 4 | 1,476 |
| patched | 22 | 4,100 |
| rewritten | 12 | 4,503 |
| dropped | 1 | 264 |

`patched` means a few path, name, or tool-name edits. `rewritten` means whole sections
change. The table below names the sections.

## Plugin, hooks, scripts

| Upstream path | Lines | Mode | What changes | Feature |
|---|---|---|---|---|
| `.claude-plugin/plugin.json` | 25 | rewritten | Becomes `.codex-plugin/plugin.json`. | 01 |
| `hooks/hooks.json` | 26 | rewritten | Codex events, `$PLUGIN_ROOT`, matcher `spawn_agent$`, role guard entry. | 01 |
| `hooks/preflight.py` | 333 | patched | Output wrapper, `source` line, `ran` line. The digest logic stays. | 01, 03 |
| `hooks/guard-spawn.py` | 262 | rewritten | V2 spawn shapes: `fork_turns`, `agent_type`. The brief detection stays. | 01 |
| `scripts/peers.py` | 264 | dropped | Reads Claude Code agent-team files that Codex does not have. | 01 |
| `scripts/state_cas.py` | 225 | patched | Docstring paths. | 00 |
| `scripts/verify_ci_ran.py` | 155 | patched | Docstring paths. | 00 |
| `scripts/verify_claim.py` | 110 | patched | Docstring paths. | 00 |
| `scripts/gitea-ci-watch.sh` | 83 | patched | Comment about `run_in_background`; called by `ci_wait.py`. | 03 |

## Shared references

| Upstream path | Lines | Mode | What changes | Feature |
|---|---|---|---|---|
| `references/forge.md` | 591 | rewritten | The CI-watch and background-shell section (about lines 320-425). The forge operation table stays. | 03 |
| `references/ste.md` | 263 | patched | The artifact table names `AGENTS.md` and `docs/rules/`. | 04 |
| `references/external-apis.md` | 116 | patched | `codex mcp list`; no `ToolSearch`. | 04 |
| `references/finding-policy.md` | 205 | verbatim | none | — |

## Roles

| Upstream path | Lines | Mode | What changes | Feature |
|---|---|---|---|---|
| `agents/issue-worker.md` | 690 | rewritten | Front-matter becomes `roles/issue-worker.toml`. Rewrite: the toolbox section, the four spawn rules (lines 162-236), the worktree boundary (lines 237-350), and the CI watch in the runbook. | 02 |
| `agents/review-scribe.md` | 174 | patched | Becomes a role file; worktree from the PM. | 05 |
| `agents/ux-explorer.md` | 140 | patched | Becomes a role file; Playwright tool names. | 05 |
| `agents/deploy-verifier.md` | 75 | patched | Becomes a role file; Playwright tool names. | 05 |
| `agents/code-auditor.md` | 87 | patched | Becomes a role file. | 05 |
| — | — | new | `roles/ci-watcher.toml`. | 03 |

Each upstream `agents/*.md` file stays in the repository as the instruction source.
A build step in `scripts/build_roles.py` writes `roles/*.toml` from it, so a sync of
the markdown reaches the TOML.

## issue-flow skill

| Upstream path | Lines | Mode | What changes | Feature |
|---|---|---|---|---|
| `skills/issue-flow/SKILL.md` | 1023 | rewritten | Two roles (31-56), core invariants (88-122), Phase 0 (123-321), Stage B launch (about 590-620), Stage C notification and messaging (621-786), Stage E status (870-897), hard rules (995-1023). | 02, 03 |
| `skills/issue-flow/references/worktrees.md` | 387 | rewritten | Everything except teardown and parked worktrees (276-359). | 02 |
| `skills/issue-flow/references/parallelism.md` | 309 | rewritten | The one rule (8-26), what is safe (27-42), specialist reviewers and the Workflow example (171-263). | 02 |
| `skills/issue-flow/references/issue-worker.md` | 187 | rewritten | The spawn call (1-30) and messaging (110-187). | 02 |
| `skills/issue-flow/references/batching.md` | 280 | patched | Worktree paths; `followup_task`. | 02 |
| `skills/issue-flow/references/collaboration.md` | 157 | patched | `followup_task` for worker messages. | 03 |
| `skills/issue-flow/references/deploy.md` | 226 | patched | Watcher subagent; `codex mcp`. | 03 |
| `skills/issue-flow/references/session-config.md` | 320 | patched | Plain-text questions; the `codex` block. | 03 |
| `skills/issue-flow/references/labels.md` | 155 | verbatim | none | — |
| `skills/issue-flow/references/spec-maintenance.md` | 115 | patched | `AGENTS.md`; `$issue-flow:` names. | 04 |

## Other skills

| Upstream path | Lines | Mode | What changes | Feature |
|---|---|---|---|---|
| `skills/project-planner/SKILL.md` | 286 | rewritten | Phase 3 scaffold gate (165-176) and the checklist (266-285). | 04 |
| `skills/project-planner/references/scaffold.md` | 401 | rewritten | `AGENTS.md`, `docs/rules/`, `.agents/skills/`, `.codex/hooks.json`, dual-harness mode, `.gitignore`. | 04 |
| `skills/project-planner/references/spec-format.md` | 250 | patched | `docs/rules/quality.md`; `AGENTS.md`. | 04 |
| `skills/project-planner/scripts/render-spec.py` | 1045 | verbatim | none | — |
| `skills/project-inherit/SKILL.md` | 192 | patched | Explorer subagents; scaffold follows `scaffold.md`. | 04 |
| `skills/spec-update/SKILL.md` | 116 | patched | Plain-text questions; paths. | 04 |
| `skills/spec-to-issues/SKILL.md` | 184 | patched | Plain-text questions; `$issue-flow:` names. | 04 |
| `skills/project-review/SKILL.md` | 316 | rewritten | Two roles (35-74), the browser check (79-90), scribe messaging (213-254). | 05 |
| `skills/repo-mirror/SKILL.md` | 293 | patched | New exclusions. | 06 |
| `skills/repo-mirror/scripts/mirror_filter.py` | 206 | patched | New default exclusions. | 06 |
| `skills/repo-mirror/templates/mirror.yml` | 71 | verbatim | none | — |

## Port-only files

| Path | Purpose | Feature |
|---|---|---|
| `upstream.lock` | Upstream tag and file modes. | 00 |
| `scripts/upstream_sync.py` | Import, check, and sync. | 00, 06 |
| `scripts/conformance.py` | Live harness checks. | 00 |
| `scripts/testbed-reset.py` | Test bed reset. | 00 |
| `scripts/validate_manifests.py` | Manifest, skill, and role checks. Ported from the upstream repository's own `scripts/validate-manifests.py`. | 01 |
| `scripts/worktree.py` | Worktree create and remove. | 02 |
| `scripts/ci_wait.py`, `scripts/deploy_wait.py` | Bounded CI and deployment polls. | 03 |
| `scripts/build_roles.py` | Role TOML from the upstream agent markdown. | 02, 05 |
| `skills/setup/SKILL.md` | The setup skill. | 01 |
| `hooks/guard-role.py`, `hooks/role-policy.json` | The role guard. | 01 |
| `.agents/plugins/marketplace.json` | The Codex marketplace. | 01 |
