# Worker model baseline

This page records the worker model eval of Feature 10 (issue #150, Epic 9). It compares `gpt-6-luna` and `gpt-6.1-sol` as the issue-worker model, and it measures the checker on `gpt-6-luna`. The raw numbers are in `evals/candidates/150-worker-model/<suite>-<model>/` (`results.json` and `summary.json`). The raw runs and rollouts stay in the ignored `evals/results/`.

## Setup

| Item | Value |
|---|---|
| Port commit | `500cec1` (head of `epic/146-worker-model-eval`) |
| Codex CLI | `codex-cli 0.167.1` |
| Run date | 2026-11-22 |
| Dispatcher model | `gpt-6-luna` (the root session that spawns the role under test) |
| Effort | `medium` for the worker and the checker |
| Runs per case | 2 for the worker suite, 1 for the checker suite |
| Worker cases | 11 (22 runs per model) |
| Checker cases | 11 (11 runs) |
| Suites | `worker-gpt-6-luna`, `checker-gpt-6-luna`, `worker-gpt-6.1-sol` |
| Partial suites | None. Each suite finished. |

The runner is `scripts/run_evals.py`. A worker run passes when all its graders pass: `hidden_tests`, `verdict`, `diff_scope`, and `gh_log`. `worker-hard-ambiguous-tax` has no hidden tests. Its expected outcome is `needs-feedback`. No run ended in an `error` outcome.

Columns of the case tables: pass = passed runs of all runs; hidden = hidden-test grader passes of runs that have that grader; the token columns are the mean of the runs, in thousands; time is the mean duration in seconds.

## Worker suite: gpt-6-luna

| Case | Pass | Hidden | Input | Cached | Output | Reasoning | Time (s) | Errors |
|---|---|---|---|---|---|---|---|---|
| worker-easy-low-stock-boundary | 2/2 | 2/2 | 933k | 882k | 6k | 2k | 141 | 0 |
| worker-easy-negative-qty | 2/2 | 2/2 | 639k | 580k | 4k | 0k | 92 | 0 |
| worker-hard-ambiguous-tax | 2/2 | n/a | 305k | 257k | 3k | 1k | 58 | 0 |
| worker-hard-error-lines | 1/2 | 2/2 | 1113k | 1052k | 9k | 2k | 185 | 0 |
| worker-hard-location | 2/2 | 2/2 | 1162k | 1108k | 10k | 2k | 208 | 0 |
| worker-medium-csv-format | 2/2 | 2/2 | 987k | 933k | 7k | 1k | 155 | 0 |
| worker-medium-money-refactor | 1/2 | 2/2 | 716k | 677k | 6k | 2k | 133 | 0 |
| worker-medium-price-parse | 2/2 | 2/2 | 984k | 937k | 7k | 1k | 150 | 0 |
| worker-large-hard-one-discount | 2/2 | 2/2 | 1206k | 1143k | 9k | 2k | 193 | 0 |
| worker-large-locate-repeated-sku | 2/2 | 2/2 | 945k | 874k | 8k | 2k | 198 | 0 |
| worker-large-medium-report-midnight | 1/2 | 2/2 | 1215k | 1165k | 9k | 3k | 185 | 0 |

Suite mean per run: pass rate 19/22 (0.864), hidden-test pass rate 20/20 (1.0), input 927,721 tokens, cached input 873,449, output 7,101, reasoning 1,638, duration 154 s.

## Worker suite: gpt-6.1-sol

| Case | Pass | Hidden | Input | Cached | Output | Reasoning | Time (s) | Errors |
|---|---|---|---|---|---|---|---|---|
| worker-easy-low-stock-boundary | 1/2 | 1/2 | 308k | 260k | 3k | 0k | 71 | 0 |
| worker-easy-negative-qty | 2/2 | 2/2 | 512k | 466k | 4k | 0k | 101 | 0 |
| worker-hard-ambiguous-tax | 2/2 | n/a | 353k | 306k | 2k | 0k | 59 | 0 |
| worker-hard-error-lines | 2/2 | 2/2 | 563k | 505k | 6k | 0k | 152 | 0 |
| worker-hard-location | 2/2 | 2/2 | 648k | 573k | 7k | 0k | 171 | 0 |
| worker-medium-csv-format | 2/2 | 2/2 | 521k | 477k | 5k | 0k | 133 | 0 |
| worker-medium-money-refactor | 2/2 | 2/2 | 582k | 532k | 5k | 0k | 120 | 0 |
| worker-medium-price-parse | 2/2 | 2/2 | 513k | 455k | 4k | 0k | 112 | 0 |
| worker-large-hard-one-discount | 2/2 | 2/2 | 616k | 554k | 6k | 0k | 154 | 0 |
| worker-large-locate-repeated-sku | 2/2 | 2/2 | 714k | 658k | 6k | 0k | 158 | 0 |
| worker-large-medium-report-midnight | 1/2 | 2/2 | 503k | 455k | 5k | 0k | 115 | 0 |

Suite mean per run: pass rate 20/22 (0.909), hidden-test pass rate 19/20 (0.95), input 530,253 tokens, cached input 476,509, output 4,763, reasoning 241, duration 122 s.

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
| luna `worker-hard-error-lines` run 1 | `verdict` | The outcome was `needs-feedback`, expected `ready-to-merge`. The worker said the brief conflicts: `batch: standalone` with `ci: skip`. The implementation was complete, and the hidden tests of the run passed. |
| luna `worker-medium-money-refactor` run 2 | `verdict` | The outcome was `ready-to-merge`. `localChecks` did not name the pre-patch failing run in the expected form. It said `tests/test_money.py failed before implementation with ModuleNotFoundError for inventory.money`. The hidden tests passed. |
| luna `worker-large-medium-report-midnight` run 1 | `verdict` | The outcome was `blocked`, expected `ready-to-merge`. The worker pushed the fix and the tests, and then stopped on the same `standalone` with `ci: skip` brief conflict. The hidden tests passed. |
| sol `worker-easy-low-stock-boundary` run 2 | `hidden_tests`, `verdict`, `diff_scope` | The worker ran its first command in a mistyped worktree path and returned `blocked` ("The assigned worktree path does not exist."). The branch changed nothing, so the hidden tests failed. Counted as a sol fail. |
| sol `worker-large-medium-report-midnight` run 1 | `verdict` | The outcome was `checkpoint`, expected `ready-to-merge`. The worker pushed a commit with 30 passing tests. The PR and the review steps remained. The hidden tests passed. |
| luna checker `checker-full-medium-price-parse` | `checker_verdict` | The verdict file is not valid JSON. The content was correct (all criteria met). The `gpt-6-luna` dispatcher wrote the file through a JavaScript template literal, which unescaped `\"` inside a JSON string. This is a harness and dispatcher fault, not a checker fault. |

Observation. The brief conflict that stopped two luna runs (`batch: standalone` with `ci: skip`) is in the imported upstream case fixtures. Those files are `verbatim` in `upstream.lock`, so this port does not edit them. The sol runs met the same brief and did not stop on it.

## Quota

The operator account quota is read from the rollout `used_percent`, in whole numbers (FR-run-budget-32). The value was 70 at the start of the three suites and 71 at the end. The step happened during the `gpt-6.1-sol` suite.

| Suite | Quota share |
|---|---|
| `worker-gpt-6-luna` | 0 points |
| `checker-gpt-6-luna` | 0 points |
| `worker-gpt-6.1-sol` | at most 1 point |
| Total | 1 point |

Epics 7 and 8 used 0 points, so the M5 total is 1 point of the 10% cap. The resolution is 1 point. The eval cannot compare the quota cost of the two models.

## Comparison

| Measure | gpt-6-luna | gpt-6.1-sol |
|---|---|---|
| Pass rate (all graders) | 19/22 (0.864) | 20/22 (0.909) |
| Hidden-test pass rate | 20/20 (1.0) | 19/20 (0.95) |
| Cases that fail both runs | none | none |
| Mean input tokens | 927,721 | 530,253 |
| Mean output tokens | 7,101 | 4,763 |
| Mean reasoning tokens | 1,638 | 241 |
| Mean duration | 154 s | 122 s |

`gpt-6-luna` used about 1.75 times the mean input tokens and about 1.5 times the mean output tokens of `gpt-6.1-sol`. Most of the input is cached. The token price of each model differs, and the quota cost per token is not known. This eval cannot show which model costs more quota.

The three `gpt-6-luna` fails and the two `gpt-6.1-sol` fails are all `verdict` or run-start failures. In every luna fail, the hidden tests passed.

The checker passed 10 of 11 cases (0.909). The one fail is the dispatcher write error above.

## Decision

The rule was fixed in the plan on issue #150 before any result. The operator delegated the decision to the PM. The default `workerModel` is `gpt-6-luna` only when both conditions are true:

1. Its hidden-test pass rate is at most 5 percentage points below that of `gpt-6.1-sol`.
2. No case fails both `gpt-6-luna` runs while it passes both `gpt-6.1-sol` runs.

Result:

1. The hidden-test pass rate of `gpt-6-luna` is 100%, and that of `gpt-6.1-sol` is 95%. The condition holds.
2. No case failed both `gpt-6-luna` runs. The condition holds.

Decision: the default `workerModel` is `gpt-6-luna` at effort `medium`. Under FR-worker-model-eval-27, the default escalation is `gpt-6.1-sol` at effort `medium`. The checker stays on `gpt-6-luna` until the operator rules on the open question below.

Open question for the operator (FR-worker-model-eval-28): the checker passed 10 of 11 cases, and the one fail was a dispatcher write error. Keep the checker on `gpt-6-luna`?
