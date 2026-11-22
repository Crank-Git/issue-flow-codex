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

Exception: the `case.json` and `tracker.json` files of the 11 worker cases come from upstream
`dev` at commit `c7b95d29dd0c221a4d1df60de7435ca20c9a5ea7` (upstream PR #126), because no tag
holds them yet. In the old brief, `batch: standalone` disagreed with `ci: skip`. The new brief
names a single-member batch, and each tracker holds its `type:batch` issue. These 22 files are
`patched` in `upstream.lock` until the next upstream tag.

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
| `evals/worker/<case>/hidden/` | The hidden tests. The sandbox of a run holds no copy of them. |
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
    [--out <dir>] [--worker-model <id>] [--worker-effort <level>] [--max-quota-percent <p>|off]
    [--keep]
```

Each run has a new sandbox: a git repo with a local bare origin, the case tracker, a copy of
the plugin tree (without `evals/`, `.git`, `.worktrees`, and `.claude`) that the brief names
as `pluginRoot` and `qualityRule`, a copy of the fake `gh` first on `PATH`, and an isolated
`CODEX_HOME`. The `:workspace` profile lets the agent read the whole disk, so the hidden
tests and the reference patches stay out of every path that the brief names. The isolated home links `auth.json` from
`~/.codex/`, holds `config.toml` with the `issue_flow` permission profile, and
holds a copy of `roles/*.toml` in `agents/`. The runner writes to `~/.codex/` in one case: when Codex replaces
the link with a refreshed token (codex-harness, "auth.json is written through a temporary file"), the runner copies that token back to
`~/.codex/auth.json` (mode 600) and prints one line.

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
`<case>/run-<n>/` with the Codex output, the `gh` log, and all rollout files (the root
rollout holds the quota samples). A record holds `case`, `run`, `suite`, `worker_model`, `worker_effort`,
`dispatcher_model`, `graders` (type, `passed`, `detail`), `outcome`, `error`, `duration_s`,
`usage` (the `scripts/usage.py` totals of all rollouts of the run), `rollouts` (path, id,
role, model, and calls of each), `last_message`, and `sandbox` (its path with `--keep`, else null).

The `outcome` is `pass` (every grader passed), `fail`, or `error`. A run is an `error` when it
times out, when `codex` exits non-zero (the error names the exit code and the last stderr line), or
when a tool output of the agent shows a refused command and a grader failed. `summary.json` counts errors apart from failures. Its pass rate, hidden-test pass
rate, and mean input and output tokens take only the runs that are not an `error`.

### Quota limit

`--max-quota-percent <p>` stops the runner before a new run when the runs of this invocation
used `<p>` percent or more of the weekly quota. The default is 3. `off` removes the limit.
The runner joins the `rate_limits` samples of the root rollouts of the earlier runs, sorts
them by time, and computes the share with `quota_share` of `scripts/usage.py`.

When the limit stops the runner, `summary.json` has `"partial": true` and `stop_reason`, and
the exit code is 1. When the rollouts of run 1 hold no quota sample, the runner stops before
run 2 and asks for `--max-quota-percent off`.

The limit is approximate. `used_percent` is a whole number, and the check runs between runs.
One invocation can use the limit plus one run plus up to 1 point. The share also misses the
quota that run 1 used before its first sample.
