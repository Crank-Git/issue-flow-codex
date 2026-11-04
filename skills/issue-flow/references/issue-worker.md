# Working with issue-workers (PM-facing)

The worker's own runbook and limits live in its role file (`roles/issue-worker.toml`,
role `issue_worker`), built from [agents/issue-worker.md](../../../agents/issue-worker.md).
The runbook holds the worker's rules: the worktree boundary, the turn budget, the
verdict. This file does not restate them. This file is the PM's side: how to launch a
worker, what to hand it, and how to react to what it returns.

## Launch

Launch one worker per claimed issue, up to `concurrency` at once (across all live
batches). The steps are in `SKILL.md`, Stage B step 5:

1. Run `python3 <pluginRoot>/scripts/worktree.py create ...`. The script prints the
   worktree `path`.
2. Call `list_agents`. Spawn only when a thread slot is free.
3. Call `spawn_agent` with `task_name: "worker_<n>"`, `agent_type: "issue_worker"`,
   `fork_turns: "none"`, and the brief below as `message`.

The `task_name` is the address of the worker for everything below, for this session
only. The worker's own worktree is what keeps concurrent workers apart.
See [worktrees.md](worktrees.md) for what goes wrong without it.
Sequenced batch members (dependency chains) launch only after their predecessor
sub-merges. When the PM has no other step, it calls `wait_agent` (`SKILL.md`, the
verdict section, owns the rules).

The worker is an **independent engineer** on `gpt-6.1-sol`: it may research (web), use the
MCP servers that the session configures, and spawn its own subagents when a thread slot is free — all
**confined to that issue's worktree** and its own scratch directory,
and all finished before it returns its verdict. The PM sets none of this;
it lives in the worker's agent definition. A worker may also **file new untriaged issues**
for out-of-scope discoveries — but only those that pass the filing gate (behavior, a
user-visible output, a guard that guards nothing, a blocked epic, a maintainer ruling).
Every other discovery it repairs in its own PR, within the files its change already
touches, and reports in `notesForPM` when the repair would reach wider. Filed issues are
picked up by the **next scheduled sweep** (SKILL.md, Stage A0/A: on load, before a merge
gate, or when the ready pool empties) — a routine worker completion does *not* trigger a
full re-triage. `notesForPM` is the exception: read it on every verdict, because a note
the PM never routes is a finding lost.

## Handoff brief (the only thing the PM passes in)

```
issue:        #<number> — <title>
branch:       issue/<number>-<slug>   (the worker checks that the worktree has this branch)
worktree:     <absolute path>         (the `path` that `worktree.py create` printed; the
                                       branch is already checked out in it)
base:         <remote>/epic/<n>-<slug>   (the integration branch; <remote>/<dev> only for standalone/hotfix.
                                       On a re-spawn for rework, pass <remote>/issue/<number>-<slug> —
                                       the branch already has commits and a PR. See Rework below.)
ci:           skip | run               (skip = batch member: draft PR, [skip ci] commits, local checks.
                                        run = standalone/hotfix: normal PR, watch provider CI)
batch:        epic #<n> | batch #<n> | standalone
members:      <count of members in the batch; 1 for standalone/hotfix>
              (how the worker knows whether a crossCheck is owed — never omit it)
crossCheck:   <URL of the batch cross-check comment on the tracking issue>
              (required whenever `members` > 1; `n/a` for standalone/hotfix and for a
               single-member batch — SKILL.md Stage B step 4 skips the check there.
               The worker validates this as its first action and returns `blocked`
               without doing any work if it is absent, empty, "pending", or
               unresolvable — see SKILL.md Stage B step 5.)
remote:       <remote>
forge:        the run configuration's forge block, passed verbatim: {type, host, owner,
              repo, interface}. The worker uses it to pick gh or tea. Never omit it; a worker
              that has to guess the forge is a worker that fails on its first tracker call.
plan:         <the plan the PM already commented on the issue>
conventions:  <test cmd, lint cmd, merge style, repo specifics>
practices:    tdd: true|false            (tests land with or before the implementation)
              ddd: true|false            (model the domain concepts the plan names)
              e2e: none|user-facing|all  (when an E2E spec is required)
              coverage: <n>|null         (threshold to report in localChecks)
              commitStyle: <e.g. conventional>
              docs: none|public-api|all
steRule:      <absolute path to the writing standard: <project>/docs/rules/ste.md when it exists,
               else <pluginRoot>/references/ste.md>
qualityRule:  <absolute path to the quality rules: <project>/docs/rules/quality.md when it exists;
               omit this field otherwise>
pluginRoot:   <absolute path of the plugin directory: two levels above this skill's
               `SKILL.md`, e.g. …/issue-flow when the skill is at
               …/issue-flow/skills/issue-flow>
```

