# Project scaffold format (project-planner reference)

How to generate `spec.html`, `AGENTS.md`, `docs/rules/`, project skills, hooks, and
`.gitignore`. `SKILL.md` Phase 3 points here. The planner shows every proposed change
in the Phase 4 review round. It writes nothing before the operator approves it.

### `spec.html` and `html/` — generated from the markdown

The markdown package is the spec. The generated site is a build product. Copy the
renderer shipped with this skill, `scripts/render-spec.py`, into the project as
`docs/specs/render-spec.py`. Then run:

```
python3 docs/specs/render-spec.py
```

The script reads `spec.md`, each feature file in its front matter, and each optional
supplement page. It renders the full content of every file. It writes `spec.html` as the
index and writes one page for each feature and supplement. Links between markdown files
point to the generated pages. A later render deletes stale pages in `html/`.

Vendor one pinned mermaid build to `docs/specs/assets/mermaid.min.js`. Commit that file
so diagrams render offline. If the download fails, state that the pages show diagrams as
readable source. Regenerate the site after each review round. Commit the markdown and
the full render together. Never edit generated HTML by hand.

### `AGENTS.md`

Write `AGENTS.md` at the project root. Keep the root file and every nested `AGENTS.md`
together under 24 KiB. Codex has a 32 KiB total project-document limit. Use the lower
limit to leave room for nested files.

Include these sections:

- A short project summary and current state.
- The stack, project layout, and where files belong.
- Build, run, test, and lint commands from the spec.
- Conventions from the spec, including naming, error handling, and commit style.
- A plain-text pointer to `docs/specs/spec.md` and the relevant feature files.
- The filing gate and its changelog bound, from the template below.
- Each `docs/rules/` path and the condition that requires a reader to read it.

If the root file would exceed 24 KiB with nested files, move detail into `docs/rules/`.
Keep the pointers and required short facts in `AGENTS.md`.

If `AGENTS.md` already exists, show proposed additions and merge them only after
approval. Preserve every existing line until approval. If `CLAUDE.md` exists without
`AGENTS.md`, propose moving its content into `AGENTS.md` and leaving `@AGENTS.md` in
`CLAUDE.md`. Move nothing until approval. Preserve an existing `.codex/config.toml` and
`.gitignore`; show additions and merge them only after approval.

Use this filing gate. Replace the two routing placeholders with the project's branch
model and issue parking place.

```markdown
- **A finding earns a tracker issue in five cases, and never otherwise.** Behavior. A
  user-visible output. A guard that guards nothing. A blocked epic. A question the
  maintainer must rule. One carve-out: anything under `docs/specs/` that describes the
  wrong product earns a spec-update issue, because the spec decides what gets built.

  **Every other finding is repaired by the change set that found it, and no issue is
  filed.** A falsified sentence, a moved citation, a stale count, a missing term and prose
  drift each reach the repair. A repair that turns out to touch behavior stops and is
  filed as a behavior finding.

  Where the repair goes:
  - Found while building an issue → that issue's own PR, limited to files it already
    touches.
  - Found at review of <integration branch> → a documentation commit on that branch,
    before the CI-trigger commit.
  - Found with nothing open → <the project's issue parking place>.

- A changelog or spec-changelog entry records a **decision**, made at a batch gate. No
  rule, hook, CI check, or test may require a changelog row, a spec edit, or a
  docs-accuracy pass **per change set or per batch member** — a batch that shipped as
  planned earns no line. A test that asserts per-member bookkeeping agreement re-creates
  the churn the filing gate exists to prevent, and fails review here.
```

### `docs/rules/`

Write all three rule files. Copy their rule content from the plugin references. Codex does
not load these files automatically. `AGENTS.md` and each worker brief must name the paths.

`docs/rules/ste.md` contains the writing rules, verbatim exclusions, artifact patterns,
and checklist from this plugin's `references/ste.md` (`<pluginRoot>/references/ste.md`; `<pluginRoot>` is two directories above this skill's `SKILL.md`). Replace its Terms section with a pointer to
`docs/specs/spec.md`'s `## Terms` table. A reader must read this file before writing
prose, code comments, docstrings, test names, issues, or pull-request text.

