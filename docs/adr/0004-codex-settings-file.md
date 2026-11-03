# 0004 — Keep the Codex-only settings in their own file

Date: 2026-11-03
Status: accepted

## Context

The port needs five settings that upstream does not have: `pmModel`, `workerModel`, `workerEffort`, `helperModel` and `waitMs`. The first design kept them as a `codex` block inside `.issue-flow.json`, the run configuration that upstream also reads and writes. Issue #25 found that no upstream 0.17.0 code writes `.issue-flow.json`: an upstream PM rewrites it from the step 11 text, and that text has no rule to keep unknown keys. A Claude Code co-operator can therefore drop the block, and the Codex settings would fall back to defaults with no warning. `docs/specs/features/03-loop-operations.md` already named the fallback for this case.

## Decision

The Codex-only settings live in `.issue-flow.codex.json` at the repository root, with flat keys. `.issue-flow.json` keeps only upstream keys, in the upstream format. `hooks/guard-wait.py` reads `waitMs` from the new file.

## Consequences

- An upstream PM cannot lose a Codex setting, because it never opens the file.
- Both harnesses can share `.issue-flow.json` unchanged (Goal 4).
- Values that both harnesses own, such as `pluginVersion`, still sit in the shared file; #77 moves the Codex plugin version out of it.
