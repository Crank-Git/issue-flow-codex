"""Tests for scripts/testbed-reset.py. Every forge call is faked; no test uses the network."""

import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("testbed_reset", ROOT / "scripts" / "testbed-reset.py")
testbed_reset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(testbed_reset)

SEED_TITLES = [i["title"] for i in json.loads(
    (ROOT / "testbed" / "seed" / "issues.json").read_text(encoding="utf-8"))["issues"]]


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class FakeForge:
    """An in-memory forge. It answers the REST calls of `gh api` and `tea api`."""

    def __init__(self, forge, repo_exists=True, server_up=True):
        self.forge = forge
        self.repo_exists = repo_exists
        self.server_up = server_up
        self.branches = ["main", "dev", "feature"]
        self.pulls = {}
        self.issues = {}
        self.labels = []
        self.calls = []
        self.git_commands = []

    def add_issue(self, title, state="open", body="", labels=None):
        number = len(self.issues) + 1
        self.issues[number] = {"number": number, "title": title, "state": state,
                               "body": body, "labels": labels or []}
        return number

    def __call__(self, args, input=None, cwd=None, env=None):
        if args[0] == "git":
            if "push" in args:
                self.git_commands.append(args)
                if "--delete" in args:
                    self.branches = [b for b in self.branches if b not in args]
                return done()
            return subprocess.run(args, input=input, cwd=cwd, env=env, text=True, capture_output=True)
        method = args[args.index("-X") + 1]
        url = urllib.parse.urlparse(args[args.index("-X") + 2])
        query = urllib.parse.parse_qs(url.query)
        body = json.loads(input) if input else None
        self.calls.append((args[0], method, url.path, body))
        result = self.answer(method, url.path, query, body)
        if args[0] == "tea" and result.returncode == 0:
            result.stderr = "HTTP/2.0 200 OK\nContent-Type: application/json\n"
        elif args[0] == "tea" and "404" in result.stderr:
            # Measured on Gitea 1.25.3: tea exits 0 on an HTTP 404 and prints the status with -i.
            return done('{"message":"not found"}', stderr="HTTP/2.0 404 Not Found\nVia: 1.1 Caddy\n")
        return result

    def answer(self, method, path, query, body):
        repo = "/repos/" + testbed_reset.BEDS[self.forge].repo
        if path == "/version" and not self.server_up:
            return done(returncode=1, stderr="dial tcp: connect: connection refused")
        if path == "/version":
            return done(json.dumps({"version": "1.25.3"}))
        if path == repo and method == "GET":
            if self.repo_exists:
                return done("{}")
            return done(returncode=1, stderr="gh: Not Found (HTTP 404)")
        if path == "/user/repos":
            self.repo_exists = True
            return done("{}")
        if path == repo and method == "PATCH":
            return done("{}")
        if path == repo + "/branches":
            return done(json.dumps([{"name": b} for b in self.branches]))
        if path == repo + "/pulls":
            return done(json.dumps([{"number": n} for n, state in self.pulls.items() if state == "open"]))
        if path.startswith(repo + "/pulls/") and method == "PATCH":
            self.pulls[int(path.rsplit("/", 1)[1])] = body["state"]
            return done("{}")
        if path == repo + "/labels" and method == "GET":
            return done(json.dumps(self.labels))
        if path == repo + "/labels" and method == "POST":
            self.labels.append({"id": 100 + len(self.labels), "name": body["name"]})
            return done("{}")
        if path.startswith(repo + "/issues/") and method == "GET":
            issue = self.issues.get(int(path.rsplit("/", 1)[1]))
            if issue is None:
                return done(returncode=1, stderr="gh: Not Found (HTTP 404)")
            if self.forge == "gitea":
                # Measured on Gitea 1.25.3: an issue that is not a pull request has "pull_request": null.
                issue = {**issue, "pull_request": None}
            return done(json.dumps(issue))
        if path == repo + "/issues" and method == "POST":
            number = self.add_issue(body["title"])
            self.issues[number]["body"] = body
            return done(json.dumps({"number": number}))
        if path.startswith(repo + "/issues/") and path.endswith("/labels") and method == "PUT":
            number = int(path.split("/")[-2])
            self.issues[number]["labels"] = body["labels"]
            return done("[]")
        if path.startswith(repo + "/issues/") and method == "PATCH":
            self.issues[int(path.rsplit("/", 1)[1])].update(body)
            return done("{}")
        raise AssertionError(f"unexpected call {method} {path}")

    def reset(self, forge):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(testbed_reset, "run", self), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = testbed_reset.main(["--forge", forge])
        return code, out.getvalue(), err.getvalue()


