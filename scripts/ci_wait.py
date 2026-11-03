#!/usr/bin/env python3
"""Wait for the CI run of one commit and print one JSON line with its state.

    python3 scripts/ci_wait.py --forge github --repo owner/name --sha SHA [--max-seconds 240]
    python3 scripts/ci_wait.py --forge gitea --sha SHA [--repo-path .]

State is one of `pending`, `success`, `failure`, `missing`. `missing` means no run
existed for the SHA during the whole window. `pending` means a run existed but did not
finish. The script ends within --max-seconds, because Codex kills a background command
at 300 seconds (codex-rs/core/src/unified_exec/mod.rs:66-75). The caller polls again.

Exit codes: 0 with the JSON line on stdout; nonzero with one line on stderr when the
invocation is bad or the forge call fails. A failed forge call is never a state.

GitHub uses `gh run list --commit` (gh 2.88.1). Gitea uses the call that
scripts/gitea-ci-watch.sh makes: `tea api /repos/{owner}/{repo}/actions/runs?head_sha=SHA`.
"""

import argparse
import json
import subprocess
import sys
import time


class WaitError(Exception):
    pass


def parse_github(body):
    try:
        return [{"status": r["status"], "conclusion": r["conclusion"], "url": r["url"]}
                for r in json.loads(body)]
    except (ValueError, KeyError, TypeError) as error:
        raise WaitError(f"gh output is not a run list: {error!r}") from None


def parse_gitea(body):
    try:
        data = json.loads(body)
    except ValueError as error:
        raise WaitError(f"tea output is not JSON: {error}") from None
    # An object without a run list is an API error such as {"message": "not found"}.
    # Reading it as "no runs" would report `missing` for a failed request.
    runs = data.get("workflow_runs", data.get("runs")) if isinstance(data, dict) else None
    if not isinstance(runs, list):
        raise WaitError(f"not a run list: {body[:200]}")
    return [{"status": r.get("status"), "conclusion": r.get("conclusion"),
             "url": r.get("html_url"), "path": r.get("path", "")} for r in runs]


def run_command(argv, timeout, cwd=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise WaitError(f"{argv[0]} did not answer within {timeout:.0f} seconds") from None
    except FileNotFoundError:
        raise WaitError(f"{argv[0]} is not installed") from None
    if done.returncode != 0:
        raise WaitError(f"{argv[0]} failed: {done.stderr.strip()[:200]}")
    return done.stdout


def github_fetcher(repo, sha, workflow=None):
    argv = ["gh", "run", "list", "-R", repo, "--commit", sha,
            "--json", "databaseId,status,conclusion,url"]
    if workflow:
        argv += ["--workflow", workflow]
    return lambda timeout: parse_github(run_command(argv, timeout))


def gitea_fetcher(repo_path, sha, workflow=None):
    argv = ["tea", "api", f"/repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}"]

    def fetch(timeout):
        runs = parse_gitea(run_command(argv, timeout, cwd=repo_path))
        return [r for r in runs if workflow in r["path"]] if workflow else runs

    return fetch


def make_fetcher(forge, repo, repo_path, sha, workflow=None):
    if forge == "github":
        return github_fetcher(repo, sha, workflow)
    return gitea_fetcher(repo_path, sha, workflow)


def classify(runs):
    """Return (state, url) for every run of one commit taken together."""
    if not runs:
        return "missing", None
    if any(r["status"] != "completed" for r in runs):
        return "pending", runs[0]["url"]
    red = [r for r in runs if r["conclusion"] not in ("success", "skipped")]
    if red:
        return "failure", red[0]["url"]
    return "success", runs[0]["url"]


def poll(observe, max_seconds, poll_seconds, clock, sleep):
    """Call observe(timeout) until it returns a result or the window ends.

    Returns the result, or None when the window ended first. No call starts after
    the deadline, and no sleep runs past it.
    """
    deadline = clock() + max_seconds
    while True:
        result = observe(max(1, deadline - clock()))
        if result is not None:
            return result
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        sleep(min(poll_seconds, remaining))


def wait(fetch, max_seconds, poll_seconds, clock=time.monotonic, sleep=time.sleep):
    last = {"state": "missing", "url": None}

    def observe(timeout):
        state, url = classify(fetch(timeout))
        last.update(state=state, url=url)
        return last if state in ("success", "failure") else None

    poll(observe, max_seconds, poll_seconds, clock, sleep)
    return dict(last)


class OneLineParser(argparse.ArgumentParser):
    def error(self, message):
        sys.exit(f"{self.prog}: {message}")


def add_forge_arguments(parser):
    parser.add_argument("--forge", choices=("github", "gitea"), required=True)
    parser.add_argument("--repo", help="owner/name; required for github")
    parser.add_argument("--repo-path", default=".", help="checkout that tea reads; gitea only")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--max-seconds", type=int, default=240)
    parser.add_argument("--poll-seconds", type=int, default=30)


def main(argv=None):
    parser = OneLineParser(description=__doc__.splitlines()[0])
    add_forge_arguments(parser)
    args = parser.parse_args(argv)
    if args.forge == "github" and not args.repo:
        parser.error("--repo is required for --forge github")
    fetch = make_fetcher(args.forge, args.repo, args.repo_path, args.sha)
    try:
        print(json.dumps(wait(fetch, args.max_seconds, args.poll_seconds)))
    except WaitError as error:
        sys.exit(f"ci_wait: {error}")


if __name__ == "__main__":
    main()