`pluginRoot` is not optional either. A worker is not told where its own definition lives,
and Codex gives a role no plugin root, so every `../references/…` link in its runbook — forge operations, the writing standard,
the finding policy — and the CI watcher script are
reachable only through it. The PM knows the path: Codex shows the absolute path of
`SKILL.md` when the skill loads.

`crossCheck` is not optional on a multi-member batch: it is the field that makes the step-4
gate un-skippable, because you cannot fill it in before the comment exists. A worker that
receives no `crossCheck` line cannot tell "the check was skipped" from "the PM forgot the
field", so it treats both as `blocked`.

`steRule` is not optional decoration: the worker writes **code comments, docstrings, test
names, and its PR body** to that standard, using the spec's `## Terms` vocabulary. Pass
the project's own copy whenever it exists — it is scoped to the source globs, so it loads
while the worker edits code.

`practices` comes from the session's [run configuration](session-config.md) and is part
of the worker's **definition of done** — not advice. A worker that cannot satisfy one
returns `needs-feedback` naming the practice; the PM checks them at the sub-merge gate
and does not waive them there.

**The PM creates the worktree**, before it spawns the worker. `worktree.py create`
fetches the remote, branches from `base`, and copies in the ignored files that the
project lists in `.worktreeinclude`. The PM passes the printed `path` as `worktree`. The
worker also reports its `pwd` as `worktree` in its verdict. The PM removes the
worktree with `worktree.py remove` after the sub-merge. The PM's job is
to keep `.worktreeinclude` accurate — a worktree is a fresh checkout of *tracked* files,
so `.env` and local secrets are otherwise missing and env-dependent suites fail as
`blocked`. And remember the worker **cannot answer a permission prompt**: every command
it needs must already be allowed in the project's Codex configuration.

## Rework: send the same worker a followup_task

Several gates send an issue **back to the worker** — an unevidenced criterion, a missed
practice, a review comment, a conflict to resolve. Two mechanisms, and they are not
equivalent:

- **Preferred — `followup_task` to the worker that returned the verdict**, by its
  `task_name` (`worker_<n>`, or `worker_<n>_c<k>`). It keeps its context, its worktree,
  and its branch already checked out, so nothing is re-pointed and nothing can be lost.
  Then the PM calls `wait_agent` for the next answer. **Never use `send_message` for
  rework**: it queues text and starts no turn, so the worker never acts on it.
- **Fallback — spawn a new worker**, when the worker is gone (session restarted, or
  `list_agents` no longer shows it). The PM creates a new worktree with `worktree.py create`
  and `--base <remote>/issue/<number>-<slug>` — the published branch — and the brief carries
  the plan, the PR number, what the gate rejected, and **the same `crossCheck` URL the
  original brief carried**: a new worker runs the First action exactly like a first launch
  and returns `blocked` without it. Passing the integration branch as `--base` here would
  reset the issue branch and orphan the PR's commits.

Either way the PM removes the worktree only once the issue is `status:batched` or
terminally parked — not between rework rounds.

## Return contract

**This mirrors the schema in `agents/issue-worker.md`, which is authoritative** — only the
agent definition reaches the worker at runtime, so that file decides what is emitted and
this one must track it. Change both together, or the PM reads a field the worker never
sends.

The worker returns exactly this object as its final message:

