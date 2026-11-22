# Worker and checker evals

This directory holds the eval cases of the worker model eval (Feature 10). The cases measure
what a worker and a criteria checker do on one concrete issue, so that a model choice can be
compared with a baseline.

## Source and license

The cases come from the upstream repository `Sniper7Kills-LLC/claude-plugins`
(https://github.com/Sniper7Kills-LLC/claude-plugins), tag `issue-flow--v0.21.0`, commit
`39f2261b11cc1a5c6cf75ee1310bc2419767644f`. Each case file is a byte-identical copy. The
`verbatim` entries of `upstream.lock` record the upstream path and the SHA-256 of each file,
and `python3 scripts/upstream_sync.py --check` fails when a copy differs.

The upstream cases are under the MIT license:

```
MIT License

Copyright (c) 2026 Sniper7Kills LLC

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Layout

| Path | Content |
|---|---|
| `evals/worker/<case>/case.json` | One worker case: the prompt, the fixture, and the graders. |
| `evals/worker/<case>/tracker.json` | The tracker state at the start of the case: one issue with its acceptance criteria. |
| `evals/worker/<case>/hidden/` | The hidden tests. The agent never sees them. |
| `evals/worker/<case>/reference.patch` | A reference solution. `tests/test_eval_cases.py` proves that the hidden tests pass with it. |
| `evals/worker/_fixture/` | The small project of the cases tagged `small`. |
| `evals/worker/_fixture_large/` | The large project of the cases tagged `large`. |
| `evals/checker/<case>/case.json` | One criteria-checker case. It reuses the fixture, the tracker, and the patch of a worker case. |
| `evals/checker/checker-partial-hard-error-lines/partial.patch` | An incomplete patch. The checker must report an unmet criterion. |
| `evals/fakegh/gh` | The fake `gh`. It serves the tracker of one run from `$IFE_TRACKER` and logs each call to `$IFE_GH_LOG`. An unknown command exits 1 and the log records an error. |
| `evals/results/` | Run results. Git ignores this directory. |

The worker case `worker-hard-ambiguous-tax` expects the outcome `needs-feedback`. It has no
`reference.patch` and no `hidden/` directory, so 10 worker cases have a reference patch.

## Case files

The `prompt` of a case is the upstream dispatcher prompt for Claude Code. The port runner
builds the Codex dispatcher prompt from the text between `BRIEF START` and `BRIEF END`, so
`case.json` stays a copy of upstream. The graders are `hidden_tests`, `verdict`,
`diff_scope`, `gh_log` (worker), and `checker_verdict`, `refs_unchanged`, `gh_log` (checker).
The upstream README at the tag above defines the case format, the graders, and the schemas of
`tracker.json` and the `gh` log.

## Run the cases

`scripts/run_evals.py` runs the cases of one suite on `codex exec` and grades each run. It
ports `scripts/run-evals.py` of upstream. A run uses the quota of the operator's Codex
account, so run it only on request.

```
python3 scripts/run_evals.py --suite worker|checker [--case <glob>] [--tag <tag>] [--runs N]
    [--out <dir>] [--worker-model <id>] [--worker-effort <level>] [--keep]
```

Each run has a new sandbox: a git repo with a local bare origin, the case tracker, the fake
`gh` first on `PATH`, and an isolated `CODEX_HOME`. The isolated home links `auth.json` from
`~/.codex/` (never a copy), holds `config.toml` with the `issue_flow` permission profile, and
holds a copy of `roles/*.toml` in `agents/`. The runner never writes to `~/.codex/`.

- The dispatcher runs `codex exec -m gpt-6-luna` with `approval_policy="never"` and stdin
  closed. It spawns one `issue_worker` (worker suite) or `criteria_checker` (checker suite)
  with `fork_turns: "none"` and the brief of the case.
- `--worker-model` and `--worker-effort` change `model` and `model_reasoning_effort` in the
  isolated copy of the role that the suite spawns: `issue-worker.toml` for the worker suite,
  `criteria-checker.toml` for the checker suite. The role file model wins over a spawn model
  (codex-harness fact 31). The files in `roles/` stay unchanged.
- The hidden tests are copied into a separate clone after the agent has finished.
- `large` cases run last.
- `IFE_CODEX` replaces the `codex` binary. The tests use it with `tests/fake_codex.py`.

The runner writes `results.json` and `summary.json` in `evals/results/<UTC time>/`, and
`<case>/run-<n>/` with the Codex output, the `gh` log, and the root rollout files (for the
quota samples). A record holds `case`, `run`, `worker_model`, `worker_effort`,
`dispatcher_model`, `graders` (type, `passed`, `detail`), `outcome`, `error`, `duration_s`,
`usage` (the `scripts/usage.py` totals of all rollouts of the run), and `last_message`.

The `outcome` is `pass` (every grader passed), `fail`, or `error`. A run is an `error` when it
times out, when `codex` exits non-zero with no events, or when the sandbox refuses a command of
the agent. `summary.json` counts errors apart from failures. Its pass rate, hidden-test pass
rate, and mean input and output tokens take only the runs that are not an `error`.
