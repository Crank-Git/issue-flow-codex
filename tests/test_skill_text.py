"""Tests for the ported text of the issue-flow skill.

Each check reads one section, not the whole file. Later issues port the other
sections, so a whole-file check would fail on text that is not yet ported.
"""

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "issue-flow"


def section(path, start, end):
    """Return the text from the line that starts with `start` up to the line that starts with `end`."""
    lines = (SKILL_DIR / path).read_text().splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i, line in enumerate(lines) if i > first and line.startswith(end))
    return "\n".join(lines[first:last])


def stage_b():
    return section("SKILL.md", "## Stage B", "## Stage C")


def verdict_section():
    return section("SKILL.md", "### Reading a worker verdict", "### C1")


def invariants():
    return " ".join(section("SKILL.md", "## Core invariants", "# Phase 0").split())


def cross_check_step():
    text = (SKILL_DIR / "SKILL.md").read_text()
    start = text.index("call `spawn_agent` once with")
    return " ".join(text[start:start + 800].split())


def worker_reference():
    return section("references/issue-worker.md", "# Working with issue-workers", "## Rework")


def parallelism_rules():
    return section("references/parallelism.md", "# Parallelism", "## Multiple issues")


class StageBTest(unittest.TestCase):
    def test_stage_b_names_spawn_agent_with_fork_turns_none(self):
        text = stage_b()
        self.assertIn("spawn_agent", text)
        self.assertIn('fork_turns: "none"', text)

    def test_stage_b_creates_the_worktree_before_it_spawns_the_worker(self):
        text = stage_b()
        self.assertIn("worktree.py", text)
        self.assertLess(text.index("worktree.py create"), text.index('task_name: "worker_<n>"'))

    def test_stage_b_launches_an_issue_worker_role(self):
        text = stage_b()
        self.assertIn('agent_type: "issue_worker"', text)
        self.assertIn('task_name: "worker_<n>"', text)

    def test_stage_b_checks_thread_slots_before_a_spawn(self):
        self.assertLess(stage_b().index("list_agents"), stage_b().index('task_name: "worker_<n>"'))

    def test_stage_b_spawns_locate_subagents_as_explorers(self):
        text = stage_b()
        self.assertIn('agent_type: "explorer"', text)
        self.assertIn("gpt-6-luna", text)

    def test_stage_b_comments_the_task_name_at_launch(self):
        self.assertIn("worker launched: <task_name>", stage_b())

    def test_stage_b_has_no_isolation_worktree(self):
        self.assertNotRegex(stage_b(), r"isolation\s*[:=]?\s*[\"`]?worktree")
        self.assertNotIn("isolation:", stage_b())

    def test_stage_b_has_no_fork_subagent_type(self):
        self.assertNotIn('subagent_type: "fork"', stage_b())
        self.assertNotIn("denies a fork whose prompt", stage_b())

    def test_stage_b_points_to_the_spawn_guard(self):
        self.assertIn("hooks/guard-spawn.py", stage_b())


class VerdictLoopTest(unittest.TestCase):
    def test_the_verdict_section_names_wait_agent_and_final_answer(self):
        text = verdict_section()
        self.assertIn("wait_agent", text)
        self.assertIn("FINAL_ANSWER", text)
        self.assertIn("codex.waitMs", text)

    def test_the_verdict_section_has_no_interim_notification_rule(self):
        text = verdict_section().lower()
        self.assertNotIn("interim", text)
        self.assertNotIn("sendmessage", text)

    def test_the_verdict_section_keeps_the_one_followup_rule(self):
        text = verdict_section()
        self.assertIn("followup_task", text)
        self.assertIn("blocked", text)

    def test_the_verdict_section_handles_errored_workers_and_repeat_answers(self):
        text = verdict_section()
        self.assertIn("errored", text)
        self.assertIn("latest", text)

    def test_the_invariants_say_the_pm_ends_its_turn_only_when_the_loop_stops(self):
        text = invariants()
        self.assertIn("ends its turn only when the loop stops", text)
        self.assertNotIn("The PM never blocks", text)

    def test_the_invariants_give_the_reason_for_the_open_turn(self):
        self.assertIn("does not wake an idle PM", invariants())

    def test_the_pm_runs_on_gpt_6_1_sol_and_roles_declare_their_model(self):
        text = section("SKILL.md", "**Model tiers.**", "## The batch model")
        self.assertIn("gpt-6.1-sol", text)
        self.assertNotIn("Opus", text)

    def test_the_cross_check_step_spawns_an_explorer(self):
        text = cross_check_step()
        self.assertIn("spawn_agent", text)
        self.assertIn('agent_type: "explorer"', text)
        self.assertIn("FINAL_ANSWER", text)
        self.assertNotIn("Haiku", text)

    def test_the_doc_read_step_spawns_an_explorer(self):
        text = section("SKILL.md", "   - **If the issue calls an external service", "   - Comment a short plan")
        self.assertIn("spawn_agent", text)
        self.assertIn('agent_type: "explorer"', text)
        self.assertIn("gpt-6-luna", text)


class PortedSectionsTest(unittest.TestCase):
    def test_no_claude_plugin_root_in_the_ported_sections(self):
        for name, text in (("stage B", stage_b()),
                           ("issue-worker reference", worker_reference()),
                           ("parallelism rules", parallelism_rules())):
            with self.subTest(section=name):
                self.assertNotIn("CLAUDE_PLUGIN_ROOT", text)

    def test_brief_carries_the_worktree_field(self):
        self.assertRegex(worker_reference(), r"(?m)^worktree:\s+<absolute path")

    def test_reference_does_not_forbid_the_pm_to_create_the_worktree(self):
        self.assertNotIn("Do not create the worktree", worker_reference())
        self.assertNotIn("isolation:", worker_reference())

    def test_reference_links_the_worker_runbook(self):
        self.assertIn("agents/issue-worker.md", worker_reference())

    def test_parallelism_uses_codex_primitives(self):
        text = parallelism_rules()
        self.assertIn("wait_agent", text)
        self.assertIn("spawn_agent", text)
        self.assertNotRegex(text, r"\bWorkflow\b")
        self.assertNotIn("task-notification", text)

    def test_parallelism_links_the_wait_agent_rules(self):
        self.assertRegex(parallelism_rules(), re.compile(r"\]\([^)]*SKILL\.md"))


if __name__ == "__main__":
    unittest.main()
