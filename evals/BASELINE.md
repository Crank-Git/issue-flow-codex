# Worker model baseline

This page records the worker model eval of Feature 10 (issue #150, Epic 9). It compares `gpt-6-luna` and `gpt-6.1-sol` as the issue-worker model, and it measures the checker on `gpt-6-luna`. The raw numbers are in `evals/candidates/150-worker-model/<suite>-<model>/` (`results.json` and `summary.json`). The raw runs and rollouts stay in the ignored `evals/results/`.

## Setup

| Item | Value |
|---|---|
| Port commit | `d01ad6b` (`dev`) for the worker suites; `500cec1` for the checker suite |
| Codex CLI | `codex-cli 0.167.1` |
| Run date | 2026-11-22 (the worker suites ran a second time on the fixed briefs) |
| Dispatcher model | `gpt-6-luna` (the root session that spawns the role under test) |
| Effort | `medium` for the worker and the checker |
| Runs per case | 2 for the worker suite, 1 for the checker suite |
| Worker cases | 11 (22 runs per model) |
| Checker cases | 11 (11 runs) |
| Suites | `worker-gpt-6-luna`, `checker-gpt-6-luna`, `worker-gpt-6.1-sol` |
| Partial suites | None. Each suite finished. |

The worker suites ran on the upstream brief fix (upstream PR #126, `c7b95d2`): each brief names a single-member batch, so `batch` agrees with `ci: skip`. The first worker results, on the old brief, are replaced. The checker cases did not change, so the checker suite was not run again.

The runner is `scripts/run_evals.py`. A worker run passes when all its graders pass: `hidden_tests`, `verdict`, `diff_scope`, and `gh_log`. `worker-hard-ambiguous-tax` has no hidden tests. Its expected outcome is `needs-feedback`. No run ended in an `error` outcome.

Columns of the case tables: pass = passed runs of all runs; hidden = hidden-test grader passes of runs that have that grader; the token columns are the mean of the runs, in thousands; time is the mean duration in seconds.

## Worker suite: gpt-6-luna

| Case | Pass | Hidden | Input | Cached | Output | Reasoning | Time (s) | Errors |
|---|---|---|---|---|---|---|---|---|
| worker-easy-low-stock-boundary | 2/2 | 2/2 | 1083k | 1018k | 8k | 2k | 175 | 0 |
| worker-easy-negative-qty | 2/2 | 2/2 | 692k | 641k | 6k | 1k | 128 | 0 |
| worker-hard-ambiguous-tax | 2/2 | n/a | 293k | 241k | 2k | 0k | 59 | 0 |
| worker-hard-error-lines | 2/2 | 2/2 | 1034k | 973k | 9k | 3k | 199 | 0 |
| worker-hard-location | 2/2 | 2/2 | 1104k | 1033k | 10k | 3k | 213 | 0 |
| worker-medium-csv-format | 2/2 | 2/2 | 1285k | 1193k | 9k | 3k | 199 | 0 |
| worker-medium-money-refactor | 2/2 | 2/2 | 937k | 876k | 7k | 2k | 166 | 0 |
| worker-medium-price-parse | 2/2 | 2/2 | 1056k | 1002k | 8k | 2k | 180 | 0 |
| worker-large-hard-one-discount | 2/2 | 2/2 | 961k | 893k | 8k | 2k | 181 | 0 |
| worker-large-locate-repeated-sku | 2/2 | 2/2 | 1188k | 1127k | 9k | 3k | 199 | 0 |
| worker-large-medium-report-midnight | 2/2 | 2/2 | 1051k | 995k | 8k | 2k | 165 | 0 |

Suite mean per run: pass rate 22/22 (1.000), hidden-test pass rate 20/20 (1.00), input 971,246 tokens, cached input 908,340, output 7,804, reasoning 2,096, duration 169 s.

## Worker suite: gpt-6.1-sol

| Case | Pass | Hidden | Input | Cached | Output | Reasoning | Time (s) | Errors |
|---|---|---|---|---|---|---|---|---|
| worker-easy-low-stock-boundary | 2/2 | 2/2 | 592k | 533k | 5k | 0k | 119 | 0 |
| worker-easy-negative-qty | 2/2 | 2/2 | 617k | 543k | 4k | 0k | 124 | 0 |
| worker-hard-ambiguous-tax | 2/2 | n/a | 322k | 268k | 2k | 0k | 58 | 0 |
| worker-hard-error-lines | 1/2 | 2/2 | 681k | 612k | 6k | 0k | 174 | 0 |
| worker-hard-location | 2/2 | 2/2 | 495k | 434k | 7k | 0k | 165 | 0 |
| worker-medium-csv-format | 2/2 | 2/2 | 655k | 598k | 5k | 0k | 137 | 0 |
| worker-medium-money-refactor | 1/2 | 2/2 | 627k | 560k | 6k | 0k | 148 | 0 |
| worker-medium-price-parse | 2/2 | 2/2 | 550k | 491k | 5k | 0k | 119 | 0 |
| worker-large-hard-one-discount | 2/2 | 2/2 | 645k | 573k | 6k | 0k | 153 | 0 |
| worker-large-locate-repeated-sku | 0/2 | 1/2 | 461k | 406k | 4k | 0k | 98 | 0 |
| worker-large-medium-report-midnight | 2/2 | 2/2 | 720k | 652k | 6k | 0k | 144 | 0 |

Suite mean per run: pass rate 18/22 (0.818), hidden-test pass rate 19/20 (0.95), input 578,641 tokens, cached input 515,537, output 4,993, reasoning 230, duration 131 s.

## Checker suite: gpt-6-luna

| Case | Pass | Input | Cached | Output | Reasoning | Time (s) |
|---|---|---|---|---|---|---|
| checker-full-easy-low-stock-boundary | 1/1 | 191k | 150k | 2k | 0k | 42 |
| checker-full-easy-negative-qty | 1/1 | 192k | 158k | 2k | 0k | 43 |
| checker-full-hard-error-lines | 1/1 | 269k | 223k | 4k | 0k | 90 |
| checker-full-hard-location | 1/1 | 243k | 198k | 3k | 0k | 70 |
| checker-full-medium-csv-format | 1/1 | 216k | 180k | 3k | 0k | 57 |
| checker-full-medium-money-refactor | 1/1 | 196k | 160k | 2k | 0k | 54 |
| checker-full-medium-price-parse | 0/1 | 214k | 171k | 2k | 0k | 54 |
| checker-partial-hard-error-lines | 1/1 | 273k | 201k | 5k | 1k | 101 |
| checker-full-large-hard-one-discount | 1/1 | 288k | 243k | 4k | 0k | 89 |
| checker-full-large-locate-repeated-sku | 1/1 | 327k | 303k | 4k | 0k | 84 |
| checker-full-large-medium-report-midnight | 1/1 | 245k | 203k | 4k | 1k | 80 |

Suite mean per run: pass rate 10/11 (0.909), input 241,291 tokens, cached input 199,156, output 3,198, reasoning 272, duration 69 s. The checker suite has no hidden tests.

## Failed runs

Grader detail comes from the `record.json` of each run.

| Run | Failed grader | Cause |
|---|---|---|
| sol `worker-hard-error-lines` run 1 | `verdict` | The outcome was `needs-feedback`, expected `ready-to-merge`. The worker committed and pushed the fix, and then asked for a decision about the PR base. The hidden tests passed. |
| sol `worker-medium-money-refactor` run 2 | `verdict` | The verdict file is not valid JSON. The worker reported `ready-to-merge`. The `gpt-6-luna` dispatcher wrote the file incorrectly. The hidden tests passed. |
| sol `worker-large-locate-repeated-sku` run 1 | `verdict` | The verdict file is not valid JSON. The worker reported `ready-to-merge`. The dispatcher wrote the file incorrectly. The hidden tests passed. |
| sol `worker-large-locate-repeated-sku` run 2 | `hidden_tests`, `verdict`, `diff_scope` | The worker could not verify its worktree and returned `blocked` before it changed a file. |
| luna checker `checker-full-medium-price-parse` | `checker_verdict` | The verdict file is not valid JSON. The content was correct (all criteria met). The `gpt-6-luna` dispatcher wrote the file through a JavaScript template literal, which unescaped `\"` inside a JSON string. This is a harness and dispatcher fault, not a checker fault. |

**Grader change after the results.** In the second worker run, 3 `gpt-6-luna` runs failed only one `verdict` check: `localChecks` must name the pre-patch failing run. Those reports said that the new tests "failed against the base implementation" or "failed against the base commit", and the hidden tests passed. The rule `PREPATCH_RUN` in `scripts/run_evals.py` did not accept those words. The operator approved a wider rule after these results were known. The new rule also accepts "against" or "on" followed by "the base", "the original" or "the unchanged", and then "commit", "implementation", "code" or "branch". The saved runs were graded again from their rollouts with the new rule, at no quota cost. The 3 luna runs now pass. No `gpt-6.1-sol` result changed. Under the old rule, `gpt-6-luna` passed 19 of 22 runs, and `worker-easy-low-stock-boundary` failed both luna runs.

## Quota

The operator account quota is read from the rollout `used_percent`, in whole numbers (FR-run-budget-32).

| Run | Quota share |
|---|---|
| First run: worker `gpt-6-luna`, checker `gpt-6-luna`, worker `gpt-6.1-sol` (old brief) | 1 point (70 to 71) |
| Second run: worker `gpt-6-luna` and worker `gpt-6.1-sol` (fixed brief) | 1 point (70 to 71, in the `gpt-6-luna` suite) |
| Total | 2 points |

Epics 7 and 8 used 0 points, so the M5 total is 2 points of the 10% cap. The resolution is 1 point. The eval cannot compare the quota cost of the two models.

## Comparison

| Measure | gpt-6-luna | gpt-6.1-sol |
|---|---|---|
| Pass rate (all graders) | 22/22 (1.0) | 18/22 (0.818) |
| Hidden-test pass rate | 20/20 (1.0) | 19/20 (0.95) |
| Cases that fail both runs | none | `worker-large-locate-repeated-sku` |
| Mean input tokens | 971,246 | 578,641 |
| Mean output tokens | 7,804 | 4,993 |
| Mean reasoning tokens | 2,096 | 230 |
| Mean duration | 169 s | 131 s |

`gpt-6-luna` used about 1.7 times the mean input tokens and about 1.6 times the mean output tokens of `gpt-6.1-sol`. Most of the input is cached. The token price of each model differs, and the quota cost per token is not known. This eval cannot show which model costs more quota.

No `gpt-6-luna` run stopped on the brief. In the first run, on the old brief, 2 of the 3 luna fails were stops on the `batch: standalone` with `ci: skip` conflict.

The checker passed 10 of 11 cases (0.909). The one fail is the dispatcher write error above.

## Decision

The rule was fixed in the plan on issue #150 before any result. The operator delegated the decision to the PM. The default `workerModel` is `gpt-6-luna` only when both conditions are true:

1. Its hidden-test pass rate is at most 5 percentage points below that of `gpt-6.1-sol`.
2. No case fails both `gpt-6-luna` runs while it passes both `gpt-6.1-sol` runs.

Result with the wider `PREPATCH_RUN` rule:

1. The hidden-test pass rate of `gpt-6-luna` is 100%, and that of `gpt-6.1-sol` is 95%. The condition holds.
2. No case failed both `gpt-6-luna` runs. The condition holds.

With the old rule, condition 2 failed on `worker-easy-low-stock-boundary`. The operator chose the wider rule and `gpt-6-luna` on 2026-11-22.

Decision: the default `workerModel` is `gpt-6-luna` at effort `medium`. Under FR-worker-model-eval-27, the default escalation is `gpt-6.1-sol` at effort `medium`. The operator keeps the checker on `gpt-6-luna` (FR-worker-model-eval-28).
