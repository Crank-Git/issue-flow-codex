# Quality rules — reviewed per rule, pass or fail

These rules apply to the Python in `scripts/`, `hooks/`, and `tests/`. The worker's
self-review and the PM's batch review give one pass or fail verdict per rule.

- Use the Python 3.11 standard library only. Add no third-party import.
- No try/except that only re-raises, or that logs and continues.
- A hook fails open: on an unexpected payload it allows the call and exits 0. The one exception is a deliberate deny decision.
- No defensive checks against states the code already excludes.
- No abstraction with a single caller. Inline it until a second caller exists.
- No configuration for a value that nothing varies.
- No dead code and no commented-out code.
- A script that fails exits nonzero and writes one line to stderr that names the cause.
- A script that prints machine-read output prints one JSON object per line.
- A test name is one behavior, in present tense: `denies a brief with fork_turns all`.
- A test of a hook feeds a recorded Codex payload. Record new payloads from a live run, never from memory.
- A comment states what the code cannot: the reason, the constraint, or the evidence. Delete comments that restate the code.
