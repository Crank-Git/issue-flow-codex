# 0002 — Keep the port in a separate repository that tracks upstream

Date: 2026-11-03
Status: accepted

## Context

issue-flow belongs to sniper7kills under the MIT license. The operator's `Crank-Git/claude-plugins` repository is a fork of it. The port can live in the upstream repository, in a hard fork, or in a separate repository that copies upstream changes on each release.

## Decision

The port lives in `Crank-Git/issue-flow-codex`. Upstream files keep their upstream paths. `upstream.lock` records the upstream tag and the port mode of each file. `scripts/upstream_sync.py` copies `verbatim` files and reports the changes to the other files.

## Consequences

- The port releases on its own schedule, with its own version.
- Each upstream release needs one sync change set. A scheduled job opens an issue for it.
- The README and the license credit upstream.
