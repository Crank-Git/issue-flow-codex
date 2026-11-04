---
name: project-review
description: >
  User-viewpoint review of the running app in a sandbox — the QA/documentation pass
  after issue-flow ships work. Use when the user says "/project-review", "review the
  project", "user-test the app", "do a UX review", "build the user manual", or wants
  recent issue-flow work exercised end to end. The PM launches a sandbox, runs/creates
  E2E tests, fans out browser-driving ux-explorer agents that click through the app as
  end users (screenshots + manual-ready walkthroughs), and a code-auditor that sweeps
  for TODOs, stubs, and acceptance-criteria gaps. Nothing is fixed — the PM gathers
  every sub-agent report, files an issue for each finding that passes the filing gate
  (behavior, output, a dead guard, a blocked epic, a maintainer ruling), lands a manual +
  E2E-test PR via a review-scribe, then confirms launching issue-flow to work the new
  backlog.
---

# Project Review — use the app like a user, file what you find, fix nothing

This is the QA + documentation pass that follows building: exercise the project **as an
end user** in a **sandbox**, capture how it really behaves, and turn what you learn into
three deliverables:

1. **Tracker issues** — every bug, UX problem, gap, missing implementation, and code TODO
   found becomes an issue, filed **by the PM**, shaped for the issue-flow loop.
2. **A user manual** — per-flow walkthrough pages with screenshots, from the explorers'
   real sessions, landed via a docs PR.
3. **E2E smoke tests** — run the existing suite against the sandbox, or create one
   codifying the explored happy paths, landed in the same PR.

**The prime directive: find, never fix.** No product code changes happen during a
review — not by you, not by any sub-agent. Docs, screenshots, and tests are the only
things written. Fixing is issue-flow's job, and handing the new backlog to issue-flow is
how a review ends.

## Two roles

- **PM (the main thread).** Orchestrates: preps the sandbox, scopes the review, fans out
  reviewers, **gathers every report, dedups, and files all issues itself**, lands the
  deliverables PR, reports, and hands off to issue-flow. The PM never explores inline
  and never lets a sub-agent file issues.
- **Subagents use Codex roles.** Spawn `ux_explorer` for a user flow, `code_auditor` for
  the source review, and `review_scribe` for the deliverables. Each role declares its
  model in `.codex/agents/`. The PM does not override that model. Each role is
  decision-free. Only the PM files issues, and no role changes product code.

Use a unique lowercase `task_name` for each spawn. Set `agent_type` to the role name and
`fork_turns` to `"none"`. Call `list_agents` before each `spawn_agent` call. If no thread slot is free,
call `wait_agent` until one frees. Use `followup_task` by `task_name` to request rework.
Call `wait_agent` and read each verdict from the queued `FINAL_ANSWER` message.

This skill runs on **GitHub or Gitea**. All tracker interaction goes through the forge's
CLI — `gh` or `tea` — falling back to that forge's MCP server when the CLI is
unavailable. Every command is named as an abstract operation and resolved in
[../../references/forge.md](../../references/forge.md). Never hardcode `gh`.

**Every issue you file is Simplified Technical English** — the standard is
[`../../references/ste.md`](../../references/ste.md), and a planned project carries it at
`.claude/rules/ste.md` with its vocabulary in `docs/specs/spec.md` § Terms. You are
turning a sub-agent's report into a work item, so the split matters: **write** the title,
the context and the "what to build" in STE; **quote verbatim** the reproduction steps,
the expected-vs-actual, the console and server-log excerpts, the `path:line` references,
and any acceptance criterion the finding contradicts. Evidence you reword is evidence you
have damaged.

---

# Phase 0 — Preflight

1. **Repo check.** Same as issue-flow: `git rev-parse --is-inside-work-tree`,
   `forge.repo.view`, `forge.auth.check`. Detect the remote name and the dev-vs-live
   branch model (review branches fork off dev when it exists, else the default branch).
