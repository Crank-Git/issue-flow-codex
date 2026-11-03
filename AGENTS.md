# issue-flow for Codex

This repository is the Codex port of issue-flow. Upstream is the Claude Code plugin
`issue-flow` by sniper7kills (MIT), in `Sniper7Kills-LLC/claude-plugins`. The port runs
the same autonomous issue loop as a native Codex CLI plugin.

Current state: the spec is approved (2026-11-03). No code exists yet. Epic 0 imports
upstream `issue-flow--v0.17.0` and builds the test harness.

## Design

Design lives in `docs/specs/`. Read `docs/specs/spec.md` and the relevant
`docs/specs/features/*.md` before you build a feature. Two supplement pages carry
the facts that most work needs:

- `docs/specs/pages/codex-harness.md` — each Codex fact the port uses, with evidence.
- `docs/specs/pages/porting-inventory.md` — the port mode of each upstream file.

Use the words in the `## Terms` table of `docs/specs/spec.md`. Never use a word from
its "Do not use" column.

## Layout

The port keeps upstream paths, so a sync compares files one to one.

| Path | Holds |
|---|---|
| `.codex-plugin/plugin.json` | The Codex plugin manifest. |
| `.agents/plugins/marketplace.json` | The Codex marketplace entry. |
| `skills/<name>/` | The seven upstream skills and the port's `setup` skill. |
| `agents/*.md` | Upstream agent instructions, the source for `roles/`. |
| `roles/*.toml` | Codex role files, built by `scripts/build_roles.py`. |
| `hooks/` | `hooks.json`, the preflight hook, the spawn guard, the role guard. |
| `references/` | Shared references: forge, STE, external APIs, finding policy. |
| `scripts/` | Python 3 standard-library scripts. No package install step. |
| `tests/` | Unit tests. |
| `upstream.lock` | The upstream tag and the port mode of each file. |
| `docs/specs/` | The spec package. |
| `docs/rules/` | The writing, quality, and external-API rules. |
| `docs/adr/` | Architecture decision records. |
| `docs/external.md` | Facts outside the code. Names only, never secrets. |

## Commands

| Purpose | Command |
|---|---|
| Unit tests | `python3 -m unittest discover -s tests` |
| Manifest check | `python3 scripts/validate_manifests.py` |
| Lock check | `python3 scripts/upstream_sync.py --check` |
| Build role files | `python3 scripts/build_roles.py` (`--check` fails on a stale file; CI runs it) |
| Render the spec | `python3 docs/specs/render-spec.py` |
| Live conformance | `python3 scripts/conformance.py` (uses the operator's Codex quota; ask first) |

The `test` skill runs the first three. A change is done when all three pass.

## Rules

Read the matching file before you write:

- `docs/rules/ste.md` — before you write any prose, code comment, docstring, test name, issue, or PR body.
- `docs/rules/quality.md` — before you write or review Python in `scripts/`, `hooks/`, or `tests/`.
- `docs/rules/external-apis.md` — before you write anything that depends on Codex, `gh`, `tea`, GitHub Actions, or upstream behavior.

## Conventions

- Each PR body names the upstream file and the section that it ports, or states `port-only`.
- Each PR body cites the evidence for each Codex claim: a `codex-harness.md` fact, a `--help` output, a source path, or a doc URL.
- A `verbatim` file in `upstream.lock` is never edited. If it must change, change its mode to `patched` in the same PR and say why.
- Commits use the conventional style: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Branch model: dev-and-live. Batches merge into `dev`. A person approves each promotion from `dev` to `main`.

## Filing gate

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
  - Found at review of an integration branch (`epic/<n>-<slug>` or `batch/<n>-<slug>`)
    → a documentation commit on that branch, before the CI-trigger commit.
  - Found with nothing open → a line on the PM's status issue, picked up by the next batch.

- A changelog or spec-changelog entry records a **decision**, made at a batch gate. No
  rule, hook, CI check, or test may require a changelog row, a spec edit, or a
  docs-accuracy pass **per change set or per batch member** — a batch that shipped as
  planned earns no line. A test that asserts per-member bookkeeping agreement re-creates
  the churn the filing gate exists to prevent, and fails review here.

The full policy is `references/finding-policy.md` (after the Epic 0 import).
