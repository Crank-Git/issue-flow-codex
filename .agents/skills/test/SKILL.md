---
name: test
description: Run the repository checks. Use before you open or update a PR, after you change a script, hook, skill, role, or upstream.lock, or when asked to test.
---

# Test issue-flow-codex

Run the three checks from the repository root, in this order. Stop at the first failure and report its output verbatim.

1. Run the unit tests: `python3 -m unittest discover -s tests`
2. Run the manifest check: `python3 scripts/validate_manifests.py`
3. Run the lock check: `python3 scripts/upstream_sync.py --check`

A change is done when all three exit 0.

If a script does not exist yet, report "not built yet" for that check. Epic 0 and Epic 1 build them.

These checks never run Codex. For live harness checks, use the `conformance` skill.
