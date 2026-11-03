# Deployment monitoring (Stage D)

A merge to the deploy branch usually triggers a build/deploy outside CI. The PM treats
**deploy success as part of "done"**: after each merge to the deploy branch it spawns
**one `ci_watcher` subagent**, anchored to the merged head SHA, and reacts when the
watcher returns its verdict — so the PM never polls. A failed deploy is never ignored.

## The platform is a project choice, not a plugin feature

This plugin ships **no provider integrations**. AWS Amplify, Vercel, Netlify, a
Kubernetes rollout — each is an architecture choice the *project* made, and the project
supplies the way to query it. The plugin knows exactly two generic paths:

1. **`mode: actions`** — the deploy runs as a workflow in the forge's own Actions
   (GitHub Actions or Gitea Actions). Deploy status *is* a run: Stage D watches it with
   the same commit-anchored watcher as CI
   ([../../../references/forge.md](../../../references/forge.md)), filtered to the
   deploy workflow, anchored to the merged head SHA. `no-run-registered` there maps to
   `no-deployment-observed` below.
2. **`mode: command`** — the project ships a **status command** that answers "what is
   the newest deployment of this branch". `project-planner`'s Epic 0 wires it
   (`scripts/deploy-status.sh`, or a `deploy-check` project skill); an existing project
   supplies it in `.issue-flow.json` or the user gives it once at preflight. The
   provider vocabulary lives inside that script — that is where "Amplify" belongs, if
   the project chose Amplify.

No status command, no deploy workflow, nothing from the user → **skip Stage D** and say
so once. Never guess a provider query.

## Detecting the deploy target (Phase 0, step 6)

In order — the first hit wins:

1. An explicit `deploy` block in `.issue-flow.json`.
2. A workflow in the forge's Actions that deploys on push to the deploy branch
   (`.github/workflows/` or `.gitea/workflows/`) → `mode: actions`, record the workflow
   file name.
3. A status command the repo ships (`scripts/deploy-status.sh`, a `deploy-check` /
   `deploy-status` project skill) → `mode: command`.
4. A status command or health URL the user supplies → `mode: command`.

Also capture the **deployed URL** (and the PR-preview URL pattern when the platform
builds previews) — Stage D cannot browser-verify without it. Ambiguity is an
plain-text question to the operator, never a guess. Record everything in the run configuration's `deploy`
block ([session-config.md](session-config.md)).

## The status command contract (`mode: command`)

One-shot, read-only, exits fast. Prints **one line** describing the newest deployment of
the deploy branch:

```
<state> <jobId> <sha>
```

- `state` is normalized to `pending | running | succeeded | failed | rolled-back`. The
  mapping from the provider's own vocabulary (`SUCCEED`, `READY`, …) is written once,
  inside the project's script.
- `jobId` is the platform's deployment/job id — used in comments and links.
- `sha` is the commit the deployment built. The watch correlates on it.
- A query failure exits non-zero. The watch reports it as `watch-error` — never a pass.

The command must run without an approval prompt: the watcher runs it with nobody to
answer a prompt. If the sandbox refuses it, the watcher returns `state: "error"`.

## The watch — one `ci_watcher` per merge

Spawned by the PM at Stage D, after each merge to the deploy branch. Codex has no
background shell that wakes the PM, and it ends any command at 300 seconds. So the wait is
a subagent, the `ci_watcher` role (`agents/ci-watcher.md`), and the PM reads its verdict
with `wait_agent` (the same reasoning as the CI watch in
[../../../references/forge.md](../../../references/forge.md)). Anchor it to **the head SHA
of the deploy branch after the merge** — normally the merge commit, or the recovery commit
whenever one was pushed on top (SKILL.md Stage C2 step 5). The deployment carries the SHA
it built; correlating against a superseded commit finds nothing and reads as a missing
deploy.

The PM calls `list_agents`, and when a thread slot is free it calls `spawn_agent` with
`task_name: "deploy_<sha7>"`, `agent_type: "ci_watcher"`, `fork_turns: "none"`, and this
brief:

```
kind:       deploy
sha:        <head of the deploy branch after the merge, 40 characters>
workdir:    <the project directory>
pluginRoot: <absolute path of the plugin directory>
forge:      <the forge block>
deploy:     <the deploy block: mode, statusCmd or workflow, pollSeconds>
deadline:   <deploy.maxMinutes, default 30>
```

The watcher runs `scripts/deploy_wait.py` again and again while the state is `pending`.
Each run ends within `--max-seconds` (default 240):

