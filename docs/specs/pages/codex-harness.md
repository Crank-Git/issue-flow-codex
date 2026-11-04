---
id: codex-harness
title: Codex harness facts
---

# Codex harness facts

This page records each Codex fact that the port depends on, with its evidence. The
target is Codex CLI 0.166.0. Source references point into `openai/codex` at commit
`dbaead01` (2026-11-03), under `codex-rs/`. Doc pages redirect from
`developers.openai.com/codex/` to `learn.chatgpt.com/docs/`.

Evidence tags:

- **live** — measured on 2026-11-03 with `codex exec` on codex-cli 0.166.0, in an isolated `CODEX_HOME`, model `gpt-6-luna`.
- **src** — read in the source.
- **help** — CLI `--help` output.
- **doc** — the official documentation.

## How upstream primitives map to Codex

| Upstream (Claude Code) | Codex | Evidence |
|---|---|---|
| `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` (Codex also reads `.claude-plugin/plugin.json`) | src `core-plugins/src/manifest.rs`, `exec-server-protocol/src/protocol.rs:55-59` |
| `/skill-name` | `$issue-flow:skill-name` | live: skill listed as `spikeplug:ping` |
| `${CLAUDE_PLUGIN_ROOT}` in hooks | `$PLUGIN_ROOT` (also `$CLAUDE_PLUGIN_ROOT`) | live |
| `${CLAUDE_PLUGIN_ROOT}` in skills | none; the model gets the absolute `SKILL.md` path | src `ext/skills/src/catalog_prompt.rs:4,28-29` |
| `agents/*.md` in the plugin | role TOML in `.codex/agents/`; a plugin cannot ship roles | src `core-plugins/src/manifest.rs:48-117` |
| `Agent` tool, background | `spawn_agent` (V2) | live |
| completion notification | `wait_agent`, then a queued `FINAL_ANSWER` message | live |
| `SendMessage` to a worker | `followup_task` (starts a turn), `send_message` (queues only) | src `tools/handlers/multi_agents_spec.rs:204-263` |
| `isolation: "worktree"` | none; the PM runs `scripts/worktree.py` | src `tools/handlers/multi_agents/spawn.rs:134` |
| `subagent_type: "fork"` | `fork_turns: "all"` (the default) | src `multi_agents_spec.rs:665-668` |
| `model: sonnet` on an agent | `model = "..."` in the role file | src `core/src/agent/role.rs:79-117` |
| `tools:` list on an agent | none; the role guard hook | src `role.rs:79-117` |
| `Bash run_in_background` + notify | none; a watcher subagent | src `core/src/unified_exec/async_watcher.rs:155-160` |
| `AskUserQuestion` | plain-text question, end the turn | src `tools/src/tool_config.rs:6-15` |
| `PushNotification` | none | help: no such tool |
| `Workflow` tool | none; spawn and wait | help: no such tool |
| `CLAUDE.md` | `AGENTS.md` (32 KiB total cap) | src `core/src/agents_md.rs`, `config/src/config_toml.rs:77` |
| `.claude/rules/*.md` with `paths:` | nested `AGENTS.md`, or `docs/rules/` read on instruction | doc agents-md |
| `.claude/settings.json` allow-list | permission profile | live |

## Facts measured live

