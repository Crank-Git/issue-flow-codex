"""Offline tests for scripts/usage.py. Every fixture is synthetic."""

import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import usage  # noqa: E402

SESSIONS = ROOT / "tests" / "fixtures" / "rollouts"
ROOT_ID = "00000000-0000-7000-8000-000000000001"
WORKER_ID = "00000000-0000-7000-8000-000000000002"
ROOT_FILE = SESSIONS / "2026" / "11" / "20" / f"rollout-2026-11-20T10-00-00-{ROOT_ID}.jsonl"
R1 = 1795000000
R2 = 1795604800


def sample(used, resets):
    return (used, resets)


def run_main(argv, env):
    """Run usage.main with the given environment. Return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = usage.main(argv)
    return code, out.getvalue(), err.getvalue()


class QuotaShareTest(unittest.TestCase):
    def test_quota_single_window(self):
        self.assertEqual(usage.quota_share([sample(10, R1), sample(25, R1), sample(30, R1)]), 20)

    def test_quota_reset_window_43(self):
        samples = [sample(60, R1), sample(95, R1 + 2), sample(0, R2), sample(8, R2)]
        self.assertEqual(usage.quota_share(samples), 43)

    def test_quota_decrease_same_window_is_zero(self):
        self.assertEqual(usage.quota_share([sample(50, R1), sample(40, R1)]), 0)

    def test_quota_resets_at_jitter_same_window(self):
        samples = [sample(10, R1), sample(20, R1 + 1), sample(30, R1 + 3)]
        self.assertEqual(usage.quota_share(samples), 20)

    def test_quota_empty_is_none(self):
        self.assertIsNone(usage.quota_share([]))

    def test_quota_sample_reads_primary_window(self):
        event = {"type": "token_count", "rate_limits": {"primary": {"used_percent": 12.5, "resets_at": R1}}}
        self.assertEqual(usage.quota_sample(event), (12.5, R1))

    def test_quota_sample_without_rate_limits_is_none(self):
        self.assertIsNone(usage.quota_sample({"type": "token_count", "rate_limits": None}))
        self.assertIsNone(usage.quota_sample({"type": "token_count"}))


class ReadTest(unittest.TestCase):
    def test_json_last_token_count_totals(self):
        rollout = usage.read_rollout(ROOT_FILE)
        self.assertEqual(
            (rollout["input"], rollout["cached_input"], rollout["output"], rollout["reasoning"]),
            (700, 340, 70, 35),
        )

    def test_model_calls_skip_unchanged_totals(self):
        self.assertEqual(usage.read_rollout(ROOT_FILE)["calls"], 4)

    def test_root_role_without_parent(self):
        self.assertEqual(usage.read_rollout(ROOT_FILE)["role"], "root")

    def test_broken_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "rollout.jsonl"
            shutil.copy(ROOT_FILE, copy)
            with copy.open("a") as handle:
                handle.write("{not json\n")
            self.assertEqual(usage.read_rollout(copy)["skipped"], 1)
            records, skipped = usage.read_jsonl(copy)
            self.assertEqual(skipped, 1)
            self.assertEqual(records[0]["type"], "session_meta")


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        shutil.copytree(SESSIONS, Path(self.home.name) / "sessions")

    def run_report(self, argv):
        code, out, err = run_main(argv + ["--json"], {"CODEX_HOME": self.home.name})
        return code, (json.loads(out) if out.strip() else None), err

    def test_session_selects_by_session_id_or_id(self):
        _, report, _ = self.run_report(["--session", ROOT_ID])
        self.assertEqual({t["id"] for t in report["threads"]}, {ROOT_ID, WORKER_ID})
        _, report, _ = self.run_report(["--session", WORKER_ID])
        self.assertEqual({t["id"] for t in report["threads"]}, {WORKER_ID})

    def test_unknown_session_exits_2(self):
        code, report, err = self.run_report(["--session", "missing"])
        self.assertEqual(code, 2)
        self.assertIsNone(report)
        self.assertIn("usage.py:", err)

    def test_no_selector_exits_2(self):
        code, _, err = self.run_report([])
        self.assertEqual(code, 2)
        self.assertIn("usage.py:", err)

    def test_cwd_since_filter(self):
        _, report, _ = self.run_report(["--cwd", "/work/proj", "--since", "2026-11-21T00:00:00Z"])
        self.assertEqual({t["id"] for t in report["threads"]}, {ROOT_ID})
        _, report, _ = self.run_report(["--cwd", "/work/proj", "--since", "2026-11-01T00:00:00Z"])
        self.assertEqual({t["id"] for t in report["threads"]}, {ROOT_ID, WORKER_ID})

    def test_since_limits_quota_samples_not_totals(self):
        _, report, _ = self.run_report(["--cwd", "/work/proj", "--since", "2026-11-21T00:00:00Z"])
        self.assertEqual(report["quota"]["share"], 8)
        self.assertEqual(report["totals"]["input"], 700)

    def test_codex_home_env(self):
        code, report, _ = self.run_report(["--session", ROOT_ID])
        self.assertEqual(code, 0)
        self.assertEqual(report["totals"]["threads"], 2)

    def test_default_home_is_dot_codex(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("os.path.expanduser", return_value="/h"):
            self.assertEqual(usage.sessions_root(), os.path.join("/h", ".codex", "sessions"))

    def test_by_role_and_total_rows(self):
        _, report, _ = self.run_report(["--session", ROOT_ID])
        roles = {row["role"]: row for row in report["by_role"]}
        self.assertEqual(roles["root"]["input"], 700)
        self.assertEqual(roles["worker"]["input"], 80)
        self.assertEqual(report["totals"]["input"], 780)
        self.assertEqual(report["totals"]["calls"], 6)
        self.assertEqual(report["totals"]["skipped_lines"], 0)

    def test_quota_share_uses_root_thread_only(self):
        _, report, _ = self.run_report(["--session", ROOT_ID])
        self.assertEqual(report["quota"]["share"], 43)

    def test_no_rate_limits_null_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "sessions" / "2026" / "11" / "20"
            day.mkdir(parents=True)
            lines = [
                {"timestamp": "2026-11-20T10:00:00Z", "type": "session_meta",
                 "payload": {"id": "x1", "session_id": "x1", "cwd": "/work/proj"}},
                {"timestamp": "2026-11-20T10:00:01Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 3}}, "rate_limits": None}},
            ]
            (day / "rollout-x1.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
            _, out, _ = run_main(["--session", "x1", "--json"], {"CODEX_HOME": tmp})
            self.assertIsNone(json.loads(out)["quota"]["share"])
            _, text, _ = run_main(["--session", "x1"], {"CODEX_HOME": tmp})
            self.assertIn("no quota data", text)

    def test_text_table_has_role_rows_and_total(self):
        _, text, _ = run_main(["--session", ROOT_ID], {"CODEX_HOME": self.home.name})
        self.assertIn("/root/worker_1", text)
        self.assertIn("TOTAL", text)
        self.assertIn("quota: 43", text)

    def test_no_network_call(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")):
            code, _, _ = run_main(["--session", ROOT_ID], {"CODEX_HOME": self.home.name})
        self.assertEqual(code, 0)


class LastTokenCountTest(unittest.TestCase):
    def write(self, tmp, lines):
        path = Path(tmp) / "rollout.jsonl"
        path.write_text("".join(line + "\n" for line in lines))
        return path

    def event(self, used):
        return json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": None,
                           "rate_limits": {"primary": {"used_percent": used, "resets_at": R1}}}})

    def test_last_token_count_returns_last_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [self.event(1), json.dumps({"type": "other"}), self.event(2)])
            self.assertEqual(usage.quota_sample(usage.last_token_count(path)), (2, R1))

    def test_last_token_count_none_without_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [json.dumps({"type": "other"})])
            self.assertIsNone(usage.last_token_count(path))

    def test_last_token_count_skips_a_line_that_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [self.event(3), '["token_count"]', '42', '"token_count"'])
            self.assertEqual(usage.quota_sample(usage.last_token_count(path)), (3, R1))

    def test_last_token_count_reads_tail_only(self):
        filler = json.dumps({"type": "filler", "text": "x" * 1000})
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [self.event(1)] + [filler] * 50)
            self.assertIsNone(usage.last_token_count(path, max_bytes=10_000))
            self.assertIsNotNone(usage.last_token_count(path))
            path = self.write(tmp, [filler] * 50 + [self.event(7)])
            self.assertEqual(usage.quota_sample(usage.last_token_count(path, max_bytes=10_000)), (7, R1))


if __name__ == "__main__":
    unittest.main()
