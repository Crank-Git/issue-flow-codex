"""Tests for hooks/guard-role.py.

Runs the hook as a subprocess fed a PreToolUse payload on stdin. The `Bash` and
`apply_patch` payloads are recorded from a live subagent (Codex 0.166.0, gpt-6-luna). The
spawn payloads copy the live `collaborationspawn_agent` tool name and field names.
"""

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard-role.py"
FIXTURES = ROOT / "tests" / "fixtures" / "hooks"
APPLY_PATCH = json.loads((FIXTURES / "pre_tool_use_apply_patch.json").read_text())
BASH = json.loads((FIXTURES / "pre_tool_use_bash.json").read_text())


def payload(base, role, **changes):
    result = copy.deepcopy(base)
    if role is None:
        del result["agent_type"]
        del result["agent_id"]
    else:
        result["agent_type"] = role
    result.update(changes)
    return result


def bash(role, command):
    return payload(BASH, role, tool_input={"command": command})


def patch(role, *paths):
    text = "*** Begin Patch\n" + "".join(f"*** Add File: {p}\n+x\n" for p in paths) + "*** End Patch"
    return payload(APPLY_PATCH, role, tool_input={"command": text})


def spawn(role, spawned):
    return payload(BASH, role, tool_name="collaborationspawn_agent",
                   tool_input={"task_name": "t", "agent_type": spawned, "fork_turns": "none",
                               "message": "brief"})


def run(stdin, **env):
    if not isinstance(stdin, str):
        stdin = json.dumps(stdin)
    environment = {k: v for k, v in os.environ.items() if k != "ISSUE_FLOW_ROLE_GUARD"}
    environment.update(env)
    return subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                          input=stdin, env=environment, timeout=30)


def decision(result):
    """Return (permissionDecision, reason) of a result, or (None, None) for an allow."""
    if not result.stdout:
        return None, None
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    return output["permissionDecision"], output["permissionDecisionReason"]


class RoleGuardTest(unittest.TestCase):
    def assertDenied(self, stdin, *words, **env):
        result = run(stdin, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        kind, reason = decision(result)
        self.assertEqual(kind, "deny", result.stdout)
        for word in words:
            self.assertIn(word, reason)

    def assertAllowed(self, stdin, **env):
        result = run(stdin, **env)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_denies_apply_patch_for_code_auditor(self):
        self.assertDenied(patch("code_auditor", "note.txt"), "code_auditor", "apply_patch")

    def test_allows_apply_patch_for_issue_worker(self):
        self.assertAllowed(patch("issue_worker", "note.txt"))

    def test_denies_spawn_of_issue_worker_from_issue_worker(self):
        self.assertDenied(spawn("issue_worker", "issue_worker"), "issue_worker", "spawn")

    def test_allows_spawn_of_another_role_from_issue_worker(self):
        self.assertAllowed(spawn("issue_worker", "code_auditor"))

    def test_allows_every_call_with_no_agent_type(self):
        for stdin in (patch(None, "note.txt"), bash(None, "git push origin main"),
                      spawn(None, "issue_worker")):
            self.assertAllowed(stdin)

    def test_off_allows_a_denied_call(self):
        stdin = patch("code_auditor", "note.txt")
        self.assertDenied(stdin)
        self.assertAllowed(stdin, ISSUE_FLOW_ROLE_GUARD="off")

    def test_allows_the_recorded_bash_call_of_code_auditor(self):
        self.assertAllowed(BASH)

    def test_denies_playwright_tools_for_code_auditor(self):
        self.assertDenied(payload(BASH, "code_auditor", tool_name="mcp__playwright__browser_click"),
                          "code_auditor", "mcp__playwright__")

    def test_allows_playwright_tools_for_ux_explorer(self):
        self.assertAllowed(payload(BASH, "ux_explorer", tool_name="mcp__playwright__browser_click"))

    def test_denies_bash_prefixes_for_each_role(self):
        cases = {
            "code_auditor": ["git commit -m x", "git push", "gh issue list", "gh pr view 1",
                             "tea issues", "  git commit -m x"],
            "review_scribe": ["git push --force origin x", "gh pr merge 3", "tea pr merge 3"],
            "deploy_verifier": ["git commit -m x", "git push"],
            "ux_explorer": ["git status"],
        }
        for role, commands in cases.items():
            for command in commands:
                with self.subTest(role=role, command=command):
                    self.assertDenied(bash(role, command), role)

    def test_allows_bash_commands_outside_the_prefixes(self):
        cases = [("code_auditor", "git status --short"), ("code_auditor", "teapot --help"),
                 ("review_scribe", "git push origin x"), ("review_scribe", "gh pr view 1"),
                 ("deploy_verifier", "gh pr view 1"), ("ux_explorer", "gitk"),
                 ("issue_worker", "git push origin x")]
        for role, command in cases:
            with self.subTest(role=role, command=command):
                self.assertAllowed(bash(role, command))

    def test_denies_apply_patch_and_spawn_for_ci_watcher(self):
        self.assertDenied(patch("ci_watcher", "note.txt"), "ci_watcher")
        self.assertDenied(spawn("ci_watcher", "code_auditor"), "ci_watcher")

    def test_denies_apply_patch_for_deploy_verifier(self):
        self.assertDenied(patch("deploy_verifier", "note.txt"), "deploy_verifier")

    def test_denies_ux_explorer_patch_outside_its_scratch_directory(self):
        self.assertDenied(patch("ux_explorer", ".worktrees/review/t1/a.md", "src/app.py"),
                          "ux_explorer", ".worktrees/review/")
        self.assertDenied(patch("ux_explorer", ".worktrees/review/../../src/app.py"), "ux_explorer")
        self.assertDenied(patch("ux_explorer", "/etc/passwd"), "ux_explorer")

    def test_allows_ux_explorer_patch_inside_its_scratch_directory(self):
        self.assertAllowed(patch("ux_explorer", ".worktrees/review/t1/a.md"))
        self.assertAllowed(patch("ux_explorer", "/home/user/project/.worktrees/review/t1/a.md"))

    def test_allows_an_unknown_role(self):
        self.assertAllowed(patch("default", "note.txt"))

    def test_allows_a_payload_that_is_not_json(self):
        self.assertAllowed("not json")

    def test_allows_a_payload_whose_tool_input_is_a_string(self):
        self.assertAllowed(payload(APPLY_PATCH, "ux_explorer", tool_input="raw"))
        self.assertAllowed(payload(BASH, "code_auditor", tool_input="git push"))


if __name__ == "__main__":
    unittest.main()