```json
{
  "type": "object",
  "required": ["issue", "outcome", "detail"],
  "properties": {
    "issue":      { "type": "number" },
    "branch":     { "type": "string" },
    "worktree":   { "type": "string", "description": "the worker's own worktree path (its pwd) — the PM's cross-check against the `path` that `worktree.py create` printed" },
    "prNumber":   { "type": "number" },
    "outcome":    { "type": "string", "enum": ["ready-to-merge", "checkpoint", "needs-feedback", "blocked"] },
    "detail":     { "type": "string" },
    "remaining":  { "type": "string", "description": "what is done, what is left, the next concrete step (required when outcome is checkpoint)" },
    "localChecks":{ "type": "string", "description": "what was run and the result, e.g. 'pytest 212 passed; ruff clean; build ok' (required when ci: skip)" },
    "criteria":   { "type": "array", "description": "one entry per acceptance criterion in the issue — required for ready-to-merge",
                    "items": { "type": "object", "required": ["text", "met", "evidence"],
                               "properties": { "text": {"type":"string"}, "met": {"type":"boolean"}, "evidence": {"type":"string"} } } },
    "question":   { "type": "string" },
    "blocker":    { "type": "string" },
    "openThreads":{ "type": "number" },
    "notesForPM": { "type": "string", "description": "findings outside this issue that the worker neither filed nor repaired — a stale record in a file its change never touched, a wider prose drift; one line each, null when there are none" }
  }
}
```

## How the PM reacts to each verdict (Stage C1)

| outcome | PM action (the gate) |
|---|---|
| `ready-to-merge` | Verify threads resolved + `localChecks` green (or CI green when `ci: run`) + the **pre-patch check** when the PR adds or changes tests (`localChecks` states the new tests failed against the pre-patch code — absent goes back to the worker) + **every acceptance criterion in `criteria` met and evidenced** (missing/unmet/unevidenced → back to the worker via `followup_task`, see Rework; disputed → `needs-feedback`); resolve any conflict vs the integration branch; `forge.pr.ready` then `forge.pr.merge.squash` **with the message written out — `--subject "<title> (#<pr>)" --body "[skip ci]"`, never the forge's default** (SKILL.md C1 step 4: GitHub's default carries the token only by luck, Gitea's carries none and starts a full CI run per sub-merge); then **check what landed** — fetch the integration branch and grep its head, re-triggering only per C1 step 4b (SKILL.md C1 step 4b); **`forge.issue.status.set <member> status:batched` as its own step, before any bookkeeping** (SKILL.md C1 step 5 — never a bare label add); then tick the tracking checklist, remove the worktree (`worktree.py remove --task <task_name>`), launch any sequenced successor. When the batch completes → batch gate (Stage C2). Standalone/hotfix: gate the PR like a batch PR into dev (the batch-PR column of `prAuthority` — [session-config.md](session-config.md)), merge `--squash`, **close the issue** (`Closes #` auto-closes only when dev is the default branch; otherwise close it manually with a comment linking the PR) and clear its status label, then Stage D directly. |
| `checkpoint` | The worker hit its turn budget with work pushed; nothing is wrong. Spawn a **fresh** worker (not a `followup_task` — that reuses the context the checkpoint exists to discard) with the same brief and `remaining` appended to the plan. First run `worktree.py remove --task worker_<n>[_c<k>]`. Then run `worktree.py create --task worker_<n>_c<k> --base <remote>/issue/<n>-<slug>` — the new worktree starts from the published branch — and spawn `worker_<n>_c<k>`. **Leave the status label untouched** — `status:in-review` if the worker had opened its PR, `status:in-progress` if it checkpointed before that; both are correct and the replacement adopts the open PR. Post one terse comment recording the checkpoint (the chain cap counts these). **Does not free the slot** — the issue is still in flight. No gate, no digest line. |
| `needs-feedback` | Label `status:needs-feedback`, post `question` as an issue comment, park per the feedback policy (notify; ask interactively only when it gates work). Free the slot. |
| `blocked` | Label `status:blocked`, comment naming `blocker`. Free the slot. |
| *(no verdict)* | Marked interim ("stopped with background work of its own still running") → not an outcome; keep the slot, the verdict follows. Final with no JSON → `followup_task` once for the verdict, then `blocked`. For an issue already gated → ignore. (SKILL.md, *Reading a worker verdict*.) |

**On every verdict, read `notesForPM`** — it carries findings the worker neither filed nor
repaired, and it is the only place they exist. Put each one through the filing gate: a
gate-passing finding becomes an issue, everything else becomes a **pending repair** in your
`flow:status` marker block, taken by the next batch that touches those files. A
`notesForPM` you do not read is a finding the worker deliberately did not file because this
policy told it not to.

After handling any verdict, top the pipeline back up to `concurrency`.

## Why this keeps the PM thin

The worker returns a few lines, not the diff/logs/files it churned through. The PM holds
only pointers + the verdict — the context discipline in
[parallelism.md](parallelism.md). The expensive context lives and dies inside disposable
workers, so a single session can clear far more issues than one context window could
hold.
