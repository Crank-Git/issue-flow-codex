"""Tests for hooks/guard-spawn.py. Ported from upstream scripts/test-guard-spawn.py.

Runs the hook as a subprocess fed a PreToolUse payload on stdin, then checks the
decision. Two properties matter as much as the blocking itself: the guard never
blocks a spawn that would have worked, and it fails open on anything it does not
understand.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard-spawn.py"
TEMPLATE = ROOT / "skills" / "issue-flow" / "references" / "issue-worker.md"


def handoff_brief():
    """Return the real handoff-brief template, so a template change cannot blind the guard."""
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("## Handoff brief")
    block = text[text.index("```", start) + 3:]
    return block[block.index("\n") + 1:block.index("```")]


BRIEF = handoff_brief()


def spawn(**tool_input):
    return {"tool_name": "Agent", "tool_input": tool_input}


def fork(prompt, **extra):
    return spawn(subagent_type="fork", description="build #42", prompt=prompt, **extra)


class GuardTestCase(unittest.TestCase):
    def run_hook(self, payload, env=None):
        """Return the parsed hook output, or None when the hook allowed the call."""
        environment = dict(os.environ)
        environment.pop("ISSUE_FLOW_SPAWN_GUARD", None)
        environment.pop("ISSUE_FLOW_FORK_GUARD", None)
        environment.update(env or {})
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def decision(self, payload, env=None):
        output = self.run_hook(payload, env)
        return output["hookSpecificOutput"].get("permissionDecision") if output else None

    def assertDenied(self, payload, env=None):
        self.assertEqual(self.decision(payload, env), "deny")

    def assertAllowed(self, payload, env=None):
        self.assertIsNone(self.decision(payload, env))

    def reason(self, payload, env=None):
        return self.run_hook(payload, env)["hookSpecificOutput"]["permissionDecisionReason"]


class BriefTemplateTest(unittest.TestCase):
    def test_extracts_the_handoff_brief_from_the_template(self):
        self.assertIn("crossCheck:", BRIEF)
        self.assertIn("base:", BRIEF)


class NameCheckTest(GuardTestCase):
    def test_denies_a_named_spawn_without_isolation(self):
        self.assertDenied(spawn(name="reviewer", subagent_type="general-purpose",
                                prompt="review the diff"))

    def test_deny_reason_offers_the_remedies_and_names_the_hook_event(self):
        output = self.run_hook(spawn(name="reviewer", subagent_type="general-purpose", prompt="x"))
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        for expected in ("Drop `name`", 'isolation: "worktree"', "ISSUE_FLOW_SPAWN_GUARD"):
            self.assertIn(expected, reason)
        self.assertEqual(output["hookSpecificOutput"].get("hookEventName"), "PreToolUse")

    def test_deny_reason_puts_dropping_the_name_first(self):
        self.assertIn("Drop `name`", self.reason(spawn(name="reviewer", prompt="x")))

    def test_deny_reason_warns_that_isolation_strands_a_workers_child(self):
        self.assertIn("commits never reach your branch",
                      self.reason(spawn(name="reviewer", prompt="x")))

    def test_deny_reason_says_the_escape_is_read_at_session_start(self):
        reason = self.reason(spawn(name="reviewer", prompt="x"))
        self.assertIn("settings.json", reason)
        self.assertIn("start a new session", reason)

    def test_allows_a_named_spawn_with_isolation(self):
        self.assertAllowed(spawn(name="worker-42", isolation="worktree",
                                 subagent_type="issue-flow:issue-worker"))

    def test_allows_an_unnamed_spawn(self):
        self.assertAllowed(spawn(subagent_type="Explore", prompt="locate"))

    def test_allows_an_unnamed_isolated_spawn(self):
        self.assertAllowed(spawn(isolation="worktree", prompt="x"))

    def test_treats_an_empty_name_as_no_name(self):
        self.assertAllowed(spawn(name="   ", prompt="x"))

    def test_ignores_a_bash_call(self):
        self.assertAllowed({"tool_name": "Bash", "tool_input": {
            "command": "gh pr checks 21", "run_in_background": True}})

    def test_allows_run_in_background_alone(self):
        self.assertAllowed(spawn(subagent_type="general-purpose", run_in_background=True,
                                 prompt="x"))

    def test_guards_the_legacy_task_tool_name(self):
        self.assertDenied({"tool_name": "Task", "tool_input": {"name": "reviewer", "prompt": "x"}})


class ModeTest(GuardTestCase):
    def test_asks_in_ask_mode(self):
        self.assertEqual(self.decision(spawn(name="reviewer", prompt="x"),
                                       {"ISSUE_FLOW_SPAWN_GUARD": "ask"}), "ask")

    def test_denies_by_default(self):
        self.assertDenied(spawn(name="reviewer", prompt="x"))

    def test_denies_for_an_unrecognized_setting(self):
        for value in ("DENY", "  deny  ", "anything-else"):
            with self.subTest(value=value):
                self.assertDenied(spawn(name="r", prompt="x"), {"ISSUE_FLOW_SPAWN_GUARD": value})

    def test_disables_the_guard_for_each_off_spelling(self):
        for value in ("off", "OFF", "0", "false", "no"):
            with self.subTest(value=value):
                self.assertAllowed(spawn(name="r", prompt="x"), {"ISSUE_FLOW_SPAWN_GUARD": value})


class FailOpenTest(GuardTestCase):
    def test_allows_malformed_json(self):
        self.assertAllowed("{not json")

    def test_allows_an_empty_payload(self):
        self.assertAllowed({})

    def test_allows_a_null_tool_input(self):
        self.assertAllowed({"tool_name": "Agent", "tool_input": None})

    def test_allows_a_string_tool_input(self):
        self.assertAllowed({"tool_name": "Agent", "tool_input": "x"})

    def test_allows_empty_stdin(self):
        self.assertAllowed("")

    def test_allows_a_fork_with_no_prompt(self):
        self.assertAllowed(spawn(subagent_type="fork"))

    def test_allows_a_fork_with_a_non_string_prompt(self):
        self.assertAllowed(spawn(subagent_type="fork", prompt=42))

    def test_allows_a_non_string_subagent_type(self):
        self.assertAllowed(spawn(subagent_type=["fork"], prompt=BRIEF))


class ForkCheckTest(GuardTestCase):
    def test_denies_a_fork_that_carries_the_handoff_brief(self):
        self.assertDenied(fork(BRIEF))

    def test_fork_deny_reason_names_the_worker_and_the_switch(self):
        reason = self.reason(fork(BRIEF))
        for expected in ("issue-flow:issue-worker", "ISSUE_FLOW_FORK_GUARD", "`crossCheck:`"):
            self.assertIn(expected, reason)

    def test_denies_a_hand_written_brief_with_list_and_bold_markup(self):
        self.assertDenied(fork(
            "Build issue #42.\n- **base:** origin/epic/7-x\n- **ci:** skip\n- **members:** 3\n"))

    def test_matches_the_fork_type_case_insensitively(self):
        self.assertDenied(spawn(subagent_type=" Fork ", prompt=BRIEF))

    def test_allows_a_plain_fork(self):
        self.assertAllowed(fork("Summarize the diff and stop."))

    def test_allows_a_fork_that_describes_a_failing_build(self):
        self.assertAllowed(fork(
            "Issue: #12 keeps failing.\nBranch: fix/x\nCI: red on lint\nFind out why."))

    def test_allows_a_fork_with_two_issue_flow_labels_only(self):
        self.assertAllowed(fork("crossCheck: see above\nmembers: 2\nNow explain the batch model."))

    def test_allows_the_brief_sent_to_the_issue_worker(self):
        self.assertAllowed(spawn(subagent_type="issue-flow:issue-worker", name="worker-42",
                                 isolation="worktree", prompt=BRIEF))

    def test_allows_the_general_purpose_fallback_carrying_the_brief(self):
        self.assertAllowed(spawn(subagent_type="general-purpose", prompt=BRIEF))

    def test_allows_labels_mid_line(self):
        self.assertAllowed(fork("Note the issue: base: ci: members: are all mentioned inline here."))

    def test_denies_a_brief_laid_out_in_each_way_a_model_re_lays_the_template(self):
        layouts = {
            "a numbered list": "1. issue: #42\n2. base: origin/dev\n3. crossCheck: n/a\n",
            "markdown headings": "## Issue: #42\n## Base: origin/dev\n## Members: 1\n",
            "a table": "| field | value |\n|---|---|\n| issue | #42 |\n| base | dev |\n| members | 1 |\n",
            "pretty-printed JSON": '{\n  "issue": 42,\n  "base": "origin/dev",\n  "crossCheck": "n/a"\n}',
            "= separators": "issue = #42\nbase = origin/dev\nsteRule = x\n",
            "a spelled-out cross-check": "Issue: #42\nBase: origin/dev\nCross-check: n/a\n",
            "a space before the colon": "issue : #42\nbase : dev\nforge : {type: gitea}\n",
            "capitalized labels only": "Issue: #42\nBase: dev\nCrossCheck: n/a\n",
        }
        for label, prompt in layouts.items():
            with self.subTest(layout=label):
                self.assertDenied(fork(prompt))

    def test_refuses_a_named_build_fork_for_the_fork_not_the_name(self):
        self.assertIn("issue-flow:issue-worker", self.reason(fork(BRIEF, name="worker-42")))

    def test_denies_a_fork_that_quotes_the_brief_fields_one_per_line(self):
        # Documented false positive: the guard cannot tell a quote from a brief.
        self.assertDenied(fork("Explain these fields:\n- issue:\n- base:\n- members:\n"))


class ForkSwitchTest(GuardTestCase):
    def test_off_allows_a_build_fork(self):
        self.assertAllowed(fork(BRIEF), {"ISSUE_FLOW_FORK_GUARD": "off"})

    def test_off_allows_a_plain_fork(self):
        self.assertAllowed(fork("Summarize the diff."), {"ISSUE_FLOW_FORK_GUARD": "off"})

    def test_turning_off_the_name_check_leaves_the_fork_check_on(self):
        self.assertDenied(fork(BRIEF), {"ISSUE_FLOW_SPAWN_GUARD": "off"})

    def test_turning_off_the_fork_check_leaves_the_name_check_on(self):
        self.assertDenied(spawn(name="reviewer", prompt="x"), {"ISSUE_FLOW_FORK_GUARD": "off"})

    def test_asks_instead_of_denying_in_fork_ask_mode(self):
        self.assertEqual(self.decision(fork(BRIEF), {"ISSUE_FLOW_FORK_GUARD": "ask"}), "ask")

    def test_ask_reason_says_to_approve_only_if_deliberate(self):
        reason = self.reason(fork(BRIEF), {"ISSUE_FLOW_FORK_GUARD": "ask"})
        self.assertIn("approve only if deliberate", reason)


if __name__ == "__main__":
    unittest.main()