2. **Browser check.** Run `codex mcp list`. If its output has no server named
   `playwright`, show the operator this command and stop before you spawn a browser role:
   `codex mcp add playwright -- npx -y @playwright/mcp@0.0.84`. Never run the add
   command. The package README uses `@latest`; release `v0.0.84` is the latest pinned
   release at https://github.com/microsoft/playwright-mcp/releases (retrieved 2026-11-04).
3. **Sandbox up.** The review runs against a **sandbox, never production**. Resolve in
   order, asking the user only when ambiguous:
   - A URL the user supplied for this review.
   - An already-running local dev server (probe common ports the repo's config names).
   - Something launchable from the repo: `docker compose up`, `npm run dev`,
     `make dev`, a devcontainer — launch it as a background process with
     `exec_command` (`tty: true`) and keep its session id, wait for the port to answer,
     and stop it through that session (`write_stdin` with Ctrl-C) at the end.
   - A deployed **dev/staging** URL (from issue-flow's deploy detection). Never the
     production URL — explorers submit test data.
   Capture: `SANDBOX_URL`, and a **`logCmd`** that prints/tails the server logs
   (`docker compose logs --tail 100`, the background task's output file, or the
   provider's log command) — explorers use it to correlate errors. Seed test data if
   the repo has a seed script; note any seeded credentials for the explorer briefs.
4. **Scope — what shipped recently.** The review focuses on recent issue-flow output,
   plus a first-run pass:
   - Find the last review marker: `forge.issue.list` filtered on `project-review run`
     and bodies containing `<!-- project-review:`. Recent = closed issues / merged batch
     PRs since then (else since the user-given range, else ~the last 30 days).
   - `forge.issue.list` with `state: closed` + merged `Epic/Batch` PRs → group into
     **user-facing flows** (auth, core object CRUD, settings, etc.). Pull each issue's
     **acceptance criteria** — they become explorer `expectations` and auditor
     `recentWork`.
   - Always add one **"first-run user"** flow (land cold, figure the app out, reach the
     core action) even if nothing recent maps to it.
   - Cap at `MAX_FLOWS` (default 6; user-tunable) — prefer flows touching the most
     recent work; list anything skipped in the digest, never skip silently.
5. **Labels.** Bootstrap issue-flow's standard labels (its `references/labels.md`
   block, which already includes `review:finding`), created with `forge.label.create`.
   On Gitea, `forge.label.create` is not idempotent on its own — check
   `forge.label.list` first and create only what is missing, exactly as `labels.md`
   documents.
6. **Review workspace.** Set `RUN_ID` to `<YYYY-MM-DD>-<short-slug>`. Set the branch
   to `review/<RUN_ID>`. Create one scratch directory for each subagent at
   `.worktrees/review/<task_name>/`. Give its absolute path in the subagent brief.
   The scribe uses a separate worktree that you create in Phase 4.

If the sandbox app does not start, stop the run and file nothing. If the browser role
cannot reach the app, record its `unreachable` verdict and report it without a finding.

# Phase 1 — E2E baseline (existing suite)

Detect an existing E2E suite (`playwright.config.*`, `cypress.config.*`, `e2e/`,
`tests/e2e/`, a `test:e2e` script). Record its framework, directory, and run command.
Run it against `SANDBOX_URL` from the PM thread. Save output under
`.worktrees/review/e2e_baseline/`. Each real failure is a finding for Phase 3 (type
`bug`, evidence = the test name + failure excerpt). If no suite exists, note it for the
scribe.

# Phase 2 — Fan out the reviewers

**The browser MCP is one shared session.** Run only one browser-driving subagent at a
time, even when more thread slots are free. Before every spawn, call `list_agents` and
count free thread slots. If no slot is free, call `wait_agent` until one frees.
Before an explorer `spawn_agent` call, inspect active roles for `ux_explorer` or
`deploy_verifier`. If either role is active, wait until it returns before you spawn the
explorer. Spawn each subagent with `fork_turns: "none"`. Run the code auditor while an
explorer uses the browser.

- **One `ux_explorer` per flow** from Phase 0 scope. Spawn it after the prior explorer
  returns. Use a distinct lowercase `task_name` for each flow. Its brief contains:
  ```
  task_name:    ux_<flow_slug_with_underscores>
  agent_type:   ux_explorer
  fork_turns:   none
  url:           <SANDBOX_URL>
  flow:          <flow goal, phrased as a user goal>
  persona:       new user, no development knowledge of this app, laptop browser
  expectations:  <acceptance criteria quoted from the flow's recent issues>
  screenshotDir: <project>/.worktrees/review/ux_<flow_slug_with_underscores>/screenshots/
  notesFile:     <project>/.worktrees/review/ux_<flow_slug_with_underscores>/walkthrough.md
  logCmd:        <the sandbox log command>
  testData:      <seeded accounts/records, if any>
  ```
  Create the screenshot and notes directories before spawn. The role writes only
  screenshots and its walkthrough under
  `.worktrees/review/ux_<flow_slug_with_underscores>/`.
- **One `code_auditor`** over the checkout. Use `task_name: "code_auditor"`,
  `agent_type: "code_auditor"`, and `fork_turns: "none"`. Its brief gives the repo path,
  scope (default whole source tree; focus paths touched by recent PRs first),
  `recentWork` with recent issue acceptance criteria, generated dirs to skip, and the
  E2E framework, directory, and run command from Phase 1. It does not use the browser.

Call `list_agents` before spawning the auditor and confirm a free thread slot. Call
`wait_agent` for each role and read its verdict from the queued `FINAL_ANSWER` message.
Start the next explorer only after the current explorer returns. If an explorer returns
`blocked` or `partial` because it cannot reach `SANDBOX_URL`, report `unreachable` and do
not add a finding. Check that the sandbox is still up before the next explorer. Keep the
PM active with `wait_agent` while a subagent runs.

# Phase 3 — Gather & file (PM only — this is the gate)

Sub-agents **report**; only the PM files. On all verdicts collected:

1. **Merge findings** from every explorer, the auditor, and the Phase 1 E2E failures.
2. **Dedup** — within the run (two explorers hitting the same broken API → one issue
   listing both flows) and against the tracker (`forge.issue.list` filtered on
   `<title keywords>`, plus bodies carrying `<!-- project-review:` from prior runs).
   Update/comment an existing issue instead of double-filing.
3. **Apply the filing gate** — [../../references/finding-policy.md](../../references/finding-policy.md).
   A finding earns an issue in five cases and never otherwise: **behavior**, **a
   user-visible output**, **a guard that guards nothing**, **a blocked epic**, **a question
   the maintainer must rule**. Severity is not the test — a cosmetic behavior defect
   qualifies; a critical-sounding documentation drift does not. Two things that **do**
   qualify and are easy to mis-route: anything under `docs/specs/` that describes the wrong
   product (`type:spec-update` — `features/*.md` and `spec.md` alike), and **an app change
   an E2E test needs** — a missing
   test-id, no seed data, no state-reset hook — which is case 3, because without it the
   suite cannot guard the flow at all. Everything else goes to the Phase 4 deliverables PR
   when it is documentation the scribe already writes, and otherwise to the run ledger only.
   **Carry the routed list forward** — it goes in the scribe's brief at Phase 4, or it does
   not happen.
   A review that walks an app end to end produces far more findings than it produces work;
   filing them all is what turns the next issue-flow session into a documentation loop. The
   gate never suppresses evidence — every finding still reaches the ledger, the summary
   issue, and the digest. State the counts in both: findings gathered, issues filed,
   repairs routed to the PR, findings recorded only.
4. **File one issue per qualifying finding** (`forge.issue.create`):
   - **Title:** user-language, from the finding (`Sign-up form loses data on validation error`).
   - **Body:** what happened (steps to reproduce, expected vs actual), **evidence**
     (screenshot reference, console/server-log excerpt, `path:line` for code findings),
     source (`Found by project-review run <RUN_ID>, flow: <flow>` / `code audit`),
     related issue links (`Relates to #<n>` for acceptance-criteria gaps — the shipped
     issue it contradicts), and the marker `<!-- project-review:<RUN_ID> -->`.
   - **Labels:** `review:finding` + `status:ready` when clear and actionable;
     `status:needs-feedback` (+ the question as a comment) when it needs a product
     decision (e.g. "is this flow supposed to exist?"). High-severity breakage of a
     core flow → add `priority:high`. A sprawling UX overhaul → file as `type:epic`
     with the findings as its checklist, and let issue-flow decompose it.
   - Screenshots referenced in issue bodies must be durable: they land in the docs PR
     (Phase 4) — link the repo path the manual will use. Neither `gh` nor `tea` can
     upload an image from the CLI, so until that PR merges the issue stands on its
     quoted evidence: paste the console/server-log excerpt inline, name the scratch
     screenshot path, and say the image lands with the docs PR.
5. Keep a run ledger (finding → issue # / PR / recorded-only) for the digest and the summary issue.

# Phase 4 — Deliverables PR (manual + E2E tests)

1. Set `scribe_task` to `review_scribe_<RUN_ID_with_underscores>`. Create the scribe
   worktree with `python3 scripts/worktree.py create --project <project> --task
   <scribe_task> --branch review/<RUN_ID> --base <remote>/<dev>
   --remote <remote>`. For a CI re-run, use `<remote>/review/<RUN_ID>` as the base.
   Read the printed path. Call `list_agents` and confirm a free thread slot. Spawn the
   `review_scribe` role with `task_name: <scribe_task>`, `agent_type: "review_scribe"`,
   and `fork_turns: "none"`. Include the worktree path in its brief. Tell the scribe to
   use that path as `workdir` for every command. This path replaces the role's harness
   worktree steps; the scribe must not create or move another worktree.
   Give it `worktree: <absolute path>`, branch `review/<RUN_ID>`, base, remote, and the
   explorers' walkthrough files.
   Set `screenshotDir` to the root containing the flow directories. Preserve those
   directories in the manual so screenshots from different flows do not overwrite each
   other. Also give it flow outcomes,
   the Phase 1 E2E detection (`framework/dir/runCmd`), `SANDBOX_URL`, `manualDir`
   (default `docs/manual`), repo conventions, and **`steRule:`** — the path to the
   project's `.claude/rules/ste.md` if it has one, else the plugin's
   `references/ste.md` — so the manual is written to the same standard as the spec —
   and **`routedRepairs:`**, the Phase 3 list of documentation findings routed to this PR
   (each one: file, what is wrong, what it should say). The scribe repairs those in the
   same PR. Omit the list and the ledger claims work nobody did.
2. Call `wait_agent` and read the scribe verdict from `FINAL_ANSWER`. Check
   `notesForPM` (app changes a test needs — e.g. missing
   test-ids — go through the filing gate like any other finding; a missing test-id that
   blocks a test is a dead guard and earns an issue, marker included, not a fix), then push the
   branch from your own checkout (`git push -u <remote> review/<RUN_ID>` — branch refs are
   shared across worktrees, so you need not enter the scribe's) and open **one PR
   `review/<RUN_ID>` → dev**: title
   `Project review <RUN_ID>: user manual + E2E smoke tests`, body listing manual pages,
   tests added, the test-run result, **the routed repairs and where each landed** (read them
   from the scribe's `repairsMade`), and the filed-issue ledger. A repair the scribe reports
   unmade is stated as unmade with its reason, never dropped from the list. Docs + tests only —
   this PR is standalone, so **CI runs normally** on it.
3. Gate the PR like any PM merge. Read `prAuthority` from `.issue-flow.json` when it
   exists. A PR into dev uses the batch-PR column in `references/session-config.md`.
   Under the default `batch-review` and stricter settings, request human approval.
   Merge only after CI passes and all threads resolve. If CI fails because of new tests,
   send the scribe the failure with `followup_task` by its `task_name`. Wait for its new
   verdict, push the branch, and wait for CI on the new head. If the scribe is gone,
   remove its worktree with `worktree.py remove`, then create it again with
   `worktree.py create` and base it on `<remote>/review/<RUN_ID>`. **Never patch product
   code to make a review test pass.** Remove the scribe worktree with
   `python3 scripts/worktree.py remove --project <project> --task <scribe_task>` when
   the PR merges or the review ends without a merge.

# Phase 5 — Report & hand off to issue-flow

1. **Review summary issue.** Create (or update) an issue titled
   `Project review <RUN_ID>`, labeled **`review:finding` only**. Do **not** label it
   `flow:status` — that label means "an operator's live issue-flow session", and
   issue-flow's co-operator check (`references/collaboration.md`) would read this record
   as another person running the loop.
   Body (bookkeeping, not a work item): sandbox used, flows walked with the outcome of
   each, findings filed as a table (issue # / severity / type), findings routed to the
   deliverables PR or recorded only (one line each, so nothing the run found is lost),
   the manual + E2E PR link, and anything skipped (flow cap, degraded browser).
   Marker `<!-- project-review:<RUN_ID> -->` — the next run scopes from it.
   Close it once the handoff decision is made.
2. **Terminal digest** (≤10 lines): flows walked, findings gathered, issues filed by
   severity, repairs routed to the PR, findings recorded only, PR link, skipped items,
   open questions.
3. **Hand off.** The review ends by pointing issue-flow at the new backlog. Ask in plain
   text: **launch `/issue-flow` now** to work the filed findings, or stop with the backlog
   triaged and ready? End the turn for the user's answer. If the user said "review then
   fix" up front, skip the question and invoke `$issue-flow:issue-flow` directly. Its
   Stage A triage picks up findings labeled `status:ready` or `status:needs-feedback`.
4. **Teardown.** Stop any sandbox you launched. Use the reviewed project's `run` skill
   stop step to end MCP server processes that remain after a subagent finishes. Remove
   the scribe worktree when the PR merges or the review ends without a merge. Run
   `python3 scripts/worktree.py remove --project <project> --task <scribe_task>`.

---

# Hard rules

- **Find, never fix.** No product code changes during a review — by the PM or any
  sub-agent. The only writes are screenshots, walkthrough notes, manual pages, E2E
  tests, and tracker issues/comments. A broken sandbox or failing flow is a finding,
  not a repair task.
- **One browser-driving agent at a time.** The browser MCP is a single shared session;
  ux-explorers run sequentially, and no other browser user (e.g. a deploy-verifier)
  may be in flight while one runs. Parallelize only non-browser work (code-auditor,
  E2E via the repo's own runner, PM filing).
- **Only the PM files issues.** Explorers, the auditor, the scribe, and any fallback
  children report findings; the PM dedups and creates every issue. One finding, one
  issue, with evidence and the `<!-- project-review:<RUN_ID> -->` marker.
- **User viewpoint is the standard.** Explorers are briefed as non-developers judging
  what they can see and do; "works if you know the trick" is a UX finding. Logs and
  code are for *evidence*, never for excusing behavior a user would call broken.
- **Sandbox only.** Never explore production, never real credentials, never real
  personal data; test data is clearly fake. Destructive admin actions stop the flow
  (`partial`) rather than run.
- **Every finding is evidenced** — screenshot, console/log excerpt, or `path:line`.
  No evidence, no issue.
- **Issues and manual pages are STE** (`references/ste.md`). Titles and your own prose
  are written to the standard; steps, excerpts, paths and quoted criteria stay verbatim.
- **Deliverables land via PR** (docs + tests → one standalone CI-run PR to dev),
  through the normal merge gate. Never push directly to dev/live; never merge red.
- **Caps are loud.** Flow cap, degraded browser, skipped areas — always in the digest
  and summary issue, never silent.
- **The review ends with the handoff** — confirm (or, if pre-authorized, launch)
  issue-flow on the new findings. Filed-but-forgotten defeats the loop.