`docs/rules/quality.md` contains the maintainability rules from the project's quality
standard. Scope its guidance to the project's language and code. A reader must read this
file before writing or reviewing source code or tests.

`docs/rules/external-apis.md` contains the rules from `references/external-apis.md`, made
concrete for services in the spec. Name pinned versions and documentation links. A
reader must read this file before writing code that uses an external service, CLI, or
library. If the project uses no external interface, keep the general rule and state that
the spec names none.

### Project skills

Write `.agents/skills/run/SKILL.md` and `.agents/skills/test/SKILL.md`. Each file needs
`name` and `description` front matter. Use commands and setup facts from the spec. Keep
paths relative to the project root. Do not add a permission allow-list. The setup skill's
`issue_flow` permission profile sets session access.

Use these templates and replace each bracketed item with a fact from the spec.

```markdown
---
name: run
description: Start the app locally for manual checks. Use when asked to run, launch, or screenshot the app.
---

# Run the project

1. Read the environment steps in `docs/specs/spec.md`.
2. Start required services with the commands from the spec.
3. Start the app with the command from the spec.
4. Confirm the ready message or URL from the spec.
```

```markdown
---
name: test
description: Run the project test suites. Use when asked to test a change or verify the project.
---

# Test the project

1. Read the test strategy in `docs/specs/spec.md`.
2. Run the unit tests with the command from the spec.
3. Run the integration and end-to-end tests that apply to the change.
4. Report each command and its result.
```

### `.codex/hooks.json`

Print the proposed `.codex/hooks.json` for the operator to apply. Codex keeps `.codex/`
read-only for the agent. Codex loads project hooks only when the operator trusts the
project's `.codex/` layer. Tell the operator this before approval. Use the current hook
format from `https://learn.chatgpt.com/docs/hooks`.

Scaffold only hooks that the spec justifies and the operator approves. Show each hook's
event, matcher, and exact command in the Phase 4 review. Keep each hook fast, idempotent,
and non-interactive. A test suite belongs in the `test` skill because it can take too
long for each edit.

Generated hooks must be safe to run unattended:

- Never delete data or change a remote service.
- Never run `git push` or `git commit`.
- Keep file changes inside the project root.
- If a hook needs a tool that may not be installed, check it with `command -v` and exit
  successfully when it is absent.
- Do not write a permission allow-list. The setup skill's `issue_flow` permission profile
  sets session access.

### Dual-harness files

Dual-harness mode is the default. When the operator selects it, write `CLAUDE.md` with
the single line `@AGENTS.md`. This lets Claude Code load the shared project instructions.

For each upstream path-scoped rule, write a `.claude/rules/<name>.md` file. Keep the
upstream `paths:` front-matter and its path patterns. Keep the rule content in
`docs/rules/<name>.md` and make the `.claude/rules/` file point to that file. Do not
duplicate the rule content.

Show these files in the Phase 4 proposal. Preserve an existing `CLAUDE.md` and each
existing rule file until the operator approves the additions.

### `docs/adr/` and `docs/external.md`

Create `docs/adr/0000-template.md` for future architecture decisions. Include the title,
date, status, context, decision, and consequences. Add an ADR only for a contested choice
settled during planning.

Create `docs/external.md` for external facts that the agents need. Record names of
environment variables, setup steps, test accounts, and support paths. Never record
secrets, tokens, or credentials.

### `.gitignore`

Keep generated HTML and the spec package in version control. Append this block to the
project root `.gitignore`. Skip lines that already exist. Show the additions for approval
and preserve every existing line.

```gitignore
.worktrees/
.issue-flow.local.json
```

When the operator selects dual-harness mode, append these upstream Claude Code lines too:

```gitignore
# Claude Code
.claude/settings.local.json
.claude/worktrees/
.claude/agent-memory-local/
CLAUDE.local.md
.claude.local.md
```

Keep the project-specific ignores for dependencies, build output, environment files,
coverage, and editor files in a separate block. Do not ignore files under `docs/specs/`.