class ResetTest(unittest.TestCase):
    def test_creates_the_repository_when_it_is_missing(self):
        forge = FakeForge("github", repo_exists=False)
        code, _, _ = forge.reset("github")
        self.assertEqual(code, 0)
        creations = [call for call in forge.calls if call[2] == "/user/repos"]
        self.assertEqual(len(creations), 1)
        self.assertTrue(creations[0][3]["private"])

    def test_creates_the_gitea_repository_when_tea_exits_0_on_a_404(self):
        forge = FakeForge("gitea", repo_exists=False)
        code, _, err = forge.reset("gitea")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len([c for c in forge.calls if c[2] == "/user/repos"]), 1)

    def test_does_not_create_the_repository_when_it_exists(self):
        forge = FakeForge("github")
        forge.reset("github")
        self.assertEqual([c for c in forge.calls if c[2] == "/user/repos"], [])

    def test_closes_pull_requests_that_are_open(self):
        forge = FakeForge("github")
        forge.pulls = {7: "open", 8: "closed", 9: "open"}
        forge.reset("github")
        self.assertEqual(forge.pulls, {7: "closed", 8: "closed", 9: "closed"})

    def test_reads_the_github_test_bed_name_from_ISSUE_FLOW_TESTBED_GITHUB(self):
        with mock.patch.dict("os.environ", {"ISSUE_FLOW_TESTBED_GITHUB": "someone/other-testbed"}):
            beds = testbed_reset.build_beds()
        self.assertEqual(beds["github"].repo, "someone/other-testbed")
        self.assertEqual(beds["github"].url, "https://github.com/someone/other-testbed.git")

    def test_refuses_a_GitHub_repository_whose_name_does_not_end_in_testbed(self):
        self.assert_refused("github")

    def test_refuses_a_Gitea_repository_whose_name_does_not_end_in_testbed(self):
        self.assert_refused("gitea")

    def assert_refused(self, forge):
        forge_fake = FakeForge(forge)
        bad = testbed_reset.Bed("someone/real-project", "https://example.invalid/x.git")
        with mock.patch.dict(testbed_reset.BEDS, {forge: bad}):
            code, out, err = forge_fake.reset(forge)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn("-testbed", err)
        self.assertEqual((forge_fake.calls, forge_fake.git_commands), ([], []))

    def test_exits_1_and_names_the_url_when_the_gitea_server_is_down(self):
        forge = FakeForge("gitea", server_up=False)
        code, out, err = forge.reset("gitea")
        self.assertEqual(code, 1)
        self.assertIn(testbed_reset.GITEA_SERVER, err)
        self.assertEqual(out, "")
        self.assertEqual(forge.git_commands, [])

    def test_force_pushes_main_and_dev_then_deletes_other_branches(self):
        forge = FakeForge("github")
        forge.reset("github")
        pushes = [" ".join(c) for c in forge.git_commands]
        self.assertTrue(any("--force" in p and "HEAD:refs/heads/main" in p for p in pushes))
        self.assertTrue(any("--force" in p and "HEAD:refs/heads/dev" in p for p in pushes))
        self.assertTrue(any("--delete" in p and "feature" in p for p in pushes))
        self.assertEqual(forge.branches, ["main", "dev"])

    def test_creates_only_the_labels_that_are_missing(self):
        forge = FakeForge("github")
        forge.labels = [{"id": 1, "name": "status:ready"}]
        forge.reset("github")
        names = [label["name"] for label in forge.labels]
        self.assertEqual(len(names), 17)
        self.assertEqual(names.count("status:ready"), 1)

    def test_closes_open_issues_outside_the_seed_set(self):
        forge = FakeForge("github")
        stray = forge.add_issue("A stray issue")
        forge.reset("github")
        self.assertEqual(forge.issues[stray]["state"], "closed")

    def test_closes_a_duplicate_of_a_seed_issue_and_keeps_the_oldest(self):
        forge = FakeForge("github")
        first = forge.add_issue(SEED_TITLES[0])
        second = forge.add_issue(SEED_TITLES[0])
        forge.reset("github")
        self.assertEqual((forge.issues[first]["state"], forge.issues[second]["state"]),
                         ("open", "closed"))

    def test_reopens_a_closed_seed_issue_instead_of_opening_a_copy(self):
        forge = FakeForge("github")
        closed = forge.add_issue(SEED_TITLES[0], state="closed")
        forge.reset("github")
        self.assertEqual(forge.issues[closed]["state"], "open")
        self.assertEqual([i["title"] for i in forge.issues.values()].count(SEED_TITLES[0]), 1)

    def test_reopens_a_closed_github_seed_issue_with_changed_fields(self):
        self.assert_reopens_changed_seed_issue("github")

    def test_reopens_a_closed_gitea_seed_issue_with_changed_fields(self):
        self.assert_reopens_changed_seed_issue("gitea")

    def assert_reopens_changed_seed_issue(self, forge_name):
        forge = FakeForge(forge_name)
        forge.reset(forge_name)
        issue = next(item for item in forge.issues.values() if item["title"] == SEED_TITLES[0])
        issue.update(body="Changed body", labels=["status:batched"])
        issue["state"] = "closed"
        self.assertEqual(issue["state"], "closed")
        forge.reset(forge_name)
        seed = json.loads((ROOT / "testbed" / "seed" / "issues.json").read_text())
        expected = seed["issues"][0]
        restored = forge.issues[issue["number"]]
        self.assertEqual(restored["title"], expected["title"])
        self.assertEqual(restored["body"], expected["body"])
        self.assertEqual(restored["state"], "open")
        if forge_name == "github":
            update = next(call[3] for call in forge.calls if call[1] == "PATCH" and
                          call[2].endswith(f"/issues/{issue['number']}"))
            self.assertEqual(update["labels"], expected["labels"])
        else:
            expected_ids = [next(label["id"] for label in forge.labels if label["name"] == name)
                            for name in expected["labels"]]
            update = next(call[3] for call in forge.calls if call[1] == "PUT" and
                          call[2].endswith(f"/issues/{issue['number']}/labels"))
            self.assertEqual(update["labels"], expected_ids)
        self.assertEqual(restored["labels"], expected["labels"] if forge_name == "github"
                         else expected_ids)

    def test_opens_the_seed_issues_once_across_two_runs(self):
        forge = FakeForge("github")
        forge.reset("github")
        _, out, _ = forge.reset("github")
        titles = [i["title"] for i in forge.issues.values()]
        self.assertEqual(sorted(titles), sorted(SEED_TITLES + ["Extend the greeting service"]))
        state = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(len(state["openIssues"]), 6)

    def test_opens_the_gitea_seed_issues_once_across_two_runs(self):
        forge = FakeForge("gitea")
        forge.reset("gitea")
        _, out, _ = forge.reset("gitea")
        titles = [i["title"] for i in forge.issues.values()]
        self.assertEqual(sorted(titles), sorted(SEED_TITLES + ["Extend the greeting service"]))
        state = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(len(state["openIssues"]), 6)

    def test_links_the_epic_to_its_sub_issues(self):
        forge = FakeForge("github")
        forge.reset("github")
        epic = next(i for i in forge.issues.values() if i["title"] == "Extend the greeting service")
        self.assertIn("- [ ] #1 Add a /version endpoint", epic["body"]["body"])

    def test_sends_label_ids_to_gitea_and_label_names_to_github(self):
        gitea = FakeForge("gitea")
        gitea.reset("gitea")
        self.assertTrue(all(isinstance(x, int) for i in gitea.issues.values()
                            for x in i["body"]["labels"]))
        github = FakeForge("github")
        github.reset("github")
        self.assertTrue(all(isinstance(x, str) for i in github.issues.values()
                            for x in i["body"]["labels"]))


if __name__ == "__main__":
    unittest.main()
