# Worktrees (the PM creates one per worker)

Every worker builds in its own git worktree. This page states who creates it, who removes
it, and what the PM does when a removal is refused.

## The rule

- The PM creates the worktree with `scripts/worktree.py create`, before it spawns the
  worker (SKILL.md, Stage B step 5). The script prints the `path`. The PM copies it into
  the brief field `worktree`.
- The worktree lives under `.worktrees/<task_name>` in the project directory. The
  `task_name` is `worker_<n>`, or `worker_<n>_c<k>` for the replacement after checkpoint
  `k`.
- No agent in the run moves its session into a worktree. Codex has no tool for it. The PM
  drives a worktree with `git -C <path>`, and a worker works in the `worktree` path of its
  brief.
- A worker's child agents work in the worker's worktree. They create no worktree.
- Rework goes back to the **same** worker with `followup_task`. See
  [Rework and checkpoint](#rework-and-checkpoint).
- The PM removes a worktree with `scripts/worktree.py remove`, after the sub-merge or at a
  checkpoint.

The spawn guard (`hooks/guard-spawn.py`) denies a `spawn_agent` call that breaks the
launch rules of Stage B. The guard does not create or move a worktree.

## What the script does

`scripts/worktree.py` takes two commands.

- `create --project <dir> --task <task_name> --branch issue/<n>-<slug> --base <remote>/<ref>
  [--remote <remote>]` makes the worktree and prints `{"path","branch","base_sha"}`.
  It copies the files that `.worktreeinclude` names and git ignores (`.env` and local
  secrets), because a worktree is a fresh checkout of *tracked* files only. Keep
  `.worktreeinclude` accurate instead of copying those files by hand.
- `remove --project <dir> --task <task_name>` removes the worktree and deletes its
  branch.

`create` reuses a **local** branch when one exists, and else makes the branch from
`--base`. A branch that exists only on the remote is not reused. For a rework spawn or a
checkpoint replacement, pass `--base <remote>/issue/<n>-<slug>`, so that the new branch
starts from the published work. Passing the integration branch there drops the PR's
commits.

Every failure exits 1 and prints one line on stderr. A bad command line exits 2 (argument
parser). The exit codes are the only interface the PM reads:

| command | exit 1 means | exit 2 means |
|---|---|---|
| `create` | git failed, for example the base does not resolve | the arguments are wrong |
| `remove` | the script **refused** to remove: the worktree holds work that no remote holds, or git failed | the arguments are wrong |

On `remove`, exit 1 changes nothing. The script owns the checks behind a refusal. This
page does not restate them. Read the stderr line for the reason.

## Rework and checkpoint

| PM action | worker | worktree |
|---|---|---|
| `followup_task` to `worker_<n>` | the same agent, context intact | its own, branch already checked out |
| a new `spawn_agent` call | a fresh agent | a new one, from `worktree.py create` |

Rework goes back by `followup_task` to the `task_name` that Stage B step 5 chose. Never use
`send_message` for it: that tool queues text and starts no turn. A fresh spawn is the
fallback for when the worker is gone (a restart, for instance). It needs
`--base <remote>/issue/<number>-<slug>` at `create`, so that the new worker continues the
published branch.

**`checkpoint` inverts this.** A worker that hit its turn budget with work pushed and
nothing wrong is replaced, not resumed. The verdict exists to drop a context that has
grown expensive, and a `followup_task` keeps exactly that context. The PM does three
things in order (SKILL.md, Stage C1):

1. `worktree.py remove --project <dir> --task worker_<n>[_c<k>]`.
2. `worktree.py create --project <dir> --task worker_<n>_c<k> --branch issue/<n>-<slug>
   --base <remote>/issue/<n>-<slug>`.
3. `spawn_agent` for `worker_<n>_c<k>`, with the new `path` in its brief.

A leftover worktree from a previous session cannot be resumed in place. Its worker is
gone. Adopt that work from the branch and the PR, then remove the directory.

## Teardown is still the PM's job

Nothing removes a worktree behind a worker. A worker's worktree always holds commits, so
the PM removes it:

```bash
python3 <pluginRoot>/scripts/worktree.py remove --project <dir> --task <task_name>
git worktree list --porcelain    # sweep for earlier sessions' leftovers
git worktree prune
```

Run `remove` at the sub-merge, at a checkpoint, and at the batch-gate and Stop sweeps.
Prune last: a tree whose directory is gone still reports its path until `prune` drops it.

### Parked standalone worktrees

A batch member parked on `needs-feedback` or `blocked` keeps its tree until the batch
gate's sweep. A standalone or hotfix issue has no batch gate, so without a rule its tree
waits for the Stop sweep, and a long session collects one per parked issue. Run
`worktree.py remove` when it parks (SKILL.md C1, `needs-feedback` and `blocked`).

Where the answer goes depends on what the script did:

- **Removed** (exit 0) → the issue goes back to `status:ready` and Stage B spawns a
  **fresh** worker, which continues the **published** `issue/<n>-<slug>` branch. When no
  branch was published, it starts from the base.
- **Refused** (exit 1) → send the answer to that worker with `followup_task`. Only that
  worker can commit and push what its tree holds. While the tree has the branch checked
  out, a fresh worker's checkout fails (`already used by worktree`). Say in the park
  comment that the tree was kept.
- **Refused, and the worker is gone** (a restart) → Phase 0 and the Stop sweep skip parked
  trees and list them in the digest. Before you spawn that issue again, commit and push what
  the tree holds with `git -C <tree>`, or ask the user. Then run `remove` and spawn fresh.

## What the PM may still do itself

The PM may run `git worktree add` for its own sequential integration-branch work (local
sub-merges, the empty commit that re-triggers CI) and drive it with `git -C`. Delegated
integration-branch work (suite runs, fix workers) goes to a subagent that works in a
worktree from `worktree.py create` with `--base <remote>/<integration-branch>`.
