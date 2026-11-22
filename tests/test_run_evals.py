"""Tests for scripts/run_evals.py. A fake `codex` (tests/fake_codex.py) stands in for Codex.

No test uses the network, the real Codex, or the operator's ~/.codex: each test sets
HOME to a temporary directory.
"""

import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_evals  # noqa: E402

FAKE = ROOT / "tests" / "fake_codex.py"
CASE = "worker-easy-negative-qty"
PATCH = ROOT / "evals" / "worker" / CASE / "reference.patch"
VERDICT = {
    "issue": 2, "outcome": "ready-to-merge",
    "criteria": [{"text": "a", "met": True, "evidence": "test_a"},
                 {"text": "b", "met": True, "evidence": "test_b"}],
    "localChecks": "pre-patch: 2 new tests fail as expected",
}


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run-evals-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        (self.home / ".codex").mkdir(parents=True)
        (self.home / ".codex" / "auth.json").write_text('{"token": "secret"}')
        (self.home / ".codex" / "config.toml").write_text("model = 'operator'\n")
        self.verdict = self.tmp / "verdict.json"
        self.verdict.write_text(json.dumps(VERDICT))
        self.record = self.tmp / "fake-record.json"
        self.out = self.tmp / "out"

    def run_suite(self, mode, *extra, suite="worker", case=CASE):
        fake = [sys.executable, str(FAKE), "--mode", mode, "--patch", str(PATCH),
                "--verdict", str(self.verdict), "--record", str(self.record)]
        env = {"HOME": str(self.home), "IFE_CODEX": shlex.join(fake)}
        argv = ["--suite", suite, "--case", case, "--runs", "1", "--out", str(self.out), *extra]
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            code = run_evals.main(argv)
        return code

    def results(self):
        return json.loads((self.out / "results.json").read_text())["records"]

    def fake_saw(self):
        return json.loads(self.record.read_text())


class IsolatedHomeTest(RunnerCase):
    def test_auth_json_is_symlink(self):
        self.run_suite("no-verdict")
        saw = self.fake_saw()
        self.assertTrue(saw["auth_is_link"])
        self.assertEqual(saw["auth_target"], str(self.home / ".codex" / "auth.json"))

    def test_operator_codex_home_unchanged(self):
        def snapshot():
            return {p.name: (p.read_text(), p.stat().st_mtime_ns) for p in (self.home / ".codex").rglob("*") if p.is_file()}
        before = snapshot()
        self.run_suite("worker-pass")
        self.assertEqual(snapshot(), before)
        self.assertEqual(sorted(p.name for p in (self.home / ".codex").iterdir()), ["auth.json", "config.toml"])

    def test_roles_written_to_isolated_agents(self):
        self.run_suite("no-verdict")
        expected = sorted(p.name for p in (ROOT / "roles").glob("*.toml"))
        self.assertEqual(self.fake_saw()["agents"], expected)

    def test_config_holds_the_permission_profile(self):
        self.run_suite("no-verdict")
        self.assertIn('default_permissions = "issue_flow"', self.fake_saw()["config"])

    def test_worker_model_and_effort_edit_role_copy_only(self):
        before = (ROOT / "roles" / "issue-worker.toml").read_bytes()
        self.run_suite("no-verdict", "--worker-model", "gpt-test-model", "--worker-effort", "high")
        saw = self.fake_saw()
        self.assertIn('model = "gpt-test-model"', saw["worker_role"])
        self.assertIn('model_reasoning_effort = "high"', saw["worker_role"])
        self.assertEqual((ROOT / "roles" / "issue-worker.toml").read_bytes(), before)
        self.assertEqual(saw["checker_role"], (ROOT / "roles" / "criteria-checker.toml").read_text())
        record = self.results()[0]
        self.assertEqual((record["worker_model"], record["worker_effort"]), ("gpt-test-model", "high"))

    def test_checker_suite_edits_the_checker_role_copy(self):
        self.run_suite("no-verdict", "--worker-model", "gpt-test-model", suite="checker",
                       case="checker-full-easy-negative-qty")
        saw = self.fake_saw()
        self.assertIn('model = "gpt-test-model"', saw["checker_role"])
        self.assertEqual(saw["worker_role"], (ROOT / "roles" / "issue-worker.toml").read_text())