```bash
python3 <pluginRoot>/scripts/deploy_wait.py --mode command --status-cmd <statusCmd> --sha <sha>
python3 <pluginRoot>/scripts/deploy_wait.py --mode actions --workflow <file> --forge github --repo <owner>/<repo> --sha <sha>
```

`pollSeconds` (default 30) comes from the `deploy` block and maps to `--poll-seconds`. The
deadline is `maxMinutes` from the `deploy` block, default 30.

**The parse contract** — the script prints one JSON line `{"state": ..., "url": ...}` and
exits 0. The watcher returns `{"kind": "deploy", "sha": ..., "state": ..., "url": ...}`.
The state is the verdict:

| `state` | meaning |
|---|---|
| `succeeded`, `failed`, `rolled-back` | terminal state observed for our SHA |
| `pending` | ours was seen `pending`/`running`. The watcher runs the script again. |
| `timeout` | the watcher's deadline passed while ours was still `pending` (`timed-out` in the table below) |
| `superseded` | ours was never observed; the branch's newest deployment is a different commit |
| `missing` | nothing deployed at all during the watch (`no-deployment-observed` in the table below). In `actions` mode a run with conclusion `skipped` deployed nothing, so it counts as `missing`. |
| `error` | the status query itself failed (`watch-error` in the table below) — never a verdict |

Five properties worth keeping if you rewrite it:

- **The SHA anchor** — a stale or unrelated deployment can never be mistaken for yours.
- **`missing` distinct from `timeout`** — "nothing ever started" and "started but never
  finished" have opposite remedies (see the reaction table).
- **`superseded` distinct from `missing`** — the status command returns the branch's
  *newest* deployment, so a deploy replaced before the first poll (the
  hotfix-after-failed-batch shape) is invisible to the anchor. Without this verdict it
  reads as "nothing deployed", whose remedy pushes a recovery commit — an empty push
  per iteration against a pipeline that is running normally.
- **`error` distinct from both** — a failed query is never a verdict.
- **Success is proven, not assumed** — only an observed terminal `succeeded` counts.

For `mode: actions`, `deploy_wait.py` reads the runs of the deploy workflow for the SHA
with the same call as `ci_wait.py`; its `missing` state is `no-deployment-observed`.

## PM reaction (Stage D)

Every non-verified terminal outcome first gets **`status:deploy-failed`** on the tracking
issue (replacing `status:deploying`), then routes by cause. That label is what Phase 0
recovery looks for when it re-adopts a deployment whose hotfix never landed. The PM
removes it when the fix deploys and verifies.

| verdict | PM action |
|---|---|
| `succeeded` | **Verify before declaring done** — build-green ≠ working. Spawn the `deploy_verifier` role against the deployed URL (skip and say so in the digest when the role is missing). On `verified`: remove `status:deploying`, comment confirmation + screenshot. On `broken`/`unreachable`: treat as a deploy failure (rows below). |
| `failed` / `rolled-back` (cause `code-regression`) | `forge.issue.status.set <n> status:deploy-failed` (removes `status:deploying`), then open a `priority:high` `type:hotfix` `status:ready` **hotfix issue** citing the failed deploy, commit, failing step, and log excerpt. Hotfixes **bypass batching**: schedule a standalone worker immediately (`ci: run`, normal PR straight to dev — the merge gate follows the batch-PR column of `prAuthority`, [session-config.md](session-config.md)). |
| `failed` (cause `config`/`secret`/`quota`/`infra`) | `forge.issue.status.set <n> status:deploy-failed` (removes `status:deploying`), then route for **human input as a comment** — `needs human input: <what>` naming the cause — and surface it to the user per the feedback policy. **No second `status:` label:** `deploy-failed` stays the only one, so no park is added here for Stage A0 step 3b to destroy. The cost is that the issue is not in the Stage A step 4 `status:needs-feedback` gather; the surfacing is what reaches the user. Do not guess at infra/secret changes. |
| `timed-out` | A deployment was observed but never reached a terminal state in the budget. Re-query once (run the status command directly). Still not terminal → surface to the user with the job id/link — never assume success. Leave `status:deploying` in place. |
| `superseded` | The branch's newest deployment is a different commit — ours was replaced before it was observed (typically a hotfix landing right behind the batch). Confirm the newer SHA contains ours (`git merge-base --is-ancestor $SHA <newestSha>`), then watch the **newest** SHA instead — its verdict covers both commits. If the newer SHA does *not* contain ours, the branch was force-moved: surface that to the user. Never push a recovery commit on this verdict. |
| `no-deployment-observed` | Nothing deployed at all during the watch. First run the status command **once, directly**: a newer deployment now in flight means this is really `superseded` — follow that row, push nothing. Then re-run the merged-head token check (SKILL.md Stage C2 step 5): a suppressed head starts no deploy — push the clean recovery commit and watch the new SHA, **once**; a second `no-deployment-observed` on the recovery SHA is a wiring problem (webhook, platform config) — surface it, do not push again. Never a pass. |
| `watch-error` | The status command itself failed — usually a permission refusal or an auth problem. Fix the cause (allow-list the exact command, re-authenticate) and relaunch the watch. Never a pass. |

