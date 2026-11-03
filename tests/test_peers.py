"""Tests for scripts/peers.py. Ported from upstream scripts/test-peers.py.

The fixtures are the real shapes read off disk during upstream issue #25: an
in-process peer under the default `auto` backend, a `tmux`-backed peer from a pinned
session, undrained mail, and the lead entry that must never be reported as a peer.
The detector runs against a temporary directory, never the real ~/.claude/teams.
Remove this module with scripts/peers.py (issue #16).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import peers  # noqa: E402

NOW = 1786681000.0
LEAD = {
    "agentId": "team-lead@session-aaa",
    "name": "team-lead",
    "tmuxPaneId": "leader",
    "backendType": "in-process",
    "joinedAt": int((NOW - 3600) * 1000),
}
IN_PROCESS_PEER = {
    "agentId": "probe-b@session-aaa",
    "name": "probe-b",
    "tmuxPaneId": "in-process",
    "backendType": "in-process",
    "joinedAt": int((NOW - 120) * 1000),
}
TMUX_PEER = {
    "agentId": "worker-18@session-bbb",
    "name": "worker-18",
    "tmuxPaneId": "%7",
    "backendType": "tmux",
    "joinedAt": int((NOW - 7200) * 1000),
}


def lead_for(session):
    """Return the lead entry as the harness writes it, with agentId matched to the session."""
    return dict(LEAD, agentId=f"team-lead@{session}")


def make_team(root, session, members, inboxes=None):
    directory = os.path.join(root, session)
    os.makedirs(os.path.join(directory, "inboxes"), exist_ok=True)
    with open(os.path.join(directory, "config.json"), "w") as handle:
        json.dump({"name": session, "leadAgentId": f"team-lead@{session}", "members": members},
                  handle)
    for name, mail in (inboxes or {}).items():
        with open(os.path.join(directory, "inboxes", f"{name}.json"), "w") as handle:
            json.dump(mail, handle)
    return directory


class PeersTestCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="peers-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.projects = os.path.join(self.work, "projects")
        os.makedirs(self.projects)

    def collect_with_staleness(self):
        return peers.collect(self.work, stale_hours=24, now=NOW, projects_dir=self.projects)

    def two_teams(self):
        make_team(self.work, "session-aaa", [lead_for("session-aaa"), IN_PROCESS_PEER],
                  inboxes={"probe-b": [{"msg": "one"}, {"msg": "two"}]})
        make_team(self.work, "session-bbb", [lead_for("session-bbb"), TMUX_PEER])


class CollectTest(PeersTestCase):
    def test_reports_no_peers_for_a_team_with_only_its_lead(self):
        make_team(self.work, "session-lead-only", [lead_for("session-lead-only")])
        self.assertFalse(peers.collect(self.work))

    def test_reports_one_in_process_peer_with_its_undrained_mail(self):
        make_team(self.work, "session-aaa", [lead_for("session-aaa"), IN_PROCESS_PEER],
                  inboxes={"probe-b": [{"msg": "one"}, {"msg": "two"}]})
        teams = peers.collect(self.work)
        self.assertEqual(len(teams), 1)
        self.assertEqual(len(teams[0]["members"]), 1)
        member = teams[0]["members"][0]
        self.assertEqual((member["name"], member["backend"], member["pendingMail"]),
                         ("probe-b", "in-process", 2))

    def test_keeps_the_pane_of_a_tmux_peer(self):
        self.two_teams()
        teams = peers.collect(self.work)
        self.assertEqual(len(teams), 2)
        tmux = [m for t in teams for m in t["members"] if m["backend"] == "tmux"]
        self.assertEqual([m["pane"] for m in tmux], ["%7"])

    def test_yields_no_peers_for_a_missing_teams_directory(self):
        self.assertEqual(peers.collect(os.path.join(self.work, "does-not-exist")), [])

    def test_skips_a_team_config_that_is_not_json(self):
        self.two_teams()
        broken = os.path.join(self.work, "session-broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "config.json"), "w") as handle:
            handle.write("{not json")
        self.assertEqual(len(peers.collect(self.work)), 2)

    def test_counts_only_unread_mail_as_pending(self):
        # Real records stay in the inbox with an explicit "read" flag.
        self.two_teams()
        mail = [{"from": "team-lead", "text": "one", "read": True},
                {"from": "team-lead", "text": "two", "read": True},
                {"from": "team-lead", "text": "three", "read": False}]
        with open(os.path.join(self.work, "session-aaa", "inboxes", "probe-b.json"), "w") as handle:
            json.dump(mail, handle)
        counts = {m["name"]: m["pendingMail"] for t in peers.collect(self.work)
                  for m in t["members"]}
        self.assertEqual(counts["probe-b"], 1)

    def test_returns_a_flat_list_without_stale_hours(self):
        self.two_teams()
        plain = peers.collect(self.work)
        self.assertIsInstance(plain, list)
        self.assertEqual(len(plain), 2)


class AgeTest(unittest.TestCase):
    def test_renders_120_seconds_as_2m(self):
        self.assertEqual(peers.age(IN_PROCESS_PEER["joinedAt"], NOW), "2m")

    def test_renders_7200_seconds_as_2h(self):
        self.assertEqual(peers.age(TMUX_PEER["joinedAt"], NOW), "2h")

    def test_renders_a_missing_join_time_as_a_question_mark(self):
        self.assertEqual(peers.age(None, NOW), "?")


class RenderTest(PeersTestCase):
    def test_states_that_there_are_no_live_peer_sessions(self):
        empty = peers.render([], NOW)
        self.assertIn("No live peer sessions", empty[0])

    def test_lists_each_peer_and_the_shutdown_request(self):
        self.two_teams()
        rendered = "\n".join(peers.render(peers.collect(self.work), NOW))
        for expected in ("probe-b", "worker-18", "shutdown_request"):
            self.assertIn(expected, rendered)


class StalenessTest(PeersTestCase):
    # A roster alone is not proof of life: 72 entries from a five-day-dead session sat on
    # the machine that filed upstream issue #25. Old rosters must not read as work in flight.
    def age_the_rosters(self):
        self.two_teams()
        week_ago = NOW - 7 * 24 * 3600
        os.utime(os.path.join(self.work, "session-aaa", "config.json"), (week_ago, week_ago))
        os.utime(os.path.join(self.work, "session-bbb", "config.json"), (NOW - 60, NOW - 60))

    def test_splits_a_fresh_team_from_a_week_old_team(self):
        self.age_the_rosters()
        live, stale = self.collect_with_staleness()
        self.assertEqual([t["session"] for t in live], ["session-bbb"])
        self.assertEqual([t["session"] for t in stale], ["session-aaa"])

    def test_carries_the_path_of_a_stale_team(self):
        self.age_the_rosters()
        _, stale = self.collect_with_staleness()
        self.assertIn("path", stale[0])

    def test_summarizes_stale_teams_without_listing_their_members(self):
        self.age_the_rosters()
        live, stale = self.collect_with_staleness()
        summary = "\n".join(peers.render(live, NOW, stale))
        self.assertIn("1 stale team directory", summary)
        self.assertNotIn("probe-b", summary)

    def test_lists_stale_members_when_asked_to_include_them(self):
        self.age_the_rosters()
        live, stale = self.collect_with_staleness()
        everything = "\n".join(peers.render(live + stale, NOW, []))
        self.assertIn("probe-b", everything)
        self.assertIn("worker-18", everything)


class SessionLivenessTest(PeersTestCase):
    # A PM that waits 36 hours on one silent helper is the case this tool exists for. Its
    # roster is old, but its session is alive and rewrites its transcript.
    def setUp(self):
        super().setUp()
        project = os.path.join(self.projects, "-some-repo")
        os.makedirs(project)
        self.transcript = os.path.join(project, "aaa11111-2222-3333-4444-555555555555.jsonl")
        with open(self.transcript, "w") as handle:
            handle.write("{}\n")
        os.utime(self.transcript, (NOW - 30, NOW - 30))
        team = make_team(self.work, "session-aaa11111",
                         [lead_for("session-aaa11111"), dict(IN_PROCESS_PEER, name="patient-helper")])
        ancient = NOW - 36 * 3600
        os.utime(os.path.join(team, "config.json"), (ancient, ancient))

    def test_keeps_an_old_roster_listed_while_its_session_is_active(self):
        live, stale = self.collect_with_staleness()
        self.assertIn("session-aaa11111", [t["session"] for t in live])
        self.assertNotIn("session-aaa11111", [t["session"] for t in stale])

    def test_labels_a_team_with_an_active_transcript_as_session_active(self):
        live, _ = self.collect_with_staleness()
        active = next(t for t in live if t["session"] == "session-aaa11111")
        self.assertEqual(active.get("liveness"), "session-active")

    def test_labels_a_team_with_no_matching_transcript_as_roster_only(self):
        orphan = make_team(self.work, "session-orphan1",
                           [lead_for("session-orphan1"), dict(IN_PROCESS_PEER, name="lost-child")])
        os.utime(os.path.join(orphan, "config.json"), (NOW - 600, NOW - 600))
        live, stale = self.collect_with_staleness()
        orphan_team = next((t for t in live if t["session"] == "session-orphan1"), None)
        self.assertIsNotNone(orphan_team)
        self.assertEqual(orphan_team.get("liveness"), "roster-only")
        self.assertIn("roster only", "\n".join(peers.render(live, NOW, stale)))

    def test_marks_the_team_stale_once_its_session_goes_quiet(self):
        os.utime(self.transcript, (NOW - 48 * 3600, NOW - 48 * 3600))
        _, stale = self.collect_with_staleness()
        self.assertIn("session-aaa11111", [t["session"] for t in stale])


if __name__ == "__main__":
    unittest.main()