class ExecTest(RunnerCase):
    def test_login_shell_finds_the_fake_gh_first(self):
        decoy = self.tmp / "decoy"
        decoy.mkdir()
        (decoy / "gh").write_text("#!/bin/sh\n")
        (decoy / "gh").chmod(0o755)
        profile_home = self.tmp / "profile-home"
        profile_home.mkdir()
        for name in (".zshenv", ".zprofile"):
            (profile_home / name).write_text(f'export PATH="{decoy}:$PATH"\n')
        case = run_evals.load_cases(str(ROOT / "evals"), "worker", CASE)[0]
        sandbox, _ = run_evals.build_sandbox(case)
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        env = run_evals.sandbox_env(sandbox, str(self.tmp / "codex-home"))
        env["HOME"] = str(profile_home)
        zsh = shutil.which("zsh")
        if not zsh:
            self.skipTest("zsh is not installed")
        found = subprocess.run([zsh, "-lc", "command -v gh"], env=env, capture_output=True, text=True)
        self.assertEqual(found.stdout.strip(), os.path.join(sandbox, "fakegh", "gh"))

    def test_config_turns_the_login_shell_off(self):
        self.run_suite("no-verdict")
        config = self.fake_saw()["config"]
        self.assertTrue(config.startswith("allow_login_shell = false\n"))

    def test_fake_gh_comes_first_on_path(self):
        self.run_suite("no-verdict")
        saw = self.fake_saw()
        fakegh = os.path.join(saw["sandbox"], "fakegh")
        self.assertEqual(saw["path_first"], fakegh)
        self.assertEqual(saw["gh_on_path"], os.path.join(fakegh, "gh"))

    def test_sandbox_env_sets_the_shell_to_zsh(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            env = run_evals.sandbox_env("/sandbox", "/home")
        self.assertEqual(env["SHELL"], "/bin/zsh")

    def test_exec_sets_approval_never_without_an_a_flag(self):
        self.run_suite("no-verdict")
        argv = self.fake_saw()["argv"]
        self.assertEqual(argv[0], "exec")
        self.assertIn('approval_policy="never"', argv)
        self.assertNotIn("-a", argv)

    def test_exec_runs_the_dispatcher_model(self):
        self.run_suite("no-verdict")
        argv = self.fake_saw()["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")

    def test_exec_closes_stdin(self):
        self.run_suite("no-verdict")
        self.assertTrue(self.fake_saw()["stdin_is_devnull"])

    def test_dispatcher_prompt_spawns_one_worker_fork_none(self):
        self.run_suite("no-verdict")
        prompt = self.fake_saw()["argv"][-1]
        self.assertEqual(prompt.count("Call spawn_agent once"), 1)
        self.assertIn('agent_type: "issue_worker"', prompt)
        self.assertIn('fork_turns: "none"', prompt)
        self.assertIn("issue:        #2", prompt)
        self.assertNotIn(str(ROOT), prompt)
        self.assertIn("worktree:     ", prompt)
        self.assertNotIn("{plugin_dir}", prompt)

    def test_checker_prompt_names_the_checker_role_and_head(self):
        self.run_suite("no-verdict", suite="checker", case="checker-full-easy-negative-qty")
        prompt = self.fake_saw()["argv"][-1]
        self.assertIn('agent_type: "criteria_checker"', prompt)
        self.assertNotIn("{head_sha}", prompt)

    def test_hidden_tests_absent_during_run(self):
        self.run_suite("worker-pass")
        self.assertEqual(self.fake_saw()["hidden_during_run"], [])
        self.assertTrue(self.results()[0]["graders"][0]["passed"])

    def test_plugin_root_and_quality_rule_are_copies_inside_the_sandbox(self):
        self.run_suite("no-verdict")
        saw = self.fake_saw()
        prompt = saw["argv"][-1]
        plugin = next(line.split(None, 1)[1] for line in prompt.splitlines() if line.startswith("pluginRoot:"))
        rule = next(line.split(None, 1)[1] for line in prompt.splitlines() if line.startswith("qualityRule:"))
        self.assertTrue(plugin.startswith(saw["sandbox"] + os.sep), plugin)
        self.assertEqual(rule, os.path.join(plugin, "docs", "rules", "quality.md"))
        self.assertEqual(saw["plugin_has"], {"roles": True, "evals": False, "git": False})


class SymlinkedTempTest(RunnerCase):
    def test_brief_worktree_equals_git_toplevel_under_a_symlinked_tmpdir(self):
        real = self.tmp / "real-tmp"
        real.mkdir()
        link = self.tmp / "link-tmp"
        link.symlink_to(real)
        case = run_evals.load_cases(str(ROOT / "evals"), "worker", CASE)[0]
        with mock.patch.dict(os.environ, {"TMPDIR": str(link)}):
            tempfile.tempdir = None
            self.addCleanup(setattr, tempfile, "tempdir", None)
            sandbox, repo = run_evals.build_sandbox(case)
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        state = run_evals.start_state(case, sandbox, repo)
        brief = run_evals.brief_of(case).replace("{plugin_dir}", run_evals.plugin_dir(sandbox))
        worktree = run_evals.make_worktree(case, "worker", repo, brief, state["head_sha"])
        toplevel = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=worktree,
                                  capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(worktree, toplevel)
        self.assertEqual(sandbox, os.path.realpath(sandbox))
        argv = run_evals.exec_argv(repo, "out.txt", "prompt")
        self.assertEqual(argv[argv.index("-C") + 1], os.path.realpath(repo))


class RecordTest(RunnerCase):
    def test_record_holds_the_fields_and_passing_graders_of_a_run(self):
        code = self.run_suite("worker-pass")
        record = self.results()[0]
        self.assertEqual(code, 0)
        self.assertEqual(record["outcome"], "pass")
        for key in ("case", "run", "suite", "worker_model", "worker_effort", "graders", "outcome",
                    "duration_s", "usage", "rollouts", "sandbox"):
            self.assertIn(key, record)
        self.assertEqual([g["type"] for g in record["graders"]], ["hidden_tests", "verdict", "diff_scope", "gh_log"])
        self.assertTrue(all(g["passed"] for g in record["graders"]), record["graders"])

    def test_record_sums_the_usage_of_all_rollouts(self):
        self.run_suite("worker-pass")
        usage = self.results()[0]["usage"]
        self.assertEqual((usage["input"], usage["output"]), (1000, 100))

    def test_run_copies_every_rollout(self):
        self.run_suite("worker-pass")
        names = sorted(p.name for p in (self.out / CASE / "run-1" / "rollouts").iterdir())
        self.assertEqual(names, ["rollout-root.jsonl", "rollout-worker.jsonl"])

    def test_missing_verdict_fails_and_keeps_last_message(self):
        code = self.run_suite("no-verdict")
        record = self.results()[0]
        verdict = next(g for g in record["graders"] if g["type"] == "verdict")
        self.assertEqual(code, 1)
        self.assertEqual(record["outcome"], "fail")
        self.assertFalse(verdict["passed"])
        self.assertIn("does not exist", verdict["detail"])
        self.assertEqual(record["last_message"], "final words of the dispatcher")

    def test_denial_in_a_tool_output_of_a_failed_run_marks_error(self):
        self.run_suite("denied")
        record = self.results()[0]
        self.assertEqual(record["outcome"], "error")
        self.assertIn("sandbox denied", record["error"])

    def test_denial_in_a_run_that_passes_every_grader_stays_a_pass(self):
        self.run_suite("denied-pass")
        self.assertEqual(self.results()[0]["outcome"], "pass")

    def test_denial_text_outside_a_tool_output_stays_a_failure(self):
        self.run_suite("quoted")
        self.assertEqual(self.results()[0]["outcome"], "fail")

    def test_nonzero_exit_without_events_marks_error(self):
        self.run_suite("crash")
        record = self.results()[0]
        self.assertEqual(record["outcome"], "error")
        self.assertIn("codex exit 3", record["error"])

    def test_nonzero_exit_after_events_marks_error_with_the_last_stderr_line(self):
        self.run_suite("crash-late")
        record = self.results()[0]
        self.assertEqual(record["outcome"], "error")
        self.assertEqual(record["error"], "codex exit 4: boom")

    def test_replaced_auth_link_copies_the_token_back_to_the_operator_file(self):
        auth = self.home / ".codex" / "auth.json"
        auth.chmod(0o644)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.run_suite("replace-auth")
        self.assertEqual(auth.read_text(), '{"token": "refreshed"}')
        self.assertFalse(auth.is_symlink())
        self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(stderr.getvalue().splitlines()), 1)

    def test_unchanged_auth_link_leaves_the_operator_file_alone(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.run_suite("no-verdict")
        self.assertEqual((self.home / ".codex" / "auth.json").read_text(), '{"token": "secret"}')
        self.assertEqual(stderr.getvalue(), "")

    def test_timeout_marks_error(self):
        real = run_evals.load_cases

        def short(*args):
            return [dict(case, timeout_s=1) for case in real(*args)]

        with mock.patch.object(run_evals, "load_cases", short):
            self.run_suite("hang")
        record = self.results()[0]
        self.assertEqual(record["outcome"], "error")
        self.assertIn("timeout after 1s", record["error"])

    @staticmethod
    def summary_of_records():
        def record(case, outcome, hidden, input_tokens, output_tokens):
            return {"case": case, "outcome": outcome, "graders": [{"type": "hidden_tests", "passed": hidden}],
                    "usage": {"input": input_tokens, "output": output_tokens}}
        return run_evals.summarize([
            record("a", "pass", True, 100, 10), record("a", "fail", False, 300, 30),
            record("a", "error", False, 9000, 900), record("b", "pass", True, 50, 5)])

    def test_summary_counts_errors_apart_from_failures(self):
        summary = self.summary_of_records()
        self.assertEqual((summary["cases"]["a"]["errors"], summary["cases"]["a"]["failed"]), (1, 1))
        self.assertEqual(summary["suite"]["runs"], 4)

    def test_summary_means_skip_error_runs(self):
        summary = self.summary_of_records()
        self.assertEqual(summary["cases"]["a"]["hidden_tests_pass_rate"], 0.5)
        self.assertEqual(summary["cases"]["a"]["mean_input_tokens"], 200)
        self.assertEqual(summary["suite"]["mean_output_tokens"], round((10 + 30 + 5) / 3, 3))

    def test_summary_json_is_written(self):
        self.run_suite("worker-pass")
        summary = json.loads((self.out / "summary.json").read_text())
        self.assertEqual(summary["cases"][CASE]["hidden_tests_pass_rate"], 1)
        self.assertEqual(summary["suite"]["mean_input_tokens"], 1000)


class OrderTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="run-evals-order-")
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def test_large_cases_run_last(self):
        cases = run_evals.load_cases(str(ROOT / "evals"), "worker")
        with mock.patch.object(run_evals, "load_cases", return_value=cases), \
                mock.patch.object(run_evals, "run_case") as run_case, \
                mock.patch.object(run_evals, "write_json"), \
                contextlib.redirect_stdout(io.StringIO()):
            run_case.side_effect = lambda case, suite, n, args, run_dir: {
                "case": case["name"], "outcome": "pass", "graders": [], "usage": {"input": 0, "output": 0},
                "error": None, "run": n}
            run_evals.main(["--suite", "worker", "--runs", "1", "--out", self.out,
                           "--max-quota-percent", "off"])
        tags = ["large" in call.args[0]["tags"] for call in run_case.call_args_list]
        self.assertEqual(tags, sorted(tags))
        self.assertTrue(any(tags) and not all(tags))


