# Session configuration (PM-facing)

Every issue-flow session runs under an explicit **run configuration**: how much work to
do, how much autonomy the PM has, and which engineering practices workers must follow.

**It is saved, and it is re-confirmed every session.** Saved values are the defaults you
present; they are never applied silently. The user's answer this session becomes the new
saved default. Two reasons: the answers are cheap to re-confirm and expensive to get
wrong (an autonomous merge the user didn't expect), and the right answer changes run to
run — "just this batch" today, "until the backlog is empty" tomorrow.

## Storage

`.issue-flow.json` at the repo root. Committed and team-shared — it is project policy,
and it must be visible to every operator and every worktree.

`.issue-flow.local.json` beside it, **gitignored**, holds one operator's personal
overrides and wins key-by-key over the committed file. Use it for anything that is about
*you* rather than the project — a lower `concurrency` on a small laptop, a shorter
`runLength` for a quick session. Without it, two people running concurrent sessions
would each write the committed file and produce a merge conflict in the very config that
governs them. Rule of thumb: **`prAuthority` and `practices` are project policy and
belong in the committed file** (a local override that loosens the merge gate defeats the
point); `concurrency`, `batchSize`, `runLength` and `review.when` are fine to override
locally. Write the session's answers to the local file when a co-operator is active,
to the committed file otherwise — and say which you wrote. (Phase 0 runs the
co-operator check, step 10, **before** the run configuration, step 11, precisely so
this decision has its input.)

```json
{
  "version": 1,
  "pluginVersion": "0.17.0",
  "forge": {
    "type": "gitea",
    "host": "http://gitea.example:3000",
    "owner": "acme",
    "repo": "widgets",
    "interface": "cli"
  },
  "concurrency": 3,
  "batchSize": 4,
  "runLength": { "mode": "issues", "value": 25 },
  "prGranularity": "batch",
  "prAuthority": "batch-review",
  "planReview": false,
  "reviewWipLimit": 2,
  "review": { "when": "end-of-session" },
  "deploy": {
    "mode": "command",
    "statusCmd": "./scripts/deploy-status.sh",
    "startCmd": null,
    "workflow": null,
    "url": "https://app.example.com",
    "previewUrlPattern": null,
    "pollSeconds": 30,
    "maxMinutes": 30
  },
  "docsMcp": { "offered": ["<server name>"], "installed": ["<server name>"], "marketplacesAdded": ["<source>"], "declined": true, "restartPending": false },
  "practices": {
    "tdd": true,
    "ddd": false,
    "e2e": "user-facing",
    "coverage": null,
    "commitStyle": "conventional",
    "docs": "public-api"
  },
  "notes": "<anything the user said that doesn't fit a field>"
}
```

Seed the first-run defaults from `docs/specs/spec.md` when a spec exists — its
`## Testing strategy` and `## Cross-cutting concerns` sections usually answer the
practices block. Say which defaults came from the spec when you present them.

If the file is missing, malformed, or from a newer `version`, fall back to the built-in
defaults below and say so. Never crash the session over config.

## pluginVersion — upgrade detection

The shared file has two version fields. `version` is the **config schema** (a newer
one than you know → defaults, as above). The shared
`.issue-flow.json` `pluginVersion` records the upstream release that last ran this
project. The Codex release is stored in `.issue-flow.codex.json` `pluginVersion`.
The Codex preflight hook reads only the Codex file for version drift.
Phase 0 records the installed Codex version whenever it writes that file.

On Codex version drift, the Codex config was written by an older plugin. Its silence
is not consent. A field the saved file lacks may be a question that did not exist yet. During the
step 11 confirm message, ask about every option the current tables define that the file
has no value for — never default one silently — then stamp the current version in
`.issue-flow.codex.json`. When the field is absent entirely, treat it the same way.
Always leave `.issue-flow.json` `pluginVersion` unchanged during a Codex run. A
`.issue-flow.local.json` override session also leaves the upstream version stamp alone
and notes the drift for the config's owner in the digest.

Version drift can also mean the **spec package** predates the current format (missing
diagrams, hand-written `spec.html`, no quality rules). That is not config business:
mention it once and point the user at `/spec-update` (refresh mode) between runs.

## forge — which tracker this project uses

`type` is `github` or `gitea`. `interface` is `cli` or `mcp` and selects the primary
interface; the other stays available as the fallback. `host`, `owner` and `repo` are
recorded by Phase 0 rather than typed by the user.

**The block is optional.** When it is absent, Phase 0 detects the forge from the remote
and defaults to `github`, so every configuration file written before this field existed
keeps working untouched.

It is **not** one of the startup questions. Phase 0 detects it, states what it found in
the first digest, and asks only when detection is ambiguous. The mechanics are in
[../../../references/forge.md](../../../references/forge.md).

## The startup prompt (Phase 0)

Ask in **one plain-text message**, then end your turn. The operator's reply continues
Phase 0. Number every item. Mark each saved value with `*`. List the options of an item
on its line. Show the models (`pmModel`, `workerModel`, `helperModel`)
and the `concurrency` in the message. The reply format is "ok" to accept all, or
"<number>: <value>" for each change.

```
issue-flow run configuration (saved answers marked *)

1. concurrency         * 3        (workers at once)
2. batchSize           * 4
3. runLength           * 25 issues
...
11. workerModel        * gpt-6.1-sol, effort medium
12. helperModel        * gpt-6-luna

Reply "ok" to accept all, or "<number>: <value>" for each change.
```

If a reply holds an invalid value, repeat the question for that item only. An item the
operator leaves unanswered keeps its saved or default value. State it in the digest.

The items fall in three groups, shown in order below. A project that an upstream PM
configured has no `.issue-flow.codex.json`. For that project, ask the upstream items as
usual and ask only the Codex questions for the Codex file.

### Group 1 — how this run should behave

| Question | Field | Options |
|---|---|---|
| How many workers in parallel? | `concurrency` | `1` (serial, easiest to follow) · `3` (default) · `5` (fast, more merge conflicts) |
| How far should this run go? | `runLength` | `one batch` · `N issues` · `until the backlog is empty` · `until you stop me` |
| Review plans before workers build them? | `planReview` | `no` (default) · `yes — hold each batch until I approve its plans` |
| How much merge authority do I have? | `prAuthority` | see the table below |

### Group 2 — how the work should be built

| Question | Field | Options |
|---|---|---|
| PR granularity? | `prGranularity` | `batch` (one CI run per epic/batch — default) · `per-issue` (a PR + CI per issue) |
| Development method? | `practices.tdd` / `.ddd` | `tests first (TDD)` · `domain-driven design` · `both` · `neither — follow existing repo style` (multi-select) |
| E2E test coverage? | `practices.e2e` | `none` · `user-facing changes only` (default) · `every issue` |
| Anything else — coverage, commit style, docs, `/project-review` cadence? | `practices.coverage`, `.commitStyle`, `.docs`, `review.when`, `notes` | free text + common options (coverage threshold, Conventional Commits, docs for public APIs, when a `/project-review` runs — default `end of session`) |

Group 2 is skippable when a saved config exists **and** the operator accepts the saved
defaults of group 1. Offer "keep saved build practices" as item 1 of group 2.

### Group 3 — Codex settings (`.issue-flow.codex.json`)

| Question | Field | Options |
|---|---|---|
| Which model runs the PM? | `pmModel` | `gpt-6.1-sol` (default) or another model name |
| Which model and effort run workers? | `workerModel`, `workerEffort` | `gpt-6.1-sol` with `medium` (default) |
| Which model runs helpers? | `helperModel` | `gpt-6-luna` (default) |
| How long does one wait call last? | `waitMs` | `600000` (default) |

## Codex-only settings — `.issue-flow.codex.json`

The Codex-only settings live in `.issue-flow.codex.json` at the repo root. The file is
committed and team-shared, like `.issue-flow.json`. It is separate because an upstream PM
rewrites `.issue-flow.json` and has no rule to keep an unknown key. `.issue-flow.json`
keeps only upstream keys, in the upstream format.

| Key | Default | Meaning |
|---|---|---|
| `pluginVersion` | installed Codex release | The Codex release that last wrote this file. |
| `pmModel` | `gpt-6.1-sol` | The model the PM session runs on. |
| `workerModel` | `gpt-6.1-sol` | The model each issue-worker runs on. |
| `workerEffort` | `medium` | The reasoning effort of each issue-worker. |
| `helperModel` | `gpt-6-luna` | The model of helpers, including the CI watcher. |
| `waitMs` | `600000` | The longest time in milliseconds that one `wait_agent` call blocks. |

```json
{ "version": 1, "pluginVersion": "0.1.0", "pmModel": "gpt-6.1-sol", "workerModel": "gpt-6.1-sol", "workerEffort": "medium",
  "helperModel": "gpt-6-luna", "waitMs": 600000 }
```

The keys are flat. There is no nested `codex` object.

A missing key takes its default. A missing file takes all five defaults.

## prAuthority — the merge gate

This is the security-relevant setting. Read the options to the user in full; do not
abbreviate them.

| Value | Sub-PR into the integration branch | Batch PR into dev | Promotion dev → live |
|---|---|---|---|
| `autonomous` | PM merges | PM merges | still user-approved, always |
| `batch-review` (default) | PM merges | **PM opens it, requests review, and waits for a human approving review before merging** | user-approved |
| `review-all` | **human approval required** | **human approval required** | user-approved |
| `propose-only` | PM opens PRs, merges nothing | PM opens it, merges nothing | user-approved |

**A standalone PR into dev takes the batch-PR column.** A hotfix, an urgent
`priority:high` singleton, a `type:spec-update` PR, `project-review`'s docs PR, and
every PR under `per-issue` granularity all run CI and land on dev — exactly what the
batch-PR column governs. Hotfixes skip *batching*, never the merge gate: under the
default `batch-review` a hotfix PR still needs a human approving review before the PM
merges it. A run that must self-merge hotfixes unattended needs `autonomous`, chosen
explicitly.

Rules:

- **Promotion to live is never autonomous**, whatever this is set to.
- When approval is required, the PM labels the tracking issue `status:awaiting-review`,
  requests review (`forge.pr.reviewer.add`, or comments naming the reviewers when no
  reviewer can be set), notifies once, and **moves on to other work** — it never blocks.
- The PM merges only on an actual **approving review** on the forge from a human other than
  itself, plus green checks and no unresolved threads. A thumbs-up reaction or a
  "looks good" comment is not an approval; a comment that says "approved, merge it" from
  a repo collaborator counts only if the PM records it as the authorization in a PR
  comment.
- Requested changes on a PR → route to a worker as PR feedback (human review is
  authoritative), then re-request review.
- If the repo has branch protection requiring reviews, that wins regardless of this
  setting — never try to route around it, and never use admin merge to bypass it.

## prGranularity — batch vs per-issue

- `batch` (default): the model documented in [batching.md](batching.md) — integration
  branch, CI-free draft sub-PRs, one CI run per batch.
- `per-issue`: no integration branch. Every issue gets its own worker branch off dev, a
  **normal (non-draft) PR into dev with `ci: run`**, and its own CI run; the worker
  watches CI itself. Stage C1 becomes the only merge gate and Stage C2 is skipped;
  conflicts are resolved per PR against dev rather than once per batch. Epics still
  exist as trackers and still close when their children do. Say plainly at startup that
  this multiplies CI usage by the number of issues — and that every one of those PRs
  takes the **batch-PR column** of `prAuthority`, so under the default `batch-review`
  each needs a human approving review (pick `autonomous` for an unattended per-issue
  run).

Hotfixes are `per-issue` regardless of this setting.

## planReview — human review at the plan stage

Off by default. When `true`, the PM holds each multi-member batch after the Stage B
cross-check and presents the member plans to the operator — one line per member with the
plan-comment link — in one plain-text message with numbered options (the PM ends its
turn and the reply continues it): approve, revise named plans, or proceed
without review this batch (SKILL.md Stage B step 4b).

Why it exists: under the default `batch-review`, the human's first contact with a batch
is the finished multi-issue diff — the most expensive possible review point. The plans
already exist as issue comments before any code is written, and re-steering there costs
one comment edit. "A bad line of a plan could lead to hundreds of bad lines of code" —
the review is deliberately placed where a correction is cheap, not where the diff is
complete.

Two caveats, stated to the user when they switch it on:

- **It makes the loop synchronous at every batch start.** The plan ask is a real
  interactive question, and the batch does not launch until it is answered. `planReview`
  is for sessions where the operator is at the keyboard; an unattended run wants it off.
- It complements, never replaces, the merge gates — `prAuthority` still governs what the
  PM may merge.

## reviewWipLimit — the cap in front of the human review gate

Soft cap on batches with anything simultaneously parked `status:awaiting-review`
(default **2**). A batch counts when its **tracking issue** carries the label (the C2
hold under `batch-review`) or **any member** does (the C1 per-PR holds under
`review-all` / `propose-only` — counting only tracking issues would leave the cap
permanently at zero there, since no batch ever reaches C2 while its members are held).
At or above it, the PM forms no new batches: it keeps filling worker slots for batches
already in flight, works parked questions, and notifies the operator once that reviews
are the constraint, naming the setting and value (SKILL.md Stage B step 1). An approval
or merge frees the cap.

Why: "the PM moves on rather than block" is correct per batch and wrong in aggregate —
when human review is the bottleneck, every additional finished-but-unreviewed batch is
inventory in front of it, aging against a moving dev, not throughput. The cap converts
silent stacking into one explicit signal.

It binds only under an authority setting that parks batches for review
(`batch-review`, `review-all`, `propose-only`); under `autonomous` nothing is ever
`status:awaiting-review` long enough to count. Set it to `null` to disable the cap
explicitly — recorded, like every other setting.

## runLength

| Mode | Meaning | Stop condition |
|---|---|---|
| `batches` | finish N batches | N batches merged (or terminally parked) |
| `issues` | up to N issues (default 25) | N issues closed |
| `backlog` | until nothing is workable | Stage A finds no workable issue |
| `open` | until the user stops it | user says stop, or budget spent |

Whatever the mode, the existing stop conditions still apply (nothing workable, budget
spent, user stop). Reaching the limit stops the loop cleanly with a final digest — it
never abandons in-flight work: let running workers finish and gate their results first,
then stop.

## deploy — how Stage D watches deployments

Recorded by Phase 0 step 6, not asked in the startup rounds (confirm only when detection
was ambiguous). The plugin ships no provider integrations — the platform is a project
architecture choice, and this block is where the project's wiring is recorded
([deploy.md](deploy.md)):

- `mode` — `actions` (a deploy workflow in the forge's own Actions; Stage D watches its
  runs), `command` (a project-supplied status command), or `none` (Stage D skipped).
- `statusCmd` — `mode: command` only: a one-shot command printing
  `<state> <jobId> <sha>` with `state` normalized to
  `pending | running | succeeded | failed | rolled-back`. It must work under the
  `issue_flow` permission profile.
- `startCmd` — optional: how to start a deploy by hand when the branch is
  push-protected.
- `workflow` — `mode: actions` only: the deploy workflow file name.
- `url` / `previewUrlPattern` — what the deploy-verifier loads.
- `pollSeconds` / `maxMinutes` — the deploy watcher's poll interval in seconds and its
  deadline in minutes (defaults 30/30).

## docsMcp — documentation access

Set in Phase 0 step 8, not in the startup questions. It records which documentation MCP
servers the PM offered, which the user installed, and whether they declined.

- A recorded `declined: true` means **do not offer again** in later sessions. Offer once
  more only when the project gains a dependency on a service none of the installed
  servers cover.
- `installed` and `marketplacesAdded` are notes, not guarantees — always confirm with
  `codex mcp list` and `codex plugin marketplace list` at startup rather than trusting the
  file. `marketplacesAdded` is a note; the command output shows what is configured now.
- `restartPending: true` means something was installed in a previous session and had not
  appeared yet. At startup, re-check whether it is live now: it is → clear the flag and
  say the server is available; it is not → tell the user once and keep the direct vendor documentation
  fallback. Never block the loop on it.
- This setting never changes what workers must do: the interface still comes from the
  vendor's documentation ([external-apis.md](../../../references/external-apis.md)). A
  doc MCP server makes that lookup fast and reliable; direct vendor documentation makes it slow. Neither
  makes assuming acceptable.

## review.when

When the trigger fires, the PM **asks** before launching `/project-review` (it is a long,
browser-driving run) unless the user chose it explicitly for this session. A review that
files issues feeds straight back into Stage A triage.

## practices — how they reach the workers

Practices are not decoration; they change the worker's definition of done. Carry them in
the handoff brief (`practices:` block in
[issue-worker.md](issue-worker.md)) and enforce them at the sub-merge gate:

| Practice | What the PM checks at the gate |
|---|---|
| `tdd: true` | the verdict's `localChecks` shows tests that exercise the new behaviour **and the pre-patch check** (the new tests were run against the pre-patch code and failed — a test that passed before the change proves nothing), and the PR history shows tests landing with (or before) the implementation |
| `ddd: true` | the plan you commented named the domain concepts/boundaries the issue touches |
| `e2e: user-facing` / `every issue` | a user-facing change ships with an E2E spec, or the verdict states why one isn't applicable |
| `coverage: <n>` | the coverage number is in `localChecks` and meets the threshold |
| `commitStyle` | the sub-PR's commits match the style before you merge |
| `docs` | public API/interface changes ship with their doc update |

A worker that cannot satisfy a practice returns `needs-feedback` naming the practice —
it never silently drops one. If a practice is repeatedly impossible for this repo (no
E2E harness exists yet), file it as an issue rather than quietly disabling the practice.

## Reporting

Include the active configuration in the **first digest of the session** (one line:
concurrency, run length, PR granularity, authority, practices) so anyone reading the
status issue knows the rules this session ran under. Re-state it in the final digest if
it changed mid-session.