1. **Plugin skills load with a namespace.** A plugin `spikeplug` with skill `ping` appears as `spikeplug:ping`.
2. **Plugin hooks load in the CLI.** A `.codex-plugin/plugin.json` plugin's SessionStart hook ran with `PLUGIN_ROOT` set to the install cache path. Its `additionalContext` reached the model.
3. **`codex exec` skips an untrusted plugin hook without a message.** The hook log stayed empty until the run added `--dangerously-bypass-hook-trust`.
4. **V2 spawn of a custom role works in `codex exec`.** Two `echo_worker` subagents with `fork_turns: "none"` returned their JSON, and the parent printed both.
5. **V2 tool names.** The parent had `spawn_agent`, `followup_task`, `send_message`, `interrupt_agent`, `list_agents`, and `wait_agent`. It had no `close_agent`.
6. **Hook name of a V2 spawn.** PreToolUse got `tool_name: "collaborationspawn_agent"` and `tool_input.agent_type: "echo_worker"`. The `Agent` alias does not match it. The matcher `spawn_agent$` matches it.
7. **Default `workspace-write` blocks git writes and network.** `git worktree add` failed: `cannot lock ref 'refs/heads/t1' ... Operation not permitted`. `git ls-remote` failed: `Could not resolve host: github.com`.
8. **A permission profile allows them.** With the profile below, `git worktree add`, `git commit`, and `git ls-remote https://github.com/openai/codex HEAD` all exited 0.
9. **Subagents inherit the profile.** A `git_worker` subagent created `.worktrees/t2` and committed.
10. **Hooks fire inside a subagent with its role.** PreToolUse for the subagent's `Bash` calls had `agent_type: "git_worker"` and an `agent_id`.
11. **`codex exec` has no `-a` flag**, and it waits for stdin unless stdin is closed. Use `-c approval_policy="never"` and `</dev/null`.
12. **A root TOML key after a table header fails.** `default_permissions` placed after `[permissions.gitw]` gave: "config defines `[permissions]` profiles but does not set `default_permissions`".
13. **The spawn message is encrypted in the hook payload.** PreToolUse for a V2 spawn had `tool_input` keys `task_name`, `fork_turns`, and `message`, plus `agent_type` only when the model set a role. `message` was a token that starts `gAAAAA`, also when the model sent a plain multi-line text. The session rollout file holds the same token. Evidence: two `gpt-6-luna` runs, codex-cli 0.166.0, 2026-11-03; payload in `tests/fixtures/hooks/pre_tool_use_spawn.json`.
14. **`updatedInput` from a PreToolUse hook changes a `wait_agent` call.** PreToolUse got `tool_name: "collaborationwait_agent"` and `tool_input: {"timeout_ms": 10000}`. The hook answered `permissionDecision: "allow"` with `updatedInput: {"timeout_ms": 40000}`. A subagent that ran `sleep 20` finished inside that one wait: the call returned `timed_out: false` about 22 s after it started, and the model's recorded arguments still read 10000. Evidence: one `gpt-6-luna` run, codex-cli 0.166.0, 2026-11-03, isolated `CODEX_HOME`; payload in `tests/fixtures/hooks/pre_tool_use_wait.json`.
15. **PostToolUse reports wait timeouts.** The hook payload has `tool_name: "collaborationwait_agent"`, and `tool_response` is a JSON string with `timed_out`. The hook environment includes `PLUGIN_DATA`. Evidence: one `gpt-6-luna` run, codex-cli 0.166.0, 2026-11-03, isolated `CODEX_HOME`; payloads in `tests/fixtures/hooks/post_tool_use_wait_timeout.json` and `post_tool_use_wait_complete.json`. Source: `hooks/src/engine/discovery.rs:312-320`.
16. **A worker cannot run nested `codex exec` probes.** In the first dogfood run (2026-11-03), a `gpt-6-luna` worker inside the `issue_flow` permission profile ran a nested `codex exec` probe. The PostToolUse payload capture worked, but macOS denied the nested sandbox's shell commands. Live Codex proofs therefore run from the gate harness (`tests/e2e/run_loop.py`) outside the worker sandbox.
17. **`PLUGIN_DATA` is not pre-created.** Codex sets the variable for plugin hooks and does not create the directory (`codex-rs core-plugins/src/store.rs:27,122`). A hook that writes there creates it first.
18. **The Bash PostToolUse `tool_response` is the raw command output.** It is a string with no exit-code header and no exit-code field. A failed command has no marker. A command that never ran shows `sandbox-exec: sandbox_apply: Operation not permitted`. Evidence: 98 payloads from the #75 gate run (Codex 0.166.0, `gpt-6-luna`), sanitized in `tests/fixtures/hooks/gate75_pm_sequence.json`. Source: `codex-rs core/src/tools/context.rs:483-490`.
19. **Subagent hook payloads share the PM's `session_id`.** They differ by `agent_id` and `agent_type`. A hook that keeps per-session state must ignore every payload with an `agent_id`, or a worker's calls change the PM's state. Same evidence as item 18.
20. **Gitea MCP tools appear as `mcp__<server>__<tool>`.** The PostToolUse matcher `^mcp__.+__list_(issues|pull_requests)$` selects the list calls. The gate run had no MCP server, so this name shape is not yet recorded from a live run.
21. **A spawned worker's `apply_patch` payload names the PM's project root as `cwd`.** The payload has no `workdir` and no `task_name`, only `agent_id` and `agent_type`. A relative path in the patch resolves against that `cwd`, so it lands in the PM's checkout. A role guard can enforce the `.worktrees/` boundary, but it cannot tell a worker's own tree from a sibling's. Evidence: the #111 gate run (Codex 0.166.0, `gpt-6-luna`); payloads in `tests/fixtures/hooks/apply_patch_outside_worktree.json` and `apply_patch_inside_worktree.json`.

