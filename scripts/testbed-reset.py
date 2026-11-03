#!/usr/bin/env python3
"""Return a test bed repository to its seed state.

`--forge github|gitea` picks one of the two test beds. The script creates the
repository when it is missing, force-pushes the seed commit to `main` and `dev`,
deletes every other branch, closes every open pull request, closes every issue
outside the seed set, creates the missing labels, and opens the seed issues.
A second run changes nothing. The last stdout line is one JSON object that
describes the resulting state.

The script touches only the two repositories named in `BEDS`.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "testbed" / "seed"
LABELS = ROOT / "skills" / "issue-flow" / "references" / "labels.md"
GITEA_SERVER = os.environ.get("GITEA_SERVER_URL", "https://telescope.lan")
GITEA_REPO = os.environ.get("ISSUE_FLOW_TESTBED_GITEA", "e/issue-flow-codex-testbed")
GITEA_LOGIN = "telescope"
KEPT_BRANCHES = ("main", "dev")
PAGE_SIZE = 50

Bed = namedtuple("Bed", "repo url")
BEDS = {
    "github": Bed("Crank-Git/issue-flow-codex-testbed",
                  "https://github.com/Crank-Git/issue-flow-codex-testbed.git"),
    "gitea": Bed(GITEA_REPO, f"{GITEA_SERVER}/{GITEA_REPO}.git"),
}

# One bootstrap line of labels.md: `gh label create "<name>" --color <hex> --description "<text>"`.
LABEL_LINE = re.compile(r'gh label create "([^"]+)"\s+--color ([0-9A-Fa-f]{6}) --description "([^"]*)"')

# A fixed identity and date make the seed commit hash identical on every run.
SEED_ENV = {"GIT_AUTHOR_NAME": "testbed", "GIT_AUTHOR_EMAIL": "testbed@example.invalid",
            "GIT_COMMITTER_NAME": "testbed", "GIT_COMMITTER_EMAIL": "testbed@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"}


class ResetError(Exception):
    """A failure that `main` reports as one line on stderr."""


def run(args, input=None, cwd=None, env=None):
    return subprocess.run(args, input=input, cwd=cwd, env=env, text=True, capture_output=True)


def request(forge, method, path, body=None):
    """Send one REST call through `gh api` or `tea api`. Return the finished process."""
    if forge == "github":
        command = ["gh", "api", "-X", method, path]
        if body is not None:
            command += ["--input", "-"]
    else:
        # -i prints the HTTP status to stderr, because tea exits 0 on an HTTP error.
        command = ["tea", "api", "--login", GITEA_LOGIN, "-i", "-X", method, path]
        if body is not None:
            command += ["-d", "@-"]
    done = run(command, input=None if body is None else json.dumps(body))
    status = re.match(r"HTTP/\S+ (\d+)", done.stderr)
    if forge == "gitea" and done.returncode == 0 and status and int(status[1]) >= 400:
        return subprocess.CompletedProcess(command, 1, done.stdout, done.stderr)
    return done


def api(forge, method, path, body=None):
    """Send one REST call and return its parsed JSON, or None for an empty reply."""
    done = request(forge, method, path, body)
    if done.returncode != 0:
        raise ResetError(f"{method} {path} on {forge} failed: {(done.stderr or done.stdout).strip()}")
    return json.loads(done.stdout) if done.stdout.strip() else None


def get_all(forge, path):
    """Return every item of a paged list. Gitea reads `limit`, GitHub reads `per_page`."""
    items, page = [], 1
    separator = "&" if "?" in path else "?"
    while True:
        batch = api(forge, "GET", f"{path}{separator}page={page}&per_page={PAGE_SIZE}&limit={PAGE_SIZE}")
        items += batch
        if len(batch) < PAGE_SIZE:
            return items
        page += 1


def check_server(forge):
    if forge != "gitea":
        return
    done = request(forge, "GET", "/version")
    if done.returncode != 0:
        raise ResetError(f"the Gitea server {GITEA_SERVER} is not reachable: "
                         f"{(done.stderr or done.stdout).strip()}")


def is_missing(done):
    return bool(re.search(r"404|not found|does not exist", done.stderr + done.stdout, re.IGNORECASE))


def ensure_repository(forge, bed):
    done = request(forge, "GET", f"/repos/{bed.repo}")
    if done.returncode == 0:
        return
    # Only a missing repository may be created. Any other failure stops the reset.
    if not is_missing(done):
        raise ResetError(f"cannot read {bed.repo} on {forge}: {(done.stderr or done.stdout).strip()}")
    api(forge, "POST", "/user/repos",
        {"name": bed.repo.split("/")[1], "private": True,
         "description": "Test bed of issue-flow-codex. The reset script rewrites it."})


def git(forge, *args, cwd):
    # tea stores the Gitea token. Its helper hands it to git without a command-line copy.
    prefix = ["-c", "credential.helper=", "-c", "credential.helper=!tea logins helper"] \
        if forge == "gitea" else []
    done = run(["git", *prefix, *args], cwd=cwd, env={**os.environ, **SEED_ENV})
    if done.returncode != 0:
        raise ResetError(f"git {args[0]} failed: {(done.stderr or done.stdout).strip()}")


def publish_seed(forge, bed):
    """Force-push the seed commit to `main` and `dev`, then delete every other branch."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "seed"
        shutil.copytree(SEED, work, ignore=shutil.ignore_patterns("issues.json", "__pycache__"))
        git(forge, "init", "--quiet", "-b", "main", cwd=work)
        git(forge, "add", "-A", cwd=work)
        git(forge, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "chore: seed the test bed",
            cwd=work)
        # main goes first so that an empty repository takes it as the default branch.
        for branch in KEPT_BRANCHES:
            git(forge, "push", "--quiet", "--force", bed.url, f"HEAD:refs/heads/{branch}", cwd=work)
        api(forge, "PATCH", f"/repos/{bed.repo}", {"default_branch": "main"})
        extra = [b["name"] for b in get_all(forge, f"/repos/{bed.repo}/branches")
                 if b["name"] not in KEPT_BRANCHES]
        if extra:
            git(forge, "push", "--quiet", "--delete", bed.url, *extra, cwd=work)