class PrepatchWordingTest(unittest.TestCase):
    def test_words_that_name_the_pre_patch_run(self):
        for text in ("pre-patch: 2 new tests fail", "the tests failed before the fix",
                     "both new tests failed against the base implementation as expected",
                     "both new tests failed against the base commit as expected"):
            with self.subTest(text=text):
                self.assertRegex(text, run_evals.PREPATCH_RUN)

    def test_a_plain_test_run_does_not_name_the_pre_patch_run(self):
        self.assertNotRegex("python3 -m unittest: 12 tests passed", run_evals.PREPATCH_RUN)


class MainErrorTest(unittest.TestCase):
    def test_a_sandbox_failure_prints_one_line_and_exits_nonzero(self):
        out = tempfile.mkdtemp(prefix="run-evals-error-")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        stderr = io.StringIO()
        with mock.patch.object(run_evals, "run_case", side_effect=RuntimeError("git init failed")), \
                contextlib.redirect_stderr(stderr):
            code = run_evals.main(["--suite", "worker", "--case", CASE, "--runs", "1", "--out", out,
                                   "--max-quota-percent", "off"])
        self.assertNotEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "error: git init failed\n")

    def test_a_case_error_in_a_run_prints_one_line_and_exits_nonzero(self):
        out = tempfile.mkdtemp(prefix="run-evals-error-")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        stderr = io.StringIO()
        with mock.patch.object(run_evals, "run_case", side_effect=run_evals.CaseError("no issue number")), \
                contextlib.redirect_stderr(stderr):
            code = run_evals.main(["--suite", "worker", "--case", CASE, "--runs", "1", "--out", out,
                                   "--max-quota-percent", "off"])
        self.assertNotEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "error: no issue number\n")


