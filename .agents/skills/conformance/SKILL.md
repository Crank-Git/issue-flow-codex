---
name: conformance
description: Run the live Codex conformance suite. Use after a Codex upgrade, before a release, or when a harness fact is in doubt. It uses the operator's Codex quota.
---

# Run the conformance suite

**This suite runs live Codex sessions and uses the operator's quota. Ask the operator before you start it.**

1. Confirm the Codex version: `codex --version`.
2. Ask the operator for approval. State the version and that the suite runs about 12 short sessions on `gpt-6-luna`.
3. If the operator approves, run `python3 scripts/conformance.py`.
4. Report each probe line verbatim.
5. For each failed probe, name the fact in `docs/specs/pages/codex-harness.md` that it checks.

A failed probe is a behavior finding under the filing gate in `AGENTS.md`: it earns a tracker issue.

If `scripts/conformance.py` does not exist yet, stop and say so. Epic 0 builds it.
