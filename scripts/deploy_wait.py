#!/usr/bin/env python3
"""Wait for the deployment of one commit and print one JSON line with its state.

    python3 scripts/deploy_wait.py --mode command --status-cmd ./scripts/deploy-status.sh --sha SHA
    python3 scripts/deploy_wait.py --mode actions --workflow deploy.yml --forge github --repo owner/name --sha SHA

State is one of `pending`, `succeeded`, `failed`, `rolled-back`, `superseded`, `missing`.
These are the deploy.md terms: `missing` is `no-deployment-observed`, and `pending`
covers a deployment seen but not finished (`timed-out` in the PM's table). The script
ends within --max-seconds; the caller polls again.

`command` mode runs the project's status command, one line `<state> <jobId> <sha>`.
`actions` mode reads the runs of the deploy workflow for the SHA, as ci_wait.py does.

Exit codes: 0 with the JSON line on stdout; nonzero with one line on stderr when the
invocation is bad or the status query fails. A failed query is never a state.
"""

import json
import shlex
import sys
import time

import ci_wait
from ci_wait import WaitError

TERMINAL = ("succeeded", "failed", "rolled-back")
RUNNING = ("pending", "running")
ACTIONS_STATE = {"success": "succeeded", "failure": "failed", "pending": "pending", "missing": "missing"}


def wait_command(status, sha, max_seconds, poll_seconds, clock=time.monotonic, sleep=time.sleep):
    seen = {"ours": False, "newest": None, "verdict": None}

    def observe(timeout):
        fields = status(timeout).split()
        if not fields:
            return None
        if len(fields) < 3:
            raise WaitError(f"status line has fewer than 3 fields: {' '.join(fields)}")
        state, job, built = fields[:3]
        seen["newest"] = {"job": job, "sha": built}
        if built != sha:
            return None
        if state in TERMINAL:
            return {"state": state, "url": None, "jobId": job, "sha": sha}
        if state in RUNNING:
            seen["ours"] = True
            seen["verdict"] = {"state": "pending", "url": None, "jobId": job, "sha": sha}
        return None

    result = ci_wait.poll(observe, max_seconds, poll_seconds, clock, sleep)
    if result:
        return result
    if seen["ours"]:
        return seen["verdict"]
    if seen["newest"]:
        return {"state": "superseded", "url": None, "jobId": seen["newest"]["job"],
                "sha": seen["newest"]["sha"]}
    return {"state": "missing", "url": None, "jobId": None, "sha": sha}


def wait_actions(fetch, sha, max_seconds, poll_seconds, clock=time.monotonic, sleep=time.sleep):
    result = ci_wait.wait(fetch, max_seconds, poll_seconds, clock, sleep)
    return {"state": ACTIONS_STATE[result["state"]], "url": result["url"], "jobId": None, "sha": sha}


def main(argv=None):
    parser = ci_wait.OneLineParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("actions", "command"), required=True)
    parser.add_argument("--status-cmd", help="status command; required for command mode")
    parser.add_argument("--workflow", help="deploy workflow file; required for actions mode")
    parser.add_argument("--forge", choices=("github", "gitea"))
    parser.add_argument("--repo", help="owner/name; required for github")
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--max-seconds", type=int, default=240)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if args.mode == "command" and not args.status_cmd:
        parser.error("--status-cmd is required for --mode command")
    if args.mode == "actions" and not (args.workflow and args.forge):
        parser.error("--workflow and --forge are required for --mode actions")
    if args.forge == "github" and not args.repo:
        parser.error("--repo is required for --forge github")
    try:
        if args.mode == "command":
            argv_status = shlex.split(args.status_cmd)
            result = wait_command(lambda timeout: ci_wait.run_command(argv_status, timeout),
                                  args.sha, args.max_seconds, args.poll_seconds)
        else:
            fetch = ci_wait.make_fetcher(args.forge, args.repo, args.repo_path, args.sha, args.workflow)
            result = wait_actions(fetch, args.sha, args.max_seconds, args.poll_seconds)
        print(json.dumps(result))
    except WaitError as error:
        sys.exit(f"deploy_wait: {error}")


if __name__ == "__main__":
    main()
