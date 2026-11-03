"""Tests for scripts/gitea-ci-watch.sh. Ported from upstream scripts/test-gitea-ci-watch.py.

Runs the real script under bash with a stub `tea`. The stub replays a queue of
responses, one per call, and logs the arguments it receives. A failed request must
never read as green, and an API error must not read as "no run".
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gitea-ci-watch.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"

STUB = """#!/usr/bin/env bash
# Replays the next queued response. A line "EXIT <n>" fails the call with code n.
printf '%s\\n' "$*" >> "$STUB_DIR/args"
n=$(cat "$STUB_DIR/count" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STUB_DIR/count"
line=$(sed -n "${n}p" "$STUB_DIR/queue")
case "$line" in
  EXIT*) exit "${line#EXIT }" ;;
  "") line=$(tail -n 1 "$STUB_DIR/queue") ;;   # past the end: repeat the last one
esac
printf '%s\\n' "$line"
"""


def runs(*items):
    return json.dumps({"total_count": len(items), "workflow_runs": list(items)})


def run_(status, conclusion=None):
    return {"status": status, "conclusion": conclusion, "head_sha": SHA}


def watch(queue, sha=SHA, **env):
    """Return (exit code, stdout, stub call arguments)."""
    with tempfile.TemporaryDirectory() as d:
        stub = os.path.join(d, "tea")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        with open(os.path.join(d, "queue"), "w") as f:
            f.write("\n".join(queue) + "\n")
        environment = dict(os.environ)
        environment.update({"IFW_TEA": stub, "STUB_DIR": d, "IFW_NONE_SLEEP": "0",
                            "IFW_RUN_SLEEP": "0", **{k: str(v) for k, v in env.items()}})
        result = subprocess.run(["bash", str(SCRIPT), sha], capture_output=True, text=True,
                                env=environment, timeout=60)
        args_path = os.path.join(d, "args")
        args = open(args_path).read().splitlines() if os.path.exists(args_path) else []
        return result.returncode, result.stdout.strip(), args


class VerdictTest(unittest.TestCase):
    def expect(self, queue, verdict, code=0, **env):
        got_code, got, _ = watch(queue, **env)
        self.assertEqual((got, got_code), (verdict, code))

    def test_reports_success_for_an_immediate_green_run(self):
        self.expect([runs(run_("completed", "success"))], "success")

    def test_anchors_the_request_to_the_commit(self):
        _, _, args = watch([runs(run_("completed", "success"))])
        self.assertIn(f"head_sha={SHA}", args[0])
        self.assertIn("/actions/runs", args[0])

    def test_waits_out_runs_that_are_still_going(self):
        self.expect([runs(run_("in_progress")), runs(run_("queued")),
                     runs(run_("completed", "success"))], "success")

    def test_reports_failure_when_one_workflow_is_red(self):
        self.expect([runs(run_("completed", "success"), run_("completed", "failure"))], "failure")

    def test_counts_a_workflow_skipped_by_its_own_condition_as_a_pass(self):
        self.expect([runs(run_("completed", "success"), run_("completed", "skipped"))], "success")

    def test_does_not_pass_a_completed_run_with_no_conclusion(self):
        self.expect([runs(run_("completed"))], "failure")

    def test_reports_failure_for_timed_out(self):
        self.expect([runs(run_("completed", "timed_out"))], "failure")

    def test_keeps_watching_while_one_run_is_still_going(self):
        self.expect([runs(run_("completed", "success"), run_("in_progress")),
                     runs(run_("completed", "success"), run_("completed", "success"))], "success")

    def test_reads_the_runs_response_shape(self):
        self.expect([json.dumps({"runs": [run_("completed", "success")]})], "success")


class NoRunAndTimeoutTest(unittest.TestCase):
    def test_reports_no_run_registered_when_no_run_appears_in_the_window(self):
        self.assertEqual(watch([runs()], IFW_NONE_LIMIT=3)[:2], (0, "no-run-registered"))

    def test_watches_a_run_that_registers_late(self):
        queue = [runs(), runs(), runs(run_("completed", "success"))]
        self.assertEqual(watch(queue, IFW_NONE_LIMIT=3)[:2], (0, "success"))

    def test_reports_timed_out_when_runs_are_still_going_at_the_limit(self):
        self.assertEqual(watch([runs(run_("in_progress"))], IFW_MAX=3)[:2], (0, "timed-out"))


class FailedRequestTest(unittest.TestCase):
    def assert_watch_error(self, response):
        self.assertEqual(watch([response])[:2], (1, "watch-error"))

    def test_reports_watch_error_for_an_api_error_object(self):
        self.assert_watch_error('{"errors": null, "message": "not found", "url": "http://x/api/swagger"}')

    def test_reports_watch_error_when_the_tea_call_fails(self):
        self.assert_watch_error("EXIT 1")

    def test_reports_watch_error_for_an_empty_response(self):
        self.assert_watch_error("")

    def test_reports_watch_error_for_a_response_that_is_not_json(self):
        self.assert_watch_error("<html>502 Bad Gateway</html>")

    def test_reports_watch_error_for_a_json_list(self):
        self.assert_watch_error("[]")


class ArgumentTest(unittest.TestCase):
    def test_refuses_an_abbreviated_sha_before_any_request(self):
        code, _, args = watch([runs(run_("completed", "success"))], sha="abc123")
        self.assertEqual(code, 2)
        self.assertEqual(args, [])

    def test_refuses_a_missing_sha(self):
        code, _, _ = watch([runs(run_("completed", "success"))], sha="")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