def write_root_rollout(run_dir, samples):
    """Write a root rollout whose token_count events carry `samples`, a list of (used_percent, resets_at)."""
    folder = Path(run_dir) / "rollouts"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"timestamp": "2026-11-22T10:00:00.000Z", "type": "session_meta", "payload": {"id": "root"}}]
    for minute, (used, resets) in enumerate(samples):
        lines.append({"timestamp": f"2026-11-22T10:{minute:02d}:30.000Z", "type": "event_msg", "payload": {
            "type": "token_count", "rate_limits": {"primary": {"used_percent": used, "resets_at": resets}}}})
    (folder / "rollout-root.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")


class QuotaLimitTest(unittest.TestCase):
    WINDOW = 1795000000

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="run-evals-quota-"))
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def invoke(self, runs_samples, *extra):
        """Run three runs of one case with a fake run_case; run n writes runs_samples[n - 1]."""
        def fake_run_case(case, suite, n, args, run_dir):
            write_root_rollout(run_dir, runs_samples[n - 1])
            return {"case": case["name"], "outcome": "pass", "graders": [], "run": n,
                    "usage": {"input": 0, "output": 0}, "error": None}
        with mock.patch.object(run_evals, "run_case", side_effect=fake_run_case) as run_case, \
                contextlib.redirect_stdout(io.StringIO()):
            code = run_evals.main(["--suite", "worker", "--case", CASE, "--runs", "3",
                                   "--out", str(self.out), *extra])
        summary = json.loads((self.out / "summary.json").read_text())
        return code, run_case.call_count, summary

    def test_stops_at_limit_writes_partial(self):
        w = self.WINDOW
        code, calls, summary = self.invoke([[(10, w), (11, w)], [(12, w), (14, w)], [(15, w)]],
                                           "--max-quota-percent", "3")
        self.assertEqual(calls, 2)
        self.assertIs(summary["partial"], True)
        self.assertIn("4", summary["stop_reason"])
        self.assertEqual(code, 1)

    def test_default_limit_is_3(self):
        w = self.WINDOW
        _, calls, summary = self.invoke([[(10, w), (13, w)], [(13, w)], [(13, w)]])
        self.assertEqual(calls, 1)
        self.assertTrue(summary["partial"])

    def test_below_limit_runs_all_and_is_not_partial(self):
        w = self.WINDOW
        code, calls, summary = self.invoke([[(10, w), (11, w)], [(12, w)], [(12, w)]])
        self.assertEqual(calls, 3)
        self.assertEqual((summary["partial"], summary["stop_reason"], code), (False, None, 0))

    def test_limit_off_never_stops(self):
        w = self.WINDOW
        _, calls, summary = self.invoke([[(10, w), (60, w)], [(90, w)], [(99, w)]], "--max-quota-percent", "off")
        self.assertEqual(calls, 3)
        self.assertFalse(summary["partial"])

    def test_share_spans_window_reset(self):
        w = self.WINDOW
        # Run 1 shares 1 point. After the reset (new resets_at) run 2 counts from 0: 1 + 2.5 = 3.5.
        _, calls, summary = self.invoke([[(98, w), (99, w)], [(2.5, w + 604800)], [(3, w + 604800)]])
        self.assertEqual(calls, 2)
        self.assertTrue(summary["partial"])

    def test_missing_quota_stops_before_second_run(self):
        code, calls, summary = self.invoke([[], [], []])
        self.assertEqual(calls, 1)
        self.assertTrue(summary["partial"])
        self.assertIn("--max-quota-percent off", summary["stop_reason"])

    def test_rejects_a_limit_that_is_not_a_number(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_evals.main(["--suite", "worker", "--max-quota-percent", "lots", "--out", str(self.out)])


if __name__ == "__main__":
    unittest.main()