def close_pull_requests(forge, bed):
    for pull in get_all(forge, f"/repos/{bed.repo}/pulls?state=open"):
        api(forge, "PATCH", f"/repos/{bed.repo}/pulls/{pull['number']}", {"state": "closed"})


def ensure_labels(forge, bed):
    """Create the labels of labels.md that the repository lacks. Return {name: id}."""
    wanted = LABEL_LINE.findall(LABELS.read_text(encoding="utf-8"))
    present = {label["name"] for label in get_all(forge, f"/repos/{bed.repo}/labels")}
    # Gitea wants a leading # on the color; GitHub rejects it.
    prefix = "#" if forge == "gitea" else ""
    for name, color, description in wanted:
        if name not in present:
            api(forge, "POST", f"/repos/{bed.repo}/labels",
                {"name": name, "color": prefix + color, "description": description})
    return {label["name"]: label["id"] for label in get_all(forge, f"/repos/{bed.repo}/labels")}


def read_issues(forge, bed):
    """Return every issue of the repository, oldest first, pull requests excluded.

    The issue list of GitHub lags behind writes and can omit an issue for minutes.
    A run that trusted it opened duplicate seed issues. Reading each number is
    consistent, and numbers have no gaps, so the first missing number ends the read.
    """
    issues, number = [], 1
    while True:
        done = request(forge, "GET", f"/repos/{bed.repo}/issues/{number}")
        if done.returncode != 0:
            if is_missing(done):
                return issues
            raise ResetError(f"cannot read issue {number} of {bed.repo}: "
                             f"{(done.stderr or done.stdout).strip()}")
        issue = json.loads(done.stdout)
        if "pull_request" not in issue:
            issues.append(issue)
        number += 1


def seed_issues(forge, bed, label_ids):
    """Open the seed issues that are missing, reopen closed ones, and close all others."""
    seed = json.loads((SEED / "issues.json").read_text(encoding="utf-8"))
    wanted = {item["title"] for item in seed["issues"] + [seed["epic"]]}
    issues = read_issues(forge, bed)
    kept = set()
    for issue in issues:
        if issue["state"] == "open" and (issue["title"] not in wanted or issue["title"] in kept):
            api(forge, "PATCH", f"/repos/{bed.repo}/issues/{issue['number']}", {"state": "closed"})
        elif issue["state"] == "open":
            kept.add(issue["title"])
    # The last write wins: an open issue beats a closed one, and the oldest open issue beats a newer one.
    known = {}
    for issue in sorted(issues, key=lambda i: (i["state"] == "open", -i["number"])):
        known[issue["title"]] = issue
    numbers = {}

    def ensure(item, body):
        issue = known.get(item["title"])
        if issue is None:
            # Gitea takes label ids; GitHub takes label names.
            labels = [label_ids[n] for n in item["labels"]] if forge == "gitea" else item["labels"]
            issue = api(forge, "POST", f"/repos/{bed.repo}/issues",
                        {"title": item["title"], "body": body, "labels": labels})
            return issue["number"]
        if issue["state"] != "open":
            api(forge, "PATCH", f"/repos/{bed.repo}/issues/{issue['number']}", {"state": "open"})
        return issue["number"]

    for item in seed["issues"]:
        numbers[item["title"]] = ensure(item, item["body"])
    checklist = "\n".join(f"- [ ] #{number} {title}" for title, number in numbers.items())
    ensure(seed["epic"], seed["epic"]["body"].replace("{{checklist}}", checklist))


def describe(forge, bed):
    repository = api(forge, "GET", f"/repos/{bed.repo}")
    return {"forge": forge, "repository": bed.repo,
            "defaultBranch": repository.get("default_branch"),
            "branches": sorted(b["name"] for b in get_all(forge, f"/repos/{bed.repo}/branches")),
            "openPullRequests": len(get_all(forge, f"/repos/{bed.repo}/pulls?state=open")),
            "openIssues": [[i["number"], i["title"]] for i in read_issues(forge, bed)
                            if i["state"] == "open"],
            "labels": len(get_all(forge, f"/repos/{bed.repo}/labels"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forge", choices=sorted(BEDS), required=True, help="the test bed to reset")
    args = parser.parse_args(argv)
    forge, bed = args.forge, BEDS[args.forge]
    try:
        check_server(forge)
        ensure_repository(forge, bed)
        publish_seed(forge, bed)
        close_pull_requests(forge, bed)
        label_ids = ensure_labels(forge, bed)
        seed_issues(forge, bed, label_ids)
        print(json.dumps(describe(forge, bed)))
    except ResetError as error:
        print(f"testbed-reset: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