The profile used in facts 8 and 9:

```toml
default_permissions = "gitw"

[permissions.gitw]
extends = ":workspace"

[permissions.gitw.filesystem.":workspace_roots"]
"." = "write"
".git" = "write"
".agents" = "write"

[permissions.gitw.network]
enabled = true
```

## Facts from source, not yet measured

- **No wake on idle.** When the PM's turn has ended, a subagent's result is only queued. A new PM turn starts only when `features.wake_on_agent_messages` is on, and that feature is under development. Source: `core/src/session/handlers.rs:89-99`, `features/src/lib.rs:1671-1675`. Port rule: the PM ends its turn only when the loop stops.
- **Thread cap.** `[features.multi_agent_v2] max_concurrent_threads_per_session`, default 4, includes the root thread. Source: `core/src/config/mod.rs:261,1716-1725`. Idle V2 subagents are unloaded to free slots and keep their state. Source: `core/src/agent/control/residency.rs`.
- **V2 is the default for current models.** The model catalog sets `multi_agent_version = v2` for `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-luna`, and others. Source: `codex debug models --bundled`; `core/src/config/mod.rs:1687-1714`.
- **Full forks cannot change the model.** Source: `prompts/src/multi_agent_instructions.rs:10`.
- **Role files.** Codex applies only `developer_instructions`, the model keys, `personality`, `service_tier`, and feature or skill disables. It ignores `sandbox_mode`, `approval_policy`, and `mcp_servers`. Source: `core/src/agent/role.rs:79-117`.
- **Hook trust is pinned to the whole plugin's content hash.** Any plugin update makes the hooks `Modified` until the operator trusts them again. Source: `hooks/src/engine/plugin_trust.rs:28-69`.
- **The Agent Plugin format loads no hooks.** A root `plugin.json` with an `agent-plugins.org` `$schema` gets no hooks. Source: `core-plugins/src/loader.rs:985-988`.
- **Background processes do not notify the model on exit.** Source: `core/src/unified_exec/async_watcher.rs:155-160`. The default background timeout is 300 s. Source: `core/src/unified_exec/mod.rs:66-75`.
- **Compaction.** After compaction, Codex queues SessionStart with `source = "compact"`. Source: `core/src/session/mod.rs:4783`.

## Known Codex issues that touch the port

| Issue | Effect on the port | Port response |
|---|---|---|
| openai/codex #46120 | No wake on subagent completion while idle. | The PM keeps its turn open with `wait_agent`. |
| openai/codex #45343, #47592 | Delegated tasks lost or repeated after compaction. | Recovery from the tracker and `list_agents` (Feature 03). |
| openai/codex #38247 | Finished V2 subagents keep MCP processes alive. | The review PM stops server processes at the end of a run. |
| openai/codex #58898 | Large quota use in multi-agent runs. | Lower-tier helper models; the run configuration shows the models. |
| openai/codex #58291 | Oversized requests from inherited history. | `fork_turns: "none"` on every spawn. |
| openai/codex #40130 | Roles cannot set sandbox, approvals, or MCP. | One profile for the session; the role guard. |

## Documentation and source disagreements

- The plugin docs say plugin lifecycle hooks "work only for plugins installed manually in Codex desktop". Fact 2 shows them running in the CLI.
- The docs call the root `plugin.json` "the portable entry point". It loads no hooks, so the port uses `.codex-plugin/plugin.json`.
