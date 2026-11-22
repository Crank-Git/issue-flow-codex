---
id: spend-analysis
title: Quota use of an operator run, November 2026
---

# Quota use of an operator run, November 2026

This page records the measured quota use of one long PM run of port version 0.1.2. The
numbers are the reason for Features 07 to 10. The project of the run is not named here.
Its repository no longer exists, but its Codex rollout files remained on disk.

## How the numbers were measured

A script read each rollout file whose `session_meta.cwd` was the project directory. The
run had one root session and 896 threads. For each thread, the script read:

- `session_meta`: `agent_role`, `agent_path`, `parent_thread_id`, and `session_id`.
- `turn_context.model`.
- the last `event_msg` of type `token_count`: `info.total_token_usage`.
- `rate_limits.primary.used_percent` on each `token_count` event.

Codex version: codex-cli 0.167.1. Plan: ChatGPT Pro. Dates: 2026-11-15 to 2026-11-21.

## Result

The run used 9.9 billion input tokens, 98% of them cached. 145 issues reached a
`ready-to-merge` verdict. The weekly quota went from 0% to 65%, reset on 2026-11-19,
and then went from 0% to 70%. The run used about 1.35 weekly quotas in 5.5 days.

| Thread group | Threads | Model | Share of input tokens |
|---|---|---|---|
| PM (root thread) | 1 | `gpt-6.1-sol` | 37% |
| Workers (`issue_worker`) | 466 | `gpt-6.1-sol` | 36% |
| Other subagents: built-in roles `default`, `worker`, `explorer`, and worker subagents | 429 | `gpt-6.1-sol`, `gpt-6-luna` | 27% |

## Findings

1. **The PM context stayed large.** The PM made 16,805 model calls. The median request
   held 213,000 input tokens. Codex compacted the PM context 50 times. The planner
   interview and five days of the loop ran in the same session.
2. **Most workers ended in `checkpoint`.** 283 of 466 workers returned `checkpoint`. They
   used 1.8 billion input tokens, more than the 148 workers that returned
   `ready-to-merge`. One issue used 17 workers. The `remaining` texts show a phase plan
   that the PM made up: "scratch-only phase", "await core C2", "browser lease", and
   "full six-suite member gate". Each phase ended in a checkpoint.
3. **The checkpoint cap did not stop the chain.** Upstream counts 3 consecutive
   checkpoints and resets the count when the PR shows new commits. Each phase pushed new
   commits, so the count reset each time.
4. **The PM spawned subagents outside the plugin roles.** The PM spawned threads named
   `review_*`, `suite_*`, `audit_*`, `prep_*`, and `batchreview_*` with the built-in
   roles `default`, `worker`, and `explorer`. The spawn guard checks only `worker_*`
   names, so it allowed them. The no-CI fallback `suite_<n>` in the skill has no
   `agent_type`, so it ran on the session model.
5. **The PM ran test suites for each sub-issue.** The batch model runs CI once for each
   batch. The PM ran full local gates for each sub-issue. The operator reported that the
   runs kept the laptop busy for hours, and `.local/` grew to 65 GB.
6. **Encouragement became budget.** The operator wrote "feel free to spread your legs
   here, you have tokens" and, later, "We have a lot oftokens still". The PM then added
   agents. The plugin has no setting that limits the quota of a run.

## What the PM spent its calls on

| Tool | Calls |
|---|---|
| `exec` | 7,010 |
| `send_message` | 2,091 |
| `followup_task` | 1,026 |
| `spawn_agent` | 859 |
| `wait_agent` | 829 |
| `list_agents` | 384 |