**Classify the cause before routing a failure.** After a free-slot check with `list_agents`,
delegate the log read to one `spawn_agent` call (`agent_type: "explorer"`, `fork_turns: "none"`);
take back the failing step, a short excerpt, and one of:

- `code-regression` — build/test/runtime error traceable to the change.
- `config` — bad build settings, env/branch config, redirects.
- `secret` — missing/expired credential, auth failure.
- `quota` — limits, throttling, capacity.
- `infra` — platform/region outage, provisioning failure.
- `unknown` — the logs do not say.

The PM takes back the cause, not the log.

A hotfix issue flows worker → PR (CI on, no batch) → merge → **Stage D again**, so a
deploy that fails twice keeps producing fixes until it goes green or is parked for the
user.

## Starting a deploy that never started

Everything else here **reads** status. Once — when the merge commit's message suppressed
the push run (see the merged-into-branch check in SKILL.md Stage C2 step 5) — nothing is
building because nothing began, and the PM has to start it.

**Preferred, and provider-independent: one clean empty commit on the deploy branch,
pushed.** Check the branch out by name first — at this point in C2 the PM's worktree is
usually the integration-branch one about to be torn down, and an unqualified commit there
publishes nothing while looking like a fix:

```bash
git fetch <remote> <deploy-branch> -q
python3 <pluginRoot>/scripts/worktree.py create --project <dir> --task dev --branch ci/<deploy-branch>-<n> --base <remote>/<deploy-branch> --remote <remote>
git -C .worktrees/dev commit --allow-empty -m "ci: run suite for batch #<n>"   # subject only, no body
git -C .worktrees/dev push <remote> HEAD:<deploy-branch>
git -C .worktrees/dev rev-parse HEAD                                           # correlate the deploy against this
```

A worktree rather than a `checkout -B`, per the PM-worktree convention in
[batching.md](batching.md) — it must not move the user's `HEAD` or their local branch.

It restarts the CI run and the deploy together, and it rewrites nothing. The pushed commit
becomes the branch head, so **it is the SHA to watch** — record it in place of the merge
commit before launching the watch.

Where the branch is protected against direct pushes, start the deploy the project's own
way: `gh workflow run <workflow-file> --ref <branch>` when the deploy workflow declares
`workflow_dispatch`, the project's wired start command (`deploy.startCmd` when the config
carries one), or the platform's own redeploy control. Whichever path is used, **say in
the digest that the deploy was started by hand** — a deployment a human triggered must
not be reported as one the merge triggered.

## The deploy-verifier agent (browser check)

A green build doesn't prove the app runs. After a deployment reports `succeeded` (and
optionally for a PR preview), spawn the `deploy_verifier` role (`spawn_agent` with
`agent_type: "deploy_verifier"` and `fork_turns: "none"`). The role arrives with Epic 5.
When `spawn_agent` does not offer it, skip the browser check and say so in the digest.
The role drives a real browser via the **Playwright** MCP server: loads the URL,
checks HTTP/render/expected-content/console/network, screenshots, and returns
`verified | broken | unreachable`. Brief:

```
url:      <deployed or PR-preview URL>
commit:   <sha that produced the deploy>
expect:   <optional text/selectors that must be present>
issue/pr: #<n> / PR #<m>
```

Requires the `playwright` MCP server in the Codex configuration (`codex mcp list` shows it;
`codex mcp add` adds it). If none is available, the verifier degrades to an HTTP/content
check with `curl` and says so. A `broken`/`unreachable` verdict flows into the same hotfix / needs-feedback
routing as a deploy failure.

## Recovery note

Phase 0 state recovery re-adopts deploys: check for any recently merged PR into the
deploy branch whose deployment was never confirmed (no success comment, no open hotfix).
For each, run the status command once (or list the deploy workflow's runs for that SHA):
already terminal → react to it now via the table above; still in flight → launch a watch
for that SHA and carry on.
